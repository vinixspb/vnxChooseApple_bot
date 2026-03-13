import asyncio
import html
import logging
import os
import random
import aiohttp
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
from services.assistant_service import get_assistant_reply, trim_history
from keyboards import get_main_menu, get_dynamic_keyboard

load_dotenv()
MANAGER_ID = os.getenv('MANAGER_ID')

bot = Bot(
    token=os.getenv('BOT_TOKEN'),
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
dp = Dispatcher()
kie_ai = KieService(os.getenv('KIE_API_KEY'))

CATALOG = []
SETTINGS = {}
STAGES = ["model_group", "size", "memory", "memory_ram", "color", "sim"]

# Браузерный UA — без него Apple CDN и другие хосты отдают 403
FETCH_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
    "Referer": "https://www.apple.com/",
}


async def load_all():
    global CATALOG, SETTINGS
    CATALOG = get_data_from_sheet()
    SETTINGS = get_settings()


def get_stub(cat, model=""):
    keys = {
        "iPhone":  "iPhone_STUB",
        "iPad":    "iPad_STUB",
        "Watch":   "AppleWatch_STUB",
        "AirPods": "AirPods_STUB",
    }
    key = keys.get(cat, "MacBook_STUB" if "iMac" not in model else "iMac_STUB")
    return SETTINGS.get(key)


async def fetch_image_bytes(url: str) -> bytes | None:
    """
    Скачиваем картинку на сервере с браузерным User-Agent.
    Нужно потому что Telegram не может напрямую получить картинки
    с Apple CDN и других хостов, которые блокируют ботов.
    """
    if not url or not url.startswith("http"):
        return None
    try:
        async with aiohttp.ClientSession(headers=FETCH_HEADERS) as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    data = await resp.read()
                    logger.info(f"fetch_image_bytes: {url[:60]} → {len(data)} bytes")
                    return data
                logger.warning(f"fetch_image_bytes: HTTP {resp.status} for {url[:60]}")
                return None
    except Exception as e:
        logger.warning(f"fetch_image_bytes error: {e}")
        return None


async def send_photo_safe(
    target,          # message или callback.message
    url: str,
    caption: str,
    reply_markup,
    is_edit: bool = False,
):
    """
    Отправляем или редактируем фото-сообщение.
    Сначала пробуем прямым URL — быстро и без трафика.
    Если Telegram отклонит (403/400) — скачиваем байты на сервере и шлём как файл.
    """
    async def _as_buffered(photo_bytes: bytes):
        buf = BufferedInputFile(photo_bytes, filename="photo.jpg")
        if is_edit:
            await target.edit_media(InputMediaPhoto(media=buf, caption=caption), reply_markup=reply_markup)
        else:
            await target.answer_photo(buf, caption=caption, reply_markup=reply_markup)

    try:
        if is_edit:
            await target.edit_media(
                InputMediaPhoto(media=url, caption=caption), reply_markup=reply_markup
            )
        else:
            await target.answer_photo(url, caption=caption, reply_markup=reply_markup)
    except Exception as e:
        logger.warning(f"send_photo_safe: прямой URL не сработал ({e}), качаю байты...")
        photo_bytes = await fetch_image_bytes(url)
        if photo_bytes:
            await _as_buffered(photo_bytes)
        else:
            # Совсем без фото — шлём просто текст
            if is_edit:
                await target.edit_caption(caption=caption, reply_markup=reply_markup)
            else:
                await target.answer(caption, reply_markup=reply_markup)


logger = logging.getLogger(__name__)


# ─────────────────────── ХЕНДЛЕРЫ ───────────────────────

