import logging
import re
from aiogram import Router, types
from aiogram.types import InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

router = Router()
logger = logging.getLogger(__name__)

@router.channel_post()
async def handle_channel_post(message: types.Message):
    """
    Автоматически сканирует посты в канале и добавляет релевантные кнопки.
    Использует регулярные выражения (re) для точного поиска слов и корней.
    """
    text = (message.text or message.caption or "").lower()
    if not text:
        return

    kb = InlineKeyboardBuilder()
    added = False

    # 1. Триггеры для AI (vnxORACLE) 
    if re.search(r'\b(ai|ии|chatgpt|oracle)\b|нейросет|генераци', text):
        kb.row(InlineKeyboardButton(text="🔮 ChatGPT и AI без VPN (vnxORACLE)", url="https://t.me/vnxORACLE_bot"))
        added = True
        
    # 2. Триггеры для VPN (vnxMATRIX) - ИСПРАВЛЕННАЯ ССЫЛКА
    if re.search(r'\b(vpn|ркн)\b|безопасност|блокир|трафик|matrix|роскомнадзор|замедл|огранич', text):
        kb.row(InlineKeyboardButton(text="🛡 Безопасный VPN (vnxMATRIX)", url="https://t.me/vnxMATRIX_Gateway_bot"))
        added = True
        
    # 3. Триггеры для Каталога (vnxSHOP)
    if re.search(r'\b(mac)\b|apple|iphone|скидк|прайс|ipad|watch|airpods', text):
        kb.row(InlineKeyboardButton(text="🍏 Найти в каталоге (vnxSHOP)", url="https://t.me/vnxSHOP_AppleFinder_bot"))
        added = True

    # Если хотя бы одна кнопка добавлена, обновляем пост
    if added:
        try:
            await message.edit_reply_markup(reply_markup=kb.as_markup())
        except Exception as e:
            logger.warning(f"Не удалось добавить кнопки к посту: {e}")
