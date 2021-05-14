import ccxt
from pycoingecko import CoinGeckoAPI
import pandas as pd
import numpy as np


binance_test_api_key = 'EtfVQ3mFRKz8CEUDHSXB6QN7CI8P70axWy41XUM2QGKApPZH9CWYZVAlwINNLt5K'
binance_test_secret_key = 'm2etMNsCWLGIXoo7hs3mxn6hZyqw6D8qY7MYj3xqb8TWkCeWtKJ0E8eSUz2r5Jnh'

# symbols of currencies to include in the index
# using ccxt symbol conventions
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
    'iota',
    'algo',
    'qtum',
    'nano',

]

# translate coingecko symbols to ccxt/binance symbols
coingecko_symbol_dict = {
    'miota': 'iota'
}

cols = ['id', 'symbol', 'current_price', 'market_cap']


def fetch_index_weights():
    cg = CoinGeckoAPI()

    # cg_cherry_picked = [coingecko_symbol_dict.get(symbol) if coingecko_symbol_dict.get(symbol) else symbol
    #                     for symbol in cherry_picked]

    markets = pd.DataFrame.from_records(cg.get_coins_markets(vs_currency='USD'))
    markets.replace(coingecko_symbol_dict, inplace=True)
    markets = markets.loc[markets['symbol'].isin(cherry_picked)]
    symbols = markets['symbol'].values
    weights = markets['market_cap'].values
    weights = weights/weights.sum()
    sqrt_weights = np.sqrt(weights)
    sqrt_weights /= sqrt_weights.sum()

    return symbols, weights, sqrt_weights


def weighted_buy_order(symbols: np.ndarray, weights: np.ndarray, usd_size: float):
    binance = ccxt.binance()
    # binance.load_markets()
    # included_symbols = [symbol for symbol in symbols if f'{symbol.upper()}/BUSD' in binance.symbols]
    # print(included_symbols)
    binance.set_sandbox_mode(True)
    binance.apiKey = binance_test_api_key
    binance.secret = binance_test_secret_key

    binance.load_markets()
    print(f"Number of available binance symbols: {len(binance.symbols)}")



    before = binance.fetch_balance()['free']
    for symbol, weight in zip(symbols, weights):
        ticker = f'{symbol.upper()}/BUSD'
        if ticker not in binance.symbols:
            continue
        price = float(binance.fetch_ticker(ticker).get('last'))
        amount = weight * usd_size / price
        try:
            order = binance.create_market_buy_order(symbol=ticker, amount=amount)
        except ccxt.InvalidOrder:
            print(f"Buy order for {amount} {ticker} is invalid!")
            print("The order amount might be below the minimum!")
        else:
            print(f"Bought {order['amount']:5f} {ticker} at {order['price']:.2f} $")

    after = binance.fetch_balance()['free']
    print("Balances before order execution:")
    print(before)
    print("Balances after order execution:")
    print(after)

    return None

def rebalance_portfolio(symbols: np.ndarray, weights: np.ndarray):
    binance = ccxt.binance()
    binance.set_sandbox_mode(True)
    binance.apiKey = binance_test_api_key
    binance.secret = binance_test_secret_key
    balance_df = pd.DataFrame.from_records(binance.fetch_balance()['free'], index=symbols)

    print("Rebalancing done!")


if __name__ == '__main__':
    print("Hi, I will just buy and hodl!")

    symbols, weights, sqrt_weights = fetch_index_weights()

    # rebalance_portfolio(symbols, weights)

    weighted_buy_order(symbols, sqrt_weights, 100)

    print("Done, now HODL!")