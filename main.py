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
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from dotenv import load_dotenv

# --- КОНФИГУРАЦИЯ И ЗАГРУЗКА ---
load_dotenv()
API_TOKEN = os.getenv('BOT_TOKEN') 
MANAGER_ID = os.getenv('MANAGER_ID') 

if not API_TOKEN:
    logging.error("❌ BOT_TOKEN не найден в .env. Завершение работы.")
    exit(1)

try:
    from keyboards import get_main_menu, get_dynamic_keyboard
    from services.sheets_manager import get_data_from_sheet 
except ImportError as e:
    logging.error(f"❌ Критическая ошибка импорта: {e}. Проверьте структуру папок.")
    exit(1)

# --- FSM СОСТОЯНИЯ ---
class ProductSelection(StatesGroup):
    selecting = State() # Единое состояние для всей воронки

# --- КОНСТАНТЫ И ГЛОБАЛЬНАЯ БАЗА ---
# Универсальный порядок выбора для всех товаров
STAGES = ["Модель", "Память", "SIM", "Цвет"] 
GLOBAL_CATALOG: List[Dict[str, Any]] = []

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
bot = Bot(token=API_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN)) 
dp = Dispatcher()

# --- ФУНКЦИИ БАЗЫ ДАННЫХ ---
async def load_catalog_if_empty():
    """Загружает базу из vnxSHOP один раз для максимальной скорости."""
    global GLOBAL_CATALOG
    if not GLOBAL_CATALOG:
        logging.info("Скачивание актуального каталога vnxSHOP...")
        GLOBAL_CATALOG = get_data_from_sheet()

def get_filtered_catalog(current_filter: Dict[str, str]) -> List[Dict[str, Any]]:
    """Динамический фильтр по всем выбранным параметрам."""
    filtered = GLOBAL_CATALOG
    for k, v in current_filter.items():
        if k == "Категория":
            # Умный поиск по категории (Mac найдет MacBook и iMac)
            prefix = v.lower()
            filtered = [item for item in filtered if prefix in str(item.get("Модель", "")).lower()]
        else:
            filtered = [item for item in filtered if item.get(k) == v]
    return filtered


# --- ХЕНДЛЕРЫ: ОСНОВНЫЕ КОМАНДЫ ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    """Сброс FSM и вывод главного меню."""
    await state.clear()
    await message.answer(
        "👋 Добро пожаловать! Выберите категорию или откройте интерактивный каталог:",
        # Ссылку на Web App можешь подставить свою
        reply_markup=get_main_menu(web_app_url=None) 
    )

@dp.callback_query(F.data == "back_to_main")
async def back_to_main(callback: types.CallbackQuery, state: FSMContext):
    """Возвращает пользователя к главному меню."""
    await state.clear()
    await callback.message.edit_text(
        "Выберите категорию техники Apple:",
        reply_markup=get_main_menu()
    )
    await callback.answer()


# --- ХЕНДЛЕРЫ: УМНАЯ ВОРОНКА (SMART FUNNEL) ---

@dp.callback_query(F.data.startswith("cat_"))
async def start_category_selection(callback: types.CallbackQuery, state: FSMContext):
    """Шаг 1: Пользователь выбрал категорию (например, iPad)."""
    await callback.answer("Загрузка каталога...", show_alert=False)
    
    await load_catalog_if_empty()
    
    if not GLOBAL_CATALOG:
        await callback.message.edit_text(
            "❌ База данных временно недоступна или пуста. Попробуйте позже.",
            reply_markup=get_main_menu()
        )
        return

    # Извлекаем категорию из callback (например, "iPad")
    category_key = callback.data.split("cat_")[1]
    
    current_filter = {"Категория": category_key}
    await state.set_state(ProductSelection.selecting)
    
    # Запускаем рекурсивный опрос с нулевого этапа (Модель)
    await ask_next_stage(callback, state, current_filter, stage_index=0)


