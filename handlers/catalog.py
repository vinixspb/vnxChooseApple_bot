import html
import logging
import os
from aiogram import Router, F, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder

from states.product_states import ProductSelection
from services.sheets_manager import get_data_from_sheet, get_settings
import services.data_store as store
from services.messages import MSG, BTN
from keyboards import get_main_menu, get_dynamic_keyboard
from utils.media import get_stub, send_photo_safe

router = Router()
logger = logging.getLogger(__name__)
MANAGER_ID = os.getenv('MANAGER_ID')

async def load_all():
    store.CATALOG = get_data_from_sheet()
    store.SETTINGS = get_settings()

@router.message(Command("reset"))
async def cmd_reset(message: types.Message, state: FSMContext):
    await state.clear()
    await load_all()
    await message.answer(MSG["reload_done"], reply_markup=get_main_menu())

@router.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
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
    data = [i for i in store.CATALOG if filters["cat"].lower() in str(i.get("model_group", "")).lower()]
    
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
    
    # ─── ИДЕАЛЬНАЯ ЛОГИКА ПРОПУСКОВ ОТ АНДРЕЯ ───
    SKIP_BY_CAT = {
        "iphone":  {"size", "memory_ram"},
        "ipad":    {"memory_ram"},
        "mac":     {"sim"},
        "watch":   {"memory_ram", "sim", "memory"},
        "airpods": {"size", "memory_ram", "sim"}
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
    kb = get_dynamic_keyboard(kb_list, "stg_")

    if stub_url:
        if callback.message.photo: await send_photo_safe(callback.message, stub_url, text, kb, is_edit=True)
        else:
            await callback.message.delete()
            await send_photo_safe(callback.message, stub_url, text, kb, is_edit=False)
    else:
        if callback.message.photo: await callback.message.edit_caption(caption=text, reply_markup=kb)
        else: await callback.message.edit_text(text, reply_markup=kb)

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

async def finalize(callback, item, state):
    def norm(k):
        v = str(item.get(k, '')).strip()
        return html.escape(v) if v else "-"

    t = html.escape(str(item.get('title', '')))
    
    # Красивое форматирование цены (100000 -> 100 000)
    raw_p = str(item.get('price', '0'))
    try:
        p = f"{int(raw_p):,}".replace(",", " ")
    except ValueError:
        p = html.escape(raw_p)

    size, mem, ram, c, sim, reg = [norm(k) for k in ['size', 'memory', 'memory_ram', 'color', 'sim', 'region']]

    text = (f"✅ <b>{t}</b>\n\n"
            + (f"📐 Размер: {size}\n" if size != "-" else "")
            + (f"💾 Память: {mem}\n" if mem != "-" else "")
            + (f"🧠 RAM: {ram}\n" if ram != "-" else "")
            + (f"🎨 Цвет: {c}\n" if c != "-" else "")
            + (f"📡 SIM: {sim}\n" if sim != "-" else "")
            + (f"🌍 Регион: {reg}\n\n" if reg != "-" else "\n")
            + f"💰 <b>Цена: {p} ₽</b>\n\n"
            + MSG["product_card_footer"])

    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text=BTN["confirm_order"], callback_data="confirm_order"))
    kb.row(InlineKeyboardButton(text=BTN["magic"], callback_data="magic_tryon"))
    kb.row(InlineKeyboardButton(text=BTN["main_menu"], callback_data="back_to_main"))

    img_url = item.get('image', '')
    photo_url = img_url if str(img_url).startswith("http") else get_stub(item.get('model_group', ''))

    if callback.message.photo:
        if photo_url: await send_photo_safe(callback.message, photo_url, text, kb.as_markup(), is_edit=True)
        else: await callback.message.edit_caption(caption=text, reply_markup=kb.as_markup())
    else:
        if photo_url: await send_photo_safe(callback.message, photo_url, text, kb.as_markup(), is_edit=False)
        else: await callback.message.answer(text, reply_markup=kb.as_markup())

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
