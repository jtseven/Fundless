from dash import dcc
from dash import html
import dash_bootstrap_components as dbc
from dash_extensions import DeferScript
from functools import reduce
from itertools import groupby
from operator import add

from analytics import PortfolioAnalytics
from config import TradingBotConfig, WeightingEnum
from utils import pretty_print_date, print_crypto_amount, convert_html_to_dash

################################################################################################################
#                                                  Layouts                                                     #
################################################################################################################


# Main Dashboard
def create_dashboard(analytics: PortfolioAnalytics, allocation_pie):
    return html.Div(children=[
        dbc.Row([
            dbc.Col([
                # dcc.Loading(
                dcc.Graph(
                    id='allocation_chart',
                    config={
                        'displayModeBar': False,
                        'staticPlot': True,
                    },
                    children=allocation_pie
                ),
            ],
                xl=5, lg=12
            ),
            dbc.Col(
                id='info_cards',
                children=create_info_cards(analytics=analytics),
                xl=7, lg=12
            )
        ], justify='center', align='center'),

        dbc.Row(
            [
                dbc.Col([create_chart_tabs()], xs=12, )
            ],
            justify='center'
        ),
        # update UI charts and info cards
        dcc.Interval(id='update-interval', interval=3 * 1000, n_intervals=0)
    ])


def create_chart_tabs():
    card = html.Div(
        [
            dbc.Row(
                [dbc.Col(
                    dbc.Tabs(
                        [
                            dbc.Tab(
                                label='History',
                                tab_id='history_tab'
                            ),
                            dbc.Tab(label='Performance', tab_id='performance_tab'),
                        ],
                        id='chart_tabs',
                        active_tab='history_tab',
                        className='m-1'
                    ),
                    xs=12,
                    sm=6,
                ), dbc.Col(
                    dcc.Dropdown(id='chart_time_range',
                                 clearable=False,
                                 searchable=False,
                                 options=[
                                     {'label': 'Today', 'value': 'day'},
                                     {'label': 'Last week', 'value': 'week'},
                                     {'label': 'Last month', 'value': 'month'},
                                     {'label': '6 Month', 'value': '6month'},
                                     {'label': 'Last Year', 'value': 'year'},
                                     {'label': 'Since Buy', 'value': 'buy'}
                                 ],
                                 value='buy',
                                 ),
                    className='ml-auto',
                )],
                justify='between'
            ),
            html.Div(
                dbc.Card(
                    [
                        # dcc.Loading(
                            dcc.Graph(
                                id='chart',
                                config={
                                    'displayModeBar': False,
                                    'staticPlot': True
                                },
                                className='chart'
                            ),
                        #     type='graph'
                        # ),
                    ],
                    body=True,
                ), )
        ],
    )
    return card


# Logout screen
def create_logout_layout():
    return html.Div(dbc.Row([
        dbc.Card(
            [html.Div(html.H4('You have been logged out')),
             html.Div(html.H6('- Good Bye -')),
             dbc.Button('Login', href='/login')],
            style={'padding': '2rem 2rem'}
        )
    ], justify='center', style={'padding-top': '15%'}), style=dict(textAlign='center'))  # end div


# Sidebar
def create_page_with_sidebar():

    with open('fundless/templates/sidebar.html', 'r') as html_code:
        sidebar = convert_html_to_dash(html_code.read())

    page = html.Div(
        className='container-fluid overflow-hidden',
        children=[
            dbc.Row(
                className='vh-100 overflow-auto',
                children=
                [
                    sidebar,
                    html.Div(
                        className='col-12 col-md-9 col-xl-10 d-flex flex-column h-md-100',
                        children=html.Main(
                            html.Div(id='page-content', className='col py-2'),
                            className='row overflow-auto'),
                    )
                ]
            )
        ]
    )
    return page


def create_not_implemented(name: str):
    jumbotron = html.Div(
        [
            html.H1(f"{name} not found", className="text-info"),
            html.P(
                "This page is not yet implemented",
                className="lead",
            ),
            html.Hr(className="my-2"),
            html.P(
                dbc.Button("Home", color="primary", href='dashboard'), className="lead"
            ),
        ],
        className="p-3 bg-light rounded-3",
    )
    return jumbotron


def create_404(pathname: str):
    jumbotron = html.Div(
        [
            html.H1("404: Not found", className="text-info"),
            html.P(
                f"The pathname {pathname} was not recognised...",
                className="lead",
            ),
            html.Hr(className="my-2"),
            html.P(
                dbc.Button("Home", color="primary", href='dashboard'), className="lead"
            ),
        ],
        className="p-3 bg-light rounded-3",
    )
    return jumbotron


