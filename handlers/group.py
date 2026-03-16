import logging
from aiogram import Router, F, types
from aiogram.types import InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

router = Router()
logger = logging.getLogger(__name__)

GROUP_REPLY_TEXT = (
    "👋 Здравствуйте! Чтобы детально обсудить ваши пожелания и подобрать идеальную технику, "
    "предлагаю перейти в удобный формат приватного диалога.\n\n"
    "Нажмите кнопку ниже, чтобы запустить персонального AI-Genius ассистента 👇\n\n"
    "<i>P.S. Я разработан лично Андреем, поэтому вы можете быть абсолютно уверены в безопасности и конфиденциальности нашей переписки!</i> 🔒"
)

@router.message(F.chat.type.in_({"group", "supergroup"}))
async def handle_group_messages(message: types.Message):
    """
    Отвечает в группе при упоминании бота или по ключевым словам.
    """
    text = (message.text or message.caption or "").lower()
    if not text:
        return
        
    bot_user = await message.bot.me()
    mentioned = f"@{bot_user.username.lower()}" in text
    
    # Ключевые слова, на которые бот должен среагировать в общем чате
    keywords = ["цена", "наличие", "почем", "купить", "подбери", "посоветуй"]
    has_keyword = any(kw in text for kw in keywords)

    if mentioned or has_keyword:
        kb = InlineKeyboardBuilder()
        # Специальная deep-link ссылка: ?start=ai
        bot_url = f"https://t.me/{bot_user.username}?start=ai"
        kb.row(InlineKeyboardButton(text="💬 Индивидуальный подбор", url=bot_url))
        
        try:
            # Отвечаем с цитированием
            await message.reply(GROUP_REPLY_TEXT, reply_markup=kb.as_markup())
        except Exception as e:
            logger.error(f"Ошибка ответа в группе: {e}")
