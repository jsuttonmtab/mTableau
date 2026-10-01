"""
Formula language for calculated fields.

Formulas are parsed into a small syntax tree. Nothing is ever passed to Python's
eval() or pasted into SQL as raw text: the tree is either evaluated against a
pandas DataFrame (for display) or translated to DuckDB SQL (for filters).

Language
--------
  Literals     123   4.5   'text'   "text"   TRUE   FALSE   NULL
  Fields       USER_EMAIL, User_Email, [User Email]       (case-insensitive)
  Arithmetic   +  -  *  /          (+ joins text when either side is text)
  Comparison   =  ==  <>  !=  <  <=  >  >=
  Logic        AND  OR  NOT
  Conditional  IF cond THEN a [ELSEIF cond THEN b ...] ELSE c [END]

Text comparisons ignore case: 'ABC' = 'abc' is true. Functions:

  CONTAINS(text, part)      STARTSWITH(text, part)    ENDSWITH(text, part)
  CONTAINS_CS / STARTSWITH_CS / ENDSWITH_CS           case-sensitive versions
  EXACT(a, b)               case-sensitive equality
  UPPER(x)  LOWER(x)  LEN(x)  TRIM(x)  CONCAT(a, b, ...)
  YEAR(date)  MONTH(date)  DAY(date)
  ISNULL(x)  ISNOTNULL(x)
  FIXED(agg, value_field, dim_field[, 'date format'])   agg: MAX MIN SUM COUNT MEAN
      (display only; can't be used as a filter)
"""
import re

import numpy as np
import pandas as pd


class FormulaError(ValueError):
    pass


# ─────────────────────────────────────────────
# Tokenizer
# ─────────────────────────────────────────────

_TOKEN_RE = re.compile(r"""
    (?P<ws>\s+)
  | (?P<num>\d+\.\d*|\.\d+|\d+)
  | (?P<str>'(?:[^'\\]|\\.|'')*'|"(?:[^"\\]|\\.|"")*")
  | (?P<bracket>\[[^\]]+\])
  | (?P<op><=|>=|<>|!=|==|[-+*/=<>(),])
  | (?P<name>[A-Za-z_][A-Za-z0-9_]*)
""", re.VERBOSE)

_KEYWORDS = {"IF", "THEN", "ELSEIF", "ELSE", "END", "AND", "OR", "NOT",
             "TRUE", "FALSE", "NULL"}


def _tokenize(text):
    tokens, pos = [], 0
    while pos < len(text):
        m = _TOKEN_RE.match(text, pos)
        if not m:
            raise FormulaError(f"Unexpected character {text[pos]!r} at position {pos + 1}")
        pos = m.end()
        kind = m.lastgroup
        val = m.group()
        if kind == "ws":
            continue
        if kind == "str":
            q = val[0]
            body = val[1:-1].replace(q + q, q)
            body = re.sub(r"\\(.)", r"\1", body)
            tokens.append(("str", body))
        elif kind == "num":
            tokens.append(("num", float(val) if "." in val else int(val)))
        elif kind == "bracket":
            tokens.append(("field", val[1:-1].strip()))
        elif kind == "name":
            up = val.upper()
            tokens.append(("kw", up) if up in _KEYWORDS else ("name", val))
        else:
            tokens.append(("op", val))
    tokens.append(("eof", None))
    return tokens


# ─────────────────────────────────────────────
# Parser → nested tuples
#   ("lit", value) ("field", name) ("call", NAME, [args]) ("not", x)
#   ("bin", op, a, b) ("neg", x) ("if", [(cond, value), ...], else_value)
# ─────────────────────────────────────────────

