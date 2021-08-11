import pandas as pd
from pathlib import Path
from pycoingecko import CoinGeckoAPI
from pydantic import validate_arguments
from pydantic.types import constr
import plotly.express as px

from config import Config

csv_dtypes = {'buy_symbol': 'object', 'sell_symbol': 'object', 'price': 'float64',
              'amount': 'float64', 'cost': 'float64', 'fee': 'float64', 'fee_symbol': 'object'}
columns = ['date', 'buy_symbol', 'sell_symbol', 'price', 'amount', 'cost', 'fee', 'fee_symbol']

date_time_regex = '(\d{4})-(\d{2})-(\d{2}) (\d{2}):(\d{2}):(\d{2})'

# translate coingecko symbols to ccxt/binance symbols
coingecko_symbol_dict = {
    'miota': 'iota'
}


class PortfolioAnalytics:
    trades_df: pd.DataFrame
    trades_file: Path
    coingecko: CoinGeckoAPI
    markets: pd.DataFrame  # CoinGecko Market Data

    def __init__(self, file_path, config: Config):
        self.config = config.trading_bot_config
        self.trades_file = Path(file_path)
        if self.trades_file.exists():
            self.update_dataframe()
        else:
            self.trades_df = pd.DataFrame(columns=columns)
            self.trades_df.to_csv(self.trades_file, index=False)
        self.coingecko = CoinGeckoAPI()
        self.update_markets()

    def update_dataframe(self):
        self.trades_df = pd.read_csv(self.trades_file, dtype=csv_dtypes, parse_dates=['date'])

    def update_file(self):
        self.trades_df.sort_values('date', inplace=True)
        self.trades_df.to_csv(self.trades_file, index=False)

    def update_markets(self):
        try:
            self.markets = pd.DataFrame.from_records(self.coingecko.get_coins_markets(
                vs_currency=self.config.base_currency.value, per_page=150))
            self.markets['symbol'] = self.markets['symbol'].str.lower()
        except Exception as e:
            print('Error while updating market data from CoinGecko:')
            print(e)
            raise e
        self.markets.replace(coingecko_symbol_dict, inplace=True)

    @validate_arguments
    def add_trade(self, date: constr(regex=date_time_regex),
                  buy_symbol: str, sell_symbol: str, price: float, amount: float,
                  cost: float, fee: float, fee_symbol: str):
        trade_dict = {'date': [date], 'buy_symbol': [buy_symbol.upper()], 'sell_symbol': [sell_symbol.upper()],
                      'price': [price], 'amount': [amount], 'cost': [cost], 'fee': [fee], 'fee_symbol': [fee_symbol.upper()]}
        self.update_dataframe()
        self.trades_df = self.trades_df.append(pd.DataFrame.from_dict(trade_dict), ignore_index=True)
        self.trades_df['date'] = pd.to_datetime(self.trades_df['date'], infer_datetime_format=True)
        self.update_file()

    def performance(self, current_portfolio_value: float) -> float:
        amount_invested = self.trades_df['cost'].sum()
        return current_portfolio_value / amount_invested - 1

    def invested(self) -> float:
        return self.trades_df['cost'].sum()

    def allocation_pie(self):

        df = self.trades_df[['buy_symbol', 'amount']].copy().groupby('buy_symbol').sum()
        df.index = df.index.str.lower()
        allocation_df = self.markets[['symbol', 'current_price']].join(df, on='symbol', how='inner')
        allocation_df['value'] = allocation_df['current_price'] * allocation_df['amount']
        allocation_df['allocation'] = allocation_df['value'] / allocation_df['value'].sum()
        allocation_df['symbol'] = allocation_df['symbol'].str.upper()
        allocation_df.loc[allocation_df['allocation'] < 0.03, 'symbol'] = 'Other'

        fig = px.pie(allocation_df, values='allocation', names='symbol', title='Coin Allocation')
        fig.update_traces(textposition='inside', textinfo='percent+label')
        fig.update_layout(showlegend=False, title={'xanchor': 'center', 'x': 0.5},
                          uniformtext_minsize=18, uniformtext_mode='hide')
        return fig.to_image(format='png', width=800, height=800)

        # df = self.trades_df.loc[df[''] < 2.e6, 'country'] = 'Other countries'
