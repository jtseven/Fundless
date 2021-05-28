import schedule
import time

from trading import TradingBot
from messages import TelegramBot
from config import Config
"""

FundLess is a crypto trading bot that is aiming at a marketcap weighted crypto portfolio - similar to an 'ETF Sparplan'
To be inline with german tax legislation it is not rebalancing on a monthly basis. Instead it is making weighted buy
orders and will possibly be able to rebalance after the one year waiting period required for tax free trades.

"""

secrets_yaml = 'secrets.yaml'
config_yaml = 'config.yaml'

if __name__ == '__main__':
    print("Hi, I will just buy and HODL!")

    # parse all settings from yaml files
    config = Config.from_yaml_files(config_yaml=config_yaml, secrets_yaml=secrets_yaml)

    # the bot interacting with exchanges
    trading_bot = TradingBot(config)

    # symbols, weights = trading_bot.fetch_index_weights()
    # trading_bot.weighted_buy_order(symbols, sqrt_weights)

    # telegram bot interacting with the user
    message_bot = TelegramBot(config, trading_bot)

    def job():
        print("Executing scheduled job...")
        message_bot.ask_savings_plan_execution()

    schedule.every().day.at("16:15").do(job)

    while True:
        schedule.run_pending()
        time.sleep(1)