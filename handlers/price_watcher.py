import asyncio
import logging
import os
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from aiogram import Router, types, F, Bot
from aiogram.filters import Filter

from services.price_parser import parse_price_list, looks_like_price_list, apply_markup
from services.sheets_writer import sync_price_list, write_sync_log
from services.price_publisher import publish_price
import services.data_store as store
from services.sheets_manager import get_data_from_sheet, get_settings
from services import incidents
from services import incident_rules as rules

_MSK = ZoneInfo("Europe/Moscow")

logger = logging.getLogger(__name__)
router = Router()

OWNER_ID         = os.getenv("MANAGER_ID")
_SECRETARY_TOKEN = os.getenv("SECRETARY_BOT_TOKEN")

# Delay before publishing to channel (accumulates updates from multiple messages)
_PUBLISH_DELAY = int(os.getenv("PUBLISH_DELAY_MINUTES", "50")) * 60

# Flag file: vnxSECRETARY creates it on "Ручная публикация прайса" → publish now
_MANUAL_PUBLISH_FLAG = Path(os.getenv(
    "MANUAL_PUBLISH_FLAG",
    str(Path(__file__).resolve().parent.parent / "data" / "publish_now.flag"),
))
_MANUAL_PUBLISH_POLL = 5  # seconds


def _get_supplier_ids() -> set[str]:
    raw = os.getenv("SUPPLIER_CHANNEL_ID", "")
    return {s.strip() for s in raw.split(",") if s.strip()}


class IsSupplierChat(Filter):
    async def __call__(self, message: types.Message) -> bool:
        ids = _get_supplier_ids()
        return bool(ids) and str(message.chat.id) in ids


async def _notify_owner(bot: Bot, text: str) -> None:
    """
    Служебное уведомление владельцу — всегда беззвучно.

    Поставщики присылают прайсы пачками, и на каждое сообщение приходило
    своё уведомление со звуком. Это рабочая телеметрия, а не событие,
    ради которого стоит доставать телефон: она должна лежать в чате
    и ждать, когда на неё посмотрят.
    """
    if not OWNER_ID:
        return
    if _SECRETARY_TOKEN:
        sec = Bot(token=_SECRETARY_TOKEN)
        try:
            await sec.send_message(OWNER_ID, text, parse_mode="HTML",
                                   disable_notification=True)
        finally:
            await sec.session.close()
    else:
        await bot.send_message(OWNER_ID, text, parse_mode="HTML",
                               disable_notification=True)


_APPLE_PREFIX_RE = re.compile(r"^Apple\s+", re.IGNORECASE)

# ── Publish-time filter: remove Samsung/Android phones and non-tech items ─────
_NON_APPLE_PUB_RE = re.compile(
    r"^(Samsung\b|Galaxy\b|"
    r"S\d{1,2}\s|S\d{1,2}$|"        # S24, S25 Ultra etc.
    r"A\d{2}\b|M\d{2}\b|"            # A56, A57, M55, M56
    r"Z\s+(?:Flip|Fold)|"            # Z Flip6, Z Fold6
    r"Sony\b|Xiaomi\b|Mi\s+\d|POCO\b|"
    r"Honor\b|Huawei\b|OnePlus\b|Oppo\b|Vivo\b|Realme\b|"
    r"Garmin\b|Fitbit\b"
    r")", re.IGNORECASE
)
# Список синхронизирован с _NON_TECH_RE в run_sheets_cleanup.py:
# что не попадает в канал, не должно попадать и в фид Meta.
_NON_TECH_PUB_RE = re.compile(r"T-Shirt|Футболк|Одежд|Толстовк|Худи\b", re.IGNORECASE)

# Бренды в любом месте строки: "Беспроводной микрофон DJI Mic 2" и т.п.
_BRAND_ANYWHERE_PUB_RE = re.compile(
    r"\b(Samsung|Galaxy|DJI|Sony|Xiaomi|POCO|Honor|Huawei|OnePlus|"
    r"Oppo|Vivo|Realme|Garmin|Fitbit|Nothing\s+Phone|Tecno|Infinix|"
    r"Insta360|GoPro|Anker|Baseus|Ugreen|JBL|Marshall|Bose|Sennheiser|Pitaka|Spigen|Nillkin|Belkin|"
    # Honor Magic 8 Pro. Цифра сразу после "Magic" обязательна — у Apple
    # есть Magic Keyboard и Magic Mouse, их отсекать нельзя.
    r"Magic\s+\d)\b",
    re.IGNORECASE,
)

