import re
from dash import html, dcc, ctx, ALL
import dash_bootstrap_components as dbc

# ─────────────────────────────────────────────
# Field/table definitions
# ─────────────────────────────────────────────

TABLE_FIELDS = {
    "usageclient":    ["CLIENT_ID", "CLIENT_NAME"],
    "usageuser":      ["USER_NAME", "USER_EMAIL", "GROUP_NAME"],
    "usagestudy":     ["LONG_NAME", "EXT_STUDY_ID", "STUDYYEAR"],
    "usagefact":      ["ACTION_TYPE", "ACTION_DATE", "TABRUN_MY", "USAGE_ID"],
    "usageqmnem":     ["QMNEM"],
}

AVAILABLE_FIELDS = [f for fields in TABLE_FIELDS.values() for f in fields]
HEAVY_FIELDS     = {"QMNEM"}
DATE_FIELDS      = {"ACTION_DATE", "TABRUN_MY", "TABRUN_TS"}

FIELD_MAP = {
    "CLIENT_ID":    "c.CLIENT_ID",
    "CLIENT_NAME":  "c.CLIENT_NAME",
    "USER_NAME":    "u.USER_NAME",
    "USER_EMAIL":   "u.USER_EMAIL",
    "GROUP_NAME":   "u.GROUP_NAME",
    "LONG_NAME":    "s.LONG_NAME",
    "EXT_STUDY_ID": "s.EXT_STUDY_ID",
    "STUDYYEAR":    "e.STUDYYEAR",
    "ACTION_TYPE":  "f.ACTION_TYPE",
    "ACTION_DATE":  "DATE(f.TABRUN_TS) as ACTION_DATE",
    "TABRUN_MY":    "f.TABRUN_MY",
    "USAGE_ID":     "f.USAGE_ID",
}

FIELD_TO_TABLE = {
    "CLIENT_ID":    "usageclient",
    "CLIENT_NAME":  "usageclient",
    "USER_NAME":    "usageuser",
    "USER_EMAIL":   "usageuser",
    "GROUP_NAME":   "usageuser",
    "LONG_NAME":    "usagestudy",
    "EXT_STUDY_ID": "usagestudy",
    "STUDYYEAR":    "usagestudy",
    "ACTION_TYPE":  "usagefact",
    "ACTION_DATE":  "usagefact",
    "TABRUN_MY":    "usagefact",
    "USAGE_ID":     "usagefact",
    "QMNEM":        "usageqmnem",
}

HEAVY_FIELD_MAP = {"QMNEM": "q.QMNEM"}

TABLE_LABELS = {
    "usageclient":    "Client",
    "usageuser":      "User",
    "usagestudy":     "Study",
    "usagefact":      "Usage",
    "usageqmnem":     html.Span(["QMnem ⚠️", html.Br(), "(Coming Soon)"]),
}

DATE_FORMAT_OPTIONS = [
    {"label": "Mon/Yr (Jan 2025) — default", "value": "none"},
    {"label": "Quarter (Q1 2025)",            "value": "quarter"},
    {"label": "Year (2025)",                  "value": "year"},
]

DEFAULT_MEASURE_OPTIONS = [
    {"label": "#TabRuns",              "value": "COUNTD_USAGE_ID"},
    {"label": "COUNT(*) — Total rows", "value": "Count"},
]


def get_field_expr(field):
    if field in FIELD_MAP:
        expr = FIELD_MAP[field]
        if " as " in expr.lower():
            return expr.split(" as ")[0].strip()
        return expr
    elif field in HEAVY_FIELD_MAP:
        return HEAVY_FIELD_MAP[field]
    return field


# ─────────────────────────────────────────────
# SQL query builder (MySQL fallback)
# ─────────────────────────────────────────────