def create_info_cards(analytics: PortfolioAnalytics):
    symbol = analytics.currency_symbol
    if analytics.performance > 0:
        color = 'text-success'
        prefix = ''
        text = 'Profit'
    else:
        color = 'text-danger'
        prefix = '',
        text = 'Loss'

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
                            html.H1('Portfolio value', className='small text-secondary'),
                            html.H5(f'{analytics.net_worth:,.2f} {symbol}', className='card-text'),
                            html.H6(f'{prefix}{analytics.performance:,.2%}', className=f'card-text {color}')
                        ]
                    )
                ], color='secondary', outline=True),
                xs=6, style={'margin': '1rem 0rem'}
            ),
            dbc.Col(
                dbc.Card([
                    dbc.CardBody(
                        [
                            html.H1(f'{text}', className='small text-secondary'),
                            html.H5(f'{prefix}{analytics.net_worth - analytics.invested:,.2f} {symbol}',
                                    className=f'card-text {color}'),
                            html.H6(html.Span(f'{analytics.invested:,.2f} {symbol}', id='invested'),
                                    className=f'card-text'),
                            dbc.Tooltip('Your invested amount', target='invested', placement='auto')
                        ]
                    )
                ], color='secondary', outline=True),
                xs=6, style={'margin': '1rem 0rem'}
            ),
        ],
        className='mb-6',
    )

    def info_badges(sym, perf, pl):
        return html.H6(
            [
                html.Span(html.Span(f"{sym}", id=f'{sym}'), className='info-text'),
                dbc.Badge(f"{perf:.0%}", color=get_color(perf), pill=True, className=f'info-badge'),
                dbc.Badge(f"{pl:,.0f} {symbol}", color=get_color(pl), pill=True, className=f'info-badge')
            ]
        )

    def name_tooltip(sym, _, __):
        return dbc.Tooltip(f'{analytics.get_coin_name(sym)}', target=f'{sym}')

    card_row_2 = dbc.Row(
        [
            dbc.Col(
                dbc.Card([
                    dbc.CardBody(
                        [
                            html.H1(html.Span(f'Gainers', id='winners'), className='small text-secondary'),
                            dbc.Tooltip('The best performing coins', target='winners', placement='auto')
                        ] + [
                            f(sym, perf, pl)
                            for sym, perf, pl in
                            zip(analytics.top_symbols, analytics.top_performances, analytics.top_growth)
                            for f in (info_badges, name_tooltip)
                        ],
                    )
                ], color='secondary', outline=True),
                xs=12, sm=6, style={'margin': '1rem 0rem'}
            ),
            dbc.Col(
                dbc.Card([
                    dbc.CardBody(
                        [
                            html.H1(html.Span(f'Losers', id='losers'), className='small text-secondary'),
                            dbc.Tooltip('The worst performing coins', target='losers', placement='auto')
                        ] + [
                            f(sym, perf, pl)
                            for sym, perf, pl in
                            zip(analytics.worst_symbols, analytics.worst_performances, analytics.worst_growth)
                            for f in (info_badges, name_tooltip)
                        ]
                    )
                ], color='secondary', outline=True),
                xs=12, sm=6, style={'margin': '1rem 0rem'}
            )
        ],
        className='mb-6',
    )

    info_cards = [card_row_1, card_row_2]
    return info_cards


def create_holdings_table(analytics: PortfolioAnalytics, **kwargs):
    df = analytics.pretty_index_df
    # Get the actual headers
    n_levels = df.columns.nlevels
    header_values = [
        list(df.columns.get_level_values(level))
        for level in range(n_levels)
    ]

    # The sizes of consecutive header groups at each level
    header_spans = [
        [len(list(group)) for _, group in groupby(level_values)]
        for level_values in header_values
    ]

    # The positions of header changes for each level as an integer
    header_breaks = [
        [sum(level_spans[:i]) for i in range(1, len(level_spans) + 1)]
        for level_spans in header_spans
    ]

    # Include breaks from higher levels
    header_breaks = [
        sorted(set(reduce(add, header_breaks[:level])).union({0}))
        for level in range(1, n_levels + 1)
    ]

    # Go from header break positions back to cell spans
    header_spans = [
        reversed(
            [
                level_breaks[i] - level_breaks[i - 1]
                for i in range(len(level_breaks) - 1, 0, -1)
            ]
        )
        for level_breaks in header_breaks
    ]

    table = [html.Thead(
        [
            html.Tr(
                children=[
                    html.Th(
                        header_values[level][pos],
                        id=f'{header_values[level][pos]}_header',
                        colSpan=span,
                        style={'text-align': 'left'} if header_values[level][pos] == 'Coin' else {'text-align': 'center'} if header_values[level][pos] in ['Currently in Index', 'Available'] else {'text-align': 'right'}
                    )
                    for pos, span in zip(
                        header_breaks[level], header_spans[level]
                    )
                ]
            )
            for level in range(n_levels)
        ]
    ),
        dbc.Tooltip(f"On {analytics.config.trading_bot_config.exchange.values[1]}",
                    target='Available_header'),
        html.Tbody(
        [
            html.Tr([
                html.Td(
                    children=df.loc[i, col] if col not in ('Coin', 'Currently in Index', f'Available') else [
                            html.Div(html.Img(src=analytics.get_coin_image(df.loc[i, col])), className='crypto-icon'),
                            html.Div(f'{analytics.get_coin_name(df.loc[i, col])}', className='crypto-text')
                    ] if col == 'Coin' else [
                        html.I(className='fas fa-check-circle text-success') if df.loc[i, col] == 'yes'
                        else html.I(className='fas fa-times-circle text-danger')],
                    className='text-danger table-cell' if (col == 'Performance') & (
                            '-' in df.loc[i, col]) else 'text-success table-cell' if ((col == 'Performance') and
                                                                                      df.loc[
                                                                                          i, col] != '0.00%') else 'table-cell',
                    style={'text-align': 'left'} if col == 'Coin' else {'text-align': 'center'} if col in ['Currently in Index', f'Available'] else {'text-align': 'right'}
                ) for col in df.columns
            ]) for i in df.index
        ]
    )]
    return dbc.Table(table, striped=False, bordered=False, hover=True, responsive=True, **kwargs)