@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
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
    data = [i for i in CATALOG if filters["cat"].lower() in str(i["model_group"]).lower()]
    for i in range(idx):
        stage = STAGES[i]
        if stage in filters:
            data = [d for d in data if d[stage] == filters[stage]]

    if not data:
        return await callback.message.answer("❌ Нет в наличии", reply_markup=get_main_menu())

    # Диагностика — видим что реально в данных
    if data and idx < len(STAGES):
        step_dbg = STAGES[idx]
        vals_dbg = list(set(d.get(step_dbg, "?") for d in data[:5]))
        logger.info(
            f"run_step idx={idx} step={step_dbg} rows={len(data)} "
            f"vals_sample={vals_dbg} "
            f"model_group_sample={data[0].get('model_group','?')}"
        )

    if idx >= len(STAGES):
        return await finalize(callback, data[0], state)

    step_name = STAGES[idx]
    vals_raw = [str(d[step_name]).strip() for d in data if d.get(step_name) and str(d[step_name]).strip()]
    vals = sorted(list(set(vals_raw)))

    # Автопропуск: единственный прочерк
    if len(vals) == 1 and vals[0] == "-":
        filters[step_name] = "-"
        logger.info(f"run_step: auto-skip {step_name} — single dash")
        return await run_step(callback, state, filters, idx + 1)

    # Автопропуск: регион если вариант один
    if step_name == "region" and len(vals) <= 1:
        filters[step_name] = vals[0] if vals else "-"
        logger.info(f"run_step: auto-skip region — single value: {filters[step_name]}")
        return await run_step(callback, state, filters, idx + 1)

    # Автопропуск: любой НЕ-model_group шаг с единственным реальным значением
    real_vals = [v for v in vals if v != "-"]
    if step_name != "model_group" and len(real_vals) == 1:
        filters[step_name] = real_vals[0]
        logger.info(f"run_step: auto-skip {step_name} — single real value: {real_vals[0]}")
        return await run_step(callback, state, filters, idx + 1)

    val_map = {}
    kb_list = []
    for i, v in enumerate(real_vals):
        key = str(i)
        val_map[key] = v

        # Для SIM — человеческие названия
        if step_name == "sim":
            sim_labels = {
                "eSim":       "eSIM + eSIM",
                "Dual eSim":  "eSIM + eSIM",
                "Nano+eSim":  "Физическая SIM + eSIM",
                "Nano+nano":  "Физическая SIM + Физическая SIM",
            }
            label = sim_labels.get(v, v)
            kb_list.append((key, label))
            continue

        # Для шага памяти показываем минимальную цену в кнопке
        if step_name == "memory":
            prices = []
            for row in data:
                if row.get("memory") == v:
                    try:
                        p = int(str(row.get("price", "0")).replace(" ", "").replace(",", ""))
                        if p > 0:
                            prices.append(p)
                    except ValueError:
                        pass
            label = f"{v}  —  от {min(prices):,} ₽".replace(",", " ") if prices else v
        else:
            label = v

        kb_list.append((key, label))

    await state.update_data(filters=filters, idx=idx, val_map=val_map)

    STEP_LABELS = {
        "model_group": "модель",
        "size":        "размер",   # диагональ / mm / Pro
        "memory":      "память",   # хранилище: 256GB / 1TB
        "memory_ram":  "RAM",      # ОЗУ: только для Mac
        "color":       "цвет",
        "sim":         "тип SIM",
        "region":      "регион",
    }

    already_selected = "\n".join(
        f"▪️ {STEP_LABELS.get(STAGES[i], STAGES[i])}: <b>{html.escape(str(filters[STAGES[i]]))}</b>"
        for i in range(idx)
        if filters.get(STAGES[i], "-") != "-"
    )
    text = (
        f"📦 <b>{html.escape(filters['cat'])}</b>\n"
        f"{already_selected}\n\n"
        f"👇 Выберите <b>{STEP_LABELS.get(step_name, step_name)}</b>:"
    )

    stub_url = get_stub(filters["cat"], filters.get("model_group", ""))
    kb = get_dynamic_keyboard(kb_list, "stg_")

    if stub_url:
        if callback.message.photo:
            await send_photo_safe(callback.message, stub_url, text, kb, is_edit=True)
        else:
            await callback.message.delete()
            await send_photo_safe(callback.message, stub_url, text, kb, is_edit=False)
    else:
        if callback.message.photo:
            await callback.message.edit_caption(caption=text, reply_markup=kb)
        else:
            await callback.message.edit_text(text, reply_markup=kb)


