# main.py

import asyncio
import logging
import os
from typing import Dict, List, Any
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties 
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from dotenv import load_dotenv
# Было: from gsheets_api import get_data_from_sheet
from services.sheets_manager import get_data_from_sheet

# --- КОНФИГУРАЦИЯ И ЗАГРУЗКА ---
load_dotenv()
API_TOKEN = os.getenv('BOT_TOKEN') 
MANAGER_ID = os.getenv('MANAGER_ID') 

if not API_TOKEN:
    logging.error("❌ BOT_TOKEN не найден в .env. Завершение работы.")
    exit(1)

# Импорты наших модулей
try:
    from keyboards import get_main_menu, get_dynamic_keyboard, get_models_keyboard
    from gsheets_api import get_data_from_sheet 
except ImportError as e:
    # Эта ошибка теперь будет ловиться только при отсутствии файлов или необходимых библиотек (gspread)
    logging.error(f"❌ Критическая ошибка импорта: {e}. Проверьте наличие gsheets_api.py, keyboards.py и установку gspread.")
    exit(1)


# --- FSM СОСТОЯНИЯ ---
class IphoneSelection(StatesGroup):
    choosing_model = State()     
    choosing_memory = State()    
    choosing_color = State()     
    choosing_sim = State()       


# --- КОНСТАНТЫ И КАТАЛОГ ---

# Порядок и названия столбцов в Google Sheets, по которым идет выбор
IPHONE_STAGES = ["Модель", "Память", "Цвет", "SIM"] 
# Вся база данных iPhone будет храниться здесь после первого запроса
IPHONE_CATALOG: List[Dict[str, Any]] = []

# --- СТАТИЧЕСКИЙ КАТАЛОГ ДЛЯ ГЛАВНОГО МЕНЮ (ИСПРАВЛЕНО) ---
# Этот словарь необходим для работы главного меню, пока не все категории переведены на Sheets.
# Используется в get_main_menu() и в обработке ошибок.
CATALOG = {
    "iphones": {"label": "📱 iPhone"},
    "macbooks": {"label": "💻 MacBook", "models": ["MacBook Air M3", "MacBook Pro M3"]}, 
    "ipads": {"label": "📟 iPad", "models": ["iPad Pro M4", "iPad Air M2"]},
    "watches": {"label": "⌚ Apple Watch", "models": ["Watch Series 9", "Watch Ultra 2"]}
}


# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logging.info("Bot configuration loaded successfully.")

# Инициализация бота и диспетчера
bot = Bot(
    token=API_TOKEN, 
    default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN)
) 
dp = Dispatcher()


# --- ФУНКЦИИ ФИЛЬТРАЦИИ ---

def filter_catalog(current_filter: Dict[str, str]) -> List[Dict[str, Any]]:
    """Фильтрует каталог по заданным параметрам."""
    return [
        item for item in IPHONE_CATALOG 
        if all(item.get(k) == v for k, v in current_filter.items())
    ]


# --- ХЕНДЛЕРЫ: ОСНОВНЫЕ КОМАНДЫ ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    """Сброс FSM и вывод главного меню с Mini App."""
    
    # Сначала очищаем состояние (FSM), чтобы сбросить прошлые выборы пользователя
    await state.clear()
    
    # Отправляем ОДНО сообщение, где есть и текст, и кнопка Mini App
    await message.answer(
        "👋 Добро пожаловать! Выберите категорию или откройте интерактивный каталог:",
        # Мы передаем ссылку на Mini App прямо в функцию создания клавиатуры
        reply_markup=get_main_menu(CATALOG, web_app_url="https://ваш-домен.ru/index.html")
    )

@dp.callback_query(F.data == "back_to_main")
async def back_to_main(callback: types.CallbackQuery, state: FSMContext):
    """Возвращает пользователя к главному меню и сбрасывает FSM."""
    await state.clear()
    await callback.message.edit_text(
        "Выберите категорию техники Apple:",
        reply_markup=get_main_menu(CATALOG)
    )
    await callback.answer()

# --- ХЕНДЛЕРЫ: ДРУГИЕ КАТЕГОРИИ (НЕ IPHONE) ---

@dp.callback_query(F.data.startswith("cat_") & ~F.data.contains("iphones"))
async def other_category_selection(callback: types.CallbackQuery):
    """Обработка выбора для MacBook, iPad, Watch (старая, статическая логика)."""
    cat_key = callback.data.split("_")[1]
    
    await callback.message.edit_text(
        f"Вы выбрали **{CATALOG[cat_key]['label']}**.\nВыберите конкретную модель:",
        reply_markup=get_models_keyboard(CATALOG, cat_key)
    )
    await callback.answer()


# --- ХЕНДЛЕРЫ: ЛОГИКА IPHONE (G-SHEETS) ---