def create_holdings_page(analytics: PortfolioAnalytics):
    # DBC Table
    table_dbc = create_holdings_table(analytics)

    return html.Div([
        html.Div(table_dbc, id='holdings_table'),
        dcc.Interval(id='holdings-update-interval', interval=3 * 1000, n_intervals=0),
        # DeferScript(src='https://unpkg.com/bootstrap-table@1.18.3/dist/bootstrap-table.min.js')
    ], style={'margin-top': '2rem'})


def create_strategy_page(analytics: PortfolioAnalytics):
    settings = html.Div(dbc.Card(className='settings-card', children=[
        dbc.Form([
            dbc.Label('Index Coins', html_for='index_coins', style={'font-weight': 'bold'}),
            dbc.Row([
                dbc.Col(
                    dcc.Dropdown(id='index_coins', multi=True, className='mb-2', style={'height': '100%'},
                                 value=[sym for sym in analytics.config.trading_bot_config.cherry_pick_symbols],
                                 options=[{'label': analytics.get_coin_name(sym), 'value': sym} for sym in
                                          analytics.markets.symbol.values if analytics.coin_available_on_exchange(sym)
                                          or sym in analytics.config.trading_bot_config.cherry_pick_symbols]
                                 ),
                    lg=10, md=12
                ),
                dbc.Col(
                    md=12, lg=2,
                    children=html.Div([
                        dbc.Button('Apply', outline=True, color='success', id='index-apply',
                                   className='my-1'),
                        dbc.Button('Reset', outline=True, color='danger', id='index-reset',
                                   className='my-1'),
                        dbc.Button('Add Holdings', outline=True, color='info', id='index-holdings',
                                   className='my-1'),
                    ], className='d-grid gap-2'),
                ),
            ]),
            html.Hr(),

            dbc.Label("Currency", html_for='base_currency', style={'font-weight': 'bold'}),
            html.Br(),
            dbc.FormText("Used in analytics and config", className='text-muted'),
            dbc.RadioItems(id='base_currency',
                           options=[
                               {'label': 'Euro', 'value': 'eur'},
                               {'label': 'US Dollar', 'value': 'usd'},
                           ],
                           value=analytics.config.trading_bot_config.base_currency.value.lower()),
            html.Hr(),

            dbc.Label("Savings Plan Base Coin", html_for='base_symbol', style={'font-weight': 'bold'}),
            html.Br(),
            dbc.FormText("Used to buy all coins", className='text-muted'),
            dbc.RadioItems(id='base_symbol',
                           options=[
                               {'label': 'Euro', 'value': 'eur'},
                               {'label': 'US Dollar', 'value': 'usd'},
                               {'label': 'Bitcoin', 'value': 'btc'},
                               {'label': 'BUSD', 'value': 'busd'},
                               {'label': 'USDC', 'value': 'usdc'},
                               {'label': 'USDT', 'value': 'usdt'},
                           ],
                           value=analytics.config.trading_bot_config.base_symbol.lower()),
            html.Hr(),

            dbc.Label(f"Savings Plan Volume ({analytics.config.trading_bot_config.base_currency.value})", html_for='volume', style={'font-weight': 'bold'}),
            html.Br(),
            dbc.FormText("How much you want to spent each time?", className='text-muted'),
            dbc.Input(className="volume-input", type="number", min=10, step=1, id='volume', value=analytics.config.trading_bot_config.savings_plan_cost),
            html.Hr(),

            dbc.Label("Index Weighting", html_for='weighting', style={'font-weight': 'bold'}),
            html.Br(),
            dbc.FormText("How your coins in the index are weighted", className='text-muted'),
            dbc.RadioItems(id='weighting',
                           options=[
                               {'label': 'Equal', 'value': 'equal'},
                               {'label': 'Market Cap', 'value': 'market_cap'},
                               {'label': 'Square Root Market Cap', 'value': 'sqrt_market_cap'},
                               {'label': 'Cubic Root Market Cap', 'value': 'cbrt_market_cap'},
                               {'label': 'Fourth Root Market Cap', 'value': 'sqrt_sqrt_market_cap'},
                               {'label': 'Custom', 'value': 'custom'}
                           ],
                           value=analytics.config.trading_bot_config.portfolio_weighting.value),

            dbc.Collapse([
                html.Hr(),
                dbc.Label("Custom Weights", html_for='custom_form', style={'font-weight': 'bold'}),
                html.Br(),
                dbc.FormText("Set your custom weights of the index", className='text-muted'),
                dbc.Form(id='custom_form')
            ], id='custom-weighting-collapse')

        ])
    ]))
    return html.Div([
        settings,
    ])


