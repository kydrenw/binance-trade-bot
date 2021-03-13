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

    def get_symbol_filter(self, origin_symbol: str, target_symbol: str, filter_type: str):
        return next(_filter for _filter in self.BinanceClient.get_symbol_info(origin_symbol + target_symbol)['filters']
                    if _filter['filterType'] == filter_type)

    def get_alt_tick(self, origin_symbol: str, target_symbol: str):
        step_size = next(
            _filter['stepSize'] for _filter in self.BinanceClient.get_symbol_info(origin_symbol + target_symbol)['filters']
            if _filter['filterType'] == 'LOT_SIZE')
        if step_size.find('1') == 0:
            return 1 - step_size.find('.')
        else:
            return step_size.find('1') - 1

    def get_min_notional(self, origin_symbol: str, target_symbol: str):
        return float(self.get_symbol_filter(origin_symbol, target_symbol, 'MIN_NOTIONAL')['minNotional'])

    def wait_for_order(self, origin_symbol, target_symbol, order_id):
        while True:
            try:
                order_status = self.BinanceClient.get_order(symbol=origin_symbol + target_symbol, orderId=order_id)
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
                        self.logger.info("Order timeout, going back to scouting mode...")
                        return None

                if order_status[u'status'] == 'PARTIALLY_FILLED':
                    # TODO
                    continue

                if order_status[u'status'] == 'CANCELED':
                    self.logger.info("Order is canceled, going back to scouting mode...")
                    return None
                time.sleep(1)

            except BinanceAPIException as e:
                self.logger.info(e)
                time.sleep(1)
            except Exception as e:
                self.logger.info("Unexpected Error: {0}".format(e))
                time.sleep(1)

        return order_status

    def buy_alt(self, origin_coin: Coin, target_coin: Coin, coin_price):
        return self.retry(self._buy_alt, origin_coin, target_coin, coin_price)

    def _buy_alt(self, origin_coin: Coin, target_coin: Coin, coin_price):
        """
        Buy altcoin
        """
        trade_log = self.db.start_trade_log(origin_coin, target_coin, False)
        origin_symbol = origin_coin.symbol
        target_symbol = target_coin.symbol

        origin_tick = self.get_alt_tick(origin_symbol, target_symbol)

        origin_balance = self.get_currency_balance(origin_symbol)
        target_balance = self.get_currency_balance(target_symbol)

        order_quantity = math.floor(target_balance * 10 ** origin_tick / coin_price) / float(10 ** origin_tick)
        self.logger.info("BUY QTY {0}".format(order_quantity))

        # Try to buy until successful
        order = None
        while order is None:
            try:
                order = self.BinanceClient.order_limit_buy(
                    symbol=origin_symbol + target_symbol,
                    quantity=order_quantity,
                    price=coin_price,
                )
                self.logger.info(str(order))
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

    def sell_alt(self, origin_coin: Coin, target_coin: Coin, coin_price):
        return self.retry(self._sell_alt, origin_coin, target_coin, coin_price)

    def _sell_alt(self, origin_coin: Coin, target_coin: Coin, coin_price):
        """
        Sell altcoin
        """
        trade_log = self.db.start_trade_log(origin_coin, target_coin, True)
        origin_symbol = origin_coin.symbol
        target_symbol = target_coin.symbol

        origin_tick = self.get_alt_tick(origin_symbol, target_symbol)

        order_quantity = math.floor(
            self.get_currency_balance(origin_symbol) * 10 ** origin_tick
        ) / float(10 ** origin_tick)
        self.logger.info("Selling {0} of {1}".format(order_quantity, origin_symbol))

        origin_balance = self.get_currency_balance(origin_symbol)
        target_balance = self.get_currency_balance(target_symbol)
        self.logger.info("Balance is {0}".format(origin_balance))
        order = None
        while order is None:
            # Should sell at calculated price to avoid lost coin
            order = self.BinanceClient.order_limit_sell(
                symbol=origin_symbol + target_symbol,
                quantity=(order_quantity),
                price=coin_price
            )

        self.logger.info("order")
        self.logger.info(str(order))

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
