import logging
import os
import re
from collections import defaultdict
from datetime import datetime
from typing import List, Dict
from zoneinfo import ZoneInfo

from aiogram import Bot

from services.channel_manager import delete_old_price_messages, save_message_ids
from services import incidents
from services import incident_rules as rules
from services import banners

logger = logging.getLogger(__name__)

PRICE_CHANNEL_ID = os.getenv("PRICE_CHANNEL_ID")
_MSK = ZoneInfo("Europe/Moscow")  # used in _format_category_message for date

# ── Category order: first = least visible, last = most visible (at bottom) ───
_CATEGORY_ORDER = ["other", "watch", "airpods", "ipad", "mac", "iphone"]

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
    if "beats" in text:                                       return "airpods"  # Apple-owned, same block
    if "apple watch" in text or re.search(r"\baw\b", text):   return "watch"
    if " watch" in text or "watch " in text:                  return "watch"
    if "ipad" in text:                                        return "ipad"
    if "macbook" in text or "mac " in text or "mac neo" in text:
                                                              return "mac"
    return "other"


# ── Mac: раскладка по линейкам ───────────────────────────────────────────────
# Раньше все маки шли одной кучей, отсортированной по алфавиту: «Air 13 (2024)
# M3 24/», «Air 13 (2024) M3 8/», «Air 13 (2025) M4 16/», между ними Pro 16 и
# Pro 14. Выбрать по такому списку невозможно.
#
# Покупатель сначала определяется с РАЗМЕРОМ («большой не хочу»), и только
# потом сравнивает процессоры и цены. Поэтому размер — верхний уровень:
# отдельный пост на MacBook Air 13″, отдельный на 15″, внутри блоки по
# процессорам от старого к новому.
#
# Хвост «16/» в названии группы — это ОЗУ: парсер режет строку по объёму
# диска, и «16/1tb» распадается на «16/» в имени модели и «1TB» в памяти.
# Разбираем обратно и показываем как «16/1TB».

_MAC_RAM_TAIL_RE = re.compile(r"\s(\d{1,2})\s*/\s*$")
_MAC_YEAR_RE     = re.compile(r"\((\d{4})\)")
_MAC_CHIP_RE     = re.compile(r"\bM(\d)\b\s*(Pro|Max|Ultra)?", re.IGNORECASE)

# Ссылка на картинку-шапку блока Mac. Задаётся в .env или в листе Settings
# ключом MAC_HEADER_IMAGE. Пусто — пост выходит без картинки.
_MAC_HEADER_IMAGE = os.getenv("MAC_HEADER_IMAGE", "")

_CHIP_TIER = {"": 0, "pro": 1, "max": 2, "ultra": 3}


def _mac_split_ram(group_name: str) -> tuple[str, str]:
    """«MacBook Air 13 (2026) M5 16/» → («MacBook Air 13 (2026) M5», «16»)."""
    m = _MAC_RAM_TAIL_RE.search(group_name)
    if m:
        return group_name[: m.start()].strip(), m.group(1)
    return group_name.strip(), ""


def _mac_line(group_name: str) -> str:
    """Линейка и размер — верхний уровень выбора: «MacBook Air 13″»."""
    t = group_name.lower()
    m = re.search(r"macbook\s+(air|pro|neo)\s*(\d{2})", t)
    if m:
        kind = {"air": "Air", "pro": "Pro", "neo": "Neo"}[m.group(1)]
        return f"MacBook {kind} {m.group(2)}″"
    if "imac" in t:                  return "iMac"
    if re.search(r"mac\s*mini", t):  return "Mac mini"
    if re.search(r"mac\s*studio", t): return "Mac Studio"
    if re.search(r"mac\s*pro", t):   return "Mac Pro"
    if "macbook" in t:               return "MacBook"
    return "Mac"


def _mac_chip(group_name: str) -> str:
    """«MacBook Pro 16 (2026) M5 Pro» → «M5 Pro»."""
    m = _MAC_CHIP_RE.search(group_name)
    if not m:
        return ""
    suffix = f" {m.group(2).capitalize()}" if m.group(2) else ""
    return f"M{m.group(1)}{suffix}"