@dp.callback_query(F.data == "cat_iphones")
async def start_iphone_selection(callback: types.CallbackQuery, state: FSMContext):
    """Начинает процесс выбора iPhone (первый этап - Модель)."""
    global IPHONE_CATALOG
    
    # 1. Загружаем данные из Sheets только при первом обращении
    if not IPHONE_CATALOG:
        await callback.answer("Загружаю каталог (это может занять несколько секунд)...", show_alert=False)
        
        logging.info("Attempting to load iPhone catalog from Google Sheets.")
        IPHONE_CATALOG = get_data_from_sheet("iPhone")
        
        if not IPHONE_CATALOG:
            # Сюда попадаем, если G-Sheets API вернул [] из-за ошибки (404, доступ, неверный ID)
            logging.error("Failed to load iPhone catalog from Sheets.")
            await callback.message.edit_text(
                "❌ Не удалось загрузить каталог iPhone. Проверьте настройки API, ID таблицы и права доступа.",
                reply_markup=get_main_menu(CATALOG)
            )
            return

    # 2. Получаем уникальные значения для первого этапа ("Модель")
    current_stage_name = IPHONE_STAGES[0] 
    unique_values = sorted(list(set(item.get(current_stage_name) for item in IPHONE_CATALOG if item.get(current_stage_name))))

    # 3. Переходим в состояние выбора модели
    await state.set_state(IphoneSelection.choosing_model)
    await state.update_data(current_filter={}) 

    # 4. Отправляем клавиатуру
    keyboard = get_dynamic_keyboard(
        data=unique_values,
        callback_prefix="val_",
        back_callback="back_to_main"
    )
    
    # Редактируем сообщение с клавиатурой
    await callback.message.edit_text(
        f"Вы выбрали **iPhone**.\nВыберите модель:",
        reply_markup=keyboard
    )


@dp.callback_query(IphoneSelection.choosing_model, F.data.startswith("val_"))
@dp.callback_query(IphoneSelection.choosing_memory, F.data.startswith("val_"))
@dp.callback_query(IphoneSelection.choosing_color, F.data.startswith("val_"))
@dp.callback_query(IphoneSelection.choosing_sim, F.data.startswith("val_"))
async def process_iphone_selection(callback: types.CallbackQuery, state: FSMContext):
    """Обрабатывает выбор на каждом этапе (Модель, Память, Цвет, SIM)."""
    await callback.answer()
    
    user_data = await state.get_data()
    current_filter = user_data.get('current_filter', {})
    
    # 1. Определяем текущий этап
    current_stage_index = len(current_filter)
    current_stage_name = IPHONE_STAGES[current_stage_index]
    
    # 2. Получаем выбранное значение (декодируем)
    selected_value_encoded = callback.data.split("val_", 1)[1]
    selected_value = selected_value_encoded.replace("_", " ").replace("-", "/") 

    # 3. Обновляем фильтр
    current_filter[current_stage_name] = selected_value
    await state.update_data(current_filter=current_filter)
    
    # 4. --- ПРОВЕРКА ЗАВЕРШЕНИЯ (ПОСЛЕДНИЙ ЭТАП - SIM) ---
    if current_stage_index == len(IPHONE_STAGES) - 1:
        
        final_items = filter_catalog(current_filter)
        
        if final_items:
            item_details = final_items[0]
            price = item_details.get("Цена", "Цена не указана")
            availability = item_details.get("Наличие", "Уточняется")
            
            # 5. Регистрация заявки
            user = callback.from_user
            manager_message = (
                "🔥 **НОВАЯ ЗАЯВКА НА IPHONE!**\n"
                f"**Параметры:** {current_filter.get('Модель')} / {current_filter.get('Память')} / {current_filter.get('Цвет')} / {current_filter.get('SIM')}\n"
                f"**Цена:** `{price}` | **Наличие:** `{availability}`\n"
                f"👤 Клиент: {user.full_name} (@{user.username or 'нет'})"
            )
            
            if MANAGER_ID:
                await bot.send_message(chat_id=MANAGER_ID, text=manager_message)

            await callback.message.edit_text(
                f"✅ Заявка принята!\nМодель: {current_filter.get('Модель')}\nЦена: **{price}**\nМенеджер скоро свяжется с вами."
            )
        else:
            await callback.message.edit_text(
                "Ошибка: Товар с такими параметрами не найден в каталоге.", 
                reply_markup=get_main_menu(CATALOG)
            )
        
        await state.clear()
        return

    # 6. --- ПРОМЕЖУТОЧНЫЙ ШАГ: ПЕРЕХОД ---
    
    next_stage_index = current_stage_index + 1
    next_stage_name = IPHONE_STAGES[next_stage_index]
    
    # 7. Фильтруем каталог и получаем уникальные значения для следующего этапа
    filtered_catalog = filter_catalog(current_filter)
    next_unique_values = sorted(list(set(item.get(next_stage_name) for item in filtered_catalog if item.get(next_stage_name))))
    
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
        back_callback="back_to_main"
    )
    
    await callback.message.edit_text(
        f"Текущий выбор: {current_filter.get('Модель')}\nВыберите **{next_stage_name}**:",
        reply_markup=keyboard
    )


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
