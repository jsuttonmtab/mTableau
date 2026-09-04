import duckdb
import re
from pathlib import Path
from data.extract import USAGE_PATH, BRIDGE_PATH, STUDY_PATH, USER_GROUP_PATH, EXTRACT_PATH

# ── Field registry ────────────────────────────────────────────────────────────
#
# Each entry maps a logical field name to:
#   col    — the SQL expression to use in SELECT / WHERE / GROUP BY
#   table  — which parquet file owns this field:
#              'usage'      — usage.parquet       (USAGE_ID grain)
#              'user_group' — user_group.parquet  (USER_ID × GROUP_NAME grain)
#              'study'      — study.parquet        (STUDY_ID grain)
#
# USER_ID is the invisible plumbing joining usage ↔ user_group.
# It never appears on a shelf — USER_NAME is the front-end display column.
#

FIELD_REGISTRY = {
    # ── Usage-grain fields (usage.parquet) ───────────────────────────────────
    "USAGE_ID":     {"col": "u.USAGE_ID",     "table": "usage"},
    "ACTION_TYPE":  {"col": "u.ACTION_TYPE",  "table": "usage"},
    "TABRUN_TS":    {"col": "u.TABRUN_TS",    "table": "usage"},
    "TABRUN_MY":    {"col": "u.TABRUN_MY",    "table": "usage"},
    "ACTION_DATE":  {"col": "u.ACTION_DATE",  "table": "usage"},
    "USER_NAME":    {"col": "u.USER_NAME",    "table": "usage"},
    "USER_EMAIL":   {"col": "u.USER_EMAIL",   "table": "usage"},
    "CLIENT_NAME":  {"col": "u.CLIENT_NAME",  "table": "usage"},

    # ── User-group fields (user_group.parquet via USER_ID) ───────────────────
    # Joining on USER_ID (integer, invisible) fans out intentionally when
    # GROUP_NAME is on the shelf — COUNT(DISTINCT u.USAGE_ID) deduplicates.
    "GROUP_NAME":   {"col": "ug.GROUP_NAME",  "table": "user_group"},

    # ── Study-grain fields (study.parquet via bridge) ────────────────────────
    "STUDY_ID":     {"col": "s.STUDY_ID",     "table": "study"},
    "EXT_STUDY_ID": {"col": "s.EXT_STUDY_ID", "table": "study"},
    "LONG_NAME":    {"col": "s.LONG_NAME",     "table": "study"},
    "STUDYID":      {"col": "s.STUDYID",       "table": "study"},
    "STUDYYEAR":    {"col": "s.STUDYYEAR",     "table": "study"},

    # ── Legacy alias ─────────────────────────────────────────────────────────
    "CLIENT_ID":    {"col": "u.CLIENT_NAME",  "table": "usage"},
}

# Convenience: plain col expression for backward-compat callers
PARQUET_FIELD_MAP = {k: v["col"] for k, v in FIELD_REGISTRY.items()}

# Fields by table — used to decide which joins to include
STUDY_FIELDS      = {k for k, v in FIELD_REGISTRY.items() if v["table"] == "study"}
USER_GROUP_FIELDS = {k for k, v in FIELD_REGISTRY.items() if v["table"] == "user_group"}

# ── Date formatting ───────────────────────────────────────────────────────────

DATE_FORMAT_MAP = {
    "year":              "CAST(YEAR({col}) AS VARCHAR)",
    "year_month":        "STRFTIME({col}, '%Y-%m')",
    "month_name":        "STRFTIME({col}, '%B %Y')",
    "month_abbrev":      "STRFTIME({col}, '%b %Y')",
    "month_num":         "STRFTIME({col}, '%m %Y')",
    "month_num_nz":      "CONCAT(CAST(MONTH({col}) AS VARCHAR), ' ', CAST(YEAR({col}) AS VARCHAR))",
    "quarter":           "CONCAT('Q', CAST(QUARTER({col}) AS VARCHAR), ' ', CAST(YEAR({col}) AS VARCHAR))",
    "month_only":        "STRFTIME({col}, '%B')",
    "month_only_abbrev": "STRFTIME({col}, '%b')",
    "month_only_num":    "STRFTIME({col}, '%m')",
    "month_only_num_nz": "CAST(MONTH({col}) AS VARCHAR)",
}

# Date fields that default to month_abbrev when no format is explicitly set
DATE_FIELDS_DEFAULT_FMT = {"TABRUN_MY", "ACTION_DATE"}