class _Parser:
    def __init__(self, text):
        self.toks = _tokenize(text)
        self.i = 0

    def peek(self):
        return self.toks[self.i]

    def take(self):
        t = self.toks[self.i]
        self.i += 1
        return t

    def accept(self, kind, val=None):
        t = self.peek()
        if t[0] == kind and (val is None or t[1] == val):
            self.i += 1
            return t
        return None

    def expect(self, kind, val=None, what=None):
        t = self.accept(kind, val)
        if not t:
            got = self.peek()
            shown = "end of formula" if got[0] == "eof" else repr(got[1])
            raise FormulaError(f"Expected {what or val or kind} but found {shown}")
        return t

    def parse(self):
        node = self.expr()
        if self.peek()[0] != "eof":
            raise FormulaError(f"Unexpected {self.peek()[1]!r} after the end of the formula")
        return node

    def expr(self):
        return self.or_()

    def or_(self):
        node = self.and_()
        while self.accept("kw", "OR"):
            node = ("bin", "OR", node, self.and_())
        return node

    def and_(self):
        node = self.not_()
        while self.accept("kw", "AND"):
            node = ("bin", "AND", node, self.not_())
        return node

    def not_(self):
        if self.accept("kw", "NOT"):
            return ("not", self.not_())
        return self.cmp()

    def cmp(self):
        node = self.add()
        t = self.peek()
        if t[0] == "op" and t[1] in ("=", "==", "<>", "!=", "<", "<=", ">", ">="):
            self.take()
            op = {"==": "=", "!=": "<>"}.get(t[1], t[1])
            node = ("bin", op, node, self.add())
        return node

    def add(self):
        node = self.mul()
        while True:
            t = self.peek()
            if t[0] == "op" and t[1] in ("+", "-"):
                self.take()
                node = ("bin", t[1], node, self.mul())
            else:
                return node

    def mul(self):
        node = self.unary()
        while True:
            t = self.peek()
            if t[0] == "op" and t[1] in ("*", "/"):
                self.take()
                node = ("bin", t[1], node, self.unary())
            else:
                return node

    def unary(self):
        if self.accept("op", "-"):
            return ("neg", self.unary())
        if self.accept("op", "+"):
            return self.unary()
        return self.primary()

    def primary(self):
        t = self.take()
        kind, val = t
        if kind == "num" or kind == "str":
            return ("lit", val)
        if kind == "kw" and val in ("TRUE", "FALSE"):
            return ("lit", val == "TRUE")
        if kind == "kw" and val == "NULL":
            return ("lit", None)
        if kind == "kw" and val == "IF":
            return self.if_()
        if kind == "op" and val == "(":
            node = self.expr()
            self.expect("op", ")", "')'")
            return node
        if kind == "field":
            return ("field", val)
        if kind == "name":
            if self.accept("op", "("):
                args = []
                if not self.accept("op", ")"):
                    while True:
                        args.append(self.expr())
                        if self.accept("op", ")"):
                            break
                        self.expect("op", ",", "',' or ')'")
                return ("call", val.upper(), args)
            return ("field", val)
        shown = "end of formula" if kind == "eof" else repr(val)
        raise FormulaError(f"Unexpected {shown}")

    def if_(self):
        branches = []
        cond = self.expr()
        self.expect("kw", "THEN", "THEN")
        branches.append((cond, self.expr()))
        while self.accept("kw", "ELSEIF"):
            cond = self.expr()
            self.expect("kw", "THEN", "THEN")
            branches.append((cond, self.expr()))
        else_val = ("lit", None)
        if self.accept("kw", "ELSE"):
            else_val = self.expr()
        self.accept("kw", "END")
        return ("if", branches, else_val)


_FIXED_UNQUOTED_FMT = re.compile(
    r"^\s*(FIXED\s*\(\s*\w+\s*,\s*[^,()]+?\s*,\s*[^,()]+?\s*,)\s*([^'\"\s].*?)\s*\)\s*$",
    re.IGNORECASE | re.DOTALL)


