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
from services import coming_soon

logger = logging.getLogger(__name__)

PRICE_CHANNEL_ID = os.getenv("PRICE_CHANNEL_ID")
_MSK = ZoneInfo("Europe/Moscow")  # used in _format_category_message for date

# ── Порядок публикации ───────────────────────────────────────────────────────
# Канал показывает сообщения в порядке отправки, поэтому отправленное
# ПОСЛЕДНИМ оказывается внизу — на самом видном месте. Отсюда порядок:
# мелочь наверх, айфоны в самый низ.
_CATEGORY_ORDER = ["accessory", "audio", "watch", "ipad", "mac", "iphone"]

_CATEGORY_TITLE = {
    "accessory": "📦 Аксессуары",
    "audio":     "🎧 Наушники и звук",
    "watch":     "⌚ Apple Watch",
    "ipad":      "🖥 iPad",
    "iphone":    "📱 iPhone",
}

# Имена файлов-баннеров для категории. Внутренний код категории — не то,
# как человек назовёт картинку: папка «accessory» напрашивается как
# «accessories» или «appleaccessories». Перебираем синонимы, чтобы файл
# подхватывался под любым разумным именем, а не молча игнорировался.
_CATEGORY_BANNER_KEYS = {
    "accessory": ["accessory", "accessories", "appleaccessories"],
    "audio":     ["audio", "airpods", "appleaudio", "sound"],
    "watch":     ["watch", "applewatch"],
    "ipad":      ["ipad", "appleipad"],
    "iphone":    ["iphone", "appleiphone"],
    "mac":       ["mac", "applemac", "macbook"],
}


def _category_keys(category: str) -> List[str]:
    return _CATEGORY_BANNER_KEYS.get(category, [category])


# Categories with memory/color/sim variants → grouped блоками с <blockquote expandable>
_GROUPED_CATEGORIES = {"iphone", "ipad"}

# Emoji prefix for group headers in grouped categories
_GROUP_EMOJI = {
    "iphone": "📱",
    "ipad":   "🖥",
    "mac":    "💻",
}

# ── Определение категории ────────────────────────────────────────────────────
# Порядок проверок важен. Аксессуары идут ПЕРВЫМИ, потому что их названия
# содержат имя модели: «15 Pro Clear Silicone Case» — это чехол, а не iPhone,
# «Стекло защитное 16 Pro» — стекло, «Magic Keyboard 11» — клавиатура.

_ACCESSORY_RE = re.compile(
    r"чехол|case\b|стекл|glass|защитн|tempered|screen\s*protect|"
    r"кабель|cable|зарядк|адаптер|charg|адаптор|"
    r"keyboard|клавиатур|mouse|мыш|trackpad|pencil|стилус|"
    r"airtag|ремешок|band\b|док|dock\b|хаб|hub\b|переходник",
    re.IGNORECASE,
)

# Модель без слова iPhone: поставщики пишут «Apple 11», «Apple 16e»,
# «Apple 14 Pro Max». Именно из-за этого полсотни айфонов раньше падали
# в кучу аксессуаров: проверка искала подстроку «iphone», а её там нет.
_BARE_IPHONE_RE = re.compile(
    r"^(?:apple\s+)?(?:"
    r"(\d{1,2})\s*(?:e\b|pro|plus|max|air|mini|$|\s)"
    r"|SE\b"          # «SE 2022» — тоже iPhone, просто без номера поколения
    r")", re.IGNORECASE)

# Целые часы, а не аксессуар к ним. «AW 10 42 Gold Case Gold Milanese Loop» —
# это часы в сборе: Case здесь означает корпус, а не защитный чехол.
# Без этой проверки слово Case отправляло такие позиции в «Чехлы».
_WATCH_MODEL_RE = re.compile(
    r"\baw\s*\d{1,2}\b|apple\s*watch|\bwatch\s*(?:ultra|se|series|s\d)", re.IGNORECASE
)
# А вот это именно аксессуар к часам, даже если рядом написано Watch
_WATCH_ACCESSORY_RE = re.compile(r"^\s*(ремеш|ремень|band\b|strap)", re.IGNORECASE)


