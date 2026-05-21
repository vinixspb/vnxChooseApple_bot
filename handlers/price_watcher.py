import logging
import os

from aiogram import Router, types
from aiogram.filters import Filter

from services.price_parser import parse_price_list, looks_like_price_list
from services.sheets_writer import write_price_list
import services.data_store as store
from services.sheets_manager import get_data_from_sheet, get_settings

logger = logging.getLogger(__name__)
router = Router()

SUPPLIER_CHANNEL_ID = os.getenv("SUPPLIER_CHANNEL_ID")
OWNER_ID = os.getenv("MANAGER_ID")


class IsSupplierChannel(Filter):
    async def __call__(self, message: types.Message) -> bool:
        if not SUPPLIER_CHANNEL_ID:
            return False
        return str(message.chat.id) == str(SUPPLIER_CHANNEL_ID)


@router.channel_post(IsSupplierChannel())
async def on_supplier_price(message: types.Message):
    text = message.text or message.caption or ""
    if not text or not looks_like_price_list(text):
        return

    logger.info("Получен прайс от поставщика, парсю...")
    items = parse_price_list(text)

    if not items:
        logger.warning("Парсер не нашёл позиций в прайсе")
        return

    # 1. Пишем в Google Sheets
    ok = write_price_list(items)

    # 2. Перезагружаем каталог в памяти
    if ok:
        store.CATALOG = get_data_from_sheet()
        store.SETTINGS = get_settings()

    # 3. Уведомляем владельца
    if OWNER_ID:
        status = "✅ Каталог обновлён!" if ok else "⚠️ Ошибка записи в Sheets, проверь логи."
        preview = "\n".join(
            f"• {i['title']} — {i['price']} ₽" for i in items[:12]
        )
        if len(items) > 12:
            preview += f"\n… и ещё {len(items) - 12} позиций"

        await message.bot.send_message(
            OWNER_ID,
            f"📥 <b>Новый прайс от поставщика</b>\n\n"
            f"Распознано позиций: <b>{len(items)}</b>\n\n"
            f"{preview}\n\n{status}",
            parse_mode="HTML",
        )

    logger.info(f"price_watcher: обработано {len(items)} позиций, ok={ok}")