def _mac_chip_sort(chip: str) -> tuple:
    """M3 < M4 < M5 < M5 Pro < M5 Max. Без чипа — в конец."""
    m = re.match(r"M(\d)(?:\s+(\w+))?", chip)
    if not m:
        return (99, 0)
    return (int(m.group(1)), _CHIP_TIER.get((m.group(2) or "").lower(), 0))


def _mac_line_sort(line: str) -> tuple:
    """Air перед Pro, внутри — по возрастанию диагонали."""
    order = {"Air": 0, "Neo": 1, "Pro": 2}
    m = re.match(r"MacBook (Air|Neo|Pro) (\d{2})", line)
    if m:
        return (0, order.get(m.group(1), 3), int(m.group(2)))
    return (1, 0, 0)


def _mac_year(group_name: str) -> int:
    m = _MAC_YEAR_RE.search(group_name)
    return int(m.group(1)) if m else 0


def _fmt_price(price: str | int) -> str:
    try:
        return f"{int(price):,}".replace(",", " ")
    except (ValueError, TypeError):
        return str(price)


_SIM_LABELS: Dict[str, str] = {
    "esim":      "eSIM",
    "esim+esim": "eSIM + eSIM",   # iPhone Duo — физической SIM нет
    "nano+esim": "Nano + eSIM",
    "nano+nano": "Nano + Nano",
    "nanoesim":  "Nano + eSIM",
    "wifi":      "WiFi",
    "lte":       "LTE",
}

_REGION_FLAG: Dict[str, str] = {
    "international": "🌐",
    "россия":        "🇷🇺",
    "европа":        "🇪🇺",
    "китай":         "🇨🇳",
    "uk":            "🇬🇧",
    "сша":           "🇺🇸",
    # Парсер выводит регион из типа SIM и называет его «Америка».
    # Без этого ключа eSIM-айфоны показывались словом, а не флагом,
    # тогда как «Европа» рядом рисовалась как 🇪🇺.
    "америка":       "🇺🇸",
}


def _fmt_sim(sim: str) -> str:
    return _SIM_LABELS.get(sim.lower().replace(" ", ""), sim)


def _fmt_sim_marked(sim: str) -> str:
    """Format SIM with visual marker: ☁️ digital-only eSIM, 📎 physical card."""
    label = _fmt_sim(sim)
    if not label or label == "-":
        return ""
    s = label.lower()
    if "nano" in s or "dual" in s or "lte" in s:
        return f"📎 {label}"
    if "esim" in s:
        return f"☁️ {label}"
    if "wifi" in s:
        return f"📶 {label}"
    return label


def _sim_order(sim: str) -> int:
    """Sort key within a group: pure eSIM first (cheaper), physical SIM second."""
    s = sim.lower().replace(" ", "")
    if not s or s == "-":
        return 3
    if "esim" in s and "nano" not in s:
        return 0   # pure eSIM
    if "wifi" in s:
        return 2   # WiFi (iPad) — after physical SIM
    return 1       # Nano+eSIM, Nano+Nano, Dual SIM, LTE


def _fmt_region(region: str) -> str:
    """Map region label to flag emoji, or return label as-is if unknown."""
    return _REGION_FLAG.get(region.strip().lower(), region)


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

    # iPhone Duo — складной флагман без номера поколения. Списки идут по
    # возрастанию, а сама категория iPhone публикуется последней как самая
    # заметная, поэтому низ списка — лучшее место. Без этого Duo с gen=0
    # оказался бы на самом верху, выше iPhone 13.
    if "duo" in name:
        gen = 999

    # SE is lowest within a generation (treat SE as gen 0 if no number)
    elif "se" in name and gen == 0:
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
    if re.search(r"keyboard|клавиатур", text):
        return "⌨️"
    if re.search(r"pencil|стилус", text):
        return "✏️"
    # чехол/case checked AFTER device-specific accessories but BEFORE device emoji,
    # so "AirPods Pro Case" and "Watch Case" get 🛡 not 🎧/⌚
    if re.search(r"чехол|case\b", text):
        return "🛡"
    if "airpods" in text or "airpod" in text:
        return "🎧"
    if "apple watch" in text or re.search(r"\baw\b|\bwatch\b", text):
        return "⌚"
    if "beats" in text:
        return "🎧"
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


