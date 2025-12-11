import asyncio
import logging
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command

# Импорты наших модулей
from keyboards import get_main_menu, get_models_keyboard
from database import CATALOG

# ВСТАВЬТЕ СЮДА ТОКЕН (или лучше берите из env)
API_TOKEN = 'ВАШ_ТОКЕН_ОТ_BOTFATHER'

# Включаем логирование, чтобы видеть ошибки
logging.basicConfig(level=logging.INFO)

bot = Bot(token=API_TOKEN)
dp = Dispatcher()

# 1. Команда /start
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
        "Привет! Выберите категорию техники Apple:",
        reply_markup=get_main_menu()
    )

# 2. Обработка выбора категории (начинается с cat_)
@dp.callback_query(F.data.startswith("cat_"))
async def category_selection(callback: types.CallbackQuery):
    cat_key = callback.data.split("_")[1] # получаем 'iphones'
    
    await callback.message.edit_text(
        f"Вы выбрали {CATALOG[cat_key]['label']}.\nВыберите модель:",
        reply_markup=get_models_keyboard(cat_key)
    )
    await callback.answer()

# 3. Обработка кнопки "Назад"
@dp.callback_query(F.data == "back_to_main")
async def back_to_main(callback: types.CallbackQuery):
    await callback.message.edit_text(
        "Выберите категорию:",
        reply_markup=get_main_menu()
    )
    await callback.answer()

# 4. Обработка выбора конкретной модели (начинается с item_)
@dp.callback_query(F.data.startswith("item_"))
async def item_selection(callback: types.CallbackQuery):
    model_name = callback.data.split("_")[1]
    
    await callback.message.answer(
        f"✅ Отличный выбор: **{model_name}**!\n"
        "Свяжитесь с менеджером для покупки."
    )
    # Важно: answer закрывает часики загрузки на кнопке
    await callback.answer(f"Выбрано: {model_name}")

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
