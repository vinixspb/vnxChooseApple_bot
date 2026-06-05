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

# Accumulated items waiting for delayed publish to @vnxSHOPprice
PENDING_PUBLISH: list[dict] = []
PUBLISH_TASK: Optional[asyncio.Task] = None
