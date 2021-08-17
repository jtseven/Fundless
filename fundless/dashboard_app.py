import dash
import dash_core_components as dcc
import dash_html_components as html

from config import Config
from analytics import PortfolioAnalytics


class Dashboard:
    app: dash.Dash
    analytics: PortfolioAnalytics
    config: Config

    def __init__(self, config: Config, analytics: PortfolioAnalytics):
        self.app = dash.Dash(name='PortfolioDashboard')
        self.config = config
        self.analytics = analytics

        self.app.layout = html.Div(children=[
            html.H1(children='FundLess Dashboard'),

            dcc.Graph(
                id='allocation_chart',
                figure=self.analytics.allocation_pie()
            ),

            dcc.Graph(
                id='performance_chart',
                figure=self.analytics.performance_chart()
            )
        ])

    def run_dashboard(self):
        self.app.run_server(debug=False)  # as the dashboard runs in a separate thread, debug mode is not supported
