import logging
import os
from collections import defaultdict
from datetime import datetime
from typing import List, Dict

from aiogram import Bot

logger = logging.getLogger(__name__)

PRICE_CHANNEL_ID = os.getenv("PRICE_CHANNEL_ID")  # ID или @username канала @vnxSHOPprice


def _fmt_price(price: str | int) -> str:
    try:
        return f"{int(price):,}".replace(",", " ")
    except (ValueError, TypeError):
        return str(price)


def _fmt_sim(sim: str) -> str:
    mapping = {
        "esim":         "eSIM",
        "nano+esim":    "Nano + eSIM",
        "nano+nano":    "Nano + Nano",
        "nanoesim":     "Nano + eSIM",
    }
    return mapping.get(sim.lower().replace(" ", ""), sim)


def format_price_message(items: List[Dict], source: str = "") -> str:
    """
    Форматирует прайс в компактный вид с группировкой по модели.
    Каждая группа — сворачиваемая цитата (<blockquote expandable>).
    """
    date_str = datetime.now().strftime("%d.%m.%Y")

    groups: dict[str, List[Dict]] = defaultdict(list)
    for item in items:
        groups[item.get("item_group_id", "Другое")].append(item)

    lines = [f"🍏 <b>Актуальный прайс — {date_str}</b>"]
    if source:
        lines.append(f"📦 Источник: <i>{source}</i>")
    lines.append("")

    for group_name, group_items in groups.items():
        lines.append(f"📱 <b>{group_name}</b>")

        sorted_items = sorted(
            group_items,
            key=lambda x: (x.get("memory", ""), x.get("color", "")),
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

    lines.append("🔄 Обновляется автоматически")
    return "\n".join(lines)


async def publish_price(bot: Bot, items: List[Dict], source: str = "") -> bool:
    """Публикует прайс в канал PRICE_CHANNEL_ID. Возвращает True при успехе."""
    if not PRICE_CHANNEL_ID:
        logger.warning("PRICE_CHANNEL_ID не задан — публикация пропущена")
        return False
    if not items:
        return False

    text = format_price_message(items, source)
    try:
        await bot.send_message(
            PRICE_CHANNEL_ID,
            text,
            parse_mode="HTML",
        )
        logger.info(f"price_publisher: опубликовано {len(items)} позиций в {PRICE_CHANNEL_ID}")
        return True
    except Exception as e:
        logger.error(f"price_publisher error: {e}")
        return False