def build_query(fields, where_clauses, params, limit=5000):
    needs_qmnem    = any(f in HEAVY_FIELDS for f in fields)
    measure_fields = [f for f in fields if f.startswith("COUNTD(")]
    regular_fields = [f for f in fields if not f.startswith("COUNTD(")]
    client_only    = {"CLIENT_ID", "CLIENT_NAME", "USER_NAME", "USER_EMAIL", "GROUP_NAME"}
    selected_set   = set(regular_fields)

    if selected_set.issubset(client_only) and not needs_qmnem and not measure_fields:
        select_fields = [FIELD_MAP[f] for f in regular_fields]
        group_sql     = ", ".join(select_fields)
        joins = ("FROM usageclient c" if selected_set.issubset({"CLIENT_NAME"})
                 else "FROM usageclient c JOIN usageuser u ON u.CLIENT_ID = c.CLIENT_ID")
        simple_where = [w for w in where_clauses if "c.CLIENT_NAME" in w]
        where_sql = f"WHERE {' AND '.join(simple_where)}" if simple_where else ""
        return f"SELECT {group_sql} {joins} {where_sql} ORDER BY {group_sql} LIMIT {limit}", False

    select_fields, group_fields = [], []
    for f in regular_fields:
        if f in FIELD_MAP:
            expr = FIELD_MAP[f]
            select_fields.append(expr)
            group_fields.append(
                expr.lower().split(" as ")[-1].strip() if " as " in expr.lower() else expr
            )
        elif f in HEAVY_FIELD_MAP:
            expr = HEAVY_FIELD_MAP[f]
            select_fields.append(expr)
            group_fields.append(expr)

    for f in measure_fields:
        m = re.match(r"COUNTD\((\w+)\)", f)
        if m:
            inner = m.group(1)
            expr  = FIELD_MAP.get(inner, f"f.{inner}")
            if " as " in expr.lower():
                expr = expr.split(" as ")[0].strip()
            select_fields.append(f"COUNT(DISTINCT {expr}) as COUNTD_{inner}")

    select_fields.append("COUNT(*) as Count")
    select_sql = ", ".join(select_fields)
    group_sql  = ", ".join(group_fields) if group_fields else "1"

    joins = """
        FROM usageclient c
        JOIN usageuser u ON u.CLIENT_ID = c.CLIENT_ID
        JOIN usagefact f ON f.USER_ID = u.USER_ID
        JOIN usagestudylinks l ON l.USAGE_ID = f.USAGE_ID
        JOIN usagestudy s ON s.STUDY_ID = l.STUDY_ID
        LEFT JOIN study_metadata_enhanced e ON e.PKID = l.STUDY_ID
    """
    if needs_qmnem:
        joins += " JOIN usageqmnem q ON q.USAGE_ID = f.USAGE_ID"

    where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
    return f"""
        SELECT {select_sql}
        {joins}
        {where_sql}
        GROUP BY {group_sql}
        ORDER BY Count DESC
        LIMIT {limit}
    """, needs_qmnem


# ─────────────────────────────────────────────
# Left panel builder
# ─────────────────────────────────────────────

