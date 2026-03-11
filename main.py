# main.py

import asyncio
import logging
import os
import io
import base64
import json
import aiohttp
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
KIE_API_KEY = os.getenv('KIE_API_KEY') 

# ТОЧНОЕ НАЗВАНИЕ МОДЕЛИ (измени здесь, если 422 повторится)
AI_MODEL_NAME = "NanoBanana" 

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
        if "imac" in mod_lower: return "iMac_STUB"
        return "MacBook_STUB"
    return ""

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
            try: await callback.message.edit_text(text=text, reply_markup=reply_markup)
            except Exception: pass

# --- ХЕНДЛЕРЫ: КОМАНДЫ ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "👋 Добро пожаловать в **vnxSHOP**!\nВыберите категорию техники Apple:",
        reply_markup=get_main_menu(web_app_url=None) 
    )

@dp.message(Command("search"))
async def cmd_search(message: types.Message, state: FSMContext):
    await state.clear()
    await load_catalog_if_empty()
    await message.answer("📱 Выберите интересующую модель iPhone:", reply_markup=get_main_menu())

@dp.message(Command("list"))
async def cmd_list(message: types.Message):
    await load_catalog_if_empty()
    models = sorted(list(set(item.get("Модель") for item in GLOBAL_CATALOG if item.get("Модель"))))
    await message.answer("📋 **Модели в наличии:**\n\n" + "\n".join([f"• {m}" for m in models]))

@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    await message.answer("❓ Помощь: выберите товар в меню, укажите параметры и дождитесь ответа менеджера. В конце доступна AI-магия!")

@dp.message(Command("support"))
async def cmd_support(message: types.Message):
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="👨‍💻 Менеджер", url="https://t.me/vinixspb"))
    await message.answer("Нужна помощь? Напишите нам!", reply_markup=kb.as_markup())


@dp.callback_query(F.data == "back_to_main")
async def back_to_main(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    if callback.message.photo:
        await callback.message.delete()
        await callback.message.answer("Выберите категорию техники Apple:", reply_markup=get_main_menu())
    else:
        await callback.message.edit_text("Выберите категорию техники Apple:", reply_markup=get_main_menu())
    await callback.answer()

# --- ХЕНДЛЕРЫ: УМНАЯ ВОРОНКА ---

@dp.callback_query(F.data.startswith("cat_"))
async def start_category_selection(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer("Загрузка...")
    await load_catalog_if_empty()
    category_key = callback.data.split("cat_")[1]
    current_filter = {"Категория": category_key}
    await state.set_state(ProductSelection.selecting)
    await ask_next_stage(callback, state, current_filter, stage_index=0)

async def ask_next_stage(callback: types.CallbackQuery, state: FSMContext, current_filter: dict, stage_index: int):
    filtered = get_filtered_catalog(current_filter)
    if not filtered:
        await callback.message.edit_text("❌ Нет в наличии.", reply_markup=get_main_menu())
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
        is_final = stage_index == len(STAGES) - 1 or all(len(set(i.get(s, "-") for i in items_with_val)) == 1 for s in STAGES[stage_index+1:])
        if is_final and min_price > 0: kb_data.append([val, str(min_price)])
        elif min_price > 0: kb_data.append([val, f"от {min_price}"])
        else: kb_data.append(val)
        safe_val = val.replace(" ", "_").replace("/", "-")[:60]
        original_values_map[safe_val] = val

    await state.update_data(current_filter=current_filter, stage_index=stage_index, val_map=original_values_map)
    keyboard = get_dynamic_keyboard(kb_data, callback_prefix="stg_")
    cat_name = current_filter.get("Категория")
    text = f"📦 **{cat_name}**\n\n"
    for i in range(stage_index):
        s_val = current_filter.get(STAGES[i])
        if s_val and s_val != "-": text += f"▪️ {STAGES[i]}: {s_val}\n"
    text += f"\n👇 Выберите **{stage_name}**:"
    photo_url = GLOBAL_SETTINGS.get(get_stub_key(cat_name, current_filter.get("Модель", "")))
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
    current_filter[STAGES[stage_index]] = selected_value
    await ask_next_stage(callback, state, current_filter, stage_index + 1)

# --- ФИНАЛЬНЫЙ ЭТАП ---

async def show_final_product(callback: types.CallbackQuery, item: dict, state: FSMContext):
    user_data = await state.get_data()
    category_name = user_data.get("current_filter", {}).get("Категория", "")
    title = item.get("Полное_название", "Товар Apple")
    price = item.get("Цена", "По запросу")
    photo_url = str(item.get("Ссылка на фото", ""))
    if not photo_url.startswith("http"):
        photo_url = GLOBAL_SETTINGS.get(get_stub_key(category_name, title))

    text = f"✅ **{title}**\n\n💰 **Цена: {price} ₽**\n\n"
    text += "Заявка сформирована! Менеджер скоро напишет.\n\n"
    text += f"✨ **Хотите небольшую магию?**\nНажмите кнопку ниже, отправьте свое фото, и мы покажем этот {title} у вас в руках!"

    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="📸 Примерить (AI магия)", callback_data="magic_tryon"))
    builder.row(InlineKeyboardButton(text="⬅️ В главное меню", callback_data="back_to_main"))

    await update_message_content(callback, text, builder.as_markup(), photo_url)
    await state.update_data(magic_product_title=title)

    # Уведомление менеджеру
    user = callback.from_user
    manager_kb = InlineKeyboardBuilder()
    if user.username: manager_kb.row(InlineKeyboardButton(text="💬 Написать", url=f"https://t.me/{user.username}"))
    else: manager_kb.row(InlineKeyboardButton(text="💬 Профиль", url=f"tg://user?id={user.id}"))
    
    if MANAGER_ID:
        try: await bot.send_message(chat_id=MANAGER_ID, text=f"🔥 ЗАЯВКА: {title} ({price} ₽)\n👤 {user.full_name} (@{user.username or 'Скрыт'})", reply_markup=manager_kb.as_markup())
        except: pass