def _get_category(item: Dict) -> str:
    group = str(item.get("item_group_id", "")).strip()
    text = (group + " " + str(item.get("title", ""))).lower()

    # 1. Часы в сборе — до правила аксессуаров: в их названии есть «Case»
    if _WATCH_MODEL_RE.search(text) and not _WATCH_ACCESSORY_RE.match(text):
        return "watch"

    # 2. Аксессуары — до всего остального, см. комментарий выше
    if _ACCESSORY_RE.search(text):
        return "accessory"

    # 2. Звук
    if re.search(r"airpods?|beats|homepod|наушник", text):
        return "audio"

    # 3. Часы
    if "apple watch" in text or re.search(r"\baw\b|\bwatch\b", text):
        return "watch"

    if "ipad" in text:
        return "ipad"

    if re.search(r"macbook|imac|mac\s*mini|mac\s*studio|mac\s*pro|mac\s+m\d|mac\s*neo", text):
        return "mac"

    if "iphone" in text:
        return "iphone"

    # 4. Голый номер модели — это iPhone
    if _BARE_IPHONE_RE.match(group):
        return "iphone"

    # Всё непонятное кладём к аксессуарам, а не в отдельную свалку:
    # отдельная категория «прочее» превращалась в мусорный ящик,
    # который никто не читает.
    return "accessory"


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


def _display_group(category: str, group_name: str) -> str:
    """
    Имя группы для заголовка блока.

    Из каталога приходит «11», «16e», «14 Pro Max» — префикс «Apple»
    снимается при нормализации, и в канале оставался голый номер.
    Возвращаем слово iPhone на место: покупателю «11» ни о чём не говорит.
    """
    name = str(group_name).strip()
    if category == "iphone" and "iphone" not in name.lower():
        return f"iPhone {name}"
    return name


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

    # Номер поколения. Ищем и «iPhone 15», и голое «15», и «16e» —
    # поставщики пишут по-разному, а порядок должен быть один.
    # Граница слова после числа не годится: в «16e» за цифрой идёт буква,
    # и такие модели улетали в начало списка с поколением 0.
    gen_match = (re.search(r"iphone\s*(\d{1,2})", name)
                 or re.search(r"^(?:apple\s+)?(\d{1,2})", name))
    gen = int(gen_match.group(1)) if gen_match else 0

    # iPhone Air без номера — это поколение 17
    if "air" in name and gen == 0:
        gen = 17

    # iPhone Duo — складной флагман без номера поколения. Списки идут по
    # возрастанию, а сама категория iPhone публикуется последней как самая
    # заметная, поэтому низ списка — лучшее место. Без этого Duo с gen=0
    # оказался бы на самом верху, выше iPhone 13.
    if "duo" in name:
        gen = 999

    # SE is lowest within a generation (treat SE as gen 0 if no number)
    elif "se" in name and gen == 0:
        gen = -1  # SE without a number sorts first of all

    # Порядок внутри поколения, сверху вниз:
    # 17e → 17 → 17 Plus → iPhone Air → 17 Pro → 17 Pro Max.
    # Сначала доступное, ниже — дороже и старше, чтобы флагман оказался
    # ближе к низу списка, на самом видном месте.
    if "pro max" in name:
        tier = 5
    elif "pro" in name:
        tier = 4
    elif re.search(r"\bair\b", name):
        tier = 3
    elif "plus" in name:
        tier = 2
    elif re.search(r"\d+\s*e\b|\be\b", name):
        tier = 0   # 16e, 17e — самые доступные
    else:
        tier = 1   # базовая модель

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


