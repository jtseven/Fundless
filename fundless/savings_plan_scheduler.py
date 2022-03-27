from datetime import date
from config import Config, IntervalEnum
from messages import TelegramBot
from typing import List
import logging
import schedule
import time
from threading import Lock


logger = logging.getLogger(__name__)


class SavingsPlanScheduler:
    def __init__(self, config: Config, message_bot: TelegramBot):
        self.config = config
        self.interval = config.trading_bot_config.savings_plan_interval
        self.execution_time = config.trading_bot_config.savings_plan_execution_time
        self.message_bot = message_bot
        self.lock = Lock()

    def job(self):
        if not self.lock.acquire(blocking=False):
            logger.warning(
                "Savings plan execution was invoked, while another order is already running!"
            )
            return
        try:
            if isinstance(self.interval, List):
                if date.today().day not in self.interval:
                    logger.info(
                        f"No savings plan execution today ({date.today().strftime('%d.%m.%y')})"
                    )
                    return
            logger.info(
                f"Executing savings plan now ({date.today().strftime('%d.%m.%y')})..."
            )
            if self.config.trading_bot_config.savings_plan_automatic_execution:
                self.message_bot.send("Executing savings plan!")
                if self.message_bot.order_planning():
                    self.message_bot.execute_order()
            else:
                self.message_bot.ask_savings_plan_execution()
        finally:
            self.lock.release()

    def run(self):
        if self.interval == IntervalEnum.daily:
            schedule.every().day.at(self.execution_time).do(self.job)
        elif self.interval == IntervalEnum.weekly:
            schedule.every().week.at(self.execution_time).do(self.job)
        elif self.interval == IntervalEnum.biweekly:
            schedule.every(2).weeks.at(self.execution_time).do(self.job)
        elif self.interval == IntervalEnum.x_daily:
            schedule.every(self.config.trading_bot_config.x_days).days.at(
                self.execution_time
            ).do(self.job)
        elif isinstance(self.interval, List):
            schedule.every().day.at(self.execution_time).do(self.job)
        else:
            raise ValueError(
                f"Unknown interval for savings plan execution: {self.interval}"
            )
        while True:
            schedule.run_pending()
            time.sleep(40)
