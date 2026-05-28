import logging
import os

from aiogram import Router, types, F
from aiogram.filters import Filter

from services.price_parser import parse_price_list, looks_like_price_list
from services.sheets_writer import sync_price_list
import services.data_store as store
from services.sheets_manager import get_data_from_sheet, get_settings

logger = logging.getLogger(__name__)
router = Router()

OWNER_ID = os.getenv("MANAGER_ID")


def _get_supplier_ids() -> set[str]:
    """
    Читает SUPPLIER_CHANNEL_ID из .env.
    Поддерживает одно значение или несколько через запятую:
    SUPPLIER_CHANNEL_ID=-1001111111111,-1002222222222
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

    source = f"{message.chat.title or message.chat.id}"
    logger.info(f"price_watcher: новый прайс из '{source}', парсю...")

    items = parse_price_list(text)
    if not items:
        logger.warning("price_watcher: позиции не распознаны")
        return

    result = sync_price_list(items)
    updated = result["updated"]
    added   = result["added"]
    ok      = updated > 0 or added > 0

    if OWNER_ID:
        preview = "\n".join(
            f"• {i['title']} — {i['price']} ₽" for i in items[:12]
        )
        if len(items) > 12:
            preview += f"\n… и ещё {len(items) - 12} позиций"

        if ok:
            status = (
                f"✅ <b>Каталог обновлён!</b>\n"
                f"   Обновлено цен: <b>{updated}</b>\n"
                f"   Добавлено новых: <b>{added}</b>"
            )
        else:
            status = "⚠️ Прайс получен, но запись в Sheets не удалась. Проверь логи."

        await message.bot.send_message(
            OWNER_ID,
            f"📥 <b>Новый прайс от поставщика</b>\n"
            f"Источник: <i>{source}</i>\n"
            f"Распознано позиций: <b>{len(items)}</b>\n\n"
            f"{preview}\n\n{status}",
            parse_mode="HTML",
        )

    # Перезагружаем каталог в памяти бота
    if ok:
        store.CATALOG  = get_data_from_sheet()
        store.SETTINGS = get_settings()
        logger.info("price_watcher: каталог перезагружен")


# ── Обработчик для каналов ───────────────────────────────────────────────────
@router.channel_post(IsSupplierChat())
async def on_supplier_channel_post(message: types.Message):
    await _process_price_message(message)


# ── Обработчик для групп и супергрупп ───────────────────────────────────────
@router.message(IsSupplierChat(), F.chat.type.in_({"group", "supergroup"}))
async def on_supplier_group_message(message: types.Message):
    await _process_price_message(message)
