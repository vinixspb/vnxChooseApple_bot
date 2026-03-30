# handlers/catalog.py
import html
import logging
import os
from aiogram import Router, F, types
from aiogram.filters import Command, CommandStart, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardButton
from aiogram.exceptions import TelegramBadRequest

from states.product_states import ProductSelection
from services.sheets_manager import get_data_from_sheet, get_settings
import services.data_store as store
from services.messages import MSG, BTN
from keyboards import get_main_menu, get_dynamic_keyboard
from utils.media import get_stub, send_photo_safe

router = Router()
logger = logging.getLogger(__name__)
MANAGER_ID = os.getenv('MANAGER_ID')

# ─── СЛОВАРЬ НОВИНОК (ДЛЯ СВОРАЧИВАНИЯ СПИСКОВ) ───
NOVELTY_KEYWORDS = {
    "iphone": ["17", "16"],
    "ipad": ["m4", "m2", "pro", "air 6"],
    "mac": ["m3", "m4"],
    "watch": ["series 10", "ultra 2", "se"],
    "airpods": ["4", "pro 2", "max"],
    "dyson": ["airwrap", "airstrait", "gen5", "v15", "supersonic"],
    "xiaomi": ["14", "13", "pad 6"]
}

async def load_all():
    store.CATALOG = get_data_from_sheet()
    store.SETTINGS = get_settings()

@router.message(Command("reset"))
async def cmd_reset(message: types.Message, state: FSMContext):
    await state.clear()
    await load_all()
    await message.answer(MSG["reload_done"], reply_markup=get_main_menu())

@router.message(CommandStart())
async def cmd_start(message: types.Message, command: CommandObject, state: FSMContext):
    await state.clear()
    
    # Обработка перехода по ссылке из Группы (Deep Link: ?start=ai)
    if command.args == "ai":
        from handlers.assistant import _launch_assistant
        await _launch_assistant(message, state)
        return
        
    await message.answer(MSG["welcome"], reply_markup=get_main_menu())

