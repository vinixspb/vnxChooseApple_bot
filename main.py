# main.py

import asyncio
import logging
import os
import io
from typing import Dict, List, Any
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.enums import ParseMode, ChatAction
from aiogram.client.default import DefaultBotProperties 
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, InputMediaPhoto, BufferedInputFile
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
    from services.sheets_manager import get_data_from_sheet, get_settings 
except ImportError as e:
    logging.error(f"❌ Критическая ошибка импорта: {e}. Проверьте структуру папок.")
    exit(1)

# --- FSM СОСТОЯНИЯ ---
class ProductSelection(StatesGroup):
    selecting = State() 
    waiting_for_magic_photo = State() 

# --- КОНСТАНТЫ И ГЛОБАЛЬНАЯ БАЗА ---
STAGES = ["Модель", "Память", "SIM", "Цвет"] 
GLOBAL_CATALOG: List[Dict[str, Any]] = []
GLOBAL_SETTINGS: Dict[str, str] = {} 

STUB_KEYS = {
    "iPhone": "iPhone_STUB",
    "iPad": "iPad_STUB",
    "Mac": "MacBook_STUB",  
    "Watch": "AppleWatch_STUB",
    "AirPods": "AirPods_STUB"
}

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
bot = Bot(token=API_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN)) 
dp = Dispatcher()

# --- ФУНКЦИИ БАЗЫ ДАННЫХ ---
async def load_catalog_if_empty():
    global GLOBAL_CATALOG, GLOBAL_SETTINGS
    if not GLOBAL_CATALOG:
        logging.info("Скачивание актуального каталога vnxSHOP...")
        GLOBAL_CATALOG = get_data_from_sheet()
        logging.info("Скачивание настроек картинок из Settings...")
        GLOBAL_SETTINGS = get_settings()

def get_filtered_catalog(current_filter: Dict[str, str]) -> List[Dict[str, Any]]:
    filtered = GLOBAL_CATALOG
    for k, v in current_filter.items():
        if k == "Категория":
            prefix = v.lower()
            filtered = [item for item in filtered if prefix in str(item.get("Модель", "")).lower()]
        else:
            filtered = [item for item in filtered if item.get(k) == v]
    return filtered

def get_stub_key(category: str, model: str = "") -> str:
    cat_lower = category.lower()
    mod_lower = model.lower()
    
    if "iphone" in cat_lower: return "iPhone_STUB"
    if "ipad" in cat_lower: return "iPad_STUB"
    if "watch" in cat_lower: return "AppleWatch_STUB"
    if "airpods" in cat_lower: return "AirPods_STUB"
    
    if "mac" in cat_lower:
        if "imac" in mod_lower:
            return "iMac_STUB"
        return "MacBook_STUB"
        
    return ""

# --- УМНАЯ ФУНКЦИЯ ДЛЯ ПЛАВНОЙ СМЕНЫ ФОТО/ТЕКСТА ---
async def update_message_content(callback: types.CallbackQuery, text: str, reply_markup, photo_url: str = None):
    has_photo_now = bool(callback.message.photo)

    if photo_url and photo_url.startswith("http"):
        if has_photo_now:
            media = InputMediaPhoto(media=photo_url, caption=text, parse_mode="MARKDOWN")
            try:
                await callback.message.edit_media(media=media, reply_markup=reply_markup)
            except Exception as e:
                if "message is not modified" not in str(e).lower():
                    await callback.message.edit_caption(caption=text, reply_markup=reply_markup)
        else:
            await callback.message.delete()
            await callback.message.answer_photo(photo=photo_url, caption=text, reply_markup=reply_markup)
    else:
        if has_photo_now:
            await callback.message.delete()
            await callback.message.answer(text=text, reply_markup=reply_markup)
        else:
            try:
                await callback.message.edit_text(text=text, reply_markup=reply_markup)
            except Exception:
                pass


# --- ХЕНДЛЕРЫ: ОСНОВНЫЕ КОМАНДЫ ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "👋 Добро пожаловать! Выберите категорию или откройте интерактивный каталог:",
        reply_markup=get_main_menu(web_app_url=None) 
    )

