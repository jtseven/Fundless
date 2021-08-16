import pandas as pd
from pathlib import Path
from pycoingecko import CoinGeckoAPI
from pydantic import validate_arguments
from pydantic.types import constr
import plotly.express as px
from typing import Tuple
import numpy as np

from config import Config

csv_dtypes = {'buy_symbol': 'object', 'sell_symbol': 'object', 'price': 'float64',
              'amount': 'float64', 'cost': 'float64', 'fee': 'float64', 'fee_symbol': 'object'}
trades_cols = ['date', 'buy_symbol', 'sell_symbol', 'price', 'amount', 'cost', 'fee', 'fee_symbol']
index_cols = ['symbol', 'amount', 'value', 'current_price', 'allocation']

date_time_regex = '(\d{4})-(\d{2})-(\d{2}) (\d{2}):(\d{2}):(\d{2})'

# translate coingecko symbols to ccxt/binance symbols
coingecko_symbol_dict = {
    'miota': 'iota'
}


class PortfolioAnalytics:
    trades_df: pd.DataFrame
    trades_file: Path
    index_df: pd.DataFrame
    history_df: pd.DataFrame
    coingecko: CoinGeckoAPI
    markets: pd.DataFrame  # CoinGecko Market Data

    def __init__(self, file_path, config: Config):
        self.config = config.trading_bot_config
        self.trades_file = Path(file_path)
        if self.trades_file.exists():
            self.update_trades_df()
        else:
            self.trades_df = pd.DataFrame(columns=trades_cols)
            self.trades_df.to_csv(self.trades_file, index=False)
        self.coingecko = CoinGeckoAPI()
        self.update_markets()

    def update_trades_df(self):
        self.trades_df = pd.read_csv(self.trades_file, dtype=csv_dtypes, parse_dates=['date'])

    def update_file(self):
        self.trades_df.sort_values('date', inplace=True)
        self.trades_df.to_csv(self.trades_file, index=False)

    def update_markets(self):
        # update market data from coingecko
        try:
            self.markets = pd.DataFrame.from_records(self.coingecko.get_coins_markets(
                vs_currency=self.config.base_currency.value, per_page=150))
            self.markets['symbol'] = self.markets['symbol'].str.lower()
        except Exception as e:
            print('Error while updating market data from CoinGecko:')
            print(e)
            raise e
        self.markets.replace(coingecko_symbol_dict, inplace=True)

        # update index portfolio value
        other = pd.DataFrame(index=self.config.cherry_pick_symbols)
        self.index_df = self.trades_df[['buy_symbol', 'amount']].copy().groupby('buy_symbol').sum()
        self.index_df.index = self.index_df.index.str.lower()
        self.index_df = pd.merge(self.index_df, other, how='outer', left_index=True, right_index=True)
        self.index_df.fillna(value=0, inplace=True, axis='columns')
        self.index_df = self.markets[['symbol', 'current_price']].join(self.index_df, on='symbol', how='inner')
        self.index_df['value'] = self.index_df['current_price'] * self.index_df['amount']
        self.index_df['allocation'] = self.index_df['value'] / self.index_df['value'].sum()
        self.index_df['symbol'] = self.index_df['symbol'].str.upper()

    @validate_arguments
    def add_trade(self, date: constr(regex=date_time_regex),
                  buy_symbol: str, sell_symbol: str, price: float, amount: float,
                  cost: float, fee: float, fee_symbol: str):
        trade_dict = {'date': [date], 'buy_symbol': [buy_symbol.upper()], 'sell_symbol': [sell_symbol.upper()],
                      'price': [price], 'amount': [amount], 'cost': [cost], 'fee': [fee],
                      'fee_symbol': [fee_symbol.upper()]}
        self.update_trades_df()
        self.trades_df = self.trades_df.append(pd.DataFrame.from_dict(trade_dict), ignore_index=True)
        self.trades_df['date'] = pd.to_datetime(self.trades_df['date'], infer_datetime_format=True)
        self.update_file()

    def index_balance(self) -> Tuple:
        self.update_markets()
        self.index_df.sort_values(by='allocation', ascending=False, inplace=True)
        allocations = self.index_df['allocation'].values * 100
        symbols = self.index_df['symbol'].values
        values = self.index_df['value'].values
        amounts = self.index_df['amount'].values
        return symbols, amounts, values, allocations

    def performance(self, current_portfolio_value: float) -> float:
        amount_invested = self.trades_df['cost'].sum()
        return current_portfolio_value / amount_invested - 1

    def invested(self) -> float:
        return self.trades_df['cost'].sum()

    def allocation_pie(self):
        self.update_markets()
        allocation_df = self.index_df.copy()
        allocation_df.loc[allocation_df['allocation'] < 0.03, 'symbol'] = 'Other'

        fig = px.pie(allocation_df, values='allocation', names='symbol', title='Coin Allocation',
                     color_discrete_sequence=px.colors.sequential.Viridis, hole=0.6)
        fig.update_traces(textposition='inside', textinfo='percent+label')
        fig.update_layout(showlegend=False, title={'xanchor': 'center', 'x': 0.5},
                          uniformtext_minsize=18, uniformtext_mode='hide',
                          annotations=[
                              dict(text=f"{allocation_df['value'].sum():.2f} {self.config.base_currency.values[1]}",
                                   x=0.5, y=0.5, font_size=28, showarrow=False)],
                          title_font=dict(size=32))
        return fig.to_image(format='png', width=800, height=800)

        # df = self.trades_df.loc[df[''] < 2.e6, 'country'] = 'Other countries'

    def update_historical_prices(self):
        for coin in self.index_df['symbol'].str.lower():
            id = self.markets.loc[self.markets['symbol'] == coin, ['id']].values[0][0]
            data = self.coingecko.get_coin_market_chart_range_by_id(id=id, vs_currency=self.config.base_currency.value,
                                                                    from_timestamp=1619877352, to_timestamp=1629122192)
            data_df = pd.DataFrame.from_records(data['prices'], columns=['timestamp', f'{coin}'])
            data_df['timestamp'] = pd.to_datetime(data_df['timestamp'], unit='ms')
            data_df.set_index('timestamp', inplace=True)
            if 'history_df' not in locals():
                history_df = data_df
            else:
                history_df = history_df.join(data_df, how='outer')
        self.history_df = history_df

    def compute_value_history(self):
        self.update_historical_prices()
        invested = self.trades_df[['date', 'buy_symbol', 'cost']].groupby(
            ['date', 'buy_symbol'], as_index=False, axis=0).sum()
        value = self.trades_df[['date', 'buy_symbol', 'amount']].groupby(
            ['date', 'buy_symbol'], as_index=False, axis=0).sum()
        invested = invested.pivot(index='date', columns='buy_symbol', values='cost')
        invested = invested.cumsum().fillna(method='pad').fillna(0)
        invested = invested.reindex(self.history_df.index, method='pad').fillna(0)
        invested.columns = invested.columns.str.lower()

        value = value.pivot(index='date', columns='buy_symbol', values='amount')
        value = value.cumsum().fillna(method='pad').fillna(0)
        value = value.reindex(self.history_df.index, method='pad').fillna(0)
        value.columns = value.columns.str.lower()
        value = value * self.history_df

        return value, invested

    def performance_chart(self):
        value, invested = self.compute_value_history()
        performance_df = pd.DataFrame(index=value.index, columns=['invested', 'net_worth'])
        performance_df['invested'] = invested.sum(axis=1)
        performance_df['net_worth'] = value.sum(axis=1)

        fig = px.line(performance_df, x=performance_df.index, y=['invested', 'net_worth'], line_shape='spline')
        return fig.to_image(format='png', width=1600, height=800)