# --- ОБРАБОТЧИКИ AI-МАГИИ (ОТКАЗОУСТОЙЧИВЫЕ ЧЕРЕЗ NANOBANANA) ---

@dp.callback_query(F.data == "magic_tryon")
async def trigger_magic(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("📸 Отправьте мне свое фото, и наша нейросеть примерит девайс!")
    await state.set_state(ProductSelection.waiting_for_magic_photo)
    await callback.answer()

@dp.message(ProductSelection.waiting_for_magic_photo, F.photo)
async def process_magic_photo(message: types.Message, state: FSMContext):
    user_data = await state.get_data()
    product_title = user_data.get("magic_product_title", "Apple девайс")
    
    if not KIE_API_KEY:
        await message.answer("❌ AI-модуль не настроен.")
        return await state.clear()

    status_msg = await message.answer("⌛️ Запускаю нейросети...")
    
    try:
        photo_id = message.photo[-1].file_id
        file_info = await bot.get_file(photo_id)
        downloaded_file = await bot.download_file(file_info.file_path)
        photo_bytes = downloaded_file.read()
        
        await status_msg.edit_text(f"🎨 Создаю магию с {product_title} через {AI_MODEL_NAME}...\nЭто займет около 20-30 секунд.")
        await bot.send_chat_action(chat_id=message.chat.id, action=ChatAction.UPLOAD_PHOTO)
        
        base64_image = base64.b64encode(photo_bytes).decode('utf-8')
        data_uri = f"data:image/jpeg;base64,{base64_image}"
        
        # УЛУЧШЕННЫЙ ПРОМПТ
        prompt_text = (
            f"A photorealistic high-quality image of the person from the input photo holding a brand new {product_title} in their hands. "
            f"Keep the original person's identity, clothes, hair, and the background exactly the same. "
            f"The {product_title} must be held naturally with realistic lighting and shadows."
        )
        
        # СТРОИМ PAYLOAD ПО СТАНДАРТУ ТВОЕГО KIE_CLIENT
        payload = {
            "model": AI_MODEL_NAME, 
            "input": {
                "prompt": prompt_text,
                "image_input": [data_uri],
                "aspect_ratio": "9:16",
                "output_format": "png",
                "google_search": False,
                "resolution": "1K"
            }
        }
        
        headers = {"Authorization": f"Bearer {KIE_API_KEY}", "Content-Type": "application/json"}
        
        async with aiohttp.ClientSession(headers=headers, timeout=aiohttp.ClientTimeout(total=200)) as session:
            # Создание задачи
            async with session.post("https://api.kie.ai/api/v1/jobs/createTask", json=payload) as resp:
                data = await resp.json()
                task_id = data.get("data", {}).get("taskId") if data.get("code") == 200 else None
            
            if not task_id: raise Exception(f"API Error: {data}")

            # Ожидание (Polling)
            result_url = None
            for _ in range(50): 
                await asyncio.sleep(4)
                async with session.get(f"https://api.kie.ai/api/v1/jobs/recordInfo?taskId={task_id}") as r_resp:
                    res_data = await r_resp.json()
                    if res_data.get("code") != 200: continue
                    info = res_data.get("data", {})
                    if info.get("state") == "success":
                        res_json = json.loads(info.get("resultJson", "{}"))
                        result_url = res_json.get("resultUrls", [None])[0]
                        break
                    elif info.get("state") == "fail": raise Exception(f"Generation Failed: {info.get('failMsg')}")

        if not result_url: raise Exception("Timeout during generation")
        
        kb = InlineKeyboardBuilder()
        kb.row(InlineKeyboardButton(text="🔮 Больше магии в vnxORACLE", url="https://t.me/vnxORACLE_bot"))
        kb.row(InlineKeyboardButton(text="⬅️ В главное меню", callback_data="back_to_main"))

        await status_msg.delete()
        await message.answer_photo(
            photo=result_url, 
            caption=f"✨ Ваша персональная магия с **{product_title}** готова! 📸\n\nПонравилось? Еще больше крутых генераций и умных ответов — в нашем главном боте **vnxORACLE**! 🔮", 
            reply_markup=kb.as_markup()
        )
        
    except Exception as e:
        logging.error(f"Magic Error: {e}")
        await status_msg.edit_text("❌ Ошибка генерации. Попробуйте другое фото или позже.")
    finally:
        await state.clear()

async def main():
    logging.info("Бот vnxChooseApple запущен.")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try: asyncio.run(main())
    except: logging.warning("Бот остановлен.")