# ── Чужой прайс целиком ──────────────────────────────────────────────────────
# Многобрендовые поставщики («BORODA SAMSUNG / MULTI-BRAND») присылают в ту же
# группу прайсы на LEGO, дроны, приставки. looks_like_price_list() смотрит
# только на форму строк — «название — число», — поэтому такое сообщение
# проходит фильтр, парсер законно возвращает ноль Apple-позиций, и рождается
# инцидент PARSE_EMPTY. При каждом прайсе от такого поставщика.
#
# Инцидент должен значить «прайс Apple пришёл, а мы его не поняли». Поэтому
# перед тревогой проверяем, был ли в сообщении наш товар вообще.
#
# Признак именно отрицательный — по чужим брендам, а не по слову «Apple».
# Поставщики пишут Apple сокращённо и без названия бренда («Duo 256 Star
# White eSim+eSim»), так что отсутствие слова «iPhone» ещё ни о чём не
# говорит, а вот слово «LEGO» говорит вполне.
_FOREIGN_GOODS_RE = re.compile(
    r"\b(LEGO|Лего|Dyson|Playstation|PS[45]\b|Xbox|Nintendo|Kindle|"
    r"Meta\s+Quest|Quest\s*[23]\b|Электросамокат|Самокат|Пылесос)\b",
    re.IGNORECASE,
)

# Строка с ценой — та же форма, по которой прайс опознаёт price_parser.
_PRICE_LINE_RE = re.compile(r"-\s*\d{3,}\s*$")

# Упоминание Apple где угодно в сообщении. Нужно только как страховка:
# если оно есть, молчать нельзя даже при полном разборе в ноль.
_APPLE_MENTION_RE = re.compile(
    r"\b(apple|iphone|ipad|ipod|imac|macbook|airpods?|airtag|homepod|"
    r"magsafe|mac\s*(?:mini|studio|pro|book)|watch\s*(?:ultra|se|series))\b",
    re.IGNORECASE,
)

_FOREIGN_SHARE = 0.6


def _is_foreign_price_list(text: str) -> bool:
    """Прайс не про наш товар: чужие бренды в строках и ни слова об Apple."""
    if _APPLE_MENTION_RE.search(text):
        return False

    lines = [ln for ln in text.splitlines() if _PRICE_LINE_RE.search(ln)]
    if not lines:
        return False

    foreign = sum(
        1 for ln in lines
        if _FOREIGN_GOODS_RE.search(ln)
        or _BRAND_ANYWHERE_PUB_RE.search(ln)
        or _NON_APPLE_PUB_RE.match(ln.strip())
        or _NON_TECH_PUB_RE.search(ln)
    )
    return foreign >= _FOREIGN_SHARE * len(lines)

# Запись ОЗУ через дробь: "8/ 256GB", "16/ 1TB". Так поставщики оформляют
# Honor и Xiaomi, замаскированные под Apple. Сама Apple объём ОЗУ
# в названии товара не указывает никогда.
_RAM_STORAGE_PUB_RE = re.compile(r"\b\d{1,2}\s*/\s*\d{2,4}\s*(?:GB|TB)\b", re.IGNORECASE)
_TRAILING_RAM_PUB_RE = re.compile(r"\b\d{1,2}\s*/\s*$")

# У Mac запись "16/256" означает ОЗУ/SSD и абсолютно законна.
# Без этой оговорки правило дроби вычистит из канала все макбуки.
_MAC_PUB_RE = re.compile(r"\b(macbook|imac|mac\s*mini|mac\s*studio|mac\s*pro|mac\s+m\d)\b",
                         re.IGNORECASE)