@dp.callback_query(ProductSelection.selecting, F.data.startswith("stg_"))
async def handle_selection(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    s = await state.get_data()
    raw_key = callback.data.replace("stg_", "")
    val = s["val_map"].get(raw_key)

    if val is None:
        await callback.message.answer("⚠️ Сессия устарела. Начните заново.", reply_markup=get_main_menu())
        await state.clear()
        return

    filters = s["filters"]
    filters[STAGES[s["idx"]]] = val
    await run_step(callback, state, filters, s["idx"] + 1)


async def finalize(callback, item, state):
    title_safe  = html.escape(str(item.get('title', '')))
    price_safe  = html.escape(str(item.get('price', '')))
    size_safe       = html.escape(str(item.get('size', '-')))
    memory_safe     = html.escape(str(item.get('memory', '-')))
    memory_ram_safe = html.escape(str(item.get('memory_ram', '-')))
    color_safe  = html.escape(str(item.get('color', '-')))
    sim_safe    = html.escape(str(item.get('sim', '-')))
    region_safe = html.escape(str(item.get('region', '-')))

    text = (
        f"✅ <b>{title_safe}</b>\n\n"
        + (f"📐 Размер: {size_safe}\n"       if size_safe != "-"       else "")
        + (f"💾 Память: {memory_safe}\n"      if memory_safe != "-"     else "")
        + (f"🧠 RAM: {memory_ram_safe}\n"     if memory_ram_safe != "-" else "")
        + f"🎨 Цвет: {color_safe}\n"
        + (f"📡 SIM: {sim_safe}\n"            if sim_safe != "-"        else "")
        + f"🌍 Регион: {region_safe}\n\n"
        f"💰 <b>Цена: {price_safe} ₽</b>\n\n"
        "Заявка создана! Менеджер свяжется с вами.\n\n"
        "✨ <b>Хотите магию?</b> Нажми кнопку и отправь своё фото!"
    )

    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="✅ Подтвердить заказ", callback_data="confirm_order"))
    kb.row(InlineKeyboardButton(text="📸 AI магия",          callback_data="magic_tryon"))
    kb.row(InlineKeyboardButton(text="⬅️ Меню",              callback_data="back_to_main"))

    image_url = item.get('image', '')
    photo_url = image_url if image_url.startswith("http") else get_stub(item.get('model_group', ''))

    if callback.message.photo:
        if photo_url:
            await send_photo_safe(callback.message, photo_url, text, kb.as_markup(), is_edit=True)
        else:
            await callback.message.edit_caption(caption=text, reply_markup=kb.as_markup())
    else:
        if photo_url:
            await send_photo_safe(callback.message, photo_url, text, kb.as_markup(), is_edit=False)
        else:
            await callback.message.answer(text, reply_markup=kb.as_markup())

    # Сохраняем title И image_url товара для AI магии
    await state.update_data(
        title=item.get('title', ''),
        product_image_url=photo_url or "",
    )

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



# ─────────────────────── АНДРЕЙ.AI КОНСУЛЬТАНТ ───────────────────────

@dp.callback_query(F.data == "start_assistant")
async def start_assistant(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await state.set_state(ProductSelection.consulting)
    await state.update_data(chat_history=[])

    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="❌ Выйти из чата", callback_data="exit_assistant"))

    greeting = (
        "👋 Привет! Я — <b>Андрей.ai</b>, цифровая субличность Андрея.\n\n"
        "Оригинал сейчас занят, но я знаю про Apple всё то же самое — "
        "и шутки у нас одинаковые 😄\n\n"
        "Помогу выбрать технику так, как Андрей делает это лично. "
        "Просто напиши что интересует — начнём! \n\n"
        "🙏 <b>Подскажите, какой у вас примерный бюджет?</b>"
    )
    await callback.message.answer(greeting, reply_markup=kb.as_markup())
    await callback.answer()


@dp.callback_query(F.data == "exit_assistant")
async def exit_assistant(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    farewell = (
        "👍 Выходим из чата с Андрей.ai.\n"
        "Захочешь вернуться — жми кнопку в меню!"
    )
    await callback.message.answer(farewell, reply_markup=get_main_menu())
    await callback.answer()


@dp.message(ProductSelection.consulting)
async def assistant_message(message: types.Message, state: FSMContext):
    user_text = (message.text or "").strip()
    if not user_text:
        return

    data = await state.get_data()
    history: list = data.get("chat_history", [])

    await message.bot.send_chat_action(message.chat.id, ChatAction.TYPING)

    reply = await get_assistant_reply(
        user_message=user_text,
        history=history,
        catalog=CATALOG,
    )

    history.append({"role": "user",      "content": user_text})
    history.append({"role": "assistant", "content": reply})
    history = trim_history(history)
    await state.update_data(chat_history=history)

    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="📱 Перейти в каталог", callback_data="back_to_main"))
    kb.row(InlineKeyboardButton(text="❌ Выйти из чата",     callback_data="exit_assistant"))

    await message.answer(reply, reply_markup=kb.as_markup())

# ─────────────────────── ПОДТВЕРЖДЕНИЕ ЗАКАЗА ───────────────────────

@dp.callback_query(F.data == "confirm_order")
async def confirm_order(callback: types.CallbackQuery, state: FSMContext):
    """
    Кнопка 'Подтвердить заказ'.
    Сейчас менеджер уже уведомлён в finalize() — здесь просто подтверждаем пользователю.
    В будущем: уведомлять менеджера только здесь, убрав из finalize.
    """
    await callback.answer("✅ Заказ подтверждён!")

    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="📸 AI магия", callback_data="magic_tryon"))
    kb.row(InlineKeyboardButton(text="⬅️ Меню",     callback_data="back_to_main"))

    try:
        await callback.message.edit_reply_markup(reply_markup=kb.as_markup())
    except Exception:
        pass

    await callback.message.answer(
        "🎉 <b>Заказ принят!</b>\n\n"
        "Менеджер свяжется с вами в ближайшее время. "
        "Если хотите — попробуйте <b>AI магию</b> 👇"
    )