def build_table_panel(worksheet_id, global_calcs=None):
    global_calcs = global_calcs or {}
    
    # Group calcs by table
    calcs_by_table = {}
    for name, defn in global_calcs.items():
        if defn.get("type") == "aggregate":
            field = defn.get("field", "")
        elif defn.get("type") == "fixed_lod":
            field = defn.get("field", "")
        elif defn.get("type") == "formula":
            formula = defn.get("formula", "").upper()
            field = next((f for f in FIELD_TO_TABLE if f.upper() in formula), "")
        else:
            field = ""
        table = FIELD_TO_TABLE.get(field, "usagefact")
        calcs_by_table.setdefault(table, []).append((name, defn))

    sections = []
    for table_key, fields in TABLE_FIELDS.items():
        label = TABLE_LABELS[table_key]
        
        # Regular fields
        field_buttons = [
            html.Div([
                html.Span(field, className="draggable-field", draggable="true",
                         **{"data-field-index": f"{worksheet_id}|{field}"},
                         style={"fontSize": "11px", "flex": "1", "cursor": "grab",
                                "color": "var(--bs-body-color)", "padding": "1px 2px",
                                "borderRadius": "3px"}),
                dbc.Button("R", id={"type": "add-rows-btn", "index": f"{worksheet_id}|{field}"},
                          color="primary", size="sm", outline=True,
                          className="py-0 px-1 me-1", style={"fontSize": "9px", "lineHeight": "1.2"}),
                dbc.Button("C", id={"type": "add-cols-btn", "index": f"{worksheet_id}|{field}"},
                          color="success", size="sm", outline=True,
                          className="py-0 px-1 me-1", style={"fontSize": "9px", "lineHeight": "1.2"}),
                dbc.Button("F", id={"type": "add-filter-btn", "index": f"{worksheet_id}|{field}"},
                          color="warning", size="sm", outline=True,
                          className="py-0 px-1", style={"fontSize": "9px", "lineHeight": "1.2"}),
            ], className="d-flex align-items-center mb-1 px-1")
            for field in fields
        ]
        
        # Add calculations for this table
        table_calcs = calcs_by_table.get(table_key, [])
        calc_buttons = []
        for name, defn in table_calcs:
            calc_buttons.append(html.Div([
                html.Div([
                    html.Span("ƒ", style={"fontSize": "10px", "color": "#6f42c1",
                                          "fontWeight": "bold", "marginRight": "3px"}),
                    html.Span(name, className="draggable-field", draggable="true",
                             **{"data-field-index": f"{worksheet_id}|calc|{name}"},
                             style={"fontSize": "11px", "cursor": "grab",
                                    "whiteSpace": "nowrap", "overflow": "hidden",
                                    "textOverflow": "ellipsis", "flex": "1"}),
                ], style={"display": "flex", "alignItems": "center", "width": "100%"}),
                html.Div([
                    dbc.Button("R", id={"type": "add-rows-btn",   "index": f"{worksheet_id}|calc|{name}"},
                              color="primary", size="sm", outline=True,
                              className="py-0 px-1 me-1", style={"fontSize": "9px", "lineHeight": "1.2"}),
                    dbc.Button("C", id={"type": "add-cols-btn",   "index": f"{worksheet_id}|calc|{name}"},
                              color="success", size="sm", outline=True,
                              className="py-0 px-1 me-1", style={"fontSize": "9px", "lineHeight": "1.2"}),
                    dbc.Button("F", id={"type": "add-filter-btn", "index": f"{worksheet_id}|calc|{name}"},
                              color="warning", size="sm", outline=True,
                              className="py-0 px-1 me-1", style={"fontSize": "9px", "lineHeight": "1.2"}),
                    dbc.Button("✏", id={"type": "edit-calc-btn",  "index": name},
                              color="secondary", size="sm", outline=True,
                              className="py-0 px-1 me-1", style={"fontSize": "9px", "lineHeight": "1.2"},
                              title="Edit"),
                    dbc.Button("✕", id={"type": "delete-calc-btn","index": name},
                              color="danger", size="sm", outline=True,
                              className="py-0 px-1", style={"fontSize": "9px", "lineHeight": "1.2"},
                              title="Delete"),
                ], style={"display": "flex", "marginTop": "2px"}),
            ], className="mb-1"))

        sections.append(html.Div([
            html.Div(label if isinstance(label, str) else label,
                     style={"fontSize": "13px", "fontWeight": "bold",
                                   "color": "#333", "letterSpacing": "0.05em",
                                   "padding": "6px 4px 3px 4px",
                                   "borderBottom": "2px solid #adb5bd",
                                   "marginBottom": "6px"}),
            html.Div(field_buttons + calc_buttons),
        ], className="mb-2"))

    return html.Div([
        html.Div("TABLES", className="fw-bold mb-1 px-1",
                style={"fontSize": "10px", "color": "#888", "letterSpacing": "0.08em"}),
        html.Div(sections),
        dbc.Button("+ Add Calculation",
            id={"type": "open-calc-modal", "index": worksheet_id},
            color="outline-secondary", size="sm",
            className="w-100 mt-2", style={"fontSize": "11px"}),
    ], id={"type": "left-panel", "index": worksheet_id},
       className="p-2 draggable-panel",
       style={"backgroundColor": "#f8f9fa", "height": "100%",
              "overflowY": "auto", "borderRight": "1px solid #dee2e6"})


# ─────────────────────────────────────────────
# Middle panel builder
# ─────────────────────────────────────────────

def build_middle_panel(worksheet_id, measure_options=None):
    measure_options = measure_options or DEFAULT_MEASURE_OPTIONS
    return html.Div([
        html.Div([
            html.Div("VALUES", className="fw-bold mb-1",
                    style={"fontSize": "10px", "color": "#888", "letterSpacing": "0.08em"}),
            dcc.Dropdown(
                id={"type": "measure-select", "index": worksheet_id},
                options=measure_options,
                value="COUNTD_USAGE_ID",
                clearable=False,
                style={"fontSize": "12px"}
            ),
        ], className="mb-3"),
        html.Hr(className="my-2"),
        html.Div([
            html.Div("FILTERS", className="fw-bold mb-1",
                    style={"fontSize": "10px", "color": "#888", "letterSpacing": "0.08em"}),
            html.Div(
                id={"type": "filter-panel", "index": worksheet_id},
                className="drop-zone",
                **{"data-shelf": "filters", "data-worksheet": worksheet_id},
                children=html.Span("Drag fields here or use F button.",
                                  className="text-muted",
                                  style={"fontSize": "11px"}),
            ),
        ]),
        html.Div([
            dbc.Button(
                [html.I(className="bi bi-play-fill me-1"), "Run Query"],
                id={"type": "run-query-btn", "index": worksheet_id},
                color="primary", size="sm",
                disabled=True,
                className="w-100",
                style={"fontSize": "12px"}),
        ], className="mt-3"),
    ], className="p-2",
       style={"backgroundColor": "#fafafa", "height": "100%",
              "overflowY": "auto", "borderRight": "1px solid #dee2e6"})


