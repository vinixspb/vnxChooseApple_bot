import logging
import os
from datetime import datetime
from zoneinfo import ZoneInfo

from aiogram import Router, types, F
from aiogram.filters import Filter

from services.price_parser import parse_price_list, looks_like_price_list, apply_markup
from services.sheets_writer import sync_price_list, write_sync_log
from services.price_publisher import publish_price
import services.data_store as store
from services.sheets_manager import get_data_from_sheet, get_settings

_MSK = ZoneInfo("Europe/Moscow")

logger = logging.getLogger(__name__)
router = Router()

OWNER_ID = os.getenv("MANAGER_ID")


def _get_supplier_ids() -> set[str]:
    """
    Читает SUPPLIER_CHANNEL_ID из .env.
    Поддерживает несколько ID через запятую:
    SUPPLIER_CHANNEL_ID=-1001378091044,-1001562517847
    """
    raw = os.getenv("SUPPLIER_CHANNEL_ID", "")
    return {s.strip() for s in raw.split(",") if s.strip()}


class IsSupplierChat(Filter):
    async def __call__(self, message: types.Message) -> bool:
        ids = _get_supplier_ids()
        if not ids:
            return False
        return str(message.chat.id) in ids


async def _process_price_message(message: types.Message) -> None:
    text = message.text or message.caption or ""
    if not text or not looks_like_price_list(text):
        return

    source = message.chat.title or str(message.chat.id)
    logger.info(f"price_watcher: прайс из '{source}'")

    raw_items = parse_price_list(text)
    if not raw_items:
        logger.warning("price_watcher: позиции не распознаны")
        return

    # Применяем наценку (телефоны: фиксированно, аксессуары: +20%)
    items = apply_markup(raw_items)

    # 1. Пишем в Google Sheets
    result = sync_price_list(items)
    updated = result["updated"]
    added   = result["added"]
    ok      = updated > 0 or added > 0

    # 2. Перезагружаем каталог в памяти
    if ok:
        store.CATALOG  = get_data_from_sheet()
        store.SETTINGS = get_settings()
        logger.info("price_watcher: каталог перезагружен")

    # 3. Сохраняем статус синхронизации
    now_msk = datetime.now(_MSK)
    store.LAST_SYNC = {
        "time":         now_msk,
        "time_str":     now_msk.strftime("%d.%m.%Y %H:%M"),
        "source":       source,
        "updated":      updated,
        "added":        added,
        "catalog_size": len(store.CATALOG),
        "ok":           ok,
    }
    write_sync_log(
        timestamp=now_msk.strftime("%d.%m.%Y %H:%M:%S"),
        source=source,
        updated=updated,
        added=added,
        catalog_size=len(store.CATALOG),
    )

    # 4. Публикуем в канал @vnxSHOPprice
    await publish_price(message.bot, items, source)

    # 5. Уведомляем владельца
    if OWNER_ID:
        preview = "\n".join(
            f"• {i['title']} — {i['price']} ₽" for i in items[:12]
        )
        if len(items) > 12:
            preview += f"\n… и ещё {len(items) - 12} позиций"

        if ok:
            status = (
                f"✅ <b>Каталог обновлён</b>\n"
                f"   Обновлено цен: {updated} | Добавлено: {added}"
            )
        else:
            status = "⚠️ Прайс получен, запись в Sheets не удалась. Проверь логи."

        await message.bot.send_message(
            OWNER_ID,
            f"📥 <b>Новый прайс от поставщика</b>\n"
            f"Источник: <i>{source}</i>\n"
            f"Позиций: <b>{len(items)}</b>\n\n"
            f"{preview}\n\n{status}",
            parse_mode="HTML",
        )


# ── Обработчик для каналов ───────────────────────────────────────────────────
@router.channel_post(IsSupplierChat())
async def on_supplier_channel_post(message: types.Message):
    await _process_price_message(message)


# ── Обработчик для групп и супергрупп ───────────────────────────────────────
@router.message(IsSupplierChat(), F.chat.type.in_({"group", "supergroup"}))
async def on_supplier_group_message(message: types.Message):
    await _process_price_message(message)
