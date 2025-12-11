# main.py

import asyncio
import logging
import os
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.enums import ParseMode
from dotenv import load_dotenv

# --- КОНФИГУРАЦИЯ ---
load_dotenv()
API_TOKEN = os.getenv('BOT_TOKEN') 
MANAGER_ID = os.getenv('MANAGER_ID') # Берем ID из .env

# Проверка обязательных переменных
if not API_TOKEN:
    logging.error("❌ BOT_TOKEN не найден в .env. Завершение работы.")
    exit(1)

# Импорты наших модулей
# Импортируем только CATALOG, так как MANAGER_ID берется из os.getenv()
try:
    from keyboards import get_main_menu, get_models_keyboard
    from database import CATALOG 
except ImportError as e:
    logging.error(f"❌ Критическая ошибка импорта: {e}. Проверьте наличие и синтаксис файлов database.py и keyboards.py.")
    exit(1)


# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logging.info("Bot configuration loaded successfully.")

# Инициализация бота и диспетчера
# Используем Markdown для форматирования сообщений
bot = Bot(token=API_TOKEN, parse_mode=ParseMode.MARKDOWN) 
dp = Dispatcher()


# --- ХЕНДЛЕРЫ ---

# 1. Команда /start
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    """Отправляет главное меню с категориями."""
    logging.info(f"User {message.from_user.id} executed /start.")
    await message.answer(
        "👋 Добро пожаловать! Выберите категорию техники Apple:",
        reply_markup=get_main_menu()
    )

# 2. Обработка кнопки "Назад"
@dp.callback_query(F.data == "back_to_main")
async def back_to_main(callback: types.CallbackQuery):
    """Возвращает пользователя к главному меню категорий."""
    await callback.message.edit_text(
        "Выберите категорию техники Apple:",
        reply_markup=get_main_menu()
    )
    await callback.answer()

# 3. Обработка выбора категории (callback_data начинается с cat_)
@dp.callback_query(F.data.startswith("cat_"))
async def category_selection(callback: types.CallbackQuery):
    """Показывает список моделей в выбранной категории."""
    cat_key = callback.data.split("_")[1] # Получаем ключ категории
    
    # Проверка на существование категории в каталоге
    if cat_key not in CATALOG:
        await callback.answer("Категория не найдена.", show_alert=True)
        return
        
    await callback.message.edit_text(
        f"Вы выбрали **{CATALOG[cat_key]['label']}**.\nВыберите конкретную модель:",
        reply_markup=get_models_keyboard(cat_key)
    )
    await callback.answer()

# 4. Обработка выбора конкретной модели (callback_data начинается с item_)
@dp.callback_query(F.data.startswith("item_"))
async def item_selection(callback: types.CallbackQuery):
    """Регистрирует заявку и отправляет уведомление менеджеру."""
    # Получаем полное имя модели
    model_name = callback.data.split("item_")[1] 
    
    user = callback.from_user
    user_id = user.id
    username = user.username
    full_name = user.full_name or "Не указано"
    
    logging.info(f"New application: User {user_id} selected {model_name}.")
    
    # 1. Отправляем подтверждение пользователю
    await callback.message.answer(
        f"✅ Отличный выбор: **{model_name}**!\n"
        "Ваша заявка передана менеджеру. Мы скоро свяжемся с вами."
    )
    
    # 2. Формируем сообщение для менеджера
    manager_message = (
        "🔥 **НОВАЯ ЗАЯВКА НА ТЕХНИКУ APPLE!**\n"
        "--- Детали заказа ---\n"
        f"**Модель:** `{model_name}`\n"
        "--- Клиент ---\n"
        f"👤 Имя: **{full_name}**\n"
        f"🆔 ID: `{user_id}`\n"
        f"🔗 @{username or 'Нет никнейма'}\n\n"
        f"[Написать клиенту](tg://user?id={user_id})"
    )
    
    # 3. Отправляем уведомление менеджеру (если MANAGER_ID указан)
    if MANAGER_ID:
        try:
            await bot.send_message(
                chat_id=MANAGER_ID,
                text=manager_message
            )
            logging.info(f"Application for {model_name} sent to manager.")
        except Exception as e:
            logging.error(f"Failed to send application to manager {MANAGER_ID}: {e}")
            
    # Закрываем индикатор загрузки на кнопке
    await callback.answer(f"Заявка на {model_name} принята.")


# --- ЗАПУСК БОТА ---

async def main():
    """Основная функция запуска бота."""
    logging.info("Starting bot polling...")
    # Начинаем опрос Телеграм
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        # Запускаем асинхронную функцию
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.warning("Bot stopped manually by user (Ctrl+C).")
    except Exception as e:
        logging.error(f"A critical runtime error occurred: {e}")
