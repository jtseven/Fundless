import schedule
import time

from trading import TradingBot, ExchangeEnum
"""

FundLess is a crypto trading bot that is aiming at a marketcap weighted crypto portfolio - similar to an 'ETF Sparplan'
To be inline with german tax legislation it is not rebalancing on a monthly basis. Instead it is making weighted buy
orders and will possibly be able to rebalance after the one year waiting period required for tax free trades.

"""

# symbols of currencies to include in the index
# using ccxt symbol conventions
cherry_picked = [
    'btc',
    'eth',
    'ada',
    'dot',
    'link',
    'vet',
    'sol',
    'neo',
    'atom',
    'iota',
    'algo',
    'qtum',
    'nano',

]

# Relevant columns from coingecko
cols = ['id', 'symbol', 'current_price', 'market_cap']


if __name__ == '__main__':
    print("Hi, I will just buy and HODL!")

    trading_bot = TradingBot(ExchangeEnum.Binance, cherry_pick=cherry_picked, test_mode=True)

    def job():
        symbols, weights, sqrt_weights = trading_bot.fetch_index_weights()
        trading_bot.weighted_buy_order(symbols, sqrt_weights, usd_size=100)

    schedule.every(1).minute.do(job)

    while True:
        schedule.run_pending()
        time.sleep(1)

    # print("Done, now HODL!")
