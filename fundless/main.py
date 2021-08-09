import schedule
import time
from datetime import date
from typing import List

from trading import TradingBot
from messages import TelegramBot
from analytics import PortfolioAnalytics
from config import Config, IntervalEnum
"""

FundLess is a crypto trading bot that is aiming at a marketcap weighted crypto portfolio - similar to an 'ETF Sparplan'
To be inline with german tax legislation it is not rebalancing on a monthly basis. Instead it is making weighted buy
orders and will possibly be able to rebalance after the one year waiting period required for tax free trades.

"""

secrets_yaml = 'secrets.yaml'
config_yaml = 'config.yaml'
trades_csv = 'fundless/data/trades.csv'
trades_csv_test = 'fundless/data/test_trades.csv'

if __name__ == '__main__':
    print("Hi, I will just buy and HODL!")

    # parse all settings from yaml files
    config = Config.from_yaml_files(config_yaml=config_yaml, secrets_yaml=secrets_yaml)

    # the analytics module for portfolio performance analysis
    if config.trading_bot_config.test_mode:
        analytics = PortfolioAnalytics(trades_csv_test, config)
    else:
        analytics = PortfolioAnalytics(trades_csv, config)

    # the bot interacting with exchanges
    trading_bot = TradingBot(config, analytics)

    # telegram bot interacting with the user
    message_bot = TelegramBot(config, trading_bot)
    interval = config.trading_bot_config.savings_plan_interval
    execution_time = config.trading_bot_config.savings_plan_execution_time

    def job():
        if isinstance(interval, List):
            if date.today().day not in interval:
                print(f"No savings plan execution today ({date.today().strftime('%d.%m.%y')})")
                return

        print(f"Executing savings plan now ({date.today().strftime('%d.%m.%y')})...")
        message_bot.ask_savings_plan_execution()

    if interval == IntervalEnum.daily:
        schedule.every().day.at(execution_time).do(job)
    elif interval == IntervalEnum.weekly:
        schedule.every().week.at(execution_time).do(job)
    elif interval == IntervalEnum.biweekly:
        schedule.every(2).weeks.at(execution_time).do(job)
    elif isinstance(interval, List):
        schedule.every().day.at(execution_time).do(job)
    else:
        raise ValueError(f'Unknown interval for savings plan execution: {interval}')

    while True:
        schedule.run_pending()
        time.sleep(10)