def create_weighting_sliders(analytics: PortfolioAnalytics):
    if analytics.config.trading_bot_config.portfolio_weighting == WeightingEnum.custom:
        if analytics.config.trading_bot_config.custom_weights is None:
            analytics.config.trading_bot_config.portfolio_weighting = WeightingEnum.equal
    return [
        dbc.Form(
            [
                dbc.Label(f"{coin.upper()}:", html_for=f"{coin}-row", width=2),
                dbc.Col(
                    dcc.Slider(
                        id=f"{coin}-row", min=0, max=100, step=1, value=int(round(weight * 100)),
                        tooltip={'always_visible': True, 'placement': 'right'}
                    ),
                    width=10,
                ),
            ],
        ) for coin, weight in zip(*analytics.fetch_index_weights())
    ]


def create_trades_page(analytics: PortfolioAnalytics):
    order_days = analytics.trades_df
    order_days.date = order_days.date.dt.floor('d')

    def print_trade_text(coin, coin_orders):
        return html.Span([
            f"{print_crypto_amount(coin_orders.amount)} ", html.B(analytics.get_coin_name(coin, abbr=True)), " for ",
            f"{coin_orders[analytics.base_cost_row]:.2f} {analytics.config.trading_bot_config.base_currency.values[1]}"
        ], className='trade-card-text')

    masonry_cards = html.Div(className='row', id='cards', **{'data-masonry': '{"percentPosition": true }'}, children=[
        html.Div(className='col-sm-6 col-xl-4 mb-4 card-item', children=dbc.Card([
            dbc.CardBody([
                html.H4(
                    f"{orders[analytics.base_cost_row].sum():,.0f} {analytics.config.trading_bot_config.base_currency.values[1]} ",
                    className='card-title'
                ),
                html.H6(pretty_print_date(date), className='card-subtitle text-secondary', ),
                html.Hr(),
                html.Div(
                    [html.Img(src=analytics.get_coin_image(sym), className='crypto-icon-small') for sym in
                     orders.sort_values('cost', ascending=False).buy_symbol.unique()],
                    className='coin-symbol-group'
                ),
                html.Hr(),
                *[
                    element
                    for coin, coin_orders in
                    orders.groupby('buy_symbol', sort=False).sum().sort_values('cost', ascending=False).head(
                        4).iterrows() for
                    element in (print_trade_text(coin, coin_orders), html.Br())
                ],
                dbc.Collapse(
                    [
                        element
                        for coin, coin_orders in
                        orders.groupby('buy_symbol', sort=False).sum().sort_values('cost', ascending=False).tail(
                            -4).iterrows() for
                        element in (print_trade_text(coin, coin_orders), html.Br())
                    ],
                    id={'type': 'card-collapse', 'index': i},
                    className='trades-collapse',
                    is_open=False
                ) if orders.buy_symbol.nunique() > 4 else None,
                dbc.Button(
                    children="Show all",
                    style={'float': 'right'},
                    color='link',
                    id={'type': 'card-toggle', 'index': i})
                if orders.buy_symbol.nunique() > 4 else None,
            ]),
        ]))
        for i, (date, orders) in enumerate(reversed(tuple(order_days.groupby('date'))))
    ])

    return html.Div(
        [
            masonry_cards,
            DeferScript(src='https://cdn.jsdelivr.net/npm/masonry-layout@4.2.2/dist/masonry.pkgd.min.js'),
        ],
        className='pt-4')
