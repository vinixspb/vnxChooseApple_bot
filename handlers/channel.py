import logging
from aiogram import Router, types
from aiogram.types import InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

router = Router()
logger = logging.getLogger(__name__)

@router.channel_post()
async def handle_channel_post(message: types.Message):
    """
    Автоматически сканирует посты в канале и добавляет релевантные кнопки.
    """
    text = (message.text or message.caption or "").lower()
    if not text:
        return

    kb = InlineKeyboardBuilder()
    added = False

    # Триггеры для AI (vnxORACLE)
    if any(kw in text for kw in ["ai", "нейросеть", "ии", "chatgpt", "oracle", "генерация"]):
        kb.row(InlineKeyboardButton(text="🔮 Нейросети и Аватары (vnxORACLE)", url="https://t.me/vnxORACLE_bot"))
        added = True
        
    # Триггеры для VPN (vnxMATRIX)
    if any(kw in text for kw in ["vpn", "безопасность", "блокировка", "трафик", "matrix"]):
        kb.row(InlineKeyboardButton(text="🛡 Безопасный VPN (vnxMATRIX)", url="https://t.me/vnxMATRIX_bot"))
        added = True
        
    # Триггеры для Каталога (vnxSHOP)
    if any(kw in text for kw in ["apple", "iphone", "mac", "скидка", "прайс", "ipad", "watch", "airpods"]):
        kb.row(InlineKeyboardButton(text="🍏 Найти в каталоге (vnxSHOP)", url="https://t.me/vnxSHOP_AppleFinder_bot"))
        added = True

    # Если хотя бы одна кнопка добавлена, обновляем пост
    if added:
        try:
            await message.edit_reply_markup(reply_markup=kb.as_markup())
        except Exception as e:
            logger.warning(f"Не удалось добавить кнопки к посту: {e}")
