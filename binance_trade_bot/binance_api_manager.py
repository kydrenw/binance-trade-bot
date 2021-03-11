import math
import time

from binance.client import Client
from binance.exceptions import BinanceAPIException

from .config import Config
from .database import Database
from .logger import Logger
from .models import Coin
from .utils import get_market_ticker_price_from_list


class BinanceAPIManager:
    def __init__(self, config: Config, db: Database, logger: Logger):
        self.BinanceClient = Client(config.BINANCE_API_KEY, config.BINANCE_API_SECRET_KEY, tld=config.BINANCE_TLD)
        self.db = db
        self.logger = logger
        self.config = config

    def get_all_market_tickers(self):
        """
        Get ticker price of all coins
        """
        return self.BinanceClient.get_all_tickers()

    def get_market_ticker_price(self, ticker_symbol: str):
        """
        Get ticker price of a specific coin
        """
        for ticker in self.BinanceClient.get_symbol_ticker():
            if ticker[u"symbol"] == ticker_symbol:
                return float(ticker[u"price"])
        return None

    def get_currency_balance(self, currency_symbol: str):
        """
        Get balance of a specific coin
        """
        for currency_balance in self.BinanceClient.get_account()[u"balances"]:
            if currency_balance[u"asset"] == currency_symbol:
                return float(currency_balance[u"free"])
        return None

    def retry(self, func, *args, **kwargs):
        time.sleep(1)
        attempts = 0
        while attempts < 20:
            try:
                return func(*args, **kwargs)
            except Exception as e:
                self.logger.info("Failed to Buy/Sell. Trying Again.")
                if attempts == 0:
                    self.logger.info(e)
                attempts += 1
        return None

    def get_alt_tick(self, origin_symbol: str, target_symbol: str):
        step_size = next(
            _filter['stepSize'] for _filter in self.BinanceClient.get_symbol_info(origin_symbol + target_symbol)['filters']
            if _filter['filterType'] == 'LOT_SIZE')
        if step_size.find('1') == 0:
            return 1 - step_size.find('.')
        else:
            return step_size.find('1') - 1

    def wait_for_order(self, origin_symbol, target_symbol, order_id):
        while True:
            try:
                order_status = self.BinanceClient.get_order(symbol=origin_symbol + target_symbol, orderId=order_id)
                # TODO
                # if order_status == 'PARTIAL_FILLED', check if having other ratio available, then cancel order, sell current filled, make new order
                break
            except BinanceAPIException as e:
                self.logger.info(e)
                time.sleep(1)
            except Exception as e:
                self.logger.info("Unexpected Error: {0}".format(e))
                time.sleep(1)

        self.logger.info(order_status)

        while order_status[u'status'] != 'FILLED':
            try:
                order_status = self.BinanceClient.get_order(symbol=origin_symbol + target_symbol, orderId=order_id)
                if order_status[u'status'] == 'NEW':
                    minutes = (time.time() - order_status[u'time'] / 1000 ) / 60
                    timeout = 0
                    if order_status[u'side'] == 'SELL':
                        timeout = float(self.config.SELL_TIMEOUT)

                    if order_status[u'side'] == 'BUY':
                        timeout = float(self.config.BUY_TIMEOUT)

                    if timeout and minutes > timeout:
                        cancel_order = None
                        while cancel_order is None:
                            cancel_order = self.BinanceClient.cancel_order(symbol=origin_symbol + target_symbol, orderId=order_id)
                        self.logger.info("Order timeout. Going back to scouting mode...")
                        return None

            except BinanceAPIException as e:
                self.logger.info(e)
                time.sleep(1)
            except Exception as e:
                self.logger.info("Unexpected Error: {0}".format(e))
                time.sleep(1)

        return order_status

    def buy_alt(self, origin_coin: Coin, target_coin: Coin, all_tickers):
        return self.retry(self._buy_alt, origin_coin, target_coin, all_tickers)

    def _buy_alt(self, origin_coin: Coin, target_coin: Coin, all_tickers):
        """
        Buy altcoin
        """
        trade_log = self.db.start_trade_log(origin_coin, target_coin, False)
        origin_symbol = origin_coin.symbol
        target_symbol = target_coin.symbol

        origin_tick = self.get_alt_tick(origin_symbol, target_symbol)

        origin_balance = self.get_currency_balance(origin_symbol)
        target_balance = self.get_currency_balance(target_symbol)
        from_coin_price = get_market_ticker_price_from_list(all_tickers, origin_symbol + target_symbol)

        order_quantity = math.floor(
            target_balance
            * 10 ** origin_tick
            / from_coin_price
        ) / float(10 ** origin_tick)
        self.logger.info("BUY QTY {0}".format(order_quantity))

        # Try to buy until successful
        order = None
        # TODO:
        # check latest market price to see if the market price < from_coin_price, then set from_coin_price = market price
        while order is None:
            try:
                order = self.BinanceClient.order_limit_buy(
                    symbol=origin_symbol + target_symbol,
                    quantity=order_quantity,
                    price=from_coin_price,
                )
                self.logger.info(order)
            except BinanceAPIException as e:
                self.logger.info(e)
                time.sleep(1)
            except Exception as e:
                self.logger.info("Unexpected Error: {0}".format(e))

        trade_log.set_ordered(origin_balance, target_balance, order_quantity)

        stat = self.wait_for_order(origin_symbol, target_symbol, order[u'orderId'])

        if stat is None:
            return None

        self.logger.info("Bought {0}".format(origin_symbol))
        trade_log.set_complete(stat["cummulativeQuoteQty"])

        return order

    def sell_alt(self, origin_coin: Coin, target_coin: Coin, all_tickers):
        return self.retry(self._sell_alt, origin_coin, target_coin, all_tickers)

    def _sell_alt(self, origin_coin: Coin, target_coin: Coin, all_tickers):
        """
        Sell altcoin
        """
        trade_log = self.db.start_trade_log(origin_coin, target_coin, True)
        origin_symbol = origin_coin.symbol
        target_symbol = target_coin.symbol

        origin_tick = self.get_alt_tick(origin_symbol, target_symbol)
        from_coin_price = get_market_ticker_price_from_list(all_tickers, origin_symbol + target_symbol)

        order_quantity = math.floor(
            self.get_currency_balance(origin_symbol) * 10 ** origin_tick
        ) / float(10 ** origin_tick)
        self.logger.info("Selling {0} of {1}".format(order_quantity, origin_symbol))

        origin_balance = self.get_currency_balance(origin_symbol)
        target_balance = self.get_currency_balance(target_symbol)
        self.logger.info("Balance is {0}".format(origin_balance))
        order = None
        while order is None:
            order = self.BinanceClient.order_limit_sell(
                symbol=origin_symbol + target_symbol,
                quantity=(order_quantity),
                price=from_coin_price
            )

        self.logger.info("order")
        self.logger.info(order)

        trade_log.set_ordered(origin_balance, target_balance, order_quantity)

        # Binance server can take some time to save the order
        self.logger.info("Waiting for Binance")

        stat = self.wait_for_order(origin_symbol, target_symbol, order[u'orderId'])

        if stat is None:
            return None

        new_balance = self.get_currency_balance(origin_symbol)
        while new_balance >= origin_balance:
            new_balance = self.get_currency_balance(origin_symbol)

        self.logger.info("Sold {0}".format(origin_symbol))

        trade_log.set_complete(stat["cummulativeQuoteQty"])

        return order

    def get_current_ratios(self):
        all_tickers = self.get_all_market_tickers()

        current_coin = self.db.get_current_coin()

        current_coin_price = get_market_ticker_price_from_list(all_tickers, current_coin + self.config.BRIDGE)

        if current_coin_price is None:
            self.logger.info("Skipping scouting... current coin {0} not found".format(current_coin + self.config.BRIDGE))
            return

        heartbeat_msg = ""

        for pair in self.db.get_pairs_from(current_coin):
            if not pair.to_coin.enabled:
                continue
            optional_coin_price = get_market_ticker_price_from_list(all_tickers, pair.to_coin + self.config.BRIDGE)

            if optional_coin_price is None:
                self.logger.info("Skipping scouting... optional coin {0} not found".format(pair.to_coin + self.config.BRIDGE))
                continue

            # Obtain (current coin)/(optional coin)
            coin_opt_coin_ratio = current_coin_price / optional_coin_price

            current_value = (
                coin_opt_coin_ratio
                - self.config.SCOUT_TRANSACTION_FEE
                * self.config.SCOUT_MULTIPLIER
                * coin_opt_coin_ratio
            )
            difference = (current_value - pair.ratio) / pair.ratio * 100

            heartbeat_msg += f"{current_coin.symbol:<5} to {pair.to_coin.symbol:<5}. Diff: {round(difference, 2):>6.2f}%\n"

        return heartbeat_msg

    def heartbeat_message(self):
        current_coin = self.db.get_current_coin().symbol
        heartbeat_data = {
            "current_coin": current_coin,
            "balance": self.get_currency_balance(current_coin),
            "ratios": self.get_current_ratios()
        }

        self.logger.info(self.config.HEARTBEAT_MESSAGE.format(**heartbeat_data))
