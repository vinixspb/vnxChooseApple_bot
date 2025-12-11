# main.py

import asyncio
import logging
import os
from typing import Dict, List, Any
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties 
from aiogram.fsm.context import FSMContext # <<< ИМПОРТ ДЛЯ FSM
from aiogram.fsm.state import State, StatesGroup # <<< ИМПОРТ ДЛЯ FSM
from dotenv import load_dotenv

# --- КОНФИГУРАЦИЯ И ЗАГРУЗКА ---
load_dotenv()
API_TOKEN = os.getenv('BOT_TOKEN') 
MANAGER_ID = os.getenv('MANAGER_ID') 

if not API_TOKEN:
    logging.error("❌ BOT_TOKEN не найден в .env. Завершение работы.")
    exit(1)

# Импорты наших модулей
try:
    from keyboards import get_main_menu, get_dynamic_keyboard
    from gsheets_api import get_data_from_sheet # <<< НОВЫЙ ИМПОРТ
except ImportError as e:
    logging.error(f"❌ Критическая ошибка импорта: {e}. Проверьте наличие файлов.")
    exit(1)


# --- FSM СОСТОЯНИЯ ---
# Определяем этапы, которые проходит пользователь при выборе iPhone
class IphoneSelection(StatesGroup):
    choosing_model = State()     # Выбор модели (15 Pro Max, 14 и т.д.)
    choosing_memory = State()    # Выбор памяти (256 GB, 512 GB)
    choosing_color = State()     # Выбор цвета (Black Titanium и т.д.)
    choosing_sim = State()       # Выбор SIM (eSIM, SIM+eSIM)


# --- КОНСТАНТЫ ---
# Порядок и названия столбцов в Google Sheets, по которым идет выбор
IPHONE_STAGES = ["Модель", "Память", "Цвет", "SIM"] 
# Вся база данных iPhone будет храниться здесь после первого запроса
IPHONE_CATALOG: List[Dict[str, Any]] = []


# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logging.info("Bot configuration loaded successfully.")

# Инициализация бота и диспетчера
bot = Bot(
    token=API_TOKEN, 
    default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN)
) 
dp = Dispatcher()


# --- ХЕНДЛЕРЫ: ОСНОВНЫЕ КОМАНДЫ ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    """Сброс FSM и вывод главного меню."""
    await state.clear()
    await message.answer(
        "👋 Добро пожаловать! Выберите категорию техники Apple:",
        reply_markup=get_main_menu()
    )

@dp.callback_query(F.data == "back_to_main")
async def back_to_main(callback: types.CallbackQuery, state: FSMContext):
    """Возвращает пользователя к главному меню и сбрасывает FSM."""
    await state.clear()
    await callback.message.edit_text(
        "Выберите категорию техники Apple:",
        reply_markup=get_main_menu()
    )
    await callback.answer()


# --- ХЕНДЛЕРЫ: ЛОГИКА IPHONE ---

@dp.callback_query(F.data == "cat_iphones")
async def start_iphone_selection(callback: types.CallbackQuery, state: FSMContext):
    """Начинает процесс выбора iPhone (первый этап)."""
    global IPHONE_CATALOG
    
    # Загружаем данные из Sheets только при первом обращении
    if not IPHONE_CATALOG:
        IPHONE_CATALOG = get_data_from_sheet("iPhone")
        if not IPHONE_CATALOG:
            await callback.answer("Ошибка загрузки каталога iPhone. Проверьте Google Sheets API.", show_alert=True)
            return

    # 1. Получаем уникальные значения для первого этапа ("Модель")
    current_stage_name = IPHONE_STAGES[0] # "Модель"
    unique_values = sorted(list(set(item[current_stage_name] for item in IPHONE_CATALOG if current_stage_name in item)))

    # 2. Переходим в состояние выбора модели
    await state.set_state(IphoneSelection.choosing_model)
    await state.update_data(current_filter={}) # Инициализируем пустой словарь фильтров

    # 3. Отправляем клавиатуру
    keyboard = get_dynamic_keyboard(
        data=unique_values,
        callback_prefix="val_",
        back_callback="back_to_main"
    )
    
    await callback.message.edit_text(
        f"Вы выбрали **iPhone**.\nВыберите модель:",
        reply_markup=keyboard
    )
    await callback.answer()