def parse(formula):
    if not formula or not str(formula).strip():
        raise FormulaError("Please enter a formula.")
    text = str(formula)
    # The original FIXED syntax allowed an unquoted date format as the 4th
    # argument, e.g. FIXED(MAX, ACTION_DATE, USER_NAME, %b %d, %Y). Keep accepting it.
    m = _FIXED_UNQUOTED_FMT.match(text)
    if m:
        text = m.group(1) + " '" + m.group(2).replace("'", "''") + "')"
    node = _Parser(text).parse()
    _check_calls(node)
    return node


# ─────────────────────────────────────────────
# Functions
# ─────────────────────────────────────────────

_TEXT_PRED = {   # name: (kind, case_sensitive)
    "CONTAINS": ("contains", False), "CONTAINS_CS": ("contains", True),
    "STARTSWITH": ("starts", False), "STARTSWITH_CS": ("starts", True),
    "ENDSWITH": ("ends", False),     "ENDSWITH_CS": ("ends", True),
}
_ARITY = {
    **{n: (2, 2) for n in _TEXT_PRED},
    "EXACT": (2, 2), "UPPER": (1, 1), "LOWER": (1, 1), "LEN": (1, 1), "TRIM": (1, 1),
    "CONCAT": (1, 99), "YEAR": (1, 1), "MONTH": (1, 1), "DAY": (1, 1),
    "ISNULL": (1, 1), "ISNOTNULL": (1, 1), "FIXED": (3, 4),
}
SUPPORTED_FUNCTIONS = sorted(_ARITY)
_FIXED_AGGS = {"MAX": "max", "MIN": "min", "SUM": "sum", "COUNT": "count", "MEAN": "mean"}


def _check_calls(node):
    kind = node[0]
    if kind == "call":
        name, args = node[1], node[2]
        if name not in _ARITY:
            raise FormulaError(f"Unknown function: {name}. Supported: {', '.join(SUPPORTED_FUNCTIONS)}")
        lo, hi = _ARITY[name]
        if not lo <= len(args) <= hi:
            want = str(lo) if lo == hi else f"{lo}-{hi}"
            raise FormulaError(f"{name} takes {want} argument(s), got {len(args)}")
        if name == "FIXED":
            agg = args[0]
            if agg[0] != "field" or agg[1].upper() not in _FIXED_AGGS:
                raise FormulaError("FIXED: first argument must be MAX, MIN, SUM, COUNT or MEAN")
            for a in args[1:3]:
                if a[0] != "field":
                    raise FormulaError("FIXED: second and third arguments must be field names")
            if len(args) == 4 and args[3][0] != "lit":
                raise FormulaError("FIXED: the date format must be a quoted string")
            return
        for a in args:
            _check_calls(a)
    elif kind == "bin":
        _check_calls(node[2]); _check_calls(node[3])
    elif kind in ("not", "neg"):
        _check_calls(node[1])
    elif kind == "if":
        for c, v in node[1]:
            _check_calls(c); _check_calls(v)
        _check_calls(node[2])


def referenced_fields(formula):
    """Field names a formula uses (as written; callers resolve case)."""
    out = []

    def walk(n):
        k = n[0]
        if k == "field":
            out.append(n[1])
        elif k == "call":
            args = n[2][1:3] if n[1] == "FIXED" else n[2]
            for a in args:
                walk(a)
        elif k == "bin":
            walk(n[2]); walk(n[3])
        elif k in ("not", "neg"):
            walk(n[1])
        elif k == "if":
            for c, v in n[1]:
                walk(c); walk(v)
            walk(n[2])
    walk(parse(formula))
    seen = []
    for f in out:
        if f not in seen:
            seen.append(f)
    return seen


def is_boolean(formula):
    """True when the formula's result is a true/false value (useful for filters)."""
    node = parse(formula)
    k = node[0]
    if k == "lit":
        return isinstance(node[1], bool)
    if k == "not":
        return True
    if k == "bin":
        return node[1] in ("AND", "OR", "=", "<>", "<", "<=", ">", ">=")
    if k == "call":
        return node[1] in _TEXT_PRED or node[1] in ("EXACT", "ISNULL", "ISNOTNULL")
    return False