def _format_mac_messages(items: List[Dict]) -> List[str]:
    """
    Отдельное сообщение на каждую линейку Mac, внутри — блоки по процессорам.

    Внутри блока сортировка по ОЗУ, затем по диску, затем по цвету: человек
    уже выбрал размер и процессор, дальше он сравнивает конфигурации и цену.
    """
    date_str = datetime.now(_MSK).strftime("%d.%m.%Y")

    # Раскладываем: линейка → процессор → позиции
    lines: Dict[str, Dict[str, List[Dict]]] = defaultdict(lambda: defaultdict(list))
    for item in items:
        raw_group = item.get("item_group_id", "Mac")
        clean, ram = _mac_split_ram(raw_group)
        entry = dict(item)
        entry["_clean_group"] = clean
        entry["_ram"] = ram
        lines[_mac_line(clean)][_mac_chip(clean) or "—"].append(entry)

    messages: List[str] = []
    for line in sorted(lines, key=_mac_line_sort):
        chips = lines[line]
        blocks: List[str] = []

        for chip in sorted(chips, key=_mac_chip_sort):
            rows = sorted(
                chips[chip],
                key=lambda x: (
                    int(x["_ram"]) if x["_ram"].isdigit() else 0,
                    _memory_gb(x.get("memory", "")),
                    x.get("color", ""),
                ),
            )

            years = sorted({_mac_year(r["_clean_group"]) for r in rows if _mac_year(r["_clean_group"])})
            year_str = f" · {'/'.join(str(y) for y in years)}" if years else ""

            body = []
            for r in rows:
                ram  = r["_ram"]
                mem  = r.get("memory", "-")
                spec = f"{ram}/{mem}" if ram and mem != "-" else (mem if mem != "-" else f"{ram} ГБ ОЗУ")
                color = r.get("color", "-")
                price = _fmt_price(r.get("price", "0"))
                parts = [p for p in [spec, color] if p and p != "-"]
                body.append(f"└ {' | '.join(parts)} — {price} ₽")

            # Размер уже в заголовке поста — в блоке остаётся семейство и чип
            family = re.sub(r"\s*\d{2}″$", "", line)
            blocks.append(
                f"💻 <b>{family} {chip}</b>{year_str}\n"
                f"<blockquote expandable>{chr(10).join(body)}</blockquote>"
            )

        header = f"🍏 <b>Актуальный прайс — {date_str}</b>\n🆕 <b>{line}</b> 🆕"
        for chunk in _pack_blocks(header, blocks):
            messages.append(chunk)

    return messages


def _pack_blocks(header: str, blocks: List[str]) -> List[str]:
    """Пакует блоки под лимит Telegram, нумеруя части только при разбиении."""
    chunks: List[str] = []
    current: List[str] = []
    current_len = len(header)
    for block in blocks:
        if current and current_len + len(block) + 2 > _MAX_MSG_LEN:
            chunks.append("\n\n".join(current))
            current, current_len = [], len(header)
        current.append(block)
        current_len += len(block) + 2
    if current:
        chunks.append("\n\n".join(current))

    total = len(chunks)
    out = []
    for i, body in enumerate(chunks, start=1):
        head = header if total == 1 else f"{header} ({i}/{total})"
        out.append(f"{head}\n\n{body}")
    return out


def _format_category_messages(category: str, items: List[Dict]) -> List[str]:
    date_str = datetime.now(_MSK).strftime("%d.%m.%Y")

    if category == "mac":
        return _format_mac_messages(items)

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
            sorted_items = sorted(
                groups[group_name],
                key=lambda x: (
                    _memory_gb(x.get("memory", "")),
                    _sim_order(x.get("sim", "")),
                    x.get("color", ""),
                ),
            )
            block_lines = []
            for item in sorted_items:
                mem    = item.get("memory", "-")
                color  = item.get("color", "-")
                sim    = _fmt_sim_marked(item.get("sim", "-"))
                region = _fmt_region(item.get("region", "-"))
                price  = _fmt_price(item.get("price", "0"))
                parts  = [p for p in [mem, color, sim, region] if p and p != "-"]
                spec   = " | ".join(parts) if parts else "—"
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