@dp.callback_query(IphoneSelection.choosing_model, F.data.startswith("val_"))
@dp.callback_query(IphoneSelection.choosing_memory, F.data.startswith("val_"))
@dp.callback_query(IphoneSelection.choosing_color, F.data.startswith("val_"))
@dp.callback_query(IphoneSelection.choosing_sim, F.data.startswith("val_"))
async def process_iphone_selection(callback: types.CallbackQuery, state: FSMContext):
    """Обрабатывает выбор на каждом этапе (Модель, Память, Цвет, SIM)."""
    user_data = await state.get_data()
    current_filter = user_data.get('current_filter', {})
    
    # 1. Определяем текущий и следующий этап
    current_stage_index = len(current_filter)
    current_stage_name = IPHONE_STAGES[current_stage_index]
    
    # 2. Получаем выбранное значение (декодируем)
    selected_value_encoded = callback.data.split("_", 1)[1]
    selected_value = selected_value_encoded.replace("_", " ").replace("-", "/") # Декодируем

    # 3. Обновляем фильтр
    current_filter[current_stage_name] = selected_value
    await state.update_data(current_filter=current_filter)
    
    # 4. Проверяем, был ли это последний этап (SIM)
    if current_stage_index == len(IPHONE_STAGES) - 1:
        # --- ФИНАЛЬНЫЙ ШАГ: РЕГИСТРАЦИЯ ЗАЯВКИ ---
        
        # Находим конечный товар
        final_item = [item for item in IPHONE_CATALOG if all(item[k] == v for k, v in current_filter.items())]
        
        if final_item:
            item_details = final_item[0]
            price = item_details.get("Цена", "Цена не указана")
            availability = item_details.get("Наличие", "Уточняется")
            
            # 5. Регистрируем заявку (та же логика, что и раньше)
            user = callback.from_user
            manager_message = (
                "🔥 **НОВАЯ ЗАЯВКА НА IPHONE!**\n"
                f"**Товар:** {current_filter.get('Модель')} | {current_filter.get('Память')} | {current_filter.get('Цвет')} | {current_filter.get('SIM')}\n"
                f"**Цена:** `{price}` | **Наличие:** `{availability}`\n"
                f"👤 Клиент: {user.full_name} (@{user.username or 'нет'})"
            )
            
            if MANAGER_ID:
                await bot.send_message(chat_id=MANAGER_ID, text=manager_message)

            await callback.message.edit_text(
                f"✅ Заявка принята!\nМодель: {current_filter.get('Модель')}\nЦена: **{price}**\nМенеджер скоро свяжется с вами."
            )
            await state.clear()
        else:
            await callback.message.edit_text("Ошибка: Товар с такими параметрами не найден.", reply_markup=get_main_menu())
            await state.clear()
        
        await callback.answer()
        return

    # 5. --- ПРОМЕЖУТОЧНЫЙ ШАГ: ПЕРЕХОД К СЛЕДУЮЩЕМУ ЭТАПУ ---
    
    next_stage_index = current_stage_index + 1
    next_stage_name = IPHONE_STAGES[next_stage_index]
    
    # 6. Фильтруем каталог по текущему выбору
    filtered_catalog = [item for item in IPHONE_CATALOG if all(item[k] == v for k, v in current_filter.items())]
    
    # 7. Получаем уникальные значения для следующего этапа
    next_unique_values = sorted(list(set(item[next_stage_name] for item in filtered_catalog if next_stage_name in item)))
    
    # 8. Переходим в следующее состояние FSM
    if next_stage_name == "Память":
        await state.set_state(IphoneSelection.choosing_memory)
    elif next_stage_name == "Цвет":
        await state.set_state(IphoneSelection.choosing_color)
    elif next_stage_name == "SIM":
        await state.set_state(IphoneSelection.choosing_sim)
    
    # 9. Отправляем клавиатуру следующего этапа
    keyboard = get_dynamic_keyboard(
        data=next_unique_values,
        callback_prefix="val_",
        back_callback="back_to_main" # Можно реализовать "Назад к предыдущему шагу", но это сложнее
    )
    
    await callback.message.edit_text(
        f"Выберите **{next_stage_name}**:",
        reply_markup=keyboard
    )
    await callback.answer()


# --- ЗАПУСК БОТА ---

async def main():
    logging.info("Starting bot polling...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.warning("Bot stopped manually by user (Ctrl+C).")
    except Exception as e:
        logging.error(f"A critical runtime error occurred: {e}")