async def ask_next_stage(callback: types.CallbackQuery, state: FSMContext, current_filter: dict, stage_index: int):
    """Сердце бота: вычисляет следующий шаг, пропускает пустые этапы и рисует кнопки."""
    filtered = get_filtered_catalog(current_filter)

    if not filtered:
        await callback.message.edit_text(
            "❌ К сожалению, товары с такими параметрами сейчас отсутствуют.", 
            reply_markup=get_main_menu()
        )
        await state.clear()
        return

    # Если мы прошли все этапы — показываем карточку товара
    if stage_index >= len(STAGES):
        await show_final_product(callback, filtered[0], state)
        return

    stage_name = STAGES[stage_index]
    unique_values = sorted(list(set(item.get(stage_name, "-") for item in filtered)))

    # АВТО-ПРОПУСК: Если для этого этапа есть только вариант "-" (нет данных), перепрыгиваем
    if len(unique_values) == 1 and unique_values[0] == "-":
        current_filter[stage_name] = "-"
        return await ask_next_stage(callback, state, current_filter, stage_index + 1)

    # Формируем кнопки с динамическими ценами
    kb_data = []
    original_values_map = {} # Маппинг для расшифровки callback_data
    
    for val in unique_values:
        if val == "-": continue # Скрываем кнопку прочерка, если есть нормальные значения

        items_with_val = [i for i in filtered if i.get(stage_name) == val]
        # Ищем минимальную цену среди оставшихся вариантов
        prices = [int(str(i.get("Цена", "0")).replace(" ", "")) for i in items_with_val if str(i.get("Цена", "0")).replace(" ", "").isdigit()]
        min_price = min(prices) if prices else 0

        # Определяем, последний ли это реальный выбор
        is_final_choice = stage_index == len(STAGES) - 1 or all(
            len(set(i.get(s, "-") for i in items_with_val)) == 1 for s in STAGES[stage_index+1:]
        )

        if is_final_choice and min_price > 0:
            kb_data.append([val, str(min_price)])
        elif min_price > 0:
            kb_data.append([val, f"от {min_price}"])
        else:
            kb_data.append(val)

        # Сохраняем маппинг для декодирования (keyboards.py обрезает строки)
        safe_val = val.replace(" ", "_").replace("/", "-")[:60]
        original_values_map[safe_val] = val

    # Сохраняем прогресс в память
    await state.update_data(current_filter=current_filter, stage_index=stage_index, val_map=original_values_map)

    keyboard = get_dynamic_keyboard(kb_data, callback_prefix="stg_", back_callback="back_to_main")

    # Формируем красивый текст текущего выбора
    cat_name = current_filter.get("Категория", "Каталог")
    text = f"📦 **{cat_name}**\n\n"
    for i in range(stage_index):
        s_name = STAGES[i]
        s_val = current_filter.get(s_name)
        if s_val and s_val != "-":
            text += f"▪️ {s_name}: {s_val}\n"

    text += f"\n👇 Выберите параметр **{stage_name}**:"

    # Обновляем сообщение
    await callback.message.edit_text(text, reply_markup=keyboard)


@dp.callback_query(ProductSelection.selecting, F.data.startswith("stg_"))
async def process_stage_selection(callback: types.CallbackQuery, state: FSMContext):
    """Обрабатывает нажатие на параметр (память, цвет и тд)."""
    await callback.answer()
    
    user_data = await state.get_data()
    encoded_val = callback.data.replace("stg_", "")
    
    # Восстанавливаем оригинальный текст (с пробелами и слэшами)
    val_map = user_data.get("val_map", {})
    selected_value = val_map.get(encoded_val, encoded_val)
    
    stage_index = user_data.get("stage_index", 0)
    current_filter = user_data.get("current_filter", {})
    
    # Записываем выбор
    stage_name = STAGES[stage_index]
    current_filter[stage_name] = selected_value
    
    # Идем на следующий этап
    await ask_next_stage(callback, state, current_filter, stage_index + 1)


# --- ФИНАЛЬНЫЙ ЭТАП: КАРТОЧКА ТОВАРА ---

async def show_final_product(callback: types.CallbackQuery, item: dict, state: FSMContext):
    """Отрисовывает красивую карточку товара с фото и отправляет заявку менеджеру."""
    title = item.get("Полное_название", "Товар Apple")
    memory = item.get("Память", "-")
    sim = item.get("SIM", "-")
    color = item.get("Цвет", "-")
    region = item.get("Регион", "")
    availability = item.get("Наличие", "Уточняется")
    price = item.get("Цена", "Цена по запросу")
    photo_url = str(item.get("Ссылка на фото", ""))

    # Собираем красивое описание
    text = f"✅ **{title}**\n\n"
    if memory != "-": text += f"💾 Память: {memory}\n"
    if sim != "-": text += f"📡 Связь: {sim}\n"
    if color != "-": text += f"🎨 Цвет: {color}\n"
    if region and region != "-": text += f"🌍 Регион: {region}\n"
    
    text += f"\n📦 Наличие: {availability}\n"
    text += f"💰 **Цена: {price} ₽**\n\n"
    text += "Заявка сформирована. Менеджер скоро свяжется с вами для оформления!"

    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="⬅️ В главное меню", callback_data="back_to_main"))

    # Отправляем карточку с фото (если нейросеть нашла ссылку)
    if photo_url.startswith("http"):
        try:
            await callback.message.delete() # Удаляем старое текстовое меню
            await callback.message.answer_photo(
                photo=photo_url,
                caption=text,
                reply_markup=builder.as_markup()
            )
        except Exception as e:
            logging.warning(f"Не удалось отправить фото: {e}")
            await callback.message.edit_text(text, reply_markup=builder.as_markup())
    else:
        await callback.message.edit_text(text, reply_markup=builder.as_markup())

    # --- ОТПРАВКА УВЕДОМЛЕНИЯ МЕНЕДЖЕРУ ---
    user = callback.from_user
    manager_message = (
        "🔥 **НОВАЯ ЗАЯВКА ИЗ БОТА!**\n"
        f"**Товар:** {title}\n"
        f"**Параметры:** {memory} / {color} / {sim} / {region}\n"
        f"**Цена:** `{price}` | **Наличие:** `{availability}`\n"
        f"👤 Клиент: {user.full_name} (@{user.username or 'Скрыт'})"
    )
    
    if MANAGER_ID:
        try:
            await bot.send_message(chat_id=MANAGER_ID, text=manager_message)
        except Exception as e:
            logging.error(f"Не удалось отправить сообщение менеджеру: {e}")

    await state.clear()


# --- ЗАПУСК БОТА ---
async def main():
    logging.info("Бот успешно запущен и готов к приему заявок.")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.warning("Бот остановлен вручную.")
    except Exception as e:
        logging.error(f"Критическая ошибка: {e}")