# ─────────────────────────────────────────────
# pandas evaluation
# ─────────────────────────────────────────────

def _resolve_column(name, df):
    if name in df.columns:
        return name
    want = name.upper().replace(" ", "_")
    for c in df.columns:
        if str(c).upper().replace(" ", "_") == want:
            return c
    raise FormulaError(f"Unknown field: {name}")


def _as_series(v, df):
    if isinstance(v, pd.Series):
        return v
    return pd.Series([v] * len(df), index=df.index, dtype=object if not isinstance(v, (int, float, bool)) else None)


def _is_texty(v):
    if isinstance(v, str):
        return True
    if isinstance(v, pd.Series):
        return v.dtype == object or pd.api.types.is_string_dtype(v)
    return False


def _text(v, df):
    s = _as_series(v, df)
    return s.where(s.isna(), s.astype(str))


def _num(v, df):
    if isinstance(v, pd.Series):
        return pd.to_numeric(v, errors="coerce")
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, (int, float)) or v is None:
        return v
    try:
        return float(v)
    except (TypeError, ValueError):
        raise FormulaError(f"Expected a number but got {v!r}")


def _truthy(v, df):
    s = _as_series(v, df)
    if s.dtype == bool:
        return s
    return s.fillna(False).astype(bool)


def _eval(node, df):
    k = node[0]
    if k == "lit":
        return node[1]
    if k == "field":
        return df[_resolve_column(node[1], df)]
    if k == "neg":
        return -_num(_eval(node[1], df), df)
    if k == "not":
        return ~_truthy(_eval(node[1], df), df)
    if k == "if":
        result = _as_series(_eval(node[2], df), df).astype(object)
        for cond, val in reversed(node[1]):
            c = _truthy(_eval(cond, df), df).to_numpy()
            v = _as_series(_eval(val, df), df).astype(object).to_numpy()
            result = pd.Series(np.where(c, v, result.to_numpy()), index=df.index)
        return _maybe_numeric(result)
    if k == "bin":
        op, a, b = node[1], _eval(node[2], df), _eval(node[3], df)
        if op == "AND":
            return _truthy(a, df) & _truthy(b, df)
        if op == "OR":
            return _truthy(a, df) | _truthy(b, df)
        if op in ("=", "<>", "<", "<=", ">", ">="):
            if _is_texty(a) or _is_texty(b):
                a, b = _text(a, df).str.lower(), _text(b, df).str.lower()
            else:
                a, b = _num(a, df), _num(b, df)
            sa, sb = _as_series(a, df), _as_series(b, df)
            res = {"=": sa.eq, "<>": sa.ne, "<": sa.lt, "<=": sa.le,
                   ">": sa.gt, ">=": sa.ge}[op](sb)
            # A comparison with an empty value is false (same as SQL).
            return res.where(sa.notna() & sb.notna(), False).astype(bool)
        if op == "+" and (_is_texty(a) or _is_texty(b)):
            na, nb = _num_or_none(a, df), _num_or_none(b, df)
            if na is None or nb is None:
                return _text(a, df).fillna("") + _text(b, df).fillna("")
            a, b = na, nb
        a, b = _num(a, df), _num(b, df)
        if op == "+":
            return _as_series(a, df) + b
        if op == "-":
            return _as_series(a, df) - b
        if op == "*":
            return _as_series(a, df) * b
        if op == "/":
            denom = _as_series(b, df).replace(0, np.nan) if isinstance(b, pd.Series) else (np.nan if b == 0 else b)
            return _as_series(a, df) / denom
    if k == "call":
        return _call(node[1], node[2], df)
    raise FormulaError(f"Can't evaluate {k}")


