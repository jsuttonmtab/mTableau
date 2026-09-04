import pandas as pd
import re

# Supported functions
SUPPORTED_FUNCTIONS = {
    "YEAR":       lambda s: pd.to_datetime(s, errors="coerce").dt.year,
    "MONTH":      lambda s: pd.to_datetime(s, errors="coerce").dt.month,
    "DAY":        lambda s: pd.to_datetime(s, errors="coerce").dt.day,
    "UPPER":      lambda s: s.astype(str).str.upper(),
    "LOWER":      lambda s: s.astype(str).str.lower(),
    "LEN":        lambda s: s.astype(str).str.len(),
    "CONCAT":     lambda a, b: a.astype(str) + b.astype(str),
    "CONTAINS":   lambda s, sub: s.astype(str).str.contains(sub, case=False, na=False),
    "STARTSWITH": lambda s, sub: s.astype(str).str.startswith(sub),
    "ENDSWITH":   lambda s, sub: s.astype(str).str.endswith(sub),
}

# Available fields for formula building
FORMULA_FIELDS = [
    "CLIENT_NAME", "CLIENT_ID",
    "USER_NAME", "USER_EMAIL", "GROUP_NAME",
    "LONG_NAME", "EXT_STUDY_ID", "STUDYID", "STUDYYEAR",
    "ACTION_TYPE", "ACTION_DATE", "TABRUN_MY", "TABRUN_TS", "USAGE_ID",
]


def parse_if_formula(formula, df):
    pattern = r"IF\s+(.+?)\s+THEN\s+(.+?)\s+ELSE\s+(.+)$"
    match = re.match(pattern, formula.strip(), re.IGNORECASE)
    if not match:
        return None
    condition_str, true_val, false_val = match.groups()
    for field in sorted(FORMULA_FIELDS, key=len, reverse=True):
        condition_str = condition_str.replace(field, f"df['{field}']")
    try:
        condition = eval(condition_str)
        true_val  = float(true_val)  if _is_number(true_val)  else true_val.strip("'\"")
        false_val = float(false_val) if _is_number(false_val) else false_val.strip("'\"")
        return pd.Series(
            [true_val if c else false_val for c in condition],
            index=df.index
        )
    except Exception as e:
        raise ValueError(f"IF formula error: {e}")


def parse_function_formula(formula, df):
    pattern = r"^(\w+)\((.+)\)$"
    match = re.match(pattern, formula.strip(), re.IGNORECASE)
    if not match:
        return None

    func_name, args_str = match.groups()
    func_name = func_name.upper()

    if func_name not in SUPPORTED_FUNCTIONS:
        raise ValueError(f"Unknown function: {func_name}. "
                        f"Supported: {', '.join(SUPPORTED_FUNCTIONS.keys())}")

    # Split args — but respect quoted strings
    args = _split_args(args_str)
    series_args = []
    for arg in args:
        arg = arg.strip()
        # Quoted string literal — pass as plain string
        if (arg.startswith("'") and arg.endswith("'")) or \
           (arg.startswith('"') and arg.endswith('"')):
            series_args.append(arg[1:-1])
        elif arg in df.columns:
            series_args.append(df[arg])
        elif arg.upper() in df.columns:
            series_args.append(df[arg.upper()])
        else:
            raise ValueError(f"Unknown field: {arg}")

    return SUPPORTED_FUNCTIONS[func_name](*series_args)


def _split_args(args_str):
    """Split function arguments respecting quoted strings."""
    args   = []
    depth  = 0
    current = ""
    in_quote = None
    for ch in args_str:
        if ch in ("'", '"') and in_quote is None:
            in_quote = ch
            current += ch
        elif ch == in_quote:
            in_quote = None
            current += ch
        elif ch == '(' and in_quote is None:
            depth += 1
            current += ch
        elif ch == ')' and in_quote is None:
            depth -= 1
            current += ch
        elif ch == ',' and depth == 0 and in_quote is None:
            args.append(current)
            current = ""
        else:
            current += ch
    if current:
        args.append(current)
    return args

def apply_calculation(formula, df):
    formula = formula.strip()
    if formula.upper().startswith("IF "):
        return parse_if_formula(formula, df)

    # FIXED(agg, value_field, dim_field) — window-style aggregate
    print(f"FIXED CHECK: formula='{formula}', has_4args={',' in formula and formula.count(',') >= 3}")
    fixed_match = re.match(r"^FIXED\((\w+),\s*(\w+),\s*(\w+)(?:,\s*(.+))?\)$", formula.strip(), re.IGNORECASE)
    print(f"FIXED CHECK: match={fixed_match is not None}, groups={fixed_match.groups() if fixed_match else 'None'}")
    if fixed_match:
        agg, value_field, dim_field, date_fmt = fixed_match.groups()
        agg = agg.upper()
        if value_field not in df.columns:
            raise ValueError(f"FIXED: field '{value_field}' not in data. Available: {list(df.columns)}")
        if dim_field not in df.columns:
            raise ValueError(f"FIXED: dimension '{dim_field}' not in data. Available: {list(df.columns)}")
        if agg not in ("MAX", "MIN", "SUM", "COUNT", "MEAN"):
            raise ValueError(f"Unknown aggregate: {agg}. Use MAX, MIN, SUM, COUNT, or MEAN.")
        agg_func = {"MAX": "max", "MIN": "min", "SUM": "sum", "COUNT": "count", "MEAN": "mean"}[agg]
        result = df.groupby(dim_field)[value_field].transform(agg_func)
        if date_fmt:
            date_fmt = date_fmt.strip().strip("'\"")
            try:
                result = pd.to_datetime(result, errors="coerce").dt.strftime(date_fmt)
            except Exception:
                pass
        return result

    if re.match(r"^\w+\(", formula):
        result = parse_function_formula(formula, df)
        if result is not None:
            return result
    return parse_math_formula(formula, df)

def parse_math_formula(formula, df):
    expr = formula.strip()
    for field in sorted(FORMULA_FIELDS + ["Count"], key=len, reverse=True):
        if field in expr and field in df.columns:
            expr = expr.replace(field, f"df['{field}']")
    try:
        result = eval(expr)
        if isinstance(result, pd.Series):
            return result
        return pd.Series([result] * len(df), index=df.index)
    except Exception as e:
        raise ValueError(f"Math formula error: {e}")


def validate_formula(name, formula, df):
    if not name or not name.strip():
        return False, "Please enter a name for the calculation."
    if not formula or not formula.strip():
        return False, "Please enter a formula."
    if name in df.columns:
        return False, f"Field '{name}' already exists. Choose a different name."
    try:
        result = apply_calculation(formula, df)
        if result is None:
            return False, "Could not parse formula."
        return True, None
    except ValueError as e:
        return False, str(e)
    except Exception as e:
        return False, f"Formula error: {e}"


def _is_number(s):
    try:
        float(s)
        return True
    except:
        return False