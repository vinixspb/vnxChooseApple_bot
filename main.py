# main.py
import asyncio
import logging
import os
from dotenv import load_dotenv

# 1. СНАЧАЛА импортируем и вызываем load_dotenv
load_dotenv()

# 2. ЗАТЕМ импортируем aiogram
from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.types import BotCommand, BotCommandScopeDefault, MenuButtonCommands

# 3. И ТОЛЬКО ТЕПЕРЬ импортируем наши роутеры (которые при импорте полезут искать ключи в os.getenv)
from handlers import catalog, assistant, magic, group, channel
from handlers.catalog import load_all


async def set_bot_commands(bot: Bot):
    commands = [
        BotCommand(command="start", description="🏠 Главное меню"),
        BotCommand(command="reset", description="🔄 Перезагрузить каталог"),
        BotCommand(command="ai",    description="🤖 Помочь с выбором (AI)"),
    ]
    await bot.set_my_commands(commands, scope=BotCommandScopeDefault())
    await bot.set_chat_menu_button(menu_button=MenuButtonCommands())


async def main():
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)
    logger.info("vnxChooseApple Bot Started (Modular Architecture)")

    bot = Bot(
        token=os.getenv("BOT_TOKEN"),
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()

    # ── Порядок роутеров КРИТИЧЕН ────────────────────────────────────────────
    # 1. group    — фильтры для группы (Chat ID проверяется первым)
    # 2. channel  — фильтры для канала
    # 3. catalog  — воронка выбора товара (inline-кнопки, FSM selecting)
    # 4. magic    — AI магия (FSM waiting_for_magic_photo)
    # 5. assistant — catch-all текст/голос (FSM consulting + свободный ввод)
    #                ↑ ВСЕГДА ПОСЛЕДНИМ — иначе перехватит группу и канал
    dp.include_router(group.router)
    dp.include_router(channel.router)
    dp.include_router(catalog.router)
    dp.include_router(magic.router)
    dp.include_router(assistant.router)   # catch-all — только последним!
    # ────────────────────────────────────────────────────────────────────────

    await set_bot_commands(bot)
    await load_all()
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
