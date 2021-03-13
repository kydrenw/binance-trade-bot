# Config consts
import configparser
import os

from .models import Coin

CFG_FL_NAME = "user.cfg"
USER_CFG_SECTION = "binance_user_config"


class Config:
    def __init__(self):
        # Init config
        config = configparser.ConfigParser()
        config["DEFAULT"] = {
            "bridge": "USDT",
            "scout_transaction_fee": "0.001",
            "scout_multiplier": "5",
            "scout_sleep_time": "5",
            "hourToKeepScoutHistory": "1",
            "tld": "com",
            "heartbeat_duration": "0",
            "heartbeat_message": "0",
            "sell_timeout": "0",
            "buy_timeout": "0",
            "min_scout_rate": "0",
            "min_notional": "10"
        }

        if not os.path.exists(CFG_FL_NAME):
            print(
                "No configuration file (user.cfg) found! See README. Assuming default config..."
            )
            config[USER_CFG_SECTION] = {}
        config.read(CFG_FL_NAME)

        self.BRIDGE_SYMBOL = os.environ.get("BRIDGE_SYMBOL") or config.get(
            USER_CFG_SECTION, "bridge"
        )
        self.BRIDGE = Coin(self.BRIDGE_SYMBOL, False)

        # Prune settings
        self.SCOUT_HISTORY_PRUNE_TIME = float(
            os.environ.get("HOURS_TO_KEEP_SCOUTING_HISTORY")
            or config.get(USER_CFG_SECTION, "hourToKeepScoutHistory")
        )

        # Get config for scout
        self.SCOUT_TRANSACTION_FEE = float(
            os.environ.get("SCOUT_TRANSACTION_FEE")
            or config.get(USER_CFG_SECTION, "scout_transaction_fee")
        )
        self.SCOUT_MULTIPLIER = float(
            os.environ.get("SCOUT_MULTIPLIER")
            or config.get(USER_CFG_SECTION, "scout_multiplier")
        )
        self.SCOUT_SLEEP_TIME = int(
            os.environ.get("SCOUT_SLEEP_TIME")
            or config.get(USER_CFG_SECTION, "scout_sleep_time")
        )

        # Get config for heartbeat
        self.HEARTBEAT_DURATION = int(
            os.environ.get("HEARTBEAT_DURATION")
            or config.get(USER_CFG_SECTION, "heartbeat_duration")
        )

        self.HEARTBEAT_MESSAGE = (
            os.environ.get("HEARTBEAT_MESSAGE")
            or config.get(USER_CFG_SECTION, "heartbeat_message")
        ).replace('\\n', '\n')

        # Get config for binance
        self.BINANCE_API_KEY = os.environ.get("API_KEY") or config.get(
            USER_CFG_SECTION, "api_key"
        )
        self.BINANCE_API_SECRET_KEY = os.environ.get("API_SECRET_KEY") or config.get(
            USER_CFG_SECTION, "api_secret_key"
        )
        self.BINANCE_TLD = os.environ.get("TLD") or config.get(USER_CFG_SECTION, "tld")

        self.SUPPORTED_COIN_LIST = (
            os.environ.get("SUPPORTED_COIN_LIST").split()
            if os.environ.get("SUPPORTED_COIN_LIST")
            else []
        )

        # Get supported coin list from supported_coin_list file
        if not self.SUPPORTED_COIN_LIST:
            with open("supported_coin_list") as f:
                self.SUPPORTED_COIN_LIST = f.read().upper().strip().splitlines()
                self.SUPPORTED_COIN_LIST = list(filter(None, self.SUPPORTED_COIN_LIST))

        self.CURRENT_COIN_SYMBOL = os.environ.get("CURRENT_COIN_SYMBOL") or config.get(
            USER_CFG_SECTION, "current_coin"
        )

        self.SELL_TIMEOUT = os.environ.get("SELL_TIMEOUT") or config.get(USER_CFG_SECTION, "sell_timeout")
        self.BUY_TIMEOUT = os.environ.get("BUY_TIMEOUT") or config.get(USER_CFG_SECTION, "buy_timeout")
        self.MIN_SCOUT_RATE = os.environ.get("MIN_SCOUT_RATE") or config.get(USER_CFG_SECTION, "min_scout_rate")
        self.MIN_NOTIONAL = os.environ.get("MIN_NOTIONAL") or config.get(USER_CFG_SECTION, "min_notional")
