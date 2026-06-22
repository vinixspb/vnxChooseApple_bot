import asyncio
import logging
import os
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

_MSK = ZoneInfo("Europe/Moscow")

logger = logging.getLogger(__name__)
router = Router()

OWNER_ID         = os.getenv("MANAGER_ID")
_SECRETARY_TOKEN = os.getenv("SECRETARY_BOT_TOKEN")

# Delay before publishing to channel (accumulates updates from multiple messages)
_PUBLISH_DELAY = int(os.getenv("PUBLISH_DELAY_MINUTES", "30")) * 60

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
    if not OWNER_ID:
        return
    if _SECRETARY_TOKEN:
        sec = Bot(token=_SECRETARY_TOKEN)
        try:
            await sec.send_message(OWNER_ID, text, parse_mode="HTML")
        finally:
            await sec.session.close()
    else:
        await bot.send_message(OWNER_ID, text, parse_mode="HTML")


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
        item = dict(row)
        item["item_group_id"] = row.get("model_group") or row.get("title", "")
        items.append(item)
    return items


async def _publish_pending(bot: Bot, manual: bool = False) -> None:
    """Publishes the full current catalog, in category order, and notifies owner."""
    if not manual and not store.CATALOG_DIRTY:
        return

    items = _catalog_items_for_publish()
    store.CATALOG_DIRTY = False

    if not items:
        if manual:
            await _notify_owner(bot, "ℹ️ Каталог пуст — нечего публиковать.")
        return

    ok = await publish_price(bot, items)
    if ok:
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
        return

    items = apply_markup(raw_items)

    # 1. Write to Google Sheets immediately
    result  = sync_price_list(items)
    updated = result["updated"]
    added   = result["added"]
    ok      = updated > 0 or added > 0

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

    # 5. Debounce: cancel existing timer, restart 30-min countdown
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
