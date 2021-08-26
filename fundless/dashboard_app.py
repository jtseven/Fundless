import dash
import dash_core_components as dcc
import dash_html_components as html
import dash_bootstrap_components as dbc
from dash.dependencies import Output, Input, State
import secrets
import flask
from flask_login import login_user, LoginManager, UserMixin, logout_user, current_user
import datetime

from config import Config
from analytics import PortfolioAnalytics

secret_key = secrets.token_hex(24)


class User(UserMixin):
    def __init__(self, username):
        self.id = username


################################################################################################################
#                                                  Layouts                                                     #
################################################################################################################


# Login screen
def create_login_layout():
    username_input = dbc.FormGroup(
        [
            dbc.Label("Username", html_for='username_input'),
            dbc.Input(type='text', id='username_input', placeholder='Enter username', autoFocus=True),
        ]
    )
    password_input = dbc.FormGroup(
        [
            dbc.Label('Password', html_for='password_input'),
            dbc.Input(
                type='password',
                id='password_input',
                placeholder='Enter password'
            ),
            dbc.FormText(
                'Forgot your password? Too bad...', color='secondary'
            )
        ]
    )

    return html.Div(
        [dcc.Location(id='url_login', refresh=True),
         dbc.Container(dbc.Row(dbc.Col(dbc.Card(
             [
                 html.Div([
                     html.H2('FundLess', className='card-title text-info'),
                     html.H6('Please login', className='card-subtitle')
                 ], style={'textAlign': 'center'}),
                 dbc.Form([
                     username_input,
                     password_input,
                     dbc.Button('Login', color='primary', id='login_button', block=True),
                     dbc.Alert('Incorrect username or password', id='output-state', is_open=False, color='danger',
                               style={'margin': '1rem'})
                 ], id='login_form'),
             ],
             body=True,
             style={'width': '22rem',
                    # 'height': '26rem'
                    }
         ), align='center', width='auto', style={'height': '100%', 'padding-top': '15%'}),
             justify='center'),
         )
         ],
    )

# Logout screen
def create_logout_layout():
    return html.Div(dbc.Row([
        dbc.Card(
            [html.Div(html.H4('You have been logged out')),
             html.Div(html.H6('- Good Bye -')),
             dbc.Button('Login', href='/login', color='primary')],
            style={'padding': '2rem 2rem'}
        )
    ], justify='center', style={'padding-top': '15%'}), style=dict(textAlign='center'))  # end div


# Sidebar
def create_page_with_sidebar(content):
    sidebar_header = dbc.Row(
        [
            dbc.Col(html.H2("Fundless", className="display-4")),
            dbc.Col(
                html.Button(
                    # use the Bootstrap navbar-toggler classes to style the toggle
                    html.Span(className="navbar-toggler-icon"),
                    className="navbar-toggler",
                    # the navbar-toggler classes don't set color, so we do it here
                    style={
                        "color": "rgba(0,0,0,.5)",
                        "border-color": "rgba(0,0,0,.1)",
                    },
                    id="toggle",
                ),
                # the column containing the toggle will be only as wide as the
                # toggle, resulting in the toggle being right aligned
                width="auto",
                # vertically align the toggle in the center
                align="center",
            ),
        ], no_gutters=True
    )

    sidebar = html.Div(
        [
            sidebar_header,
            # we wrap the horizontal rule and short blurb in a div that can be
            # hidden on a small screen
            html.Div(
                [
                    html.Hr(),
                    html.P(
                        "Passively invest into the world of crypto",
                        className="lead",
                    ),
                ],
                id="blurb",
            ),
            # use the Collapse component to animate hiding / revealing links
            dbc.Collapse(
                dbc.Nav(
                    [
                        dbc.NavLink(
                            [html.I(className='fas fa-chart-line mr-2 nav-icon'), html.Span('Dashboard')],
                            href="/dashboard", active="exact", className='navbar-element'
                        ),
                        dbc.NavLink(
                            [html.I(className='fas fa-align-justify mr-2 nav-icon'), html.Span('Holdings')],
                            href="/holdings", active="exact", disabled=True, className='navbar-element'
                        ),
                        dbc.NavLink(
                            [html.I(className='fas fa-chess mr-2 nav-icon'), html.Span('Strategy')],
                            href="/strategy", active="exact", disabled=True, className='navbar-element'
                        ),
                        dbc.Button(id='user-status-div', color='primary', block=True)
                    ],
                    vertical=True,
                    pills=True,
                    id='sidebar-nav'
                ),
                id="collapse",
            ),
        ],
        id="sidebar",
        className='sticky-top'
    )

    page = html.Div([
        sidebar,
        html.Div(children=content, id='sidebar-page-content')
    ])
    return html.Div([page])


