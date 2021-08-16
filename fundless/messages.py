import time
import json
import ccxt
import telegram.error
from telegram.ext import (
    Updater,
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    Filters,
    CallbackContext,
    TypeHandler
)
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove, KeyboardButton
from telegram.chataction import ChatAction
import logging
from typing import Callable, Any
from trading import TradingBot
from config import Config
import sys
from redo import retriable
from random import randint

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)


class StateChangeUpdate(Update):
    next_state: int

    def __init__(self, update_id: int, next_state: int, **_kwargs: Any):
        super().__init__(update_id, **_kwargs)
        self.next_state = next_state


# Decorator to check if message is from authorized sender
def authorized_only(command_handler: Callable[..., None]) -> Callable[..., Any]:
    def wrapper(self, *args, **kwargs):
        update = kwargs.get('update') or args[0]
        chat_id = int(self.chat_id)
        if int(update.message.chat_id) != chat_id:
            logger.info(f'Rejected unauthorized message from: {update.message.chat_id}')
            update.message.reply_text('Sorry, you are not authorized, to use this bot!')
            update.message.reply_text('Initiating self destruction...')
            return wrapper

        logger.info(
            'Executing handler: %s for chat_id: %s',
            command_handler.__name__,
            chat_id
        )
        try:
            return command_handler(self, *args, **kwargs)
        except Exception as e:
            logger.exception('Exception occurred within Telegram Bot')
            raise e

    return wrapper


REBALANCING_DECISION, PLANNING, EXECUTING, CHECKING = range(4)


