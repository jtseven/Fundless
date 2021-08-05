import pandas as pd
from pathlib import Path
from pydantic import validate_arguments
from pydantic.types import constr

csv_dtypes = {'buy_symbol': 'object', 'sell_symbol': 'object', 'price': 'float64',
              'amount': 'float64', 'cost': 'float64', 'fee': 'float64', 'fee_symbol': 'object'}
columns = ['date', 'buy_symbol', 'sell_symbol', 'price', 'amount', 'cost', 'fee', 'fee_symbol']

date_time_regex = '(\d{4})-(\d{2})-(\d{2}) (\d{2}):(\d{2}):(\d{2})'


class PortfolioAnalytics:
    trades_df: pd.DataFrame
    trades_file: Path

    def __init__(self, file_path):
        self.trades_file = Path(file_path)
        if self.trades_file.exists():
            self.update_dataframe()
        else:
            self.trades_df = pd.DataFrame(columns=columns)
            self.trades_df.to_csv(self.trades_file, index=False)

    def update_dataframe(self):
        self.trades_df = pd.read_csv(self.trades_file, dtype=csv_dtypes, parse_dates=['date'])

    def update_file(self):
        self.trades_df.sort_values('date', inplace=True)
        self.trades_df.to_csv(self.trades_file, index=False)

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