def _num_or_none(v, df):
    """Numeric view of v if every non-null value is numeric, else None."""
    if isinstance(v, pd.Series):
        conv = pd.to_numeric(v, errors="coerce")
        return conv if conv.notna().sum() == v.notna().sum() else None
    if isinstance(v, str):
        try:
            return float(v)
        except ValueError:
            return None
    return v


def _maybe_numeric(s):
    conv = pd.to_numeric(s, errors="coerce")
    if conv.notna().sum() == s.notna().sum() and s.notna().any():
        return conv
    return s


def _call(name, args, df):
    if name == "FIXED":
        agg = _FIXED_AGGS[args[0][1].upper()]
        value_col = _resolve_column(args[1][1], df)
        dim_col = _resolve_column(args[2][1], df)
        result = df.groupby(dim_col)[value_col].transform(agg)
        if len(args) == 4 and args[3][1]:
            try:
                result = pd.to_datetime(result, errors="coerce").dt.strftime(str(args[3][1]))
            except Exception:
                pass
        return result

    vals = [_eval(a, df) for a in args]
    if name in _TEXT_PRED:
        kind, cs = _TEXT_PRED[name]
        s = _text(vals[0], df)
        part = vals[1]
        if isinstance(part, pd.Series):
            p = _text(part, df)
            pairs = zip(s.tolist(), p.tolist())
            def test(x, y):
                if x is None or y is None or (isinstance(x, float) and np.isnan(x)):
                    return False
                x, y = (x, y) if cs else (x.lower(), y.lower())
                return (y in x) if kind == "contains" else (x.startswith(y) if kind == "starts" else x.endswith(y))
            return pd.Series([test(x, y) for x, y in pairs], index=df.index)
        part = "" if part is None else str(part)
        if not cs:
            s, part = s.str.lower(), part.lower()
        if kind == "contains":
            res = s.str.contains(part, regex=False, na=False)
        elif kind == "starts":
            res = s.str.startswith(part, na=False)
        else:
            res = s.str.endswith(part, na=False)
        return res.fillna(False).astype(bool)
    if name == "EXACT":
        a, b = _text(vals[0], df), _text(vals[1], df)
        return a.eq(b).fillna(False).astype(bool)
    if name == "UPPER":
        return _text(vals[0], df).str.upper()
    if name == "LOWER":
        return _text(vals[0], df).str.lower()
    if name == "TRIM":
        return _text(vals[0], df).str.strip()
    if name == "LEN":
        return _text(vals[0], df).str.len()
    if name == "CONCAT":
        out = _text(vals[0], df).fillna("")
        for v in vals[1:]:
            out = out + _text(v, df).fillna("")
        return out
    if name in ("YEAR", "MONTH", "DAY"):
        d = pd.to_datetime(_as_series(vals[0], df), errors="coerce")
        return getattr(d.dt, name.lower())
    if name == "ISNULL":
        return _as_series(vals[0], df).isna()
    if name == "ISNOTNULL":
        return _as_series(vals[0], df).notna()
    raise FormulaError(f"Unknown function: {name}")


def evaluate(formula, df):
    """Evaluate a formula against df; always returns a Series aligned to df."""
    result = _eval(parse(formula), df)
    if isinstance(result, pd.Series):
        return result
    return _as_series(result, df)


# ─────────────────────────────────────────────
# DuckDB SQL translation (for filters)
# ─────────────────────────────────────────────

def _sql_str(v):
    return "'" + str(v).replace("'", "''") + "'"


def _sql_lit(v):
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, (int, float)):
        return repr(v)
    return _sql_str(v)


def _is_text_node(n):
    if n[0] == "lit":
        return isinstance(n[1], str)
    if n[0] == "call":
        return n[1] in ("UPPER", "LOWER", "TRIM", "CONCAT")
    return False