@router.callback_query(F.data == "back_to_main")
async def back_to_main(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    if callback.message.photo: await callback.message.delete()
    await callback.message.answer(MSG["choose_category"], reply_markup=get_main_menu())
    await callback.answer()

@router.callback_query(F.data.startswith("cat_"))
async def start_category(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer("Загрузка...")
    await load_all()
    cat = callback.data.split("_")[1]
    await state.set_state(ProductSelection.selecting)
    await run_step(callback, state, {"cat": cat}, 0)

async def run_step(callback, state, filters, idx):
    data = [i for i in store.CATALOG if filters["cat"].lower() in str(i.get("model_group", i.get("Модель", ""))).lower()]
    
    for i in range(idx):
        stage = store.STAGES[i]
        if stage in filters and filters[stage] != "*SKIPPED*":
            req_val = filters[stage]
            data = [
                d for d in data 
                if str(d.get(stage, "")).strip() == req_val 
                or (req_val == "-" and not str(d.get(stage, "")).strip())
            ]

    if not data:
        return await callback.message.answer(MSG["out_of_stock"], reply_markup=get_main_menu())

    if idx >= len(store.STAGES):
        return await finalize(callback, data[0], state)

    step_name = store.STAGES[idx]
    cat = filters.get("cat", "").lower()
    
    SKIP_BY_CAT = {
        "iphone":  {"size", "memory_ram"},
        "airpods": {"size", "sim", "memory_ram"},
        "watch":   {"size", "sim", "memory_ram", "memory"},
        "dyson":   {"size", "sim", "memory_ram", "memory"},
    }
    
    if step_name in SKIP_BY_CAT.get(cat, set()):
        filters[step_name] = "*SKIPPED*"
        return await run_step(callback, state, filters, idx + 1)

    vals_raw = [str(d.get(step_name, "")).strip() for d in data]
    vals_raw = ["-" if not v else v for v in vals_raw]
    vals = sorted(list(set(vals_raw)))

    if len(vals) == 1 and vals[0] == "-":
        filters[step_name] = "-"
        return await run_step(callback, state, filters, idx + 1)
        
    if step_name == "region" and len(vals) <= 1:
        filters[step_name] = vals[0] if vals else "-"
        return await run_step(callback, state, filters, idx + 1)

    real_vals = [v for v in vals if v != "-"]
    if step_name != "model_group" and len(real_vals) == 1:
        filters[step_name] = real_vals[0]
        return await run_step(callback, state, filters, idx + 1)

    # ─── ЛОГИКА СВОРАЧИВАНИЯ СПИСКОВ ───
    extra_btn = None
    if step_name == "model_group" and len(real_vals) > 5:
        show_all = filters.get("show_all_models", False)
        keywords = NOVELTY_KEYWORDS.get(cat, [])
        
        if keywords:
            novelties = [v for v in real_vals if any(kw in str(v).lower() for kw in keywords)]
            older = [v for v in real_vals if v not in novelties]
            
            if novelties and older:
                if not show_all:
                    real_vals = novelties
                    extra_btn = {"text": "🔻 Другие модели", "callback_data": "toggle_models"}
                else:
                    extra_btn = {"text": "🔺 Свернуть", "callback_data": "toggle_models"}

    val_map = {}
    kb_list = []
    for i, v in enumerate(real_vals):
        key = str(i)
        val_map[key] = v

        if step_name == "sim":
            sim_labels = {"eSim": "eSIM + eSIM", "Dual eSim": "eSIM + eSIM", "Nano+eSim": "Физическая SIM + eSIM", "Nano+nano": "Физическая SIM + Физическая SIM"}
            kb_list.append((key, sim_labels.get(v, v)))
            continue

        if step_name == "memory":
            prices = []
            for row in data:
                m = str(row.get("memory", "")).strip()
                if not m: m = "-"
                if m == v:
                    try:
                        p_str = str(row.get("price", "0")).replace(" ", "").replace(",", "")
                        p = int(float(p_str))
                        if p > 0: prices.append(p)
                    except ValueError: pass
            label = f"{v}  —  от {min(prices):,} ₽".replace(",", " ") if prices else v
        else:
            label = v

        kb_list.append((key, label))

    await state.update_data(filters=filters, idx=idx, val_map=val_map)

    STEP_LABELS = {"model_group": "модель", "size": "размер", "memory": "память", "memory_ram": "RAM", "color": "цвет", "sim": "тип SIM", "region": "регион"}
    
    already_selected_lines = []
    for i in range(idx):
        stg = store.STAGES[i]
        val = filters.get(stg, "-")
        if val and val not in ["-", "*SKIPPED*"]:
            already_selected_lines.append(f"▪️ {STEP_LABELS.get(stg, stg)}: <b>{html.escape(str(val))}</b>")
            
    already_selected = "\n".join(already_selected_lines)
    text = f"📦 <b>{html.escape(filters['cat'])}</b>\n{already_selected}\n\n👇 Выберите <b>{STEP_LABELS.get(step_name, step_name)}</b>:"

    stub_url = get_stub(filters["cat"], filters.get("model_group", ""))
    kb = get_dynamic_keyboard(kb_list, "stg_", extra_btn=extra_btn)

    try:
        if stub_url:
            if callback.message.photo: await send_photo_safe(callback.message, stub_url, text, kb, is_edit=True)
            else:
                await callback.message.delete()
                await send_photo_safe(callback.message, stub_url, text, kb, is_edit=False)
        else:
            if callback.message.photo: await callback.message.edit_caption(caption=text, reply_markup=kb)
            else: await callback.message.edit_text(text, reply_markup=kb)
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            logger.error(f"Telegram edit error: {e}")

# ─── ОБРАБОТЧИК КНОПКИ СВЕРНУТЬ/РАЗВЕРНУТЬ ───
@router.callback_query(ProductSelection.selecting, F.data == "toggle_models")
async def toggle_models_list(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    s = await state.get_data()
    filters = s.get("filters", {})
    filters["show_all_models"] = not filters.get("show_all_models", False)
    await state.update_data(filters=filters)
    await run_step(callback, state, filters, s["idx"])

@router.callback_query(ProductSelection.selecting, F.data.startswith("stg_"))
async def handle_selection(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    s = await state.get_data()
    val = s.get("val_map", {}).get(callback.data.replace("stg_", ""))
    if val is None:
        await callback.message.answer(MSG["session_expired"], reply_markup=get_main_menu())
        return await state.clear()

    filters = s["filters"]
    filters[store.STAGES[s["idx"]]] = val
    await run_step(callback, state, filters, s["idx"] + 1)

# ─── БЛОК: Бесшовный выбор цвета ───
def get_siblings(item):
    siblings = []
    for d in store.CATALOG:
        if d.get("availability", "").lower() != "in stock": continue
        if (d.get("model_group") == item.get("model_group") and
            d.get("memory") == item.get("memory") and
            d.get("memory_ram") == item.get("memory_ram") and
            d.get("sim") == item.get("sim") and
            d.get("size") == item.get("size")):
            siblings.append(d)
    return siblings

@router.callback_query(F.data.startswith("csw_"))
async def show_color_options(callback: types.CallbackQuery, state: FSMContext):
    item_id_prefix = callback.data.replace("csw_", "")
    item = next((x for x in store.CATALOG if str(x.get("id")).startswith(item_id_prefix)), None)
    if not item: return await callback.answer("❌ Товар не найден", show_alert=True)
    
    siblings = get_siblings(item)
    unique_colors = {}
    for sib in siblings:
        c = sib.get("color", "-")
        if c != "-" and c not in unique_colors:
            unique_colors[c] = sib
            
    kb = InlineKeyboardBuilder()
    for c, sib in unique_colors.items():
        prefix = "✅ " if c == item.get("color") else ""
        cb_data = f"csel_{sib['id']}"
        while len(cb_data.encode('utf-8')) > 60: cb_data = cb_data[:-1]
        kb.row(InlineKeyboardButton(text=f"{prefix}{c}", callback_data=cb_data))
        
    back_data = f"csel_{item['id']}"
    while len(back_data.encode('utf-8')) > 60: back_data = back_data[:-1]
    kb.row(InlineKeyboardButton(text="⬅️ Назад", callback_data=back_data))
    
    try: await callback.message.edit_reply_markup(reply_markup=kb.as_markup())
    except TelegramBadRequest: pass
    await callback.answer()

@router.callback_query(F.data.startswith("csel_"))
async def select_new_color(callback: types.CallbackQuery, state: FSMContext):
    item_id_prefix = callback.data.replace("csel_", "")
    item = next((x for x in store.CATALOG if str(x.get("id")).startswith(item_id_prefix)), None)
    if not item: return await callback.answer("❌ Товар не найден", show_alert=True)
    await callback.answer("Загружаю...")
    await finalize(callback, item, state)

async def finalize(callback, item, state):
    def norm(k):
        v = str(item.get(k, '')).strip()
        return html.escape(v) if v else "-"

    t = html.escape(str(item.get('title', '')))
    p = html.escape(str(item.get('price', '')))
    size, mem, ram, c, sim, reg = [norm(k) for k in ['size', 'memory', 'memory_ram', 'color', 'sim', 'region']]

    text = (f"✅ <b>{t}</b>\n\n"
            + (f"📐 Размер: {size}\n" if size != "-" else "")
            + (f"💾 Память: {mem}\n" if mem != "-" else "")
            + (f"🧠 RAM: {ram}\n" if ram != "-" else "")
            + f"🎨 Цвет: {c}\n"
            + (f"📡 SIM: {sim}\n" if sim != "-" else "")
            + f"🌍 Регион: {reg}\n\n💰 <b>Цена: {p} ₽</b>\n\n"
            + MSG["product_card_footer"])

    siblings = get_siblings(item)
    colors_available = list(set([s.get("color", "-") for s in siblings if s.get("color", "-") != "-"]))

    kb = InlineKeyboardBuilder()
    
    # 1. 🎨 Другой цвет
    if len(colors_available) > 1:
        cb_data = f"csw_{item['id']}"
        while len(cb_data.encode('utf-8')) > 60: cb_data = cb_data[:-1]
        kb.row(InlineKeyboardButton(text=BTN["other_color"], callback_data=cb_data))
        
    kb.row(InlineKeyboardButton(text=BTN["confirm_order"], callback_data="confirm_order"))
    kb.row(InlineKeyboardButton(text=BTN["magic"], callback_data="magic_tryon"))
    kb.row(InlineKeyboardButton(text=BTN["main_menu"], callback_data="back_to_main"))

    # ФИКС: Берем базовую категорию из памяти, а не название модели
    s = await state.get_data()
    cat = s.get("filters", {}).get("cat", "iphone")

    img_url = item.get('image', '')
    photo_url = img_url if str(img_url).startswith("http") else get_stub(cat, item.get('model_group', ''))

    try:
        if callback.message.photo:
            if photo_url: await send_photo_safe(callback.message, photo_url, text, kb.as_markup(), is_edit=True)
            else: await callback.message.edit_caption(caption=text, reply_markup=kb.as_markup())
        else:
            if photo_url: await send_photo_safe(callback.message, photo_url, text, kb.as_markup(), is_edit=False)
            else: await callback.message.answer(text, reply_markup=kb.as_markup())
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            logger.error(f"Telegram edit error in finalize: {e}")

    await state.update_data(title=item.get('title', ''), product_image_url=photo_url or "")

    if MANAGER_ID:
        user = callback.from_user
        m_text = f"🔥 <b>НОВАЯ ЗАЯВКА!</b>\n<b>Товар:</b> {t}\n<b>Параметры:</b> {mem} / {c} / {sim} / {reg}\n<b>Цена:</b> {p} ₽\n👤 {html.escape(user.full_name)} (@{html.escape(user.username or 'Скрыт')})"
        await callback.bot.send_message(MANAGER_ID, m_text)

@router.callback_query(F.data == "confirm_order")
async def confirm_order(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer("✅ Заказ подтверждён!")
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text=BTN["magic"], callback_data="magic_tryon"))
    kb.row(InlineKeyboardButton(text=BTN["main_menu"], callback_data="back_to_main"))
    try: await callback.message.edit_reply_markup(reply_markup=kb.as_markup())
    except Exception: pass
    await callback.message.answer(MSG["product_order_accepted"])