# ─────────────────────── AI МАГИЯ ───────────────────────

@dp.callback_query(F.data == "magic_tryon")
async def magic_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("📸 Пришлите ваше фото!")
    await state.set_state(ProductSelection.waiting_for_magic_photo)
    await callback.answer()


# Юморные сообщения пока идёт генерация — меняем каждые 5 секунд
MAGIC_MESSAGES = [
    "⌛️ Колдуем...",
    "📐 Проектируем идеальный хват под вашу руку...",
    "🎨 Выбираем цвет, который подчёркивает ваш характер...",
    "🔬 Рассчитываем оптимальное расположение камер на задней стенке...",
    "✨ Наносим финишный антибликовый слой...",
    "🪄 Калибруем магнитный коннектор под вашу ауру...",
    "💅 Полируем грани до зеркального блеска...",
    "📡 Согласовываем частоты с ближайшей вышкой 5G...",
    "🧬 Синхронизируем чип с вашей биометрией...",
    "🌈 Применяем фирменный эффект Apple Glow™...",
    "🎭 Добавляем индивидуальности в каждый пиксель...",
    "🔭 Финальная проверка всех 48 мегапикселей...",
    "🎁 Упаковываем результат в фирменную коробочку...",
]


async def _animate_magic_msg(msg, stop_event: asyncio.Event):
    """Меняет текст сообщения каждые 5 секунд пока идёт генерация."""
    shown = {MAGIC_MESSAGES[0]}
    pool = MAGIC_MESSAGES[1:]
    while not stop_event.is_set():
        await asyncio.sleep(5)
        if stop_event.is_set():
            break
        remaining = [m for m in pool if m not in shown]
        if not remaining:
            remaining = pool  # пошли по второму кругу
        pick = random.choice(remaining)
        shown.add(pick)
        try:
            await msg.edit_text(pick)
        except Exception:
            pass  # сообщение уже удалено или не изменилось — ок


@dp.message(ProductSelection.waiting_for_magic_photo, F.photo)
async def magic_process(message: types.Message, state: FSMContext):
    data = await state.get_data()
    title = data.get("title", "Apple девайс")
    product_image_url = data.get("product_image_url", "")
    title_safe = html.escape(title)

    msg = await message.answer(MAGIC_MESSAGES[0])
    stop_event = asyncio.Event()
    animator = asyncio.create_task(_animate_magic_msg(msg, stop_event))

    try:
        # Фото пользователя
        file = await bot.get_file(message.photo[-1].file_id)
        user_photo_bytes = (await bot.download_file(file.file_path)).read()
        await bot.send_chat_action(message.chat.id, ChatAction.UPLOAD_PHOTO)

        # Фото товара из карточки — качаем на сервере
        product_image_bytes = None
        if product_image_url:
            product_image_bytes = await fetch_image_bytes(product_image_url)
            if product_image_bytes:
                logger.info(f"magic_process: product image loaded ({len(product_image_bytes)} bytes)")
            else:
                logger.warning("magic_process: не удалось загрузить фото товара, работаем без референса")

        url = await kie_ai.generate_magic_image(
            user_photo_bytes,
            title,
            product_image_bytes=product_image_bytes,
        )
        if not url:
            raise ValueError("API вернул пустой URL")

        stop_event.set()
        animator.cancel()

        kb = InlineKeyboardBuilder()
        kb.row(InlineKeyboardButton(text="🔮 Больше в vnxORACLE", url="https://t.me/vnxORACLE_bot"))
        kb.row(InlineKeyboardButton(text="⬅️ Меню", callback_data="back_to_main"))

        await msg.delete()
        await message.answer_photo(
            url,
            caption=f"✨ Ваша магия с <b>{title_safe}</b>!\n\nЗаходите в <b>vnxORACLE</b> за добавкой!",
            reply_markup=kb.as_markup()
        )
    except RuntimeError as e:
        stop_event.set()
        animator.cancel()
        if str(e) == "CREDITS_INSUFFICIENT":
            await msg.edit_text("⚠️ Магия временно недоступна — скоро вернётся!")
        else:
            await msg.edit_text("❌ Ошибка магии. Попробуйте другое фото.")
    except Exception as e:
        stop_event.set()
        animator.cancel()
        logger.error(f"magic_process error: {e}")
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
