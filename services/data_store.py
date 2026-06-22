# services/data_store.py
import asyncio
import datetime
from typing import Optional
from zoneinfo import ZoneInfo

_MSK = ZoneInfo("Europe/Moscow")

CATALOG  = []
SETTINGS = {}
STAGES   = ["model_group", "size", "memory", "memory_ram", "color", "sim"]
LAST_SYNC: dict = {}
START_TIME = datetime.datetime.now(_MSK)

# Catalog has unpublished changes — full catalog is republished on next debounce
CATALOG_DIRTY: bool = False
PUBLISH_TASK: Optional[asyncio.Task] = None
