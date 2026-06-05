import asyncio
import logging
import os
from datetime import datetime
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


async def _delayed_publish(bot: Bot) -> None:
    """Waits _PUBLISH_DELAY seconds, then publishes all pending items in category order."""
    try:
        await asyncio.sleep(_PUBLISH_DELAY)
    except asyncio.CancelledError:
        return

    items = list(store.PENDING_PUBLISH)
    store.PENDING_PUBLISH.clear()
    store.PUBLISH_TASK = None

    if not items:
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

        await _notify_owner(
            bot,
            f"📢 <b>Прайс опубликован в канал</b>\n"
            f"{' | '.join(sorted(cats))}\n"
            f"Позиций: {len(items)}",
        )


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

    # 4. Accumulate items for delayed publish (deduplicate by id, keep latest price)
    existing = {i["id"]: i for i in store.PENDING_PUBLISH}
    for item in items:
        existing[item["id"]] = item
    store.PENDING_PUBLISH = list(existing.values())

    # 5. Debounce: cancel existing timer, restart 30-min countdown
    if store.PUBLISH_TASK and not store.PUBLISH_TASK.done():
        store.PUBLISH_TASK.cancel()
        await asyncio.gather(store.PUBLISH_TASK, return_exceptions=True)
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
