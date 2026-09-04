from dash import html, dcc
import dash_bootstrap_components as dbc
from data.extract import get_extract_info
from utils.config import load_config


def build_settings_layout():
    info = get_extract_info()
    cfg  = load_config()

    if info["exists"]:
        extract_status = dbc.Alert([
            html.Div(html.Span("✅ Current Local Extract", className="fw-bold")),
            html.Div(f"Last refreshed: {info['last_refreshed']}",
                    style={"fontSize": "13px"}),
            html.Div(f"File size: {info['size_mb']} MB",
                    style={"fontSize": "13px"}),
            html.Div(f"Rows: {info['rows']:,}" if info['rows'] else "",
                    style={"fontSize": "13px"}),
        ], color="success", className="mb-0")
    else:
        extract_status = dbc.Alert(
            "⚠️ No extract found. Click Refresh Extract to create one.",
            color="warning", className="mb-0"
        )

    return html.Div([
        html.H4("Settings", className="mb-4 fw-bold"),

        dbc.Row([

            # ── Data Extract ──────────────────────────────
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader(html.H6("🗄 Data Extract",
                                          className="mb-0 fw-bold")),
                    dbc.CardBody([
                        html.P(
                            "The data extract pulls all records from MySQL and saves "
                            "them locally as a Parquet file. Queries run against this "
                            "file are significantly faster than live database queries.",
                            style={"fontSize": "13px"}, className="text-muted mb-3"
                        ),
                        extract_status,
                        html.Div(id="extract-progress-display",
                                className="mt-2", style={"fontSize": "12px"}),
                        html.Div(id="settings-extract-clock",
                                className="mt-1 text-primary fw-bold",
                                style={"fontSize": "12px", "display": "none"}),
                        dbc.Alert([
                            html.Strong("Before refreshing: "),
                        html.Span("Run these exports in MySQL Workbench first:"),
                            html.Div([
                                html.Div([
                                    html.Pre(
                                        "SELECT USAGE_ID, USER_ID, ACTION_TYPE, TABRUN_TS, TABRUN_MY\n"
                                        "INTO OUTFILE 'C:/ProgramData/MySQL/MySQL Server 8.0/Uploads/usagefact_extract.csv'\n"
                                        "FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '\"'\n"
                                        "LINES TERMINATED BY '\\n' FROM usagefact;",
                                        id="sql-query-1",
                                        style={"fontSize": "11px", "backgroundColor": "#f8f9fa",
                                               "padding": "8px", "borderRadius": "4px",
                                               "marginBottom": "4px", "whiteSpace": "pre-wrap"}
                                    ),
                                    dcc.Clipboard(target_id="sql-query-1", title="Copy SQL",
                                                 className="mb-2",
                                                 style={"fontSize": "10px"}),
                                ]),
                                html.Div([
                                    html.Pre(
                                        "SELECT USAGE_ID, STUDY_ID\n"
                                        "INTO OUTFILE 'C:/ProgramData/MySQL/MySQL Server 8.0/Uploads/usagestudylinks_extract.csv'\n"
                                        "FIELDS TERMINATED BY ','\n"
                                        "LINES TERMINATED BY '\\n' FROM usagestudylinks;",
                                        id="sql-query-2",
                                        style={"fontSize": "11px", "backgroundColor": "#f8f9fa",
                                               "padding": "8px", "borderRadius": "4px",
                                               "marginBottom": "4px", "whiteSpace": "pre-wrap"}
                                    ),
                                    dcc.Clipboard(target_id="sql-query-2", title="Copy SQL",
                                                 style={"fontSize": "10px"}),
                                ]),
                            ], className="mt-2")
                        ], color="info", className="mb-3 mt-3", style={"fontSize": "12px"}),

                        html.Div(className="mt-3 d-flex gap-2", children=[
                            dbc.Button("🔄 Refresh Extract",
                                      id="settings-refresh-btn",
                                      color="primary", size="sm"),
                            dbc.Button("⏹ Cancel",
                                      id="settings-cancel-btn",
                                      color="danger", size="sm",
                                      style={"display": "none"}),
                        ]),
                    ])
                ], className="mb-4 shadow-sm"),
            ], width=6),

            # ── Database Connection ───────────────────────
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader(html.H6("🔌 Database Connection",
                                          className="mb-0 fw-bold")),
                    dbc.CardBody([
                        html.P(
                            "Enter your database credentials. "
                            "Changes take effect immediately.",
                            style={"fontSize": "13px"}, className="text-muted mb-3"
                        ),
                        dbc.Row([
                            dbc.Col([
                                dbc.Label("Host", size="sm", className="fw-bold"),
                                dbc.Input(id="cfg-host", value=cfg["DB_HOST"],
                                         size="sm",
                                         placeholder="e.g. 10.30.100.222"),
                            ], width=8),
                            dbc.Col([
                                dbc.Label("Port", size="sm", className="fw-bold"),
                                dbc.Input(id="cfg-port", value=cfg["DB_PORT"],
                                         size="sm", placeholder="3306"),
                            ], width=4),
                        ], className="mb-2"),
                        dbc.Row([
                            dbc.Col([
                                dbc.Label("Database", size="sm",
                                         className="fw-bold"),
                                dbc.Input(id="cfg-dbname", value=cfg["DB_NAME"],
                                         size="sm"),
                            ], width=6),
                            dbc.Col([
                                dbc.Label("User", size="sm", className="fw-bold"),
                                dbc.Input(id="cfg-user", value=cfg["DB_USER"],
                                         size="sm"),
                            ], width=6),
                        ], className="mb-2"),
                        dbc.Label("Password", size="sm", className="fw-bold"),
                        dbc.Input(id="cfg-password", value=cfg["DB_PASSWORD"],
                                 type="password", size="sm", className="mb-2"),
                        dbc.Label("MySQL Upload Path", size="sm",
                                 className="fw-bold"),
                        dbc.Input(id="cfg-upload-path",
                                 value=cfg["MYSQL_UPLOAD_PATH"],
                                 size="sm", className="mb-3",
                                 placeholder=r"\\server\C$\ProgramData\MySQL\..."),
                        dbc.Button("💾 Save Configuration",
                                  id="cfg-save-btn",
                                  color="primary", size="sm"),
                        html.Div(id="cfg-save-msg", className="mt-2",
                                style={"fontSize": "12px"}),
                    ])
                ], className="mb-4 shadow-sm"),
            ], width=6),
        ]),

    ], className="p-4")