def _is_num_node(n):
    if n[0] == "lit":
        return isinstance(n[1], (int, float)) and not isinstance(n[1], bool)
    if n[0] == "neg":
        return True
    if n[0] == "bin" and n[1] in ("-", "*", "/"):
        return True
    if n[0] == "call":
        return n[1] in ("LEN", "YEAR", "MONTH", "DAY")
    return False


def to_sql(formula, column_for):
    """
    Translate a formula to a DuckDB SQL expression. column_for(name) must return
    the SQL column for a field name, or None if the field isn't queryable.
    Returns None when the formula can't be expressed in SQL (e.g. FIXED).
    """
    try:
        return _sql(parse(formula), column_for)
    except _NotSQL:
        return None


class _NotSQL(Exception):
    pass


def _txt(sql):
    return f"CAST({sql} AS VARCHAR)"


def _sql(n, col):
    k = n[0]
    if k == "lit":
        return _sql_lit(n[1])
    if k == "field":
        c = col(n[1])
        if not c:
            raise _NotSQL(n[1])
        return c
    if k == "neg":
        return f"(-{_sql(n[1], col)})"
    if k == "not":
        return f"(NOT COALESCE({_sql(n[1], col)}, FALSE))"
    if k == "if":
        parts = " ".join(f"WHEN COALESCE({_sql(c, col)}, FALSE) THEN {_sql(v, col)}" for c, v in n[1])
        return f"(CASE {parts} ELSE {_sql(n[2], col)} END)"
    if k == "bin":
        op, a, b = n[1], n[2], n[3]
        sa, sb = _sql(a, col), _sql(b, col)
        if op in ("AND", "OR"):
            return f"(COALESCE({sa}, FALSE) {op} COALESCE({sb}, FALSE))"
        if op in ("=", "<>", "<", "<=", ">", ">="):
            if _is_num_node(a) or _is_num_node(b):
                return f"COALESCE(TRY_CAST({sa} AS DOUBLE) {op} TRY_CAST({sb} AS DOUBLE), FALSE)"
            return f"COALESCE(lower({_txt(sa)}) {op} lower({_txt(sb)}), FALSE)"
        if op == "+" and (_is_text_node(a) or _is_text_node(b)):
            return f"(COALESCE({_txt(sa)}, '') || COALESCE({_txt(sb)}, ''))"
        if op == "/":
            return f"(TRY_CAST({sa} AS DOUBLE) / NULLIF(TRY_CAST({sb} AS DOUBLE), 0))"
        return f"(TRY_CAST({sa} AS DOUBLE) {op} TRY_CAST({sb} AS DOUBLE))"
    if k == "call":
        name, args = n[1], n[2]
        if name == "FIXED":
            raise _NotSQL("FIXED")
        s = [_sql(a, col) for a in args]
        if name in _TEXT_PRED:
            kind, cs = _TEXT_PRED[name]
            x, y = _txt(s[0]), _txt(s[1])
            if not cs:
                x, y = f"lower({x})", f"lower({y})"
            fn = {"contains": "contains", "starts": "starts_with", "ends": "suffix"}[kind]
            return f"COALESCE({fn}({x}, {y}), FALSE)"
        if name == "EXACT":
            return f"COALESCE({_txt(s[0])} = {_txt(s[1])}, FALSE)"
        if name == "UPPER":
            return f"upper({_txt(s[0])})"
        if name == "LOWER":
            return f"lower({_txt(s[0])})"
        if name == "TRIM":
            return f"trim({_txt(s[0])})"
        if name == "LEN":
            return f"length({_txt(s[0])})"
        if name == "CONCAT":
            return "(" + " || ".join(f"COALESCE({_txt(x)}, '')" for x in s) + ")"
        if name in ("YEAR", "MONTH", "DAY"):
            return f"{name.lower()}(TRY_CAST({s[0]} AS TIMESTAMP))"
        if name == "ISNULL":
            return f"({s[0]} IS NULL)"
        if name == "ISNOTNULL":
            return f"({s[0]} IS NOT NULL)"
    raise _NotSQL(k)
