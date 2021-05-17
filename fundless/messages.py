import ccxt
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters
import logging
from typing import Callable, Any
from utils import parse_secrets
from trading import TradingBot

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)


# Decorator to check if message is from authorized sender
def authorized_only(command_handler: Callable[..., None]) -> Callable[..., Any]:
    def wrapper(self, *args, **kwargs):
        update = kwargs.get('update') or args[0]
        chat_id = int(self.chat_id)

        if int(update.message.chat_id) != chat_id:
            logger.info(f'Rejected unauthorized message from: {update.message.chat_id}')
            return wrapper

        logger.info(
            'Executing handler: %s for chat_id: %s',
            command_handler.__name__,
            chat_id
        )
        try:
            return command_handler(self, *args, **kwargs)
        except BaseException:
            logger.exception('Exception occurred within Telegram Bot')

    return wrapper


class TelegramBot:
    def __init__(self, trading_bot: TradingBot):
        secrets = parse_secrets('secrets.yaml')
        self.chat_id = secrets['telegram']['private_chat_id']
        self.updater = Updater(token=secrets['telegram']['token'])
        self.dispatcher = self.updater.dispatcher
        self.trading_bot = trading_bot

        handles = [
            CommandHandler('start', self._start),
            CommandHandler('balance', self._balance),
            MessageHandler(Filters.command, self._unknown)
        ]

        for handle in handles:
            self.dispatcher.add_handler(handle)

        self.updater.start_polling()
        self.updater.idle()

    def cleanup(self):
        self.updater.stop()

    @authorized_only
    def _start(self, update, context):
        context.bot.send_message(chat_id=self.chat_id, text="I'm FundLess, please talk to me!")

    @authorized_only
    def _balance(self, update, context):
        try:
            balance = self.trading_bot.get_balance()
        except ccxt.BaseError:
            msg = "--- I had a problem getting your balance from the exchange! ---"
        else:
            msg = "--- Your current portfolio: ---\n"
            for symbol, amount in balance.items():
                msg += f"{symbol}:\t{amount:10f}\n"
        context.bot.send_message(chat_id=self.chat_id, text=msg)

    def ask_order_execution(self):
        pass  # TODO
        return True

    def _unknown(self, update, context):
        context.bot.send_message(chat_id=self.chat_id, text="Sorry, I didn't understand that command.")