async def _send_banner(bot: Bot, category: str) -> int | None:
    """
    Отправляет картинку-шапку категории. Возвращает message_id или None.

    Сначала пробуем file_id, сохранённый командой /banner: его не нужно
    нигде хостить и он не может протухнуть. Если его нет — прямую ссылку
    из Settings. Нет ни того, ни другого — просто ничего не отправляем.
    """
    file_id = banners.get(category)
    if not file_id:
        url = _header_image(category)
        if not url:
            return None
        file_id = url

    try:
        msg = await bot.send_photo(
            PRICE_CHANNEL_ID, file_id, disable_notification=True
        )
        return msg.message_id
    except Exception as e:
        # Баннер — украшение. Из-за него публикация прайса падать не должна.
        logger.warning(f"price_publisher: баннер '{category}' не отправлен: {e}")
        return None


def _header_image(category: str) -> str:
    """
    Картинка-шапка для категории. Берётся из листа Settings, иначе из .env.

    Через Settings — чтобы менять баннер без правки кода и перезапуска бота.
    """
    try:
        import services.data_store as store
        from_settings = str(store.SETTINGS.get(f"{category.upper()}_HEADER_IMAGE", "")).strip()
        if from_settings:
            return from_settings
    except Exception:
        pass
    if category == "mac":
        return _MAC_HEADER_IMAGE
    return os.getenv(f"{category.upper()}_HEADER_IMAGE", "")


async def _send_block(bot: Bot, text: str, image_url: str = ""):
    """
    Отправляет блок прайса, при наличии ссылки — с картинкой над текстом.

    Картинка идёт превью ссылки с флагом show_above_text, а не отдельным
    фото с подписью: у подписи к фото лимит 1024 символа, в него прайс
    не помещается, да и разбивать список на фото и текст неудобно читать.
    Флаг появился в Bot API 7.0; на старом aiogram аккуратно откатываемся
    к обычному сообщению, чтобы публикация не сорвалась из-за баннера.
    """
    if image_url:
        try:
            from aiogram.types import LinkPreviewOptions
            return await bot.send_message(
                PRICE_CHANNEL_ID,
                text,
                parse_mode="HTML",
                disable_notification=True,
                link_preview_options=LinkPreviewOptions(
                    is_disabled=False,
                    url=image_url,
                    prefer_large_media=True,
                    show_above_text=True,
                ),
            )
        except (ImportError, TypeError) as e:
            logger.warning(f"price_publisher: баннер не поддержан этой версией aiogram ({e})")

    return await bot.send_message(
        PRICE_CHANNEL_ID,
        text,
        parse_mode="HTML",
        disable_notification=True,
    )


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
        # Баннер идёт отдельным сообщением перед блоком — его message_id
        # попадает в тот же список, поэтому при следующей публикации он
        # удалится вместе с прайсом и дубля картинок в канале не будет.
        banner_id = await _send_banner(bot, cat)
        if banner_id:
            new_ids.append(banner_id)

        header_image = _header_image(cat)
        for text in _format_category_messages(cat, cat_items):
            try:
                msg = await _send_block(bot, text, header_image)
                new_ids.append(msg.message_id)
            except Exception as e:
                incidents.report(
                    component=rules.TELEGRAM,
                    exc=e,
                    detail=f"Сообщение категории '{cat}' не отправлено в канал",
                    key=cat,
                    context={
                        "канал":  PRICE_CHANNEL_ID or "не задан",
                        "длина":  len(text),
                    },
                )

    if new_ids:
        save_message_ids(new_ids)
        logger.info(f"price_publisher: {len(new_ids)} сообщений, {len(items)} позиций")
        # Публикация прошла — гасим инциденты доставки в канал
        for cat in _CATEGORY_ORDER:
            incidents.ok(rules.TELEGRAM, "TG_FORBIDDEN", "TG_BAD_REQUEST",
                         "TG_RATE_LIMIT", "TG_NETWORK", key=cat)
        return True
    return False