# Обломок разбора: в названии модели остался только тип SIM или связи.
# В канале это выглядело как отдельный товар «📱 eSim — 28 700 ₽»,
# без памяти и цвета. Такую строку показывать покупателю нельзя:
# что это за товар, не понимает никто, включая нас.
#
# Прежний список перечислял сочетания вручную и не знал «eSim+eSim»,
# которое появилось вместе с iPhone Duo. Теперь любое слово о связи,
# в любой комбинации через плюс, — обломок.
_SIM_WORD = r"(?:e-?sim|nano|wi-?fi|lte|dual\s*sim|sim)"
_JUNK_GROUP_RE = re.compile(
    rf"^\s*(?:{_SIM_WORD}(?:\s*\+\s*{_SIM_WORD})*|-)\s*$",
    re.IGNORECASE,
)


def _is_apple_product(item: dict) -> bool:
    """
    Returns False for Samsung/Android phones mislabeled as Apple,
    and for non-tech items (T-shirts etc.) that leak in from suppliers.
    """
    group = str(item.get("item_group_id", "")).strip()
    if _JUNK_GROUP_RE.match(group):
        return False

    for field in ("item_group_id", "title"):
        val = str(item.get(field, "")).strip()
        if not val:
            continue
        if _NON_TECH_PUB_RE.search(val):
            return False
        if _BRAND_ANYWHERE_PUB_RE.search(val):
            return False
        if not _MAC_PUB_RE.search(val):
            if _RAM_STORAGE_PUB_RE.search(val) or _TRAILING_RAM_PUB_RE.search(val):
                return False
        if _NON_APPLE_PUB_RE.match(val):
            return False
        # Catch "Apple S24 8/", "Apple Z Flip7" etc. after stripping prefix
        stripped = _APPLE_PREFIX_RE.sub("", val).strip()
        if stripped != val and _NON_APPLE_PUB_RE.match(stripped):
            return False
    return True


def _normalize_group(name: str) -> str:
    """Strip redundant 'Apple ' prefix so 'Apple iPhone 15' == 'iPhone 15'."""
    return _APPLE_PREFIX_RE.sub("", name).strip()


def _infer_sim_from_id(item_id: str) -> str:
    """
    Extract SIM type from the deterministic ID for old Sheets rows where
    the sim field was never populated.
    ID format: APPLEIPHONE15PRO-256GB-NANOESIM-NATURALTILANIUM
    """
    uid = str(item_id).upper().replace("+", "").replace(" ", "")
    if "ESIMESIM" in uid:
        return "eSIM + eSIM"   # iPhone Duo — проверяем до голого ESIM
    if "NANOESIM" in uid:
        return "Nano + eSIM"
    if "NANONANO" in uid:
        return "Nano + Nano"
    if "ESIM" in uid:
        return "eSIM"
    if "WIFI" in uid:
        return "WiFi"
    if "LTE" in uid:
        return "LTE"
    return "-"


_ID_MEMORY_RE = re.compile(r"^\d{1,4}(GB|TB)$", re.IGNORECASE)


def _infer_memory_from_id(item_id: str) -> str:
    """
    Достаёт объём памяти из детерминированного ID.

    ID собирается как APPLEIPHONE18PRO-256GB-ESIM-BLACK, то есть объём
    в нём есть всегда. Для части строк Sheets возвращает пустое поле
    memory — и тогда в канале выходило три одинаковых «Black | eSIM»
    по разным ценам: это 256, 512 и 1 ТБ, но отличить их невозможно,
    да и сортировка по памяти работать не может.
    """
    for part in str(item_id).split("-"):
        if _ID_MEMORY_RE.match(part.strip()):
            return part.strip().upper()
    return "-"


def _catalog_items_for_publish() -> list[dict]:
    """
    Full current in-stock catalog, mapped for publish_price().
    Publishing always reflects the live catalog (not just today's delta) —
    otherwise categories untouched by the latest supplier message would
    vanish from the channel once old messages get deleted.
    """
    items = []
    for row in store.CATALOG:
        if str(row.get("availability", "")).strip().lower() != "in stock":
            continue
        if not _is_apple_product(row):
            continue
        item = dict(row)
        raw_group = row.get("model_group") or row.get("title", "")
        item["item_group_id"] = _normalize_group(raw_group)

        # Проверку на обломок разбора делаем здесь, а не в _is_apple_product:
        # та смотрит на колонку листа, а в канал уходит имя из model_group.
        # Из-за этого «eSim» проходил фильтр и вылезал в прайсе отдельным
        # блоком «iPhone eSim» — товаром, которого не существует.
        if _JUNK_GROUP_RE.match(item["item_group_id"]):
            continue

        # Backfill SIM from ID for old rows with empty sim field
        sim = str(item.get("sim", "")).strip()
        if not sim or sim == "-":
            item["sim"] = _infer_sim_from_id(item.get("id", ""))

        # То же для памяти: без неё строки неразличимы и не сортируются
        mem = str(item.get("memory", "")).strip()
        if not mem or mem == "-":
            item["memory"] = _infer_memory_from_id(item.get("id", ""))

        items.append(item)
    return items


