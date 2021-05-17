import ccxt
import numpy as np
from enum import Enum
import pandas as pd
from pycoingecko import CoinGeckoAPI
from typing import List

from utils import parse_secrets


class ExchangeEnum(Enum):
    Binance = 1
    Kraken = 2


# translate coingecko symbols to ccxt/binance symbols
coingecko_symbol_dict = {
    'miota': 'iota'
}


def print_order_allocation(symbols: np.ndarray, weights:np.ndarray):
    print(f" ------ Order Allocation: ------ ")
    for symbol, weight in zip(symbols, weights):
        ticker = f'{symbol.upper()}'
        print(f"\t- {ticker}:\t{(weight*100):5.2f} %")


class TradingBot:
    exchange: ccxt.Exchange
    coingecko: CoinGeckoAPI
    test_mode: bool = True
    markets: pd.DataFrame
    cherry_pick: List[str] = ['btc', 'eth']

    def __init__(self, exchange_name: ExchangeEnum, cherry_pick: List[str], secrets_file='secrets.yaml', test_mode=True):
        secrets = parse_secrets(secrets_file)
        self.cherry_pick = cherry_pick
        self.test_mode = test_mode
        self.init_exchange(secrets=secrets, exchange_name=exchange_name)
        self.coingecko = CoinGeckoAPI()
        self.update_markets()

    def update_markets(self):
        try:
            self.markets = pd.DataFrame.from_records(self.coingecko.get_coins_markets(vs_currency='USD'))
        except Exception as e:
            print('Error while updating market data from CoinGecko:')
            print(e)
        self.markets.replace(coingecko_symbol_dict, inplace=True)

    def init_exchange(self, secrets: dict, exchange_name: ExchangeEnum = ExchangeEnum.Binance):
        if exchange_name == ExchangeEnum.Binance:
            self.exchange = ccxt.binance()
            if self.test_mode:
                self.exchange.apiKey = secrets['exchanges']['testnet']['binance']['api_key']
                self.exchange.secret = secrets['exchanges']['testnet']['binance']['secret']
            else:
                self.exchange.apiKey = secrets['exchanges']['mainnet']['binance']['api_key']
                self.exchange.secret = secrets['exchanges']['mainnet']['binance']['secret']
        else:
            raise ValueError('Invalid Exchange given!')

        self.exchange.set_sandbox_mode(self.test_mode)
        self.exchange.load_markets()

    # Compute the weights by market cap, fetching data from coingecko
    # Square root weights yield a less top heavy distribution of coin allocation (lower bitcoin weighting)
    def fetch_index_weights(self):
        picked_markets = self.markets.loc[self.markets['symbol'].isin(self.cherry_pick)]
        symbols = picked_markets['symbol'].values
        weights = picked_markets['market_cap'].values
        weights = weights / weights.sum()
        sqrt_weights = np.sqrt(np.sqrt(weights))
        sqrt_weights /= sqrt_weights.sum()
        return symbols, weights, sqrt_weights

    # Place a weighted market buy order on Binance for multiple coins
    def weighted_buy_order(self, symbols: np.ndarray, weights: np.ndarray, usd_size: float):
        print_order_allocation(symbols, weights)
        # Start buying
        before = self.exchange.fetch_balance()['free']
        for symbol, weight in zip(symbols, weights):
            ticker = f'{symbol.upper()}/BUSD'
            if ticker not in self.exchange.symbols:
                print(f"Warning: {ticker} not available, skipping...")
                continue
            price = self.exchange.fetch_ticker(ticker).get('last')
            if price <= 0.0:
                print(f"Warning: Price for {ticker} is {price}, skipping {ticker}...")
                continue
            amount = weight * usd_size / price
            try:
                order = self.exchange.create_market_buy_order(symbol=ticker, amount=amount)
            except ccxt.InvalidOrder:
                print(f"Buy order for {amount} {ticker} is invalid!")
                print("The order amount might be below the minimum!")
            else:
                print(f"Bought {order['amount']:5f} {ticker} at {order['price']:.2f} $")

        # Report state of portfolio before and after buy orders
        after = self.exchange.fetch_balance()['free']
        print("Balances before order execution:")
        print(before)
        print("Balances after order execution:")
        print(after)