################################################################################################################
#                                            Dashboard Class                                                   #
################################################################################################################
class Dashboard:
    app: dash.Dash
    analytics: PortfolioAnalytics
    config: Config

    def __init__(self, config: Config, analytics: PortfolioAnalytics):
        server = flask.Flask(__name__)
        external_stylesheets = [
            # "https://cdn.jsdelivr.net/npm/@fortawesome/fontawesome-free@5.15.4/css/fontawesome.min.css",
            dbc.themes.LITERA,  # FLATLY, LITERA, YETI
            'https://use.fontawesome.com/releases/v5.15.1/css/all.css',

        ]
        self.app = dash.Dash(name=__name__, external_stylesheets=external_stylesheets, server=server,
                             title='FundLess', update_title='FundLess...', suppress_callback_exceptions=False,
                             meta_tags=[
                                 {"name": "viewport", "content": "width=device-width, initial-scale=1"},
                             ]
                             )
        self.config = config
        self.analytics = analytics

        # Preload data heavy figures
        self.allocation_chart = self.analytics.allocation_pie(title=False)
        self.history_chart = self.analytics.value_history_chart(title=False)
        self.performance_chart = self.analytics.performance_chart(title=False)
        self.update_portfolio_metrics()

        # config flask login
        server.config.update(SECRET_KEY=secret_key)
        if config.dashboard_config.domain_name:
            server.config.update(SERVER_NAME=f'{config.dashboard_config.domain_name}:{80}')

        # Login manager object will be used to login / logout users
        login_manager = LoginManager()
        login_manager.init_app(server)
        login_manager.login_view = '/login'

        # Main Layout
        self.app.layout = html.Div([
            dcc.Location(id='url', refresh=False),
            dcc.Location(id='redirect', refresh=True),
            dcc.Store(id='login-status', storage_type='session'),
            # html.Div(id='user-status-div', style=dict(textAlign='right')),
            html.Div(id='page-content'),
            # update UI charts and info cards
            dcc.Interval(id='update-interval', interval=10 * 1000, n_intervals=0),
            html.Div(id='dummy', style={'display': 'none'}),
            html.Div(id='dummy2', style={'display': 'none'}),

        ])

        @login_manager.user_loader
        def load_user(username):
            """
                This function loads the user by user id. Typically this looks up the user from a user database.
                We won't be registering or looking up users in this example, since we'll just login using LDAP server.
                So we'll simply return a User object with the passed in username.
            """
            return User(username)

        # add callback for toggling the collapse of navbar on small screens
        @self.app.callback(
            Output("navbar-collapse", "is_open"),
            [Input("navbar-toggler", "n_clicks")],
            [State("navbar-collapse", "is_open")],
        )
        def toggle_navbar_collapse(n, is_open):
            if n:
                return not is_open
            return is_open

        @self.app.callback(
            Output("collapse", "is_open"),
            [Input("toggle", "n_clicks")],
            [State("collapse", "is_open")],
        )
        def toggle_collapse(n, is_open):
            if n:
                return not is_open
            return is_open

        # Login callback
        @self.app.callback(
            [Output('url_login', 'pathname'), Output('output-state', 'is_open')],
            [Input('login_form', 'n_submit')],
            [State('username_input', 'value'), State('password_input', 'value')]
        )
        def login_button_click(n, username: str, password: str):
            if username:
                username = username.lower().strip()
            if n:
                if n > 0:
                    if username == config.secrets.dashboard_user and password == config.secrets.dashboard_password:
                        user = User(username)
                        login_user(user)
                        return '/dashboard', False
                    else:
                        return '/login', True
            else:
                return '/login', False

        # Update pie chart and info cards (quick)
        @self.app.callback(Output('allocation_chart', 'figure'), Output('info_cards', 'children'),
                           Input('update-interval', 'n_intervals'),
                           State('chart_time_range', 'value'), State('chart_tabs', 'active_tab'))
        def update_charts_quick(_, chart_range, active_tab):
            self.allocation_chart = analytics.allocation_pie(title=False)
            info_cards = self.create_info_cards()
            return self.allocation_chart, info_cards

        # Update markets from API (quick)
        @self.app.callback(Output('dummy2', 'children'),
                           Input('update-interval', 'n_intervals'))
        def update_data_quick(_):
            self.analytics.update_trades_df()
            self.analytics.update_markets()
            return None

        # Update performance and history charts
        @self.app.callback(Output('chart', 'figure'),
                           Input('update-interval', 'n_intervals'),
                           Input('chart_time_range', 'value'), Input('chart_tabs', 'active_tab'))
        def update_charts_slow(_, chart_range, active_tab):
            timestamp = self.get_timerange(chart_range)
            self.performance_chart = self.analytics.performance_chart(from_timestamp=timestamp, title=False)
            self.history_chart = analytics.value_history_chart(from_timestamp=timestamp, title=False)
            if active_tab == 'history_tab':
                chart = self.history_chart
            elif active_tab == 'performance_tab':
                chart = self.performance_chart
            else:
                print('Invalid tab selected!')
                chart = None
            return chart

        # Update price history from API (slow)
        @self.app.callback(Output('dummy', 'children'),
                           Input('update-interval', 'n_intervals'))
        def update_data_slow(_):
            self.analytics.update_historical_prices()
            return None

        # Check login status to show correct login/logout button
        @self.app.callback(Output('user-status-div', 'children'), Output('user-status-div', 'href'),
                           Output('login-status', 'data'),
                           [Input('url', 'pathname')])
        def login_status(url):
            """ callback to display login/logout link in the header """
            if hasattr(current_user, 'is_authenticated') and current_user.is_authenticated \
                    and url != '/logout':  # If the URL is /logout, then the user is about to be logged out anyways
                return 'Logout', '/logout', current_user.get_id()
            elif url == '/login':
                # do not show login button, if already on login screen
                return None, None, 'loggedout'
            else:
                return 'Login', '/login', 'loggedout'

        def create_not_implemented(name: str):
            return dbc.Jumbotron(
                [
                    html.H1(f"{name} not found", className="text-info"),
                    html.Hr(),
                    html.P(f"This page is not yet implemented"),
                ]
            )

        def create_404(pathname: str):
            return dbc.Jumbotron(
                [
                    html.H1("404: Not found", className="text-danger"),
                    html.Hr(),
                    html.P(f"The pathname {pathname} was not recognised..."),
                ]
            )

        # Page forward callback
        @self.app.callback(Output('page-content', 'children'), Output('redirect', 'pathname'),
                           [Input('url', 'pathname')])
        def display_page(pathname):
            """ callback to determine layout to return """
            view = None
            url = dash.no_update
            if pathname == '/login':
                if current_user.is_authenticated:
                    view = 'Already logged in, forwarding...'
                    url = '/dashboard'
                else:
                    view = create_login_layout()
            elif pathname == '/dashboard':
                if current_user.is_authenticated:
                    view = create_page_with_sidebar(self.create_dashboard())
                else:
                    view = create_login_layout()
            elif pathname == '/holdings':
                if current_user.is_authenticated:
                    view = create_page_with_sidebar(create_not_implemented('Holdings'))
                else:
                    view = create_login_layout()
            elif pathname == '/strategy':
                if current_user.is_authenticated:
                    view = create_page_with_sidebar(create_not_implemented('Strategy'))
                else:
                    view = create_login_layout()
            elif pathname == '/logout':
                if current_user.is_authenticated:
                    logout_user()
                    view = create_logout_layout()
                else:
                    view = create_login_layout()
                    url = '/login'
            else:  # You could also return a 404 "URL not found" page here
                if current_user.is_authenticated:
                    view = create_page_with_sidebar(self.create_dashboard())
                else:
                    view = 'Redirecting to login...'
                    url = '/login'
            return view, url

    def run_dashboard(self):
        host = '0.0.0.0'
        self.app.run_server(host=host, port=80,
                            debug=False)  # as the dashboard runs in a separate thread, debug mode is not supported

    def update_portfolio_metrics(self):
        symbols, amounts, values, allocations = self.analytics.index_balance()
        self.net_worth = values.sum()
        self.performance = self.analytics.performance(self.net_worth)
        self.invested = self.analytics.invested()
        top_gainers = self.analytics.index_df.sort_values('performance', ascending=False).head(3)
        worst_gainers = self.analytics.index_df.sort_values('performance', ascending=True).head(3)
        self.top_symbols = top_gainers['symbol'].values
        self.top_performances = top_gainers['performance'].values
        self.top_growth = top_gainers['value'].values - top_gainers['cost'].values
        self.worst_symbols = worst_gainers['symbol'].values
        self.worst_performances = worst_gainers['performance'].values
        self.worst_growth = worst_gainers['value'].values - worst_gainers['cost'].values

    def get_timerange(self, value: str):
        now = datetime.datetime.now()
        if value == 'day':
            timestamp = (now - datetime.timedelta(days=1)).timestamp()
        elif value == 'week':
            timestamp = (now - datetime.timedelta(weeks=1)).timestamp()
        elif value == 'month':
            timestamp = (now - datetime.timedelta(days=30)).timestamp()
        elif value == '6month':
            timestamp = (now - datetime.timedelta(days=182)).timestamp()
        elif value == 'year':
            timestamp = (now - datetime.timedelta(days=365)).timestamp()
        else:
            timestamp = None
        return timestamp

    ################################################################################################################
    #                                                  Layouts                                                     #
    ################################################################################################################

    def create_info_cards(self):
        self.update_portfolio_metrics()
        currency_symbol = self.config.trading_bot_config.base_currency.values[1]
        if self.performance > 0:
            color = 'text-success'
            prefix = '+ '
        else:
            color = 'text-danger'
            prefix = ''

        def get_color(val: float):
            if val >= 0:
                return 'success'
            else:
                return 'danger'
        # Info Cards
        card_row_1 = dbc.Row(
            [
                dbc.Col(
                    dbc.Card([
                        dbc.CardBody(
                            [
                                # html.I(className='fa-solid fa-up', style={'fontsize': '36'}),
                                html.H1('Portfolio value', className='small text-secondary'),
                                html.H5(f'{self.net_worth:,.2f} {currency_symbol}', className='card-text'),
                                html.H6(f'{prefix}{self.performance:,.2%}', className=f'card-text {color}')
                            ]
                        )
                    ], color='secondary', outline=True),
                    xs=6, style={'margin': '1rem 0rem'}
                ),
                dbc.Col(
                    dbc.Card([
                        dbc.CardBody(
                            [
                                html.H1(f'Invested amount', className='small text-secondary'),
                                html.H5(f'{self.invested:,.2f} {currency_symbol}', className=f'card-text'),
                                html.H6(f'{prefix}{self.net_worth - self.invested:,.2f} {currency_symbol}',
                                        className=f'card-text {color}')
                            ]
                        )
                    ], color='secondary', outline=True),
                    xs=6, style={'margin': '1rem 0rem'}
                ),
            ],
            className='mb-6',
        )
        card_row_2 = dbc.Row(
            [
                dbc.Col(
                    dbc.Card([
                        dbc.CardBody(
                            [
                                html.H1(f'Winners', className='small text-secondary')
                            ] + [html.H6([f"{sym}",
                                          dbc.Badge(f"{perf:.2%}", className="ml-1", color=get_color(perf), pill=True),
                                          dbc.Badge(f"{pl:,.2f} {currency_symbol}", className="ml-1",
                                                    color=get_color(pl),
                                                    pill=True)
                                          ])
                                 for sym, perf, pl in zip(self.top_symbols, self.top_performances, self.top_growth)],
                        )
                    ], color='secondary', outline=True),
                    xs=12, sm=6, style={'margin': '1rem 0rem'}
                ),
                dbc.Col(
                    dbc.Card([
                        dbc.CardBody(
                            [
                                html.H1(f'Loosers', className='small text-secondary')
                            ] + [html.H6([f"{sym}",
                                          dbc.Badge(f"{perf:.2%}", className="ml-1", color=get_color(perf), pill=True),
                                          dbc.Badge(f"{pl:,.2f} {currency_symbol}", className="ml-1",
                                                    color=get_color(pl), pill=True)
                                          ])
                                 for sym, perf, pl in
                                 zip(self.worst_symbols, self.worst_performances, self.worst_growth)]
                        )
                    ], color='secondary', outline=True),
                    xs=12, sm=6, style={'margin': '1rem 0rem'}
                )
            ],
            className='mb-6',
        )

        info_cards = [card_row_1, card_row_2]
        return info_cards

    def create_chart_tabs(self):
        card = html.Div(
            [
                dbc.Row(
                    [dbc.Col(
                        dbc.Tabs(
                            [
                                dbc.Tab(
                                    # [html.I(className='fas fa-chart-line mr-2'), html.Span('History')],
                                    label='History',
                                    tab_id='history_tab'
                                ),
                                dbc.Tab(label='Performance', tab_id='performance_tab'),
                            ],
                            id='chart_tabs',
                            card=True,
                            active_tab='history_tab',
                            className='m-1'
                        ),
                        xs=12,
                        sm=6,
                        # className='col-auto me-auto'
                    ), dbc.Col(
                        dbc.Select(
                            id='chart_time_range',
                            options=[
                                {'label': 'Today', 'value': 'day'},
                                {'label': 'Last week', 'value': 'week'},
                                {'label': 'Last month', 'value': 'month'},
                                {'label': '6 Month', 'value': '6month'},
                                {'label': 'Last Year', 'value': 'year'},
                                {'label': 'Since Buy', 'value': 'buy'}
                            ],
                            value='buy',
                            placeholder='Chart range',
                            bs_size='sm',
                            className='w-auto m-1'
                        ),
                        className='col-auto ml-auto',
                    )],
                    justify='between'
                ),
                html.Div(
                dbc.Card(
                    [
                        dcc.Graph(
                            id='chart',
                            config={
                                'displayModeBar': False
                            },
                            className='chart'
                        ),
                    ],
                    body=True,
                ), )
            ],
            # color='secondary', outline=True,
        )
        return card

    # Main Dashboard
    def create_dashboard(self):
        return html.Div(children=[
            # update performance chart every 5 minutes
            # dcc.Interval(id='performance-interval', interval=5 * 60 * 1000, n_intervals=0),
            dbc.Container([
                dbc.Row([
                    dbc.Col([
                        dcc.Graph(
                            id='allocation_chart',
                            figure=self.allocation_chart,
                            config={
                                'displayModeBar': False
                            }
                        ),

                    ],
                        xl=5, lg=12
                    ),
                    dbc.Col(
                        id='info_cards',
                        children=self.create_info_cards(),
                        xl=7, lg=12
                    )
                ], justify='center', no_gutters=False, align='center'),

                dbc.Row(
                    [
                        dbc.Col([self.create_chart_tabs()], xs=12,)
                    ],
                    justify='center', no_gutters=False
                )],
                fluid=False,),
        ])