async def _publish_pending(bot: Bot, manual: bool = False) -> None:
    """Publishes the full current catalog, in category order, and notifies owner."""
    if not manual and not store.CATALOG_DIRTY:
        return

    items = _catalog_items_for_publish()
    store.CATALOG_DIRTY = False

    if not items:
        # Каталог не пуст, а публиковать нечего — значит фильтр съел всё
        if store.CATALOG:
            incidents.report(
                component=rules.PUBLISHER,
                code="PUBLISH_NOTHING_TO_SHOW",
                detail=f"В каталоге {len(store.CATALOG)} строк, "
                       f"после фильтров осталось 0",
            )
        if manual:
            await _notify_owner(bot, "ℹ️ Каталог пуст — нечего публиковать.")
        return

    incidents.resolve(rules.PUBLISHER, "PUBLISH_NOTHING_TO_SHOW")

    ok = await publish_price(bot, items)
    if not ok:
        incidents.report(
            component=rules.PUBLISHER,
            code="PUBLISH_FAILED",
            detail=f"Ни одно сообщение не ушло в канал ({len(items)} позиций)",
            context={"канал": os.getenv("PRICE_CHANNEL_ID", "не задан")},
        )
    if ok:
        incidents.resolve(rules.PUBLISHER, "PUBLISH_FAILED")
        cats = set()
        for i in items:
            g = (i.get("item_group_id","") + " " + i.get("title","")).lower()
            if "iphone" in g:       cats.add("📱 iPhone")
            elif "ipad" in g:       cats.add("🖥 iPad")
            elif "macbook" in g or "mac " in g: cats.add("💻 Mac")
            elif "airpods" in g:    cats.add("🎧 AirPods")
            elif "watch" in g:      cats.add("⌚ Watch")
            else:                   cats.add("📦 Аксессуары")

        prefix = "📢 <b>Прайс опубликован в канал (вручную)</b>\n" if manual else "📢 <b>Прайс опубликован в канал</b>\n"
        await _notify_owner(
            bot,
            f"{prefix}"
            f"{' | '.join(sorted(cats))}\n"
            f"Позиций: {len(items)}",
        )


async def _cancel_publish_task() -> None:
    if store.PUBLISH_TASK and not store.PUBLISH_TASK.done():
        store.PUBLISH_TASK.cancel()
        await asyncio.gather(store.PUBLISH_TASK, return_exceptions=True)
    store.PUBLISH_TASK = None


async def _delayed_publish(bot: Bot) -> None:
    """Waits _PUBLISH_DELAY seconds, then publishes all pending items in category order."""
    try:
        await asyncio.sleep(_PUBLISH_DELAY)
    except asyncio.CancelledError:
        return

    store.PUBLISH_TASK = None
    await _publish_pending(bot)


async def watch_manual_publish(bot: Bot) -> None:
    """
    Polls for a flag file created by vnxSECRETARY's "Ручная публикация прайса"
    button. On detection, cancels the debounce timer and publishes immediately.
    """
    while True:
        try:
            if _MANUAL_PUBLISH_FLAG.exists():
                _MANUAL_PUBLISH_FLAG.unlink(missing_ok=True)
                logger.info("price_watcher: ручная публикация по команде vnxSECRETARY")
                await _cancel_publish_task()
                await _publish_pending(bot, manual=True)
        except Exception as e:
            logger.error(f"watch_manual_publish: {e}")
        await asyncio.sleep(_MANUAL_PUBLISH_POLL)


