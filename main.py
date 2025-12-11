import asyncio
import logging
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from dotenv import load_dotenv # <-- НОВЫЙ ИМПОРТ
import os # <-- НОВЫЙ ИМПОРТ

# Загружаем переменные окружения из файла .env
load_dotenv()
API_TOKEN = os.getenv('BOT_TOKEN') # Читаем токен

# --- Проверка токена ---
if not API_TOKEN:
    logging.error("BOT_TOKEN не найден в .env. Бот не будет запущен.")
    exit(1)
# -----------------------

# Импорты наших модулей
from keyboards import get_main_menu, get_models_keyboard
from database import CATALOG

# Включаем логирование, чтобы видеть ошибки
logging.basicConfig(level=logging.INFO)

# Инициализация бота
bot = Bot(token=API_TOKEN) # Здесь API_TOKEN уже правильный
dp = Dispatcher()
# ... остальной код бота ...
