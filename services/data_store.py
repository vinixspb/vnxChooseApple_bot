# services/data_store.py
import datetime
from zoneinfo import ZoneInfo

_MSK = ZoneInfo("Europe/Moscow")

CATALOG  = []
SETTINGS = {}
STAGES   = ["model_group", "size", "memory", "memory_ram", "color", "sim"]

# Заполняется при каждой синхронизации прайса (price_watcher / run_price_update)
LAST_SYNC: dict = {}

# Время старта бота (МСК)
START_TIME = datetime.datetime.now(_MSK)