@dp.callback_query(F.data == "back_to_main")
async def back_to_main(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    if callback.message.photo:
        await callback.message.delete()
        await callback.message.answer("Выберите категорию техники Apple:", reply_markup=get_main_menu())
    else:
        await callback.message.edit_text("Выберите категорию техники Apple:", reply_markup=get_main_menu())
    await callback.answer()


# --- ХЕНДЛЕРЫ: УМНАЯ ВОРОНКА (SMART FUNNEL) ---

@dp.callback_query(F.data.startswith("cat_"))
async def start_category_selection(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer("Загрузка каталога...", show_alert=False)
    await load_catalog_if_empty()
    
    if not GLOBAL_CATALOG:
        await callback.message.edit_text(
            "❌ База данных временно недоступна или пуста. Попробуйте позже.",
            reply_markup=get_main_menu()
        )
        return

    category_key = callback.data.split("cat_")[1]
    current_filter = {"Категория": category_key}
    await state.set_state(ProductSelection.selecting)
    
    await ask_next_stage(callback, state, current_filter, stage_index=0)


async def ask_next_stage(callback: types.CallbackQuery, state: FSMContext, current_filter: dict, stage_index: int):
    filtered = get_filtered_catalog(current_filter)

    if not filtered:
        await callback.message.edit_text("❌ Нет товаров с такими параметрами.", reply_markup=get_main_menu())
        await state.clear()
        return

    if stage_index >= len(STAGES):
        await show_final_product(callback, filtered[0], state)
        return

    stage_name = STAGES[stage_index]
    unique_values = sorted(list(set(item.get(stage_name, "-") for item in filtered)))

    if len(unique_values) == 1 and unique_values[0] == "-":
        current_filter[stage_name] = "-"
        return await ask_next_stage(callback, state, current_filter, stage_index + 1)

    kb_data = []
    original_values_map = {} 
    
    for val in unique_values:
        if val == "-": continue 

        items_with_val = [i for i in filtered if i.get(stage_name) == val]
        prices = [int(str(i.get("Цена", "0")).replace(" ", "")) for i in items_with_val if str(i.get("Цена", "0")).replace(" ", "").isdigit()]
        min_price = min(prices) if prices else 0

        is_final_choice = stage_index == len(STAGES) - 1 or all(
            len(set(i.get(s, "-") for i in items_with_val)) == 1 for s in STAGES[stage_index+1:]
        )

        if is_final_choice and min_price > 0:
            kb_data.append([val, str(min_price)])
        elif min_price > 0:
            kb_data.append([val, f"от {min_price}"])
        else:
            kb_data.append(val)

        safe_val = val.replace(" ", "_").replace("/", "-")[:60]
        original_values_map[safe_val] = val

    await state.update_data(current_filter=current_filter, stage_index=stage_index, val_map=original_values_map)

    keyboard = get_dynamic_keyboard(kb_data, callback_prefix="stg_", back_callback="back_to_main")

    cat_name = current_filter.get("Категория", "Каталог")
    model_name = current_filter.get("Модель", "")
    
    text = f"📦 **{cat_name}**\n\n"
    for i in range(stage_index):
        s_name = STAGES[i]
        s_val = current_filter.get(s_name)
        if s_val and s_val != "-":
            text += f"▪️ {s_name}: {s_val}\n"

    text += f"\n👇 Выберите параметр **{stage_name}**:"

    stub_key = get_stub_key(cat_name, model_name)
    photo_url = GLOBAL_SETTINGS.get(stub_key, "")

    await update_message_content(callback, text, keyboard, photo_url)


@dp.callback_query(ProductSelection.selecting, F.data.startswith("stg_"))
async def process_stage_selection(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    
    user_data = await state.get_data()
    encoded_val = callback.data.replace("stg_", "")
    
    val_map = user_data.get("val_map", {})
    selected_value = val_map.get(encoded_val, encoded_val)
    
    stage_index = user_data.get("stage_index", 0)
    current_filter = user_data.get("current_filter", {})
    
    stage_name = STAGES[stage_index]
    current_filter[stage_name] = selected_value
    
    await ask_next_stage(callback, state, current_filter, stage_index + 1)


# --- ФИНАЛЬНЫЙ ЭТАП: КАРТОЧКА ТОВАРА И AI МАГИЯ ---

async def show_final_product(callback: types.CallbackQuery, item: dict, state: FSMContext):
    user_data = await state.get_data()
    category_name = user_data.get("current_filter", {}).get("Категория", "")

    title = item.get("Полное_название", "Товар Apple")
    memory = item.get("Память", "-")
    sim = item.get("SIM", "-")
    color = item.get("Цвет", "-")
    region = item.get("Регион", "")
    availability = item.get("Наличие", "Уточняется")
    price = item.get("Цена", "Цена по запросу")
    
    photo_url = str(item.get("Ссылка на фото", ""))
    if not photo_url.startswith("http"):
        stub_key = get_stub_key(category_name, title)
        photo_url = GLOBAL_SETTINGS.get(stub_key, "")

    text = f"✅ **{title}**\n\n"
    if memory != "-": text += f"💾 Память: {memory}\n"
    if sim != "-": text += f"📡 Связь: {sim}\n"
    if color != "-": text += f"🎨 Цвет: {color}\n"
    if region and region != "-": text += f"🌍 Регион: {region}\n"
    
    text += f"\n📦 Наличие: {availability}\n"
    text += f"💰 **Цена: {price} ₽**\n\n"
    text += "Заявка сформирована. Менеджер скоро свяжется с вами для оформления!\n\n"
    
    text += f"✨ **Кстати, хотите небольшую магию?**\n"
    text += f"Нажмите кнопку ниже, чтобы увидеть, как этот {title} будет смотреться с вами!"

    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="📸 Примерить (AI магия)", callback_data="magic_tryon"))
    builder.row(InlineKeyboardButton(text="⬅️ В главное меню", callback_data="back_to_main"))

    await update_message_content(callback, text, builder.as_markup(), photo_url)

    await state.update_data(magic_product_title=title)

    user = callback.from_user
    manager_message = (
        "🔥 **НОВАЯ ЗАЯВКА ИЗ БОТА!**\n"
        f"**Товар:** {title}\n"
        f"**Параметры:** {memory} / {color} / {sim} / {region}\n"
        f"**Цена:** `{price} ₽` | **Наличие:** `{availability}`\n"
        f"👤 Клиент: {user.full_name} (@{user.username or 'Скрыт'})"
    )
    
    manager_kb = InlineKeyboardBuilder()
    if user.username:
        manager_kb.row(InlineKeyboardButton(text="💬 Написать клиенту", url=f"https://t.me/{user.username}"))
    else:
        manager_kb.row(InlineKeyboardButton(text="💬 Профиль клиента", url=f"tg://user?id={user.id}"))

    if MANAGER_ID:
        try:
            await bot.send_message(chat_id=MANAGER_ID, text=manager_message, reply_markup=manager_kb.as_markup())
        except Exception as e:
            logging.error(f"Не удалось отправить сообщение менеджеру: {e}")

# --- ОБРАБОТЧИКИ ДЛЯ AI-МАГИИ ---

@dp.callback_query(F.data == "magic_tryon")
async def trigger_magic(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer(
        "Отлично! 📸 Отправьте мне любое свое фото, и наша нейросеть покажет магию с выбранным устройством!"
    )
    await state.set_state(ProductSelection.waiting_for_magic_photo)
    await callback.answer()

@dp.message(ProductSelection.waiting_for_magic_photo, F.photo)
async def process_magic_photo(message: types.Message, state: FSMContext):
    """Принимаем фото от клиента, скачиваем его и отправляем в нейросеть"""
    user_data = await state.get_data()
    product_title = user_data.get("magic_product_title", "Apple девайс")
    
    # Отправляем первичный статус
    status_msg = await message.answer("⌛️ Скачиваю фотографию...")
    
    try:
        # 1. Получаем ID самого большого фото (лучшего качества)
        photo_id = message.photo[-1].file_id
        
        # 2. Скачиваем фото в оперативную память сервера
        file_info = await bot.get_file(photo_id)
        downloaded_file = await bot.download_file(file_info.file_path)
        photo_bytes = downloaded_file.read()
        
        # 3. Обновляем статус и включаем анимацию "отправки фото" в шапке чата
        await status_msg.edit_text(f"✨ Нейросеть начала работу! Интегрируем {product_title}...\nПожалуйста, подождите 10-15 секунд.")
        await bot.send_chat_action(chat_id=message.chat.id, action=ChatAction.UPLOAD_PHOTO)
        
        # --- МЕСТО ДЛЯ ВЫЗОВА API vnxORACLE ---
        # Здесь мы отправим photo_bytes в OpenAI / Replicate
        await asyncio.sleep(4) # Временная имитация работы
        
        # Временная логика (пока не подключим API, отправляем оригинальное фото клиента обратно)
        result_photo = BufferedInputFile(photo_bytes, filename="magic_result.jpg")
        
        # Подготавливаем рекламную клавиатуру
        promo_kb = InlineKeyboardBuilder()
        promo_kb.row(InlineKeyboardButton(text="🔮 Открыть vnxORACLE", url="https://t.me/vnxORACLE_bot"))
        promo_kb.row(InlineKeyboardButton(text="⬅️ В главное меню", callback_data="back_to_main"))

        final_text = (
            f"✨ Ваша персональная магия с **{product_title}** готова! 📸\n\n"
            f"Понравилось? Хочешь больше нейросетевой магии, крутых генераций и умных ответов на любые вопросы? "
            f"Переходи к нашему главному AI-помощнику — **vnxORACLE**! 🔮"
        )

        # Удаляем сообщение со статусом "Генерирую..."
        await status_msg.delete()
        
        # Отправляем готовое фото
        await message.answer_photo(photo=result_photo, caption=final_text, reply_markup=promo_kb.as_markup())
        
    except Exception as e:
        logging.error(f"Ошибка при обработке фото: {e}")
        await status_msg.edit_text("❌ Произошла ошибка при обработке фотографии. Попробуйте отправить другое фото.")

    # Возвращаем пользователя в обычное состояние
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
