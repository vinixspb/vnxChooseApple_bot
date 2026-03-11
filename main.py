import asyncio
import html
import logging
import os
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.enums import ParseMode, ChatAction
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardButton, InputMediaPhoto
from aiogram.utils.keyboard import InlineKeyboardBuilder
from dotenv import load_dotenv

from states.product_states import ProductSelection
from services.sheets_manager import get_data_from_sheet, get_settings
from services.kie_service import KieService
from keyboards import get_main_menu, get_dynamic_keyboard

load_dotenv()
MANAGER_ID = os.getenv('MANAGER_ID')

# ФИX #1: Переходим с MARKDOWN на HTML — он не падает на _ в динамических данных
bot = Bot(
    token=os.getenv('BOT_TOKEN'),
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
dp = Dispatcher()
kie_ai = KieService(os.getenv('KIE_API_KEY'))

CATALOG = []
SETTINGS = {}
STAGES = ["model_group", "memory", "sim", "color"]


async def load_all():
    global CATALOG, SETTINGS
    CATALOG = get_data_from_sheet()
    SETTINGS = get_settings()


def get_stub(cat, model=""):
    keys = {
        "iPhone": "iPhone_STUB",
        "iPad": "iPad_STUB",
        "Watch": "AppleWatch_STUB",
        "AirPods": "AirPods_STUB"
    }
    key = keys.get(cat, "MacBook_STUB" if "iMac" not in model else "iMac_STUB")
    return SETTINGS.get(key)


# ─────────────────────── ХЕНДЛЕРЫ ───────────────────────

@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    # ФИX #1: Теги HTML вместо ** для жирного
    await message.answer("👋 Добро пожаловать в <b>vnxSHOP</b>!", reply_markup=get_main_menu())


@dp.callback_query(F.data == "back_to_main")
async def back_to_main(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    if callback.message.photo:
        await callback.message.delete()
    await callback.message.answer("Выберите категорию:", reply_markup=get_main_menu())
    await callback.answer()


@dp.callback_query(F.data.startswith("cat_"))
async def start_category(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer("Загрузка...")
    await load_all()

    cat = callback.data.split("_")[1]
    await state.set_state(ProductSelection.selecting)
    await run_step(callback, state, {"cat": cat}, 0)


async def run_step(callback, state, filters, idx):
    # Фильтруем по категории
    data = [i for i in CATALOG if filters["cat"].lower() in str(i["model_group"]).lower()]

    # Фильтруем по уже выбранным шагам
    for i in range(idx):
        stage = STAGES[i]
        if stage in filters:
            data = [d for d in data if d[stage] == filters[stage]]

    if not data:
        return await callback.message.answer("❌ Нет в наличии", reply_markup=get_main_menu())

    if idx >= len(STAGES):
        return await finalize(callback, data[0], state)

    step_name = STAGES[idx]
    vals = sorted(list(set(d[step_name] for d in data if d.get(step_name))))

    # Пропускаем шаг, если единственное значение — прочерк
    if len(vals) == 1 and vals[0] == "-":
        filters[step_name] = "-"
        return await run_step(callback, state, filters, idx + 1)

    # ФИX #2: val_map строим по числовому индексу — полностью исключает
    # коллизии и спецсимволы в callback_data (_, /, скобки и т.д.)
    val_map = {}
    kb_list = []
    for i, v in enumerate(vals):
        if v == "-":
            continue
        key = str(i)           # "0", "1", "2" — всегда безопасно
        val_map[key] = v
        kb_list.append((key, v))  # передаём (ключ, метка) в клавиатуру

    await state.update_data(filters=filters, idx=idx, val_map=val_map)

    # ФИX #1 + ФИX #3: html.escape на КАЖДОМ динамическом значении,
    # проверяем STAGES[i], а не STAGES[idx] — это и был баг с idx vs i
    already_selected = "\n".join(
        f"▪️ {STAGES[i]}: <b>{html.escape(str(filters[STAGES[i]]))}</b>"
        for i in range(idx)
        if filters.get(STAGES[i], "-") != "-"   # ФИX #3: был filters[STAGES[idx]]
    )
    text = (
        f"📦 <b>{html.escape(filters['cat'])}</b>\n"
        f"{already_selected}\n\n"
        f"👇 Выберите <b>{html.escape(step_name)}</b>:"
    )

    photo = get_stub(filters["cat"], filters.get("model_group", ""))
    kb = get_dynamic_keyboard(kb_list, "stg_")

    # ФИX #4: edit_text нельзя вызывать на photo-сообщении → используем edit_caption
    if photo and not callback.message.photo:
        await callback.message.delete()
        await callback.message.answer_photo(photo, caption=text, reply_markup=kb)
    elif photo:
        await callback.message.edit_media(
            InputMediaPhoto(media=photo, caption=text), reply_markup=kb
        )
    else:
        if callback.message.photo:
            # ФИX #4: photo-сообщение — только edit_caption, не edit_text
            await callback.message.edit_caption(caption=text, reply_markup=kb)
        else:
            await callback.message.edit_text(text, reply_markup=kb)


@dp.callback_query(ProductSelection.selecting, F.data.startswith("stg_"))
async def handle_selection(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    s = await state.get_data()

    # ФИX #2: достаём значение из val_map по числовому ключу
    raw_key = callback.data.replace("stg_", "")
    val = s["val_map"].get(raw_key)

    if val is None:
        # Защита: если ключ не найден — возвращаем в меню
        await callback.message.answer("⚠️ Сессия устарела. Начните заново.", reply_markup=get_main_menu())
        await s_state.clear() if (s_state := callback) else None
        return

    filters = s["filters"]
    filters[STAGES[s["idx"]]] = val
    await run_step(callback, state, filters, s["idx"] + 1)


async def finalize(callback, item, state):
    # ФИX #1: HTML-теги, html.escape на всех полях из таблицы
    title_safe   = html.escape(str(item.get('title', '')))
    price_safe   = html.escape(str(item.get('price', '')))
    memory_safe  = html.escape(str(item.get('memory', '-')))
    color_safe   = html.escape(str(item.get('color', '-')))
    sim_safe     = html.escape(str(item.get('sim', '-')))
    region_safe  = html.escape(str(item.get('region', '-')))

    text = (
        f"✅ <b>{title_safe}</b>\n\n"
        f"💾 Память: {memory_safe}\n"
        f"🎨 Цвет: {color_safe}\n"
        f"📡 SIM: {sim_safe}\n"
        f"🌍 Регион: {region_safe}\n\n"
        f"💰 <b>Цена: {price_safe} ₽</b>\n\n"
        "Заявка создана! Менеджер свяжется с вами.\n\n"
        "✨ <b>Хотите магию?</b> Отправьте фото!"
    )

    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="📸 AI магия", callback_data="magic_tryon"))
    kb.row(InlineKeyboardButton(text="⬅️ Меню", callback_data="back_to_main"))

    image_url = item.get('image', '')
    photo = image_url if image_url.startswith("http") else get_stub(item.get('model_group', ''))

    # ФИX #4: правильный метод в зависимости от типа сообщения
    if callback.message.photo:
        if photo:
            await callback.message.edit_media(
                InputMediaPhoto(media=photo, caption=text), reply_markup=kb.as_markup()
            )
        else:
            await callback.message.edit_caption(caption=text, reply_markup=kb.as_markup())
    else:
        if photo:
            await callback.message.answer_photo(photo, caption=text, reply_markup=kb.as_markup())
        else:
            await callback.message.answer(text, reply_markup=kb.as_markup())

    await state.update_data(title=item.get('title', ''))

    if MANAGER_ID:
        user = callback.from_user
        m_text = (
            f"🔥 <b>НОВАЯ ЗАЯВКА!</b>\n"
            f"<b>Товар:</b> {title_safe}\n"
            f"<b>Параметры:</b> {memory_safe} / {color_safe} / {sim_safe} / {region_safe}\n"
            f"<b>Цена:</b> {price_safe} ₽\n"
            f"👤 {html.escape(user.full_name)} "
            f"(@{html.escape(user.username or 'Скрыт')})"
        )
        await bot.send_message(MANAGER_ID, m_text)


# ─────────────────────── AI МАГИЯ ───────────────────────

@dp.callback_query(F.data == "magic_tryon")
async def magic_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("📸 Пришлите ваше фото!")
    await state.set_state(ProductSelection.waiting_for_magic_photo)
    await callback.answer()


@dp.message(ProductSelection.waiting_for_magic_photo, F.photo)
async def magic_process(message: types.Message, state: FSMContext):
    data = await state.get_data()
    title = data.get("title", "Apple девайс")
    title_safe = html.escape(title)
    msg = await message.answer("⌛️ Колдуем через nano-banana-2...")

    try:
        file = await bot.get_file(message.photo[-1].file_id)
        photo_bytes = (await bot.download_file(file.file_path)).read()
        await bot.send_chat_action(message.chat.id, ChatAction.UPLOAD_PHOTO)

        url = await kie_ai.generate_magic_image(photo_bytes, title)
        if not url:
            raise ValueError("API вернул пустой URL")

        kb = InlineKeyboardBuilder()
        kb.row(InlineKeyboardButton(text="🔮 Больше в vnxORACLE", url="https://t.me/vnxORACLE_bot"))
        kb.row(InlineKeyboardButton(text="⬅️ Меню", callback_data="back_to_main"))

        await msg.delete()
        await message.answer_photo(
            url,
            caption=f"✨ Ваша магия с <b>{title_safe}</b>!\n\nЗаходите в <b>vnxORACLE</b> за добавкой!",
            reply_markup=kb.as_markup()
        )
    except Exception as e:
        logging.error(f"magic_process error: {e}")
        await msg.edit_text("❌ Ошибка магии. Попробуйте другое фото.")
    finally:
        await state.clear()


# ─────────────────────── ЗАПУСК ───────────────────────

async def main():
    logging.basicConfig(level=logging.INFO)
    logging.info("vnxChooseApple Bot Started")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