async def _process_price_message(message: types.Message) -> None:
    text = message.text or message.caption or ""
    if not text or not looks_like_price_list(text):
        return

    source = message.chat.title or str(message.chat.id)
    logger.info(f"price_watcher: прайс из '{source}'")

    raw_items = parse_price_list(text)
    if not raw_items:
        # Чужой товар — это не сбой. Гасим инцидент, если он остался
        # с прошлых таких же сообщений, и молчим.
        if _is_foreign_price_list(text):
            logger.info(f"price_watcher: прайс из '{source}' не про Apple — пропуск")
            incidents.resolve(rules.PARSER, "PARSE_EMPTY", key=source)
            return

        # Сообщение прошло фильтр looks_like_price_list, но парсер ничего не понял.
        # Почти всегда это смена формата у поставщика — молча терять такое нельзя.
        incidents.report(
            component=rules.PARSER,
            code="PARSE_EMPTY",
            detail=f"Прайс от '{source}' не разобран: 0 позиций",
            key=source,
            context={"длина сообщения": len(text),
                     "начало": text[:120].replace("\n", " ")},
        )
        return

    incidents.resolve(rules.PARSER, "PARSE_EMPTY", key=source)

    items = apply_markup(raw_items)

    # 1. Write to Google Sheets immediately
    result  = sync_price_list(items)
    updated = result["updated"]
    added   = result["added"]
    ok      = updated > 0 or added > 0

    # Тихий отказ: позиции разобраны, но в таблицу не легло ничего.
    # Ошибки при этом может не быть вовсе — именно так выглядела
    # потеря прав Редактора, прожившая незамеченной несколько недель.
    if not ok:
        incidents.report(
            component=rules.SHEETS,
            code="SYNC_WROTE_NOTHING",
            detail=f"Прайс от '{source}': разобрано {len(items)} позиций, "
                   f"записано 0",
            context={"источник": source, "позиций": len(items)},
        )

    # 2. Reload catalog in memory
    if ok:
        store.CATALOG  = get_data_from_sheet()
        store.SETTINGS = get_settings()

    # 3. Save sync status
    now = datetime.now(_MSK)
    store.LAST_SYNC = {
        "time":         now,
        "time_str":     now.strftime("%d.%m.%Y %H:%M"),
        "source":       source,
        "updated":      updated,
        "added":        added,
        "catalog_size": len(store.CATALOG),
        "ok":           ok,
    }
    write_sync_log(
        timestamp=now.strftime("%d.%m.%Y %H:%M:%S"),
        source=source,
        updated=updated,
        added=added,
        catalog_size=len(store.CATALOG),
    )

    # 4. Mark catalog dirty — full live catalog gets republished after debounce
    store.CATALOG_DIRTY = True

    # 5. Debounce: cancel existing timer, restart 50-min countdown
    await _cancel_publish_task()
    store.PUBLISH_TASK = asyncio.create_task(_delayed_publish(message.bot))

    # 6. Brief notification to owner
    delay_min = _PUBLISH_DELAY // 60
    status = (
        f"✅ Обновлено: {updated} | Добавлено: {added}"
        if ok else "⚠️ Sheets недоступен, проверь логи"
    )
    await _notify_owner(
        message.bot,
        f"📊 <b>Прайс от {source}</b>\n"
        f"{status}\n"
        f"📢 Публикация в канал через {delay_min} мин",
    )


# ── Каналы: новые посты ──────────────────────────────────────────────────────
@router.channel_post(IsSupplierChat())
async def on_supplier_channel_post(message: types.Message):
    await _process_price_message(message)


# ── Каналы: РЕДАКТИРОВАНИЕ ───────────────────────────────────────────────────
@router.edited_channel_post(IsSupplierChat())
async def on_supplier_channel_post_edited(message: types.Message):
    await _process_price_message(message)


# ── Группы: новые сообщения ──────────────────────────────────────────────────
@router.message(IsSupplierChat(), F.chat.type.in_({"group", "supergroup"}))
async def on_supplier_group_message(message: types.Message):
    await _process_price_message(message)


# ── Группы: РЕДАКТИРОВАНИЕ ───────────────────────────────────────────────────
@router.edited_message(IsSupplierChat(), F.chat.type.in_({"group", "supergroup"}))
async def on_supplier_group_message_edited(message: types.Message):
    await _process_price_message(message)
