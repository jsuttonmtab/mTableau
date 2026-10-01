"""
Calculated fields. The formula language and its safe evaluator live in
utils/formula.py; this module keeps the API the app already uses.
"""
from utils.formula import (FormulaError, SUPPORTED_FUNCTIONS, evaluate,  # noqa: F401
                           parse, referenced_fields, is_boolean, to_sql)

# Fields offered when building formulas (and fetched for formulas that use them)
FORMULA_FIELDS = [
    "CLIENT_NAME", "CLIENT_ID",
    "USER_NAME", "USER_EMAIL", "GROUP_NAME",
    "LONG_NAME", "EXT_STUDY_ID", "STUDYID", "STUDYYEAR",
    "ACTION_TYPE", "ACTION_DATE", "TABRUN_MY", "TABRUN_TS", "USAGE_ID",
]


def apply_calculation(formula, df):
    """Evaluate a formula against a DataFrame. Raises ValueError on bad formulas."""
    return evaluate(formula, df)


def formula_source_fields(formula):
    """Known source fields (upper-case FORMULA_FIELDS names) a formula references."""
    try:
        refs = referenced_fields(formula)
    except FormulaError:
        return []
    known = {f.upper(): f for f in FORMULA_FIELDS}
    out = []
    for r in refs:
        f = known.get(r.upper().replace(" ", "_"))
        if f and f not in out:
            out.append(f)
    return out


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
