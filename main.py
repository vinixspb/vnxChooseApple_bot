import asyncio
import logging
import os
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.enums import ParseMode, ChatAction
from aiogram.client.default import DefaultBotProperties 
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardButton, InputMediaPhoto, BufferedInputFile
from aiogram.utils.keyboard import InlineKeyboardBuilder
from dotenv import load_dotenv

from states.product_states import ProductSelection
from services.sheets_manager import get_data_from_sheet, get_settings
from services.kie_service import KieService
from keyboards import get_main_menu, get_dynamic_keyboard

load_dotenv()
MANAGER_ID = os.getenv('MANAGER_ID')
bot = Bot(token=os.getenv('BOT_TOKEN'), default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN))
dp = Dispatcher()
kie_ai = KieService(os.getenv('KIE_API_KEY'))

# Глобальные данные
CATALOG = []
SETTINGS = {}
STAGES = ["model_group", "memory", "sim", "color"]

async def load_all():
    global CATALOG, SETTINGS
    CATALOG = get_data_from_sheet()
    SETTINGS = get_settings()

def get_stub(cat, model=""):
    keys = {"iPhone": "iPhone_STUB", "iPad": "iPad_STUB", "Watch": "AppleWatch_STUB", "AirPods": "AirPods_STUB"}
    key = keys.get(cat, "MacBook_STUB" if "iMac" not in model else "iMac_STUB")
    return SETTINGS.get(key)

# --- ХЕНДЛЕРЫ ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("👋 Добро пожаловать в **vnxSHOP**!", reply_markup=get_main_menu())

@dp.callback_query(F.data == "back_to_main")
async def back_to_main(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    if callback.message.photo: await callback.message.delete()
    await callback.message.answer("Выберите категорию:", reply_markup=get_main_menu())
    await callback.answer()

@dp.callback_query(F.data.startswith("cat_"))
async def start_category(callback: types.CallbackQuery, state: FSMContext):
    # СЕНЬОР-ФИКС: отвечаем сразу, чтобы query не протух пока грузим Sheets
    await callback.answer("Загрузка...") 
    await load_all()
    
    cat = callback.data.split("_")[1]
    await state.set_state(ProductSelection.selecting)
    await run_step(callback, state, {"cat": cat}, 0)

async def run_step(callback, state, filters, idx):
    data = [i for i in CATALOG if filters["cat"].lower() in str(i["model_group"]).lower()]
    for i in range(idx):
        data = [d for d in data if d[STAGES[i]] == filters[STAGES[i]]]
    
    if not data:
        return await callback.message.answer("❌ Нет в наличии", reply_markup=get_main_menu())

    if idx >= len(STAGES):
        return await finalize(callback, data[0], state)

    step_name = STAGES[idx]
    vals = sorted(list(set(d[step_name] for d in data)))
    
    if len(vals) == 1 and vals[0] == "-":
        filters[step_name] = "-"
        return await run_step(callback, state, filters, idx + 1)

    kb_list = []
    val_map = {}
    for v in vals:
        if v == "-": continue
        safe = v.replace(" ", "_")[:60]
        val_map[safe] = v
        kb_list.append(v)

    await state.update_data(filters=filters, idx=idx, val_map=val_map)
    
    text = f"📦 **{filters['cat']}**\n" + "\n".join([f"▪️ {STAGES[i]}: {filters[STAGES[i]]}" for i in range(idx) if filters[STAGES[idx]] != "-"])
    text += f"\n\n👇 Выберите **{step_name}**:"
    
    photo = get_stub(filters["cat"], filters.get("model_group", ""))
    
    if photo and not callback.message.photo:
        await callback.message.delete()
        await callback.message.answer_photo(photo, caption=text, reply_markup=get_dynamic_keyboard(kb_list, "stg_"))
    elif photo:
        await callback.message.edit_media(InputMediaPhoto(media=photo, caption=text), reply_markup=get_dynamic_keyboard(kb_list, "stg_"))
    else:
        await callback.message.edit_text(text, reply_markup=get_dynamic_keyboard(kb_list, "stg_"))

@dp.callback_query(ProductSelection.selecting, F.data.startswith("stg_"))
async def handle_selection(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    s = await state.get_data()
    val = s["val_map"].get(callback.data.replace("stg_", ""), callback.data.replace("stg_", ""))
    filters = s["filters"]
    filters[STAGES[s["idx"]]] = val
    await run_step(callback, state, filters, s["idx"] + 1)

async def finalize(callback, item, state):
    text = f"✅ **{item['title']}**\n\n💰 **Цена: {item['price']} ₽**\n\nЗаявка создана! Менеджер свяжется с вами.\n\n✨ **Хотите магию?** Отправьте фото!"
    
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="📸 AI магия", callback_data="magic_tryon"))
    kb.row(InlineKeyboardButton(text="⬅️ Меню", callback_data="back_to_main"))
    
    photo = item['image'] if item['image'].startswith("http") else get_stub(item['model_group'])
    if callback.message.photo:
        await callback.message.edit_media(InputMediaPhoto(media=photo, caption=text), reply_markup=kb.as_markup())
    else:
        await callback.message.answer_photo(photo, caption=text, reply_markup=kb.as_markup())
    
    await state.update_data(title=item['title'])
    
    if MANAGER_ID:
        m_text = f"🔥 **НОВАЯ ЗАЯВКА!**\n**Товар:** {item['title']}\n**Параметры:** {item['memory']} / {item['color']} / {item['sim']} / {item['region']}\n**Цена:** {item['price']}\n👤 {callback.from_user.full_name} (@{callback.from_user.username or 'Скрыт'})"
        await bot.send_message(MANAGER_ID, m_text)

@dp.callback_query(F.data == "magic_tryon")
async def magic_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("📸 Пришлите ваше фото!")
    await state.set_state(ProductSelection.waiting_for_magic_photo)
    await callback.answer()

@dp.message(ProductSelection.waiting_for_magic_photo, F.photo)
async def magic_process(message: types.Message, state: FSMContext):
    data = await state.get_data()
    title = data.get("title", "Apple девайс")
    msg = await message.answer("⌛️ Колдуем через nano-banana-2...")
    
    try:
        file = await bot.get_file(message.photo[-1].file_id)
        photo_bytes = (await bot.download_file(file.file_path)).read()
        await bot.send_chat_action(message.chat.id, ChatAction.UPLOAD_PHOTO)
        
        url = await kie_ai.generate_magic_image(photo_bytes, title)
        if not url: raise Exception("API Error")
        
        kb = InlineKeyboardBuilder()
        kb.row(InlineKeyboardButton(text="🔮 Больше в vnxORACLE", url="https://t.me/vnxORACLE_bot"))
        kb.row(InlineKeyboardButton(text="⬅️ Меню", callback_data="back_to_main"))
        
        await msg.delete()
        await message.answer_photo(url, caption=f"✨ Ваша магия с {title}!\n\nЗаходите в **vnxORACLE** за добавкой!", reply_markup=kb.as_markup())
    except:
        await msg.edit_text("❌ Ошибка магии. Попробуйте другое фото.")
    finally:
        await state.clear()

async def main():
    logging.info("vnxChooseApple Senior Bot Started")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