def _format_mac_messages(items: List[Dict]) -> List[tuple]:
    """
    Отдельное сообщение на каждую линейку Mac, внутри — блоки по процессорам.

    Возвращает пары (текст, ключи баннера): у каждой линейки может быть
    своя картинка-шапка.

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

    messages: List[tuple] = []
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
                body.append(f"• {' | '.join(parts)} — {price} ₽")

            # Размер уже в заголовке поста — в блоке остаётся семейство и чип
            family = re.sub(r"\s*\d{2}″$", "", line)
            blocks.append(
                f"💻 <b>{family} {chip}</b>{year_str}\n"
                f"<blockquote expandable>{chr(10).join(body)}</blockquote>"
            )

        header = f"🍏 <b>Актуальный прайс — {date_str}</b>\n🆕 <b>{line}</b> 🆕"

        # Ключи баннера от частного к общему: своя картинка у 13-дюймовых,
        # иначе общая для Air, иначе общая для всех маков.
        family = re.sub(r"\s*\d{2}″$", "", line)
        keys = [banners.slug(line), banners.slug(family), "mac"]

        for chunk in _pack_blocks(header, blocks):
            messages.append((chunk, keys))

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


# ── Подгруппы внутри простых категорий ───────────────────────────────────────
# Плоский список в полсотни строк читать невозможно: клавиатуры вперемешку
# с чехлами, колонками и метками. Разбиваем на понятные полки.
# Порядок правил = порядок полок в сообщении.

_SUBGROUPS: Dict[str, List[tuple]] = {
    "accessory": [
        ("🛡", "Чехлы и защита",  r"чехол|case\b|стекл|glass|защитн|tempered|screen"),
        ("🔌", "Кабели и зарядка", r"кабель|cable|зарядк|адаптер|charg|переходник"),
        ("⌨️", "Клавиатуры и стилусы", r"keyboard|клавиатур|mouse|мыш|trackpad|pencil|стилус"),
        ("🔘", "AirTag",          r"airtag"),
        ("⌚", "Ремешки",          r"ремешок|band\b"),
    ],
    "audio": [
        ("🎧", "AirPods",  r"airpods?"),
        ("🎧", "Beats",    r"beats"),
        ("🔊", "HomePod",  r"homepod"),
    ],
}

_SUBGROUP_FALLBACK = ("📦", "Прочее")


def _format_subgrouped(category: str, items: List[Dict]) -> List[tuple]:
    """
    Простая категория, разложенная по полкам: аксессуары, звук.

    Внутри полки сортировка по названию, чтобы одинаковые товары
    разных цветов стояли рядом.
    """
    date_str = datetime.now(_MSK).strftime("%d.%m.%Y")
    rules = _SUBGROUPS.get(category, [])

    shelves: Dict[str, List[Dict]] = defaultdict(list)
    order: List[str] = []

    for item in items:
        text = (str(item.get("item_group_id", "")) + " " + str(item.get("title", ""))).lower()
        placed = False
        for emoji, title, pattern in rules:
            if re.search(pattern, text, re.IGNORECASE):
                key = f"{emoji} {title}"
                if key not in shelves:
                    order.append(key)
                shelves[key].append(item)
                placed = True
                break
        if not placed:
            key = f"{_SUBGROUP_FALLBACK[0]} {_SUBGROUP_FALLBACK[1]}"
            if key not in shelves:
                order.append(key)
            shelves[key].append(item)

    # Полки идут в порядке правил, «Прочее» всегда последним
    rule_order = [f"{e} {t}" for e, t, _ in rules]
    order.sort(key=lambda k: rule_order.index(k) if k in rule_order else 99)

    blocks = []
    for key in order:
        rows = sorted(shelves[key], key=lambda x: (x.get("title") or x.get("item_group_id", "")))
        lines = []
        for item in rows:
            name  = item.get("title") or item.get("item_group_id", "")
            price = _fmt_price(item.get("price", "0"))
            lines.append(f"• {name} — {price} ₽")
        blocks.append(
            f"<b>{key}</b>\n<blockquote expandable>{chr(10).join(lines)}</blockquote>"
        )

    header = (f"🍏 <b>Актуальный прайс — {date_str}</b>\n"
              f"<b>{_CATEGORY_TITLE.get(category, category)}</b>")
    return [(t, _category_keys(category)) for t in _pack_blocks(header, blocks)]


def _format_watch_messages(items: List[Dict], category: str = "watch") -> List[tuple]:
    """Часы по модельным рядам: Series, Ultra, SE — каждый своим блоком."""
    date_str = datetime.now(_MSK).strftime("%d.%m.%Y")

    def line(group: str) -> str:
        t = group.lower()
        ultra = re.search(r"ultra\s*(\d)", t)
        if ultra:
            return f"Apple Watch Ultra {ultra.group(1)}"
        if re.search(r"\bse\b", t):
            return "Apple Watch SE"
        # «AW 10 42», «Series 10», «S10» — всё это Series 10
        series = re.search(r"(?:series|\bs|\baw)\s*(\d{1,2})\b", t)
        if series:
            return f"Apple Watch Series {series.group(1)}"
        return "Apple Watch"

    groups: Dict[str, List[Dict]] = defaultdict(list)
    for item in items:
        groups[line(str(item.get("item_group_id", "")))].append(item)

    def sort_key(name: str) -> tuple:
        if "Ultra" in name:
            return (2, int(re.search(r"(\d+)", name).group(1)) if re.search(r"\d", name) else 0)
        if "SE" in name:
            return (0, 0)
        m = re.search(r"(\d+)", name)
        return (1, int(m.group(1)) if m else 0)

    blocks = []
    for name in sorted(groups, key=sort_key):
        rows = sorted(groups[name], key=lambda x: (x.get("title") or ""))
        lines = []
        for item in rows:
            title = item.get("title") or item.get("item_group_id", "")
            price = _fmt_price(item.get("price", "0"))
            lines.append(f"• {title} — {price} ₽")
        blocks.append(
            f"⌚ <b>{name}</b>\n<blockquote expandable>{chr(10).join(lines)}</blockquote>"
        )

    header = (f"🍏 <b>Актуальный прайс — {date_str}</b>\n"
              f"<b>{_CATEGORY_TITLE['watch']}</b>")
    return [(t, _category_keys(category)) for t in _pack_blocks(header, blocks)]


def _split_by_banner(category: str, header: str, blocks: List[tuple]) -> List[tuple]:
    """
    Группа со своей картинкой выезжает в отдельный пост.

    Правило простое и наглядное: положил assets/banners/iphoneair.png —
    iPhone Air получил собственный пост с этим баннером. Не положил —
    группа едет вместе с остальными. Так можно выделить хоть одну модель,
    хоть все, не трогая код.
    """
    out: List[tuple] = []
    pending: List[str] = []

    def flush():
        if pending:
            for chunk in _pack_blocks(header, pending):
                out.append((chunk, _category_keys(category)))
            pending.clear()

    for name, body in blocks:
        key = banners.slug(name)
        if banners.resolve([key]) and key != category:
            flush()
            for chunk in _pack_blocks(header, [body]):
                out.append((chunk, [key] + _category_keys(category)))
        else:
            pending.append(body)

    flush()
    return out


def _format_category_messages(category: str, items: List[Dict]) -> List[tuple]:
    date_str = datetime.now(_MSK).strftime("%d.%m.%Y")

    if category == "mac":
        return _format_mac_messages(items)

    if category in _SUBGROUPS:
        return _format_subgrouped(category, items)

    if category == "watch":
        return _format_watch_messages(items)

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
            display_name = _display_group(category, group_name)
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
                block_lines.append(f"• {spec} — {price} ₽")

            blocks.append((
                display_name,
                f"{group_emoji} <b>{display_name}</b>\n"
                f"<blockquote expandable>{chr(10).join(block_lines)}</blockquote>"
            ))

        header = (f"🍏 <b>Актуальный прайс — {date_str}</b>\n"
                  f"<b>{_CATEGORY_TITLE.get(category, category)}</b>")
        return _split_by_banner(category, header, blocks)

    # Подстраховка: категория без своего оформления выходит плоским списком.
    # Сейчас такого не бывает — все категории разложены по полкам выше, —
    # но пусть непредусмотренное печатается, а не теряется.
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
    return [(t, _category_keys(category)) for t in _pack_chunks(date_str, lines, sep="\n")]


# ── Темп отправки ────────────────────────────────────────────────────────────
# Telegram пускает в один чат около 20 сообщений в минуту. Публикация теперь
# шлёт их полтора десятка с баннерами, и на лимите отправка начинала падать —
# молча терялся ХВОСТ очереди, а в хвосте идут айфоны, самое ценное.
# Поэтому: пауза между сообщениями и обязательный повтор при flood control.
_SEND_DELAY = float(os.getenv("PUBLISH_SEND_DELAY", "3.5"))
_SEND_RETRIES = 3


async def _send_throttled(send):
    """
    Отправляет с паузой и повтором при ограничении частоты.

    Telegram при flood control сообщает, сколько ждать. Раньше это было
    обычным исключением: сообщение терялось, публикация шла дальше.
    Теперь ждём столько, сколько просят, и повторяем — прайс должен
    доехать целиком, даже если это займёт лишнюю минуту.
    """
    import asyncio

    for attempt in range(_SEND_RETRIES):
        try:
            result = await send()
            await asyncio.sleep(_SEND_DELAY)
            return result
        except Exception as e:
            wait = getattr(e, "retry_after", None)
            if wait is None:
                m = re.search(r"retry after (\d+)", str(e), re.IGNORECASE)
                wait = int(m.group(1)) if m else None

            if wait is None or attempt == _SEND_RETRIES - 1:
                raise

            logger.warning(
                f"price_publisher: Telegram просит подождать {wait} с "
                f"(попытка {attempt + 1} из {_SEND_RETRIES})"
            )
            await asyncio.sleep(wait + 1)

    return None


async def _send_banner(bot: Bot, found: tuple) -> int | None:
    """
    Отправляет картинку-шапку. Возвращает message_id или None.

    Файл из репозитория уходит как загрузка: так он не зависит от того,
    открыт ли репозиторий наружу, и его не видно ни в одном чате.
    file_id и ссылка отправляются как есть.
    """
    key, kind, value = found

    try:
        if kind == "file":
            from aiogram.types import FSInputFile
            photo = FSInputFile(str(value))
        else:
            photo = str(value)

        msg = await _send_throttled(
            lambda: bot.send_photo(PRICE_CHANNEL_ID, photo, disable_notification=True)
        )
        return msg.message_id if msg else None
    except Exception as e:
        # Баннер — украшение. Из-за него публикация прайса падать не должна.
        logger.warning(f"price_publisher: баннер '{key}' не отправлен: {e}")
        return None


async def _send_block(bot: Bot, text: str):
    return await _send_throttled(
        lambda: bot.send_message(
            PRICE_CHANNEL_ID,
            text,
            parse_mode="HTML",
            disable_notification=True,
        )
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
        blocks = _format_category_messages(cat, cat_items)
        # Mac отдаёт пары (текст, ключи баннера), остальные категории —
        # просто текст с ключом по имени категории.
        if blocks and not isinstance(blocks[0], tuple):
            blocks = [(t, _category_keys(cat)) for t in blocks]

        sent_banner: str | None = None
        for text, banner_keys in blocks:
            # Баннер идёт отдельным сообщением перед блоком, его message_id
            # попадает в тот же список — при следующей публикации он удалится
            # вместе с прайсом, и картинки не будут копиться в канале.
            found = banners.resolve(banner_keys)
            if found and found[0] != sent_banner:
                banner_id = await _send_banner(bot, found)
                if banner_id:
                    new_ids.append(banner_id)
                    sent_banner = found[0]

            try:
                msg = await _send_block(bot, text)
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

    # Анонсы — в самом конце, то есть внизу канала, на самом видном месте.
    # Модель, уже появившаяся в наличии, из анонсов выпадает сама.
    date_str = datetime.now(_MSK).strftime("%d.%m.%Y")
    in_stock_groups = [str(i.get("item_group_id", "")) for i in items]
    for entry in coming_soon.pending(in_stock_groups):
        found = banners.resolve([entry.get("key", "")])
        if found:
            banner_id = await _send_banner(bot, found)
            if banner_id:
                new_ids.append(banner_id)
        try:
            msg = await _send_block(bot, coming_soon.format_post(entry, date_str))
            new_ids.append(msg.message_id)
        except Exception as e:
            incidents.report(
                component=rules.TELEGRAM,
                exc=e,
                detail=f"Анонс «{entry.get('title')}» не отправлен в канал",
                key="coming_soon",
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
