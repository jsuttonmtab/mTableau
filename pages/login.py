from dash import html, dcc
import dash_bootstrap_components as dbc

def build_login_layout():
    return html.Div([
        html.Div([
            html.Div([
                html.Img(src="/assets/mtableauLogo2.png",
                         style={"height": "60px", "marginBottom": "20px",
                                "display": "block", "margin": "0 auto"}),
                html.H4("Sign In", className="mb-3 fw-bold text-center"),
                dbc.Input(id="login-email", placeholder="Email",
                         type="email", size="sm", className="mb-2"),
                dbc.Input(id="login-password", placeholder="Password",
                         type="password", size="sm", className="mb-3"),
                dbc.Button("Sign In", id="login-btn",
                          color="primary", className="w-100 mb-2"),
                html.Div(id="login-error", style={"fontSize": "12px"}),
            ], style={"width": "320px", "padding": "30px",
                      "backgroundColor": "white", "borderRadius": "8px",
                      "boxShadow": "0 2px 10px rgba(0,0,0,0.1)"}),
        ], style={"display": "flex", "justifyContent": "center",
                  "alignItems": "center", "minHeight": "100vh",
                  "backgroundColor": "#f0f2f5"}),
    ])

def build_change_password_layout():
    return html.Div([
        html.Div([
            html.Div([
                html.H4("Change Password", className="mb-2 fw-bold text-center"),
                html.P("You must change your password before continuing.",
                       className="text-muted text-center", style={"fontSize": "13px"}),
                dbc.Input(id="cp-new-password", placeholder="New password",
                         type="password", size="sm", className="mb-2"),
                dbc.Input(id="cp-confirm-password", placeholder="Confirm password",
                         type="password", size="sm", className="mb-3"),
                dbc.Button("Change Password", id="cp-btn",
                          color="primary", className="w-100 mb-2"),
                html.Div(id="cp-error", style={"fontSize": "12px"}),
            ], style={"width": "320px", "padding": "30px",
                      "backgroundColor": "white", "borderRadius": "8px",
                      "boxShadow": "0 2px 10px rgba(0,0,0,0.1)"}),
        ], style={"display": "flex", "justifyContent": "center",
                  "alignItems": "center", "minHeight": "100vh",
                  "backgroundColor": "#f0f2f5"}),
    ])
