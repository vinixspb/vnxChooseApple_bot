# main.py

import asyncio
import logging
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.enums import ParseMode

# Чтение переменных окружения
from dotenv import load_dotenv
import os 
load_dotenv()

# Импорты наших модулей
from keyboards import get_main_menu, get_models_keyboard
from database import CATALOG, MANAGER_ID

# Чтение токена и инициализация
API_TOKEN = os.getenv('BOT_TOKEN') 
if not API_TOKEN:
    logging.error("BOT_TOKEN не найден в .env. Бот не запущен.")
    exit(1)

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Инициализация бота и диспетчера
bot = Bot(token=API_TOKEN, parse_mode=ParseMode.MARKDOWN) # Используем Markdown для форматирования
dp = Dispatcher()

# 1. Команда /start
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    logging.info(f"User {message.from_user.id} started the bot.")
    await message.answer(
        "👋 Добро пожаловать! Выберите категорию техники Apple:",
        reply_markup=get_main_menu()
    )

# 2. Обработка кнопки "Назад"
@dp.callback_query(F.data == "back_to_main")
async def back_to_main(callback: types.CallbackQuery):
    await callback.message.edit_text(
        "Выберите категорию техники Apple:",
        reply_markup=get_main_menu()
    )
    await callback.answer()

# 3. Обработка выбора категории (начинается с cat_)
@dp.callback_query(F.data.startswith("cat_"))
async def category_selection(callback: types.CallbackQuery):
    cat_key = callback.data.split("_")[1] # Получаем ключ категории (например, 'iphones')
    
    await callback.message.edit_text(
        f"Вы выбрали **{CATALOG[cat_key]['label']}**.\nВыберите конкретную модель:",
        reply_markup=get_models_keyboard(cat_key)
    )
    await callback.answer()

# 4. Обработка выбора конкретной модели (начинается с item_) - ФУНКЦИЯ ЗАЯВКИ
@dp.callback_query(F.data.startswith("item_"))
async def item_selection(callback: types.CallbackQuery):
    # Убираем префикс и получаем полное имя модели
    model_name = callback.data.split("item_")[1] 
    
    user = callback.from_user
    user_id = user.id
    username = user.username
    full_name = user.full_name or "Не указано"
    
    # 1. Отправляем подтверждение пользователю
    await callback.message.answer(
        f"✅ Отличный выбор: **{model_name}**!\n"
        "Ваша заявка передана менеджеру. Мы скоро свяжемся с вами."
    )
    
    # 2. Формируем сообщение для менеджера (используем Markdown)
    manager_message = (
        "🔥 **НОВАЯ ЗАЯВКА НА ТЕХНИКУ!**\n"
        "--- Детали заказа ---\n"
        f"**Модель:** `{model_name}`\n"
        "--- Клиент ---\n"
        f"👤 Имя: **{full_name}**\n"
        f"🆔 ID: `{user_id}`\n"
        f"🔗 @{username or 'Нет никнейма'}\n\n"
        f"[Написать клиенту](tg://user?id={user_id})"
    )
    
    # 3. Отправляем уведомление менеджеру
    if MANAGER_ID:
        try:
            await bot.send_message(
                chat_id=MANAGER_ID,
                text=manager_message
            )
            logging.info(f"Application for {model_name} sent to manager {MANAGER_ID}")
        except Exception as e:
            logging.error(f"Failed to send application to manager: {e}")
            
    # Закрываем индикатор загрузки на кнопке
    await callback.answer(f"Заявка на {model_name} принята.")

async def main():
    logging.info("Starting bot polling...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.warning("Bot stopped manually.")
    except Exception as e:
        logging.error(f"Fatal error during bot runtime: {e}")
