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

# Categories with memory/color/sim variants → grouped блоками с <blockquote expandable>
_GROUPED_CATEGORIES = {"iphone", "ipad", "mac"}

# Emoji prefix for group headers in grouped categories
_GROUP_EMOJI = {
    "iphone": "📱",
    "ipad":   "🖥",
    "mac":    "💻",
}


def _get_category(item: Dict) -> str:
    text = (item.get("item_group_id", "") + " " + item.get("title", "")).lower()
    if "iphone" in text:                                      return "iphone"
    if "airpods" in text or "airpod" in text:                 return "airpods"
    if "apple watch" in text or re.search(r"\baw\b", text):   return "watch"
    if " watch" in text or "watch " in text:                  return "watch"
    if "ipad" in text:                                        return "ipad"
    if "macbook" in text or "mac " in text or "mac neo" in text:
                                                              return "mac"
    if "beats" in text:                                       return "beats"
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


def _iphone_group_sort_key(group_name: str) -> tuple:
    """
    Sort iPhone groups by generation number, then model tier.
    SE < numbered (12 < 13 < 14 < 15 < 16 < 17 ...)
    Within generation: Air/e < base < Plus < Pro < Pro Max
    """
    name = group_name.lower()

    # Extract generation number (iPhone 15, iPhone 16 Pro, etc.)
    gen_match = re.search(r"iphone\s+(\d+)", name)
    gen = int(gen_match.group(1)) if gen_match else 0

    # SE is lowest within a generation (treat SE as gen 0 if no number)
    if "se" in name and gen == 0:
        gen = -1  # SE without a number sorts first of all

    # Model tier within generation
    if "pro max" in name:
        tier = 4
    elif "pro" in name:
        tier = 3
    elif "plus" in name:
        tier = 2
    elif re.search(r"\bair\b|\be\b", name):
        tier = 0   # Air and 'e' before base
    else:
        tier = 1   # base model

    return (gen, tier)


def _item_emoji(item: Dict) -> str:
    """Emoji per accessory/item type for simple-list categories."""
    text = (item.get("item_group_id", "") + " " + item.get("title", "")).lower()
    if "airtag" in text:
        return "🔘"
    if re.search(r"кабель|cable|зарядк|адаптер|charg", text):
        return "🔌"
    if re.search(r"стекло|glass|защитн|tempered|screen", text):
        return "💎"
    if "homepod" in text:
        return "🔊"
    # чехол/case checked AFTER device-specific accessories but BEFORE device emoji,
    # so "AirPods Pro Case" and "Watch Case" get 🛡 not 🎧/⌚
    if re.search(r"чехол|case\b", text):
        return "🛡"
    if "airpods" in text or "airpod" in text:
        return "🎧"
    if "apple watch" in text or re.search(r"\baw\b|\bwatch\b", text):
        return "⌚"
    if "beats" in text:
        return "🎵"
    return "🍎"


# Telegram hard limit is 4096 chars (incl. HTML tags) — stay safely under it
_MAX_MSG_LEN = 3500


def _pack_chunks(date_str: str, blocks: List[str], sep: str) -> List[str]:
    """Packs atomic blocks into messages under _MAX_MSG_LEN, numbering parts if split."""
    chunks: List[str] = []
    current: List[str] = []
    current_len = 0
    for block in blocks:
        block_len = len(block) + len(sep)
        if current and current_len + block_len > _MAX_MSG_LEN:
            chunks.append(sep.join(current))
            current, current_len = [], 0
        current.append(block)
        current_len += block_len
    if current:
        chunks.append(sep.join(current))

    total = len(chunks)
    return [
        f"🍏 <b>Актуальный прайс{f' ({i}/{total})' if total > 1 else ''} — {date_str}</b>\n\n{body}"
        for i, body in enumerate(chunks, start=1)
    ]


def _format_category_messages(category: str, items: List[Dict]) -> List[str]:
    date_str = datetime.now(_MSK).strftime("%d.%m.%Y")

    if category in _GROUPED_CATEGORIES:
        group_emoji = _GROUP_EMOJI.get(category, "")

        groups: Dict[str, List[Dict]] = defaultdict(list)
        for item in items:
            groups[item.get("item_group_id", "Другое")].append(item)

        # iPhone: sort by generation→tier; iPad/Mac: alphabetically
        if category == "iphone":
            sorted_groups = sorted(groups, key=_iphone_group_sort_key)
        else:
            sorted_groups = sorted(groups)

        blocks = []
        for group_name in sorted_groups:
            # De-duplicate: same (memory, color, sim) spec → keep cheapest.
            # Prevents "blind twins" when old rows have no SIM field and two
            # suppliers carry the same configuration at different prices.
            best: dict[tuple, dict] = {}
            for it in groups[group_name]:
                key = (it.get("memory", ""), it.get("color", ""), it.get("sim", ""))
                try:
                    candidate_price = int(it.get("price", 0) or 0)
                    existing_price  = int(best[key].get("price", 0) or 0) if key in best else None
                except (ValueError, TypeError):
                    candidate_price, existing_price = 0, None
                if existing_price is None or candidate_price < existing_price:
                    best[key] = it

            sorted_items = sorted(
                best.values(),
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

            blocks.append(
                f"{group_emoji} <b>{group_name}</b>\n"
                f"<blockquote expandable>{chr(10).join(block_lines)}</blockquote>"
            )
        return _pack_chunks(date_str, blocks, sep="\n\n")

    # Simple flat list — accessories, AirPods, Watch, Beats: emoji + name — price
    sorted_items = sorted(
        items,
        key=lambda x: (x.get("item_group_id", ""), _memory_gb(x.get("memory", "")), x.get("color", "")),
    )
    lines = []
    for item in sorted_items:
        emoji = _item_emoji(item)
        name  = item.get("title") or item.get("item_group_id", "")
        price = _fmt_price(item.get("price", "0"))
        lines.append(f"{emoji} {name} — {price} ₽")
    return _pack_chunks(date_str, lines, sep="\n")


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
        for text in _format_category_messages(cat, cat_items):
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
