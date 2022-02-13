import schedule
import time
from datetime import date
from typing import List
import coloredlogs
import logging
import threading

from trading import TradingBot
from messages import TelegramBot
from analytics import PortfolioAnalytics
from config import Config, IntervalEnum
from dashboard_app import Dashboard
from exchanges import Exchanges
"""

FundLess is a crypto trading bot that is aiming at a marketcap weighted crypto portfolio - similar to an 'ETF Sparplan'
To be inline with german tax legislation it is not rebalancing on a monthly basis. Instead it is making weighted buy
orders and will possibly be able to rebalance after the one year waiting period required for tax free trades.

"""
telegram_bot = True

secrets_yaml = 'secrets.yaml'
config_yaml = 'config.yaml'
trades_csv = 'fundless/data/trades.csv'
trades_csv_test = 'fundless/data/test_trades.csv'
order_ids_csv = 'fundless/data/order_ids.csv'
order_ids_csv_test = 'fundless/data/ids_test.csv'

# logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)


if __name__ == '__main__':
    logging_format = '%(asctime)s %(hostname)s %(name)s[%(process)d] %(levelname)s %(message)s'
    coloredlogs.install(level='INFO', fmt=logging_format)
    logger = logging.getLogger()

    logger.info("Hi, I will just buy and HODL!")

    # parse all settings from yaml files
    config = Config.from_yaml_files(config_yaml=config_yaml, secrets_yaml=secrets_yaml)

    # initialize exchanges with api credentials from secrets file
    exchanges = Exchanges(config)

    # the analytics module for portfolio performance analysis
    if config.trading_bot_config.test_mode:
        analytics = PortfolioAnalytics(trades_csv_test, order_ids_csv_test, config, exchanges)
    else:
        analytics = PortfolioAnalytics(trades_csv, order_ids_csv, config, exchanges)

    # the bot interacting with exchanges
    trading_bot = TradingBot(config, analytics, exchanges)

    # telegram bot interacting with the user
    if telegram_bot:
        message_bot = TelegramBot(config, trading_bot)
    else:
        message_bot = None

    # dashboard as web application
    if config.dashboard_config.dashboard:
        dashboard = Dashboard(config, analytics)
        webapp = threading.Thread(target=dashboard.run_dashboard, daemon=True)
        webapp.start()

    # automated saving plan execution
    if message_bot is not None:
        interval = config.trading_bot_config.savings_plan_interval
        execution_time = config.trading_bot_config.savings_plan_execution_time

        def job():
            if isinstance(interval, List):
                if date.today().day not in interval:
                    logger.info(f"No savings plan execution today ({date.today().strftime('%d.%m.%y')})")
                    return

            logger.info(f"Executing savings plan now ({date.today().strftime('%d.%m.%y')})...")
            if config.trading_bot_config.savings_plan_automatic_execution:
                message_bot.send('Executing savings plan!')
                if message_bot.order_planning():
                    message_bot.execute_order()
            else:
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