class TelegramBot:

    def __init__(self, config: Config, trading_bot: TradingBot):
        secrets = config.secrets.telegram
        self.command_keyboard = [
            [KeyboardButton(r"/savings_plan"),
             KeyboardButton(r"/config")],
            [KeyboardButton(r"/balance"),
             KeyboardButton(r"/index")],
            [KeyboardButton(r"/performance"),
             KeyboardButton(r"/allocation")],
            [KeyboardButton(r"/cancel")]
        ]
        self.chat_id = secrets['chat_id']
        self.updater = Updater(token=secrets['token'])
        self.dispatcher = self.updater.dispatcher
        self.trading_bot = trading_bot
        self.rebalance = False
        self.order_weights = None
        self.order_symbols = None
        self.currency_string = config.trading_bot_config.base_currency.values[1]

        self.UnknownAnswerHandler = MessageHandler(Filters.text & ~Filters.command, self._unknown)

        self.savings_plan_conversation = ConversationHandler(
            entry_points=[CommandHandler('savings_plan', self._rebalancing_question)],
            states={
                REBALANCING_DECISION: [MessageHandler(Filters.regex('^(Yes|No)$'), self._rebalancing_decision)],
                PLANNING: [MessageHandler(Filters.regex('^(Yes|No)$'), self._order_planning)],
                EXECUTING: [MessageHandler(Filters.regex('^(Yes|No)$'), self._savings_plan_execution)],
                CHECKING: [TypeHandler(StateChangeUpdate, self._change_conversation_state),
                            MessageHandler(Filters.text | Filters.command, self._executing_answer)]
            },
            fallbacks=[CommandHandler('cancel', self._cancel), self.UnknownAnswerHandler]
        )

        handles = [
            self.savings_plan_conversation,
            CommandHandler('start', self._start),
            CommandHandler('balance', self._balance),
            CommandHandler('index', self._index),
            CommandHandler('performance', self._performance),
            CommandHandler('allocation', self._allocation),
            CommandHandler('config', self._config),
            CommandHandler('cancel', self._cancel),
            MessageHandler(Filters.command, self._unknown_command),
            MessageHandler(Filters.text & ~Filters.command, self._hodl_answer),
        ]

        for handle in handles:
            self.dispatcher.add_handler(handle)
        self.queue = self.updater.start_polling()

    def cleanup(self):
        self.updater.stop()

    @staticmethod
    def _error(update: Update, context: CallbackContext):
        """Log Errors caused by Updates."""
        sys.stderr.write(f"ERROR: '{context.error}' caused by '{update}'")
        pass

    @authorized_only
    def _config(self, update: Update, _: CallbackContext):
        msg = self.trading_bot.bot_config.print_markdown()
        update.message.reply_text("This is your current config:")
        update.message.reply_text(msg, parse_mode='MarkdownV2')

    @authorized_only
    def _performance(self, update: Update, _: CallbackContext):
        invested = self.trading_bot.analytics.invested()
        balance = self.trading_bot.analytics.index_balance()[2].sum()
        performance = self.trading_bot.analytics.performance(balance)

        msg = "```\n"
        msg += "----- Performance Report: -----\n"
        msg += f"\tInvested amount:\t{invested:7.2f} {self.currency_string}\n"
        msg += f"\tPortfolio value:\t{balance:7.2f} {self.currency_string}\n"
        msg += f"\tPerformance:\t\t\t\t{performance:.2%}\n"
        msg += "-------------------------------"
        msg += "```"

        update.message.reply_text(msg, parse_mode='MarkdownV2')

    @authorized_only
    def _allocation(self, update: Update, context: CallbackContext):
        allocation_pie_chart = self.trading_bot.analytics.allocation_pie()
        context.bot.send_photo(chat_id=self.chat_id, photo=allocation_pie_chart)


    @authorized_only
    def _start(self, _: Update, context: CallbackContext):
        context.bot.send_message(chat_id=self.chat_id, text="I'm FundLess, please talk to me!")

    @retriable(attempts=5, sleeptime=4, retry_exceptions=(telegram.error.NetworkError,))
    @authorized_only
    def _balance(self, _: Update, context: CallbackContext) -> None:
        context.bot.send_chat_action(chat_id=self.chat_id, action=ChatAction.TYPING)
        try:
            symbols, amounts, values, allocations = self.trading_bot.balance()
        except ccxt.BaseError as e:
            msg = "I had a problem getting your balance from the exchange!"
            context.bot.send_message(chat_id=self.chat_id, text=msg)
            context.bot.send_message(chat_id=self.chat_id, text='Thas is, what the exchange returned:')
            context.bot.send_message(chat_id=self.chat_id, text=str(e))
        except KeyError as e:
            context.bot.send_message(chat_id=self.chat_id,
                                     text='Uh ohhh, I had a problem while computing your balances')
            context.bot.send_message(chat_id=self.chat_id,
                                     text=f'Could not find {e.args[0]} in market data of {self.trading_bot.bot_config.exchange.value}')
        else:
            msg = "```\n"
            msg += "--- Your current portfolio: ---\n"
            for symbol, allocation, value in zip(symbols, allocations, values):
                if value < 1.0:
                    continue
                msg += f" {symbol + ':': <6} {allocation:6.2f}% {value:10,.2f} {self.currency_string}\n"
            msg += "-------------------------------\n"
            msg += f"  Overall Balance: {values.sum():,.2f} {self.currency_string}"
            msg += "```"
            context.bot.send_message(chat_id=self.chat_id, text=msg, parse_mode='MarkdownV2')

    @retriable(attempts=5, sleeptime=4, retry_exceptions=(telegram.error.NetworkError,))
    @authorized_only
    def _index(self, _: Update, context: CallbackContext) -> None:
        context.bot.send_chat_action(chat_id=self.chat_id, action=ChatAction.TYPING)
        try:
            symbols, amounts, values, allocations = self.trading_bot.analytics.index_balance()
            _, index_weights = self.trading_bot.fetch_index_weights(symbols=symbols)
        except KeyError as e:
            context.bot.send_message(chat_id=self.chat_id,
                                     text='Uh ohhh, I had a problem while computing your balances')
            context.bot.send_message(chat_id=self.chat_id,
                                     text=f'Could not find {e.args[0]} in market data of {self.trading_bot.bot_config.exchange.value}')
        else:
            tracking_error = allocations - (index_weights * 100)
            msg = "```\n"
            msg += "Your current index portfolio:\n"
            msg += f"- Coin  Alloc  Value AllocErr -\n"
            for symbol, allocation, value, error in zip(symbols, allocations, values, tracking_error):
                msg += f"  {symbol + ':': <6} {allocation:4.1f}% {value:3,.0f} {self.currency_string}  {error:4.1f}pp\n"
            msg += "-------------------------------\n"
            msg += f"  Overall Balance: {values.sum():,.2f} {self.currency_string}"
            msg += "```"
            context.bot.send_message(chat_id=self.chat_id, text=msg, parse_mode='MarkdownV2')

    @retriable(attempts=5, sleeptime=4, retry_exceptions=(telegram.error.NetworkError,))
    def ask_savings_plan_execution(self):
        reply_keyboard = [[
            KeyboardButton(r"/savings_plan"),
            KeyboardButton(r"/cancel")
        ]]
        markup = ReplyKeyboardMarkup(reply_keyboard, resize_keyboard=True, one_time_keyboard=True)
        msg = f"Should I execute your savings plan?"
        self.updater.bot.send_message(chat_id=self.chat_id, text=msg, reply_markup=markup)

    @retriable(attempts=5, sleeptime=4, retry_exceptions=(telegram.error.NetworkError,))
    @authorized_only
    def _order_planning(self, update: Update, context: CallbackContext):
        # TODO check if bot asked for execution before
        if update.message.text == 'No':
            update.message.reply_text("Okay, canceling this savings plan!")
            return ConversationHandler.END

        update.message.reply_text(
            "Alright! I am computing the optimal buy order..."
        )
        context.bot.send_chat_action(chat_id=self.chat_id, action=ChatAction.TYPING)
        time.sleep(2)
        if self.rebalance:
            symbols, weights = self.trading_bot.rebalancing_weights()
            # filter coin order volumes that are below the minimum threshold for the exchange
            symbols_filtered, weights_filtered = self.trading_bot.volume_corrected_weights(symbols, weights)
        else:
            symbols, weights = self.trading_bot.fetch_index_weights()
            # filter coin order volumes that are below the minimum threshold for the exchange
            symbols_filtered, weights_filtered = self.trading_bot.volume_corrected_weights(symbols, weights)
        if len(symbols_filtered) < len(symbols):
            update.message.reply_text("The order volume is too low, to buy the following coins:")
            update.message.reply_text(f"{[symbol for symbol in symbols if symbol not in symbols_filtered]}")
            update.message.reply_text(
                "But don't worry, I will fix this by rebalancing your portfolio with the next savings plan execution!")
        symbols = symbols_filtered
        weights = weights_filtered
        msg = ("```\nThat's what I came up with:\n"
               "---------------------------")
        for symbol, weight in zip(symbols, weights):
            msg += f"\n  {symbol.upper() + ':': <6}  {weight * self.trading_bot.bot_config.savings_plan_cost:6.2f} {self.currency_string}"
        msg += "\n---------------------------"
        msg += f"\n Sum:  {weights.sum() * self.trading_bot.bot_config.savings_plan_cost:.2f} {self.currency_string}"
        msg += "\n```"
        print(msg)
        update.message.reply_text(msg, parse_mode='MarkdownV2')
        update.message.reply_text(f"You are buying with {self.trading_bot.bot_config.base_symbol.upper()}")
        context.bot.send_chat_action(chat_id=self.chat_id, action=ChatAction.TYPING)
        time.sleep(2)
        reply_keyboard = [[
            "Yes",
            "No"
        ]]
        markup = ReplyKeyboardMarkup(reply_keyboard, resize_keyboard=True, one_time_keyboard=True)
        update.message.reply_text(text="Should I proceed?", reply_markup=markup)

        self.order_weights = weights
        self.order_symbols = symbols
        return EXECUTING

    @authorized_only
    def _rebalancing_question(self, update: Update, context: CallbackContext):
        update.message.reply_text("Great!")
        update.message.reply_text("I will first check, if rebalancing of your portfolio is recommended...")

        allocation_error = self.trading_bot.allocation_error()
        rel_to_volume = allocation_error['rel_to_order_volume']
        if abs(rel_to_volume.max()) >= 0.10:
            symbol = allocation_error['symbols'][rel_to_volume.argmax()]
            err = abs(rel_to_volume.max())
            update.message.reply_text(f"The absolute allocation error of {symbol} is {err:.1%} of your order volume!")
            reply_keyboard = [[
                "Yes",
                "No"
            ]]
            markup = ReplyKeyboardMarkup(reply_keyboard, resize_keyboard=True, one_time_keyboard=True)
            update.message.reply_text("Would you like me to rebalance your portfolio with this savings plan execution?",
                                      reply_markup=markup)
            return REBALANCING_DECISION
        else:
            update.message.reply_text("Ahh perfect, your portfolio looks well balanced!")
            self.rebalance = False
            reply_keyboard = [[
                "Yes",
                "No"
            ]]
            markup = ReplyKeyboardMarkup(reply_keyboard, resize_keyboard=True, one_time_keyboard=True)
            update.message.reply_text("Should I proceed computing your buy order?", reply_markup=markup)
            return PLANNING

    @authorized_only
    def _rebalancing_decision(self, update: Update, context: CallbackContext):
        if update.message.text == 'Yes':
            update.message.reply_text("Alright, I will rebalance your portfolio with this order...")
            self.rebalance = True
        elif update.message.text == 'No':
            update.message.reply_text("Okay, no rebalancing this time...")
            self.rebalance = False
        reply_keyboard = [[
            "Yes",
            "No"
        ]]
        markup = ReplyKeyboardMarkup(reply_keyboard, resize_keyboard=True, one_time_keyboard=True)
        update.message.reply_text("Should I proceed?", reply_markup=markup)
        return PLANNING

    @authorized_only
    def _savings_plan_execution(self, update: Update, context: CallbackContext):
        if update.message.text == 'Yes':
            update.message.reply_text(
                f"Great! I am buying your crypto on {self.trading_bot.bot_config.exchange.values[1]}")
            update.message.reply_text(
                f"Your order volume is {self.trading_bot.bot_config.savings_plan_cost:,.0f} {self.currency_string} ...")
            try:
                context.bot.send_chat_action(chat_id=self.chat_id, action=ChatAction.TYPING)
                report = self.trading_bot.weighted_buy_order(self.order_symbols, self.order_weights)
            except ccxt.BaseError as e:
                update.message.reply_text("Ohhh, there was a Problem with the exchange! Sorry :(")
                update.message.reply_text('This is, what the exchange returned:')
                update.message.reply_text(str(e))
                update.message.reply_text('Try to solve it and try again next time')
                update.message.reply_text('See you :)')
                return ConversationHandler.END
            problems = report['problems']
            if problems['fail']:
                update.message.reply_text('I can not place your orders!')
                context.bot.send_chat_action(chat_id=self.chat_id, action=ChatAction.TYPING)
                time.sleep(1)
                if len(problems['symbols'].keys()) > 0:
                    msg = "Problematic coins:"
                    for symbol in problems['symbols'].keys():
                        msg += f"\n\t- {symbol}, {problems['symbols'][symbol]}"
                    update.message.reply_text(msg)
                else:
                    update.message.reply_text(problems['description'])
                context.bot.send_chat_action(chat_id=self.chat_id, action=ChatAction.TYPING)
                time.sleep(1)
                update.message.reply_text('Solve the problems and try again next time!')
                update.message.reply_text("See you")
                return ConversationHandler.END
            else:
                order_ids = report['order_ids']
                placed_symbols = report['symbols']
                update.message.reply_text("I did it!")
                update.message.reply_text("Was a pleasure working with you")
                update.message.reply_text(
                    "I will check if your orders went threw in a few seconds and get back to you :)")
                context.job_queue.run_once(self.check_orders, when=10, context=(order_ids, placed_symbols, 1, update))
                return CHECKING
        else:
            update.message.reply_text("Hmmm.. okay.. I will ask you another time")
            return ConversationHandler.END

    @authorized_only
    def _executing_answer(self, update: Update, context: CallbackContext):
        update.message.reply_text('Your order is being executed on the exchange, just relax for a while')
        update.message.reply_text('I will get back to you shortly!')
        return CHECKING

    def check_orders(self, context: CallbackContext):
        job = context.job
        order_ids, symbols, n_retry, update = job.context
        context.bot.send_message(self.chat_id, text='I am checking your orders now!')
        context.bot.send_chat_action(self.chat_id, action=ChatAction.TYPING)
        order_report = self.trading_bot.check_orders(order_ids, symbols)
        open_orders = order_report['open']
        closed_orders = order_report['closed']
        missing = [symbol for symbol in symbols if symbol not in closed_orders + open_orders]
        if len(missing) > 0:
            context.bot.send_message(self.chat_id, text='Oh ohh, I did not find all the orders I placed :0')
            context.bot.send_message(self.chat_id, text='Orders for those coins are missing:')
            msg = "```\n"
            for missing_symbol in missing:
                msg += f"  - {missing_symbol.upper()}\n"
            msg += "```"
            context.bot.send_message(self.chat_id, text=msg)

        if len(closed_orders) > 0:
            volume = 0.
            msg = "```\n"
            msg += "----- Completed Coins -----"
            for symbol in closed_orders:
                msg += f"\n  - {symbol.split('/')[0].upper()}"
                volume += order_report[symbol]['cost']
            msg += "\n---------------------------"
            msg += f"\n-- Filled Volume: {volume:<4.0f} {self.currency_string} --"
            msg += "\n```"
            context.bot.send_message(self.chat_id, text=msg, parse_mode='MarkdownV2')

        if len(open_orders) > 0:
            context.bot.send_message(self.chat_id, text='Some of your orders are not filled yet:')
            msg = "```\n"
            for symbol in open_orders:
                msg += f"  - {symbol.upper()}\n"
            msg += "```"
            context.bot.send_message(self.chat_id, text=msg, parse_mode='MarkdownV2')
            if n_retry > 10:
                context.bot.send_message(self.chat_id, text="We have waited long enough! Pls solve the orders that are"
                                                            "still open manually..")
                state_update = StateChangeUpdate(randint(0, 999999999), next_state=ConversationHandler.END)
                state_update._effective_user = update.effective_user
                state_update._effective_chat = update.effective_chat
                context.update_queue.put(state_update)
            else:
                wait_time = 60 * n_retry * n_retry  # have an exponentialy increasing wait time
                context.bot.send_message(self.chat_id,
                                         text=f"I will wait {wait_time / 60:.0f} minutes and get back to you :)")
                context.job_queue.run_once(self.check_orders, when=wait_time,
                                           context=(order_ids, symbols, n_retry + 1, update))
                state_update = StateChangeUpdate(randint(0, 999999999), next_state=CHECKING)
                state_update._effective_user = update.effective_user
                state_update._effective_chat = update.effective_chat
                context.update_queue.put(state_update)

        elif len(closed_orders) == len(order_ids):
            context.bot.send_message(self.chat_id, text='Nice, all your orders are filled!')
            context.bot.send_message(self.chat_id, text='See you :)')
            state_update = StateChangeUpdate(randint(0, 999999999), next_state=ConversationHandler.END)
            state_update._effective_user = update.effective_user
            state_update._effective_chat = update.effective_chat
            context.update_queue.put(state_update)

    def _change_conversation_state(self, update: StateChangeUpdate, __: CallbackContext):
        if update.next_state == ConversationHandler.END:
            return ConversationHandler.END
        elif update.next_state == CHECKING:
            return CHECKING
        else:
            raise ValueError('Invalid state passed!')

    @authorized_only
    def _cancel(self, update: Update, _: CallbackContext) -> int:
        user = update.message.from_user
        logger.info("User %s canceled the conversation.", user.first_name)
        update.message.reply_text(
            'Bye! I hope we can talk again some day.', reply_markup=ReplyKeyboardRemove()
        )
        return ConversationHandler.END

    @authorized_only
    def _hodl_answer(self, update: Update, context: CallbackContext) -> None:
        markup = ReplyKeyboardMarkup(self.command_keyboard, resize_keyboard=True, one_time_keyboard=True)
        context.bot.send_chat_action(chat_id=self.chat_id, action=ChatAction.TYPING)
        time.sleep(1)
        update.message.reply_text("HODL!", reply_markup=ReplyKeyboardRemove())
        update.message.reply_text("You can use the following commands:", reply_markup=markup)
        update.message.reply_text("/savings_plan\n/config\n/balance\n/index\n/performance\n/allocation\n/cancel",
                                  reply_markup=markup)

    @authorized_only
    def _unknown(self, _: Update, context: CallbackContext):
        context.bot.send_message(chat_id=self.chat_id, text="Sorry, I didn't understand that.")
        reply_keyboard = [[
            "Yes",
            "No",
            "/cancel"
        ]]
        markup = ReplyKeyboardMarkup(reply_keyboard, resize_keyboard=True, one_time_keyboard=True)
        context.bot.send_message(chat_id=self.chat_id, text='Would you like to proceed or cancel?', reply_markup=markup)

    @authorized_only
    def _unknown_command(self, update: Update, context: CallbackContext):
        context.bot.send_message(chat_id=self.chat_id, text="Sorry, I do not know that command.")
        markup = ReplyKeyboardMarkup(self.command_keyboard, resize_keyboard=True, one_time_keyboard=True)
        context.bot.send_message(chat_id=self.chat_id, text='You can use these commands:', reply_markup=markup)
