# main.py
import asyncio
import logging
import os
from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.types import BotCommand, BotCommandScopeDefault, MenuButtonCommands
from dotenv import load_dotenv

# Импортируем наши новые модули (роутеры)
from handlers import catalog, assistant, magic
from handlers.catalog import load_all

# Загружаем переменные окружения (токены, ключи)
load_dotenv()

async def set_bot_commands(bot: Bot):
    """
    Устанавливает команды для синей кнопки Menu (слева от поля ввода текста).
    Это перезаписывает то, что было установлено через BotFather.
    """
    commands = [
        BotCommand(command="start", description="🏠 Главное меню"),
        BotCommand(command="reset", description="🔄 Перезагрузить каталог"),
        BotCommand(command="ai",    description="🤖 Помочь с выбором (AI)")
    ]
    # Применяем команды для всех пользователей по умолчанию
    await bot.set_my_commands(commands, scope=BotCommandScopeDefault())
    
    # Гарантируем, что кнопка Menu отображается как кнопка команд
    await bot.set_chat_menu_button(menu_button=MenuButtonCommands())

async def main():
    # Настраиваем базовое логирование
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)
    logger.info("vnxChooseApple Bot Started (Modular Architecture)")

    # Инициализация бота с глобальным ParseMode.HTML для защиты от спецсимволов
    bot = Bot(
        token=os.getenv('BOT_TOKEN'),
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )
    
    # Инициализация диспетчера
    dp = Dispatcher()

    # Подключаем модули (роутеры) в строгом порядке
    # ВАЖНО: Порядок имеет значение. catalog ловит специфичные коллбеки,
    # assistant ловит свободный текст, magic ловит фото в определенном состоянии.
    dp.include_router(catalog.router)
    dp.include_router(assistant.router)
    dp.include_router(magic.router)

    # Выполняем стартовую настройку
    await set_bot_commands(bot)
    
    # Первичная загрузка каталога в глобальное хранилище data_store
    await load_all()
    
    # Запускаем пулинг
    await dp.start_polling(bot)

if __name__ == "__main__":
    # Запускаем асинхронный цикл событий
    asyncio.run(main())