# ─────────────────────────────────────────────
# Shelf label helper
# ─────────────────────────────────────────────

def _shelf_label(label, color="#6c757d"):
    return html.Span(label, style={
        "fontSize": "10px", "fontWeight": "600", "color": color,
        "letterSpacing": "0.07em", "marginRight": "8px",
        "minWidth": "65px", "display": "inline-block"
    })


# ─────────────────────────────────────────────
# Main layout
# ─────────────────────────────────────────────

def build_layout(worksheet_id):
    return html.Div([

        # Stores
        dcc.Store(id={"type": "ws-rows",         "index": worksheet_id}, data=[], storage_type="memory"),
        dcc.Store(id={"type": "ws-cols",         "index": worksheet_id}, data=[], storage_type="memory"),
        dcc.Store(id={"type": "ws-field-filters","index": worksheet_id}, data={}, storage_type="memory"),
        dcc.Store(id={"type": "ws-date-formats", "index": worksheet_id}, data={}, storage_type="memory"),
        dcc.Store(id={"type": "ws-measure",      "index": worksheet_id}, data="COUNTD_USAGE_ID", storage_type="memory"),
        dcc.Store(id={"type": "ws-filters",      "index": worksheet_id}, data=[], storage_type="memory"),

        # Three-panel flex container
        html.Div([

            # LEFT PANEL
            html.Div(
                children=build_table_panel(worksheet_id),
                style={"width": "175px", "flexShrink": "0",
                       "height": "100%", "overflowY": "auto"}
            ),

            # MIDDLE + RIGHT
            html.Div([

                # MIDDLE PANEL
                html.Div(
                    id={"type": "middle-panel", "index": worksheet_id},
                    children=build_middle_panel(worksheet_id),
                    style={"width": "220px", "flexShrink": "0",
                           "height": "100%", "overflowY": "auto",
                           "borderRight": "1px solid #dee2e6"}
                ),

                # RIGHT AREA — shelves + data
                html.Div([

                    # COLUMNS shelf
                    html.Div([
                        _shelf_label("COLUMNS", "#157347"),
                        html.Div(
                            id={"type": "cols-shelf", "index": worksheet_id},
                            className="d-inline-flex align-items-center flex-wrap gap-1 drop-zone",
                            **{"data-shelf": "cols", "data-worksheet": worksheet_id},
                            style={"flex": "1", "minHeight": "26px"}
                        ),
                    ], className="d-flex align-items-center px-2 py-1 border-bottom",
                       style={"backgroundColor": "#f0fff4", "minHeight": "34px",
                              "flexShrink": "0"}),

                    # ROWS shelf
                    html.Div([
                        _shelf_label("ROWS", "#0a3d6b"),
                        html.Div(
                            id={"type": "rows-shelf", "index": worksheet_id},
                            className="d-inline-flex align-items-center flex-wrap gap-1 drop-zone",
                            **{"data-shelf": "rows", "data-worksheet": worksheet_id},
                            style={"flex": "1", "minHeight": "26px"}
                        ),
                    ], className="d-flex align-items-center px-2 py-1 border-bottom",
                       style={"backgroundColor": "#f0f4ff", "minHeight": "34px",
                              "flexShrink": "0"}),

                    # DATA TABLE — takes all remaining space
                    dcc.Loading(
                        id={"type": "table-loading", "index": worksheet_id},
                        type="circle",
                        color="#0f1f3d",
                        fullscreen=False,
                        children=html.Div(
                            id={"type": "data-table-container", "index": worksheet_id},
                            children=html.Div(
                                "Add fields to Rows and Columns, set filters, then click Run Query.",
                                className="text-muted fst-italic p-4"
                            ),
                            style={"flex": "1", "overflowY": "auto", "overflowX": "auto"}
                        ),
                        style={"flex": "1", "overflow": "hidden",
                               "display": "flex", "flexDirection": "column",
                               "minHeight": "100px"}
                    ),

                ], style={
                    "flex": "1",
                    "display": "flex",
                    "flexDirection": "column",
                    "overflow": "hidden",
                    "minHeight": "0",
                }),

            ], style={
                "flex": "1",
                "display": "flex",
                "flexDirection": "row",
                "overflow": "hidden",
                "minHeight": "0",
            }),

        ], style={
            "display": "flex",
            "flexDirection": "row",
            "flex": "1",
            "overflow": "hidden",
            "minHeight": "0",
        }),

    ], style={
        "height": "100%",
        "overflow": "hidden",
        "display": "flex",
        "flexDirection": "column",
        "minHeight": "0",
    })