import asyncio

import coloredlogs
import logging
import threading

from trading import TradingBot
from messages import TelegramBot
from analytics import PortfolioAnalytics
from config import Config
from dashboard_app import Dashboard
from exchanges import Exchanges
from savings_plan_scheduler import SavingsPlanScheduler

"""

FundLess is a crypto trading bot that is aiming at a marketcap weighted crypto portfolio - similar to an 'ETF Sparplan'
To be inline with german tax legislation it is not rebalancing on a monthly basis. Instead it is making weighted buy
orders and will possibly be able to rebalance after the one year waiting period required for tax free trades.

"""
telegram_bot = True

secrets_yaml = "secrets.yaml"
config_yaml = "config.yaml"
trades_csv = "fundless/data/trades.csv"
trades_csv_test = "fundless/data/test_trades.csv"
order_ids_csv = "fundless/data/order_ids.csv"
order_ids_csv_test = "fundless/data/ids_test.csv"


if __name__ == "__main__":
    logging_format = "%(asctime)s %(hostname)s %(name)s[%(process)d] %(levelname)s %(message)s"
    coloredlogs.install(level="INFO", fmt=logging_format)
    logger = logging.getLogger()

    logger.info("Hi, I will just buy and HODL!")

    # parse all settings from yaml files
    config = Config.from_yaml_files(config_yaml=config_yaml, secrets_yaml=secrets_yaml)

    # initialize exchanges with api credentials from secrets file
    logger.info("Initializing exchanges...")
    exchanges = Exchanges(config)

    # the analytics module for portfolio performance analysis
    logger.info("Initializing analytics module...")
    if config.trading_bot_config.test_mode:
        analytics = PortfolioAnalytics(trades_csv_test, order_ids_csv_test, config, exchanges)
    else:
        analytics = PortfolioAnalytics(trades_csv, order_ids_csv, config, exchanges)

    # the bot interacting with exchanges
    logger.info("Initializing trading bot...")
    trading_bot = TradingBot(config, analytics, exchanges)

    # telegram bot interacting with the user
    if telegram_bot:
        logger.info("Initializing telegram bot...")
        message_bot = TelegramBot(config, trading_bot)
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        task = loop.create_task(message_bot.run_polling())
        threading.Thread(target=loop.run_forever, daemon=True).start()
    else:
        message_bot = None

    if message_bot is not None:
        logger.info("Initializing savings plan scheduler...")
        scheduler = SavingsPlanScheduler(config, message_bot)
        savings_plan = threading.Thread(target=scheduler.run, daemon=True)
        savings_plan.start()
    else:
        savings_plan = None
        logger.warning("Savings plan is not executed, when the telegram bot is not running!")

    # dashboard as web application
    if config.dashboard_config.dashboard:
        logger.info("Initializing dashboard...")
        dashboard = Dashboard(config, analytics)
        webapp = threading.Thread(target=dashboard.run_dashboard, daemon=True)
        webapp.start()
    else:
        webapp = None

    if webapp is not None:
        webapp.join()
    if savings_plan is not None:
        savings_plan.join()