# ── Measure definitions ───────────────────────────────────────────────────────
#
# Values are callables that accept no arguments and return a SQL fragment.
# This makes it trivial to add new measures without touching build_duckdb_query.
#
MEASURE_MAP = {
    "Count":               "COUNT(*) AS Count",
    "COUNTD_USAGE_ID":     "COUNT(DISTINCT u.USAGE_ID) AS Count",
    "COUNTD_USER_NAME":    "COUNT(DISTINCT u.USER_NAME) AS Count",
    "COUNTD_CLIENT_NAME":  "COUNT(DISTINCT u.CLIENT_NAME) AS Count",
    "COUNTD_EXT_STUDY_ID": "COUNT(DISTINCT s.EXT_STUDY_ID) AS Count",
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def extract_available():
    """True when the four-file extract is present (or legacy single file)."""
    from data.extract import extract_exists
    return extract_exists() or EXTRACT_PATH.exists()


def _needs_user_group_join(fields, where_clauses, global_calcs):
    """True if GROUP_NAME appears anywhere in the query."""
    for f in fields:
        if f in USER_GROUP_FIELDS:
            return True
    where_text = " ".join(where_clauses)
    for f in USER_GROUP_FIELDS:
        if f in where_text:
            return True
    for defn in (global_calcs or {}).values():
        if isinstance(defn, dict):
            if defn.get("dim",   "") in USER_GROUP_FIELDS:
                return True
            if defn.get("field", "") in USER_GROUP_FIELDS:
                return True
    return False


def _needs_study_join(fields, where_clauses, measure_sql, global_calcs):
    """True if any study-grain field appears anywhere in the query."""
    for f in fields:
        if f in STUDY_FIELDS:
            return True
    where_text = " ".join(where_clauses)
    for sf in STUDY_FIELDS:
        if sf in where_text:
            return True
    if any(sf in measure_sql for sf in STUDY_FIELDS):
        return True
    for defn in (global_calcs or {}).values():
        if isinstance(defn, dict):
            if defn.get("dim",   "") in STUDY_FIELDS:
                return True
            if defn.get("field", "") in STUDY_FIELDS:
                return True
    return False


def _build_from_clause(need_user_group, need_study):
    """
    Returns the FROM … JOIN block, including only the joins actually needed.

    Usage only:
        FROM read_parquet('usage.parquet') u

    + GROUP_NAME:
        FROM read_parquet('usage.parquet') u
        JOIN read_parquet('user_group.parquet') ug ON u.USER_ID = ug.USER_ID

    + study fields (with or without group):
        FROM read_parquet('usage.parquet') u
        [JOIN read_parquet('user_group.parquet') ug ON u.USER_ID = ug.USER_ID]
        JOIN read_parquet('bridge.parquet') b ON u.USAGE_ID = b.USAGE_ID
        JOIN read_parquet('study.parquet')  s ON b.STUDY_ID = s.STUDY_ID

    The user_group join fans out intentionally when GROUP_NAME is on the shelf.
    COUNT(DISTINCT u.USAGE_ID) deduplicates correctly in all cases.
    """
    usage_path      = str(USAGE_PATH)
    user_group_path = str(USER_GROUP_PATH)
    bridge_path     = str(BRIDGE_PATH)
    study_path      = str(STUDY_PATH)

    clause = f"FROM read_parquet('{usage_path}') u"

    if need_user_group:
        clause += (
            f"\n        JOIN read_parquet('{user_group_path}') ug"
            f" ON u.USER_ID = ug.USER_ID"
        )

    if need_study:
        clause += (
            f"\n        JOIN read_parquet('{bridge_path}') b"
            f" ON u.USAGE_ID = b.USAGE_ID"
            f"\n        JOIN read_parquet('{study_path}') s"
            f" ON b.STUDY_ID = s.STUDY_ID"
        )

    return clause


def run_extract_query(sql):
    con    = duckdb.connect()
    result = con.execute(sql).fetchdf()
    con.close()
    return result


# ── Main query builder ────────────────────────────────────────────────────────

def build_duckdb_query(fields, where_clauses, limit=None,
                       date_formats=None, measure="COUNTD_USAGE_ID",
                       global_calcs=None):
    date_formats = date_formats or {}
    global_calcs = global_calcs or {}

    # ── Resolve measure SQL ───────────────────────────────────────────────────
    if measure and measure.startswith("calc_"):
        calc_name = measure[5:]
        calc_defn = global_calcs.get(calc_name, {})
        if isinstance(calc_defn, dict) and calc_defn.get("type") == "aggregate":
            func  = calc_defn.get("func", "COUNT")
            field = calc_defn.get("field", "USAGE_ID")
            col   = FIELD_REGISTRY.get(field, {}).get("col", field)
            if func == "COUNTD":
                measure_sql = f"COUNT(DISTINCT {col}) AS Count"
            else:
                measure_sql = f"{func}({col}) AS Count"
        else:
            measure_sql = MEASURE_MAP["COUNTD_USAGE_ID"]
    else:
        measure_sql = MEASURE_MAP.get(measure, "COUNT(DISTINCT u.USAGE_ID) AS Count")

    # ── Separate LOD calcs ────────────────────────────────────────────────────
    lod_calcs = {
        name: defn for name, defn in global_calcs.items()
        if isinstance(defn, dict) and defn.get("type") == "fixed_lod"
    }
    # ── Separate LOD calcs ────────────────────────────────────────────────────
    # Only include LOD calcs that are actually in the query fields
    lod_calcs = {}
    for f in fields:
        calc_name = f[5:] if f.startswith("calc_") else f
        defn = global_calcs.get(calc_name, {})
        if isinstance(defn, dict) and defn.get("type") == "fixed_lod":
            lod_calcs[calc_name] = defn
    has_lod = bool(lod_calcs)

    # ── Determine which joins are needed ─────────────────────────────────────
    # Exclude LOD calc fields from regular fields — they're handled as window functions
    lod_field_names = set()
    for name in lod_calcs:
        lod_field_names.add(name)
        lod_field_names.add(f"calc_{name}")
    regular_fields = [f for f in fields if f not in lod_field_names and not f.startswith("COUNTD(")]
    need_user_group  = _needs_user_group_join(regular_fields, where_clauses, lod_calcs)
    need_study       = _needs_study_join(regular_fields, where_clauses, measure_sql, lod_calcs)
    from_clause      = _build_from_clause(need_user_group, need_study)

    # ── Build SELECT + GROUP BY lists ─────────────────────────────────────────
    select_fields = []
    group_fields  = []   # what we GROUP BY (alias or raw col expression)

    for f in regular_fields:
        col = FIELD_REGISTRY.get(f, {}).get("col", f)

        # Resolve date format
        fmt = date_formats.get(f, "none")
        if fmt == "none" and f in DATE_FIELDS_DEFAULT_FMT:
            fmt = "month_abbrev"

        if fmt != "none" and fmt in DATE_FORMAT_MAP:
            col_expr = DATE_FORMAT_MAP[fmt].replace("{col}", col)
            select_fields.append(f"{col_expr} AS {f}")
            group_fields.append(f)            # group by alias
        elif "(" in col:
            # Expression column (e.g. u.ACTION_DATE already has no parens,
            # but a future computed field might).
            select_fields.append(f"{col} AS {f}")
            group_fields.append(f)
        else:
            select_fields.append(col)
            group_fields.append(col)

    select_fields.append(measure_sql)

    select_sql = ", ".join(select_fields)
    group_sql  = ", ".join(group_fields) if group_fields else "1"
    all_where = list(where_clauses)
    where_sql   = f"WHERE {' AND '.join(all_where)}"

    # ── Build ORDER BY ────────────────────────────────────────────────────────
    # Date-formatted fields sort by their underlying raw column so the result
    # is chronological rather than alphabetical.
    order_parts = []
    for g in group_fields:
        fmt = date_formats.get(g, "none")
        if fmt == "none" and g in DATE_FIELDS_DEFAULT_FMT:
            fmt = "month_abbrev"
        if fmt != "none":
            raw_col = FIELD_REGISTRY.get(g, {}).get("col", g)
            order_parts.append(raw_col)
        else:
            # Only wrap simple field names, not expressions
            if "(" in g or " " in g or "." in g:
                order_parts.append(g)
            else:
                order_parts.append(f"LOWER({g})")

    # Strip table aliases for outer query ordering
    order_parts = [p.split(".")[-1] if "." in p and p != "Count DESC" else p for p in order_parts]
    order_parts.append("Count DESC")
    order_sql    = ", ".join(order_parts)
    limit_clause = f"LIMIT {limit}" if limit else ""

    # ── Simple query (no LOD) ─────────────────────────────────────────────────
    if not has_lod:
        return f"""
            SELECT {select_sql}
            {from_clause}
            {where_sql}
            GROUP BY {group_sql}
            ORDER BY {order_sql}
            {limit_clause}
        """

    # ── LOD query — window functions in a subquery ────────────────────────────
    #
    # Pattern (unchanged from original, just with table-aliased columns):
    #
    #   SELECT outer_dims, MAX("calc") AS "calc", COUNT(DISTINCT u.USAGE_ID) AS Count
    #   FROM (
    #       SELECT inner_cols,
    #              AGG(field) OVER (PARTITION BY dim) AS "calc"
    #       FROM usage u [JOIN bridge b … JOIN study s …]
    #       WHERE …
    #   ) inner_q
    #   GROUP BY outer_dims
    #   ORDER BY …
    #
    inner_cols = list(dict.fromkeys(group_fields))  # dedupe, preserve order

    for defn in lod_calcs.values():
        dim_field   = FIELD_REGISTRY.get(defn.get("dim",   ""), {}).get("col", defn.get("dim",   ""))
        value_field = FIELD_REGISTRY.get(defn.get("field", ""), {}).get("col", defn.get("field", ""))
        if dim_field   not in inner_cols: inner_cols.append(dim_field)
        if value_field not in inner_cols: inner_cols.append(value_field)

    # USAGE_ID is needed for COUNT DISTINCT in the outer query
    usage_id_col = FIELD_REGISTRY["USAGE_ID"]["col"]  # "u.USAGE_ID"
    if usage_id_col not in inner_cols:
        inner_cols.append(usage_id_col)

    inner_select = ", ".join(inner_cols)

    lod_window_exprs = []
    for calc_name, defn in lod_calcs.items():
        dim_col   = FIELD_REGISTRY.get(defn.get("dim",   ""), {}).get("col", defn.get("dim",   ""))
        agg       = defn.get("agg", "MAX")
        value_col = FIELD_REGISTRY.get(defn.get("field", ""), {}).get("col", defn.get("field", ""))
        lod_window_exprs.append(
            f'{agg}({value_col}) OVER (PARTITION BY {dim_col}) AS "{calc_name}"'
        )

    lod_window_sql = ", ".join(lod_window_exprs)

    # Strip table aliases for outer query (inner_q doesn't have u., s., etc.)
    outer_group_fields = [g.split(".")[-1] if "." in g else g for g in group_fields]
    outer_group    = ", ".join(outer_group_fields) if outer_group_fields else "1"
    outer_dim_cols = ", ".join(outer_group_fields)
    outer_lod_cols = ", ".join(
        [f'MAX("{name}") AS "{name}"' for name in lod_calcs.keys()]
    )

    # LOD calcs that are on rows/cols need to be in GROUP BY too
    lod_on_rows = []
    for f in fields:
        calc_name = f[5:] if f.startswith("calc_") else f
        if calc_name in lod_calcs:
            lod_on_rows.append(f'"{calc_name}"')
            
   # Strip table aliases from measure for outer query
    outer_measure_sql = measure_sql
    for alias in ("u.", "s.", "ug.", "b."):
        outer_measure_sql = outer_measure_sql.replace(alias, "")

    outer_select_parts = []
    if group_fields:
        outer_select_parts.append(outer_dim_cols)
    if lod_on_rows:
        # These LOD calcs are dimensions (on rows/cols), not aggregated
        outer_select_parts.extend(lod_on_rows)
    # LOD calcs NOT on rows still get MAX'd
    lod_not_on_rows = [
        f'MAX("{name}") AS "{name}"' for name in lod_calcs
        if name not in [f[5:] if f.startswith("calc_") else f for f in fields]
    ]
    if lod_not_on_rows:
        outer_select_parts.append(", ".join(lod_not_on_rows))
    outer_select_parts.append(outer_measure_sql)
    outer_select = ", ".join(outer_select_parts)

    # Update GROUP BY to include LOD fields that are on rows/cols
    if lod_on_rows:
        if outer_group == "1":
            outer_group = ", ".join(lod_on_rows)
        else:
            outer_group = outer_group + ", " + ", ".join(lod_on_rows)

    return f"""
        SELECT {outer_select}
        FROM (
            SELECT {inner_select}, {lod_window_sql}
            {from_clause}
            {where_sql}
        ) inner_q
        GROUP BY {outer_group}
        ORDER BY {order_sql}
        {limit_clause}
    """