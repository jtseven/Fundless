import ccxt
from pycoingecko import CoinGeckoAPI
import pandas as pd
import numpy as np
from math import sqrt
from sklearn.preprocessing import MinMaxScaler

# Press ⌃F5 to execute it or replace it with your code.
# Press Double ⇧ to search everywhere for classes, files, tool windows, actions, and settings.

binance_test_api_key = 'EtfVQ3mFRKz8CEUDHSXB6QN7CI8P70axWy41XUM2QGKApPZH9CWYZVAlwINNLt5K'
binance_test_secret_key = 'm2etMNsCWLGIXoo7hs3mxn6hZyqw6D8qY7MYj3xqb8TWkCeWtKJ0E8eSUz2r5Jnh'

cherry_picked = [
    'btc',
    'eth',
    'ada',
    'dot',
    'link',
    'ltc',
    'vet',
    'sol',
    'eos',
    'neo',
    'atom',
    'miota',
    'algo',
    'zec',
    'qtum',
    'nano',
    'ksm',

]

cols = ['id', 'symbol', 'current_price', 'market_cap']


def print_hi(name):
    # Use a breakpoint in the code line below to debug your script.
    print(f'Hi, {name}')  # Press F9 to toggle the breakpoint.


def fetch_index_weights():
    cg = CoinGeckoAPI()
    markets = pd.DataFrame.from_records(cg.get_coins_markets(vs_currency='USD'))
    markets = markets.loc[markets['symbol'].isin(cherry_picked)]
    symbols = markets['symbol'].values
    weights = markets['market_cap'].values
    weights = weights/weights.sum()
    sqrt_weights = np.sqrt(weights)
    sqrt_weights /= sqrt_weights.sum()

    return symbols, weights, sqrt_weights


def weighted_buy_order(symbols: np.ndarray, weights: np.ndarray, usd_size: float):
    binance = ccxt.binance()
    binance.set_sandbox_mode(True)
    binance.apiKey = binance_test_api_key
    binance.secret = binance_test_secret_key

    binance.load_markets()
    print(binance.symbols)



    before = binance.fetch_balance()['free']
    for symbol, weight in zip(symbols, weights):
        if f'{symbol.upper()}/USDT' not in binance.symbols:
            continue
        price = float(binance.fetch_ticker(f'{symbol.upper()}/USDT').get('last'))
        amount = weight * usd_size / price
        binance.create_market_buy_order(symbol=f'{symbol.upper()}/USDT', amount=amount)

    after = binance.fetch_balance()['free']
    print(before)
    print(after)

    return None

def rebalance_portfolio(symbols: np.ndarray, weights: np.ndarray):
    binance = ccxt.binance()
    binance.set_sandbox_mode(True)
    binance.apiKey = binance_test_api_key
    binance.secret = binance_test_secret_key
    balance_df = pd.DataFrame.from_records(binance.fetch_balance()['free'], index=symbols)

    print("Rebalancing done!")


# Press the green button in the gutter to run the script.
if __name__ == '__main__':
    print_hi('PyCharm')

    symbols, weights, sqrt_weights = fetch_index_weights()

    # rebalance_portfolio(symbols, weights)

    weighted_buy_order(symbols, sqrt_weights, 100)

    # cg = CoinGeckoAPI()
    # markets = cg.get_coins_markets(vs_currency='USD')
    # print(markets)
    #
    # markets_df = pd.DataFrame.from_records(markets)
    # markets_df = markets_df[cols]
    # cherry_picked_markets = markets_df.loc[markets_df['symbol'].isin(cherry_picked)]
    #
    # cherry_picked_markets['weighting'] = cherry_picked_markets['market_cap'].apply(lambda val: val/cherry_picked_markets['market_cap'].sum())
    # cherry_picked_markets['sqrt_weighting'] = cherry_picked_markets['market_cap'].apply(lambda val: sqrt(val/cherry_picked_markets['market_cap'].sum()))
    #
    # normalizer = MinMaxScaler()
    # values = cherry_picked_markets['sqrt_weighting'].values
    # cherry_picked_markets['sqrt_weighting'] = values/values.sum()


    print("Done")