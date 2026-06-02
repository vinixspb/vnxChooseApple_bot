import logging
import os
import re
from collections import defaultdict
from datetime import datetime
from typing import List, Dict
from zoneinfo import ZoneInfo

from aiogram import Bot

logger = logging.getLogger(__name__)

PRICE_CHANNEL_ID = os.getenv("PRICE_CHANNEL_ID")
_MSK = ZoneInfo("Europe/Moscow")


def _notify_with_sound() -> bool:
    """Звук только с 11:00 до 13:00 по Москве. Всё остальное время — тихо."""
    hour = datetime.now(_MSK).hour
    return 11 <= hour < 13


def _fmt_price(price: str | int) -> str:
    try:
        return f"{int(price):,}".replace(",", " ")
    except (ValueError, TypeError):
        return str(price)


def _fmt_sim(sim: str) -> str:
    mapping = {
        "esim":      "eSIM",
        "nano+esim": "Nano + eSIM",
        "nano+nano": "Nano + Nano",
        "nanoesim":  "Nano + eSIM",
        "wifi":      "WiFi",
        "lte":       "LTE",
    }
    return mapping.get(sim.lower().replace(" ", ""), sim)


def _memory_gb(mem: str) -> int:
    """Convert memory string to GB integer for sorting: 256GB→256, 1TB→1024."""
    m = re.match(r"^(\d+)(GB|TB)?$", str(mem).strip().upper())
    if not m:
        return 0
    n = int(m.group(1))
    return n * 1024 if (m.group(2) or "GB") == "TB" else n


def format_price_message(items: List[Dict], source: str = "") -> str:
    """Форматирует прайс в компактный вид с группировкой по модели."""
    if not items:
        return ""

    date_str = datetime.now(_MSK).strftime("%d.%m.%Y")

    groups: dict[str, List[Dict]] = defaultdict(list)
    for item in items:
        groups[item.get("item_group_id", "Другое")].append(item)

    lines = [f"🍏 <b>Актуальный прайс — {date_str}</b>", ""]

    for group_name, group_items in groups.items():
        lines.append(f"📱 <b>{group_name}</b>")

        # Сортируем: память по возрастанию (числово), затем цвет
        sorted_items = sorted(
            group_items,
            key=lambda x: (_memory_gb(x.get("memory", "")), x.get("color", "")),
        )

        block_lines = []
        for item in sorted_items:
            mem   = item.get("memory", "-")
            color = item.get("color", "-")
            sim   = _fmt_sim(item.get("sim", "-"))
            price = _fmt_price(item.get("price", "0"))

            parts = [p for p in [mem, color, sim] if p and p != "-"]
            spec  = " | ".join(parts) if parts else "—"
            block_lines.append(f"└ {spec} — {price} ₽")

        block = "\n".join(block_lines)
        lines.append(f"<blockquote expandable>{block}</blockquote>")
        lines.append("")

    return "\n".join(lines).rstrip()


async def publish_price(bot: Bot, items: List[Dict], source: str = "") -> bool:
    """Публикует прайс в канал. 11:00–13:00 МСК — со звуком, остальное — тихо."""
    if not PRICE_CHANNEL_ID:
        logger.warning("PRICE_CHANNEL_ID не задан — публикация пропущена")
        return False
    if not items:
        return False

    text = format_price_message(items)
    if not text:
        logger.info("price_publisher: нет Apple-позиций для публикации")
        return False

    with_sound = _notify_with_sound()
    try:
        await bot.send_message(
            PRICE_CHANNEL_ID,
            text,
            parse_mode="HTML",
            disable_notification=not with_sound,
        )
        mode = "со звуком" if with_sound else "тихо"
        logger.info(f"price_publisher: {len(items)} позиций → {PRICE_CHANNEL_ID} ({mode})")
        return True
    except Exception as e:
        logger.error(f"price_publisher error: {e}")
        return False
