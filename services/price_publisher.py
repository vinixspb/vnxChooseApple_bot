import logging
import os
import re
from collections import defaultdict
from datetime import datetime
from typing import List, Dict
from zoneinfo import ZoneInfo

from aiogram import Bot

from services.channel_manager import delete_old_price_messages, save_message_ids

logger = logging.getLogger(__name__)

PRICE_CHANNEL_ID = os.getenv("PRICE_CHANNEL_ID")
_MSK = ZoneInfo("Europe/Moscow")  # used in _format_category_message for date

# ── Category order: first = least visible, last = most visible (at bottom) ───
_CATEGORY_ORDER = ["other", "beats", "watch", "airpods", "ipad", "mac", "iphone"]

_CATEGORY_EMOJI = {
    "iphone":  "📱",
    "ipad":    "🖥",
    "mac":     "💻",
    "airpods": "🎧",
    "watch":   "⌚",
    "beats":   "🎵",
    "other":   "📦",
}
_CATEGORY_TITLE = {
    "iphone":  "iPhone",
    "ipad":    "iPad",
    "mac":     "MacBook & Mac",
    "airpods": "AirPods",
    "watch":   "Apple Watch",
    "beats":   "Beats",
    "other":   "Аксессуары",
}


def _get_category(item: Dict) -> str:
    text = (item.get("item_group_id", "") + " " + item.get("title", "")).lower()
    if "iphone" in text:                             return "iphone"
    if "airpods" in text or "airpod" in text:        return "airpods"
    if "apple watch" in text or " watch " in text:   return "watch"
    if "ipad" in text:                               return "ipad"
    if "macbook" in text or "mac " in text or "mac neo" in text:
                                                     return "mac"
    if "beats" in text:                              return "beats"
    return "other"


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
    """Numeric sort key: 256GB→256, 1TB→1024."""
    m = re.match(r"^(\d+)(GB|TB)?$", str(mem).strip().upper())
    if not m:
        return 0
    n = int(m.group(1))
    return n * 1024 if (m.group(2) or "GB") == "TB" else n


def _format_category_message(category: str, items: List[Dict]) -> str:
    emoji    = _CATEGORY_EMOJI.get(category, "📦")
    title    = _CATEGORY_TITLE.get(category, "Прайс")
    date_str = datetime.now(_MSK).strftime("%d.%m.%Y")

    groups: Dict[str, List[Dict]] = defaultdict(list)
    for item in items:
        groups[item.get("item_group_id", "Другое")].append(item)

    lines = [f"{emoji} <b>{title} — {date_str}</b>", ""]

    for group_name in sorted(groups):
        sorted_items = sorted(
            groups[group_name],
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

        lines.append(f"<b>{group_name}</b>")
        lines.append(f"<blockquote expandable>{''.join(chr(10).join(block_lines))}</blockquote>")
        lines.append("")

    return "\n".join(lines).rstrip()


async def publish_price(bot: Bot, items: List[Dict], source: str = "") -> bool:
    """
    Publishes items grouped by category in fixed order (iPhone last = most visible).
    Deletes old messages first. All messages sent silently (disable_notification=True).
    """
    if not PRICE_CHANNEL_ID or not items:
        return False

    by_category: Dict[str, List[Dict]] = defaultdict(list)
    for item in items:
        by_category[_get_category(item)].append(item)

    await delete_old_price_messages(bot, PRICE_CHANNEL_ID)

    new_ids: List[int] = []

    for cat in _CATEGORY_ORDER:
        cat_items = by_category.get(cat, [])
        if not cat_items:
            continue
        text = _format_category_message(cat, cat_items)
        if not text:
            continue
        try:
            msg = await bot.send_message(
                PRICE_CHANNEL_ID,
                text,
                parse_mode="HTML",
                disable_notification=True,
            )
            new_ids.append(msg.message_id)
        except Exception as e:
            logger.error(f"publish_price [{cat}]: {e}")

    if new_ids:
        save_message_ids(new_ids)
        logger.info(f"price_publisher: {len(new_ids)} сообщений, {len(items)} позиций")
        return True
    return False
