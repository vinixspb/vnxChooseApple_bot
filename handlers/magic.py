# handlers/magic.py
import asyncio
import html
import logging
import random
import os
from aiogram import Router, F, types
from aiogram.filters import StateFilter
from aiogram.enums import ChatAction
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder

from states.product_states import ProductSelection
from services.kie_service import KieService
from services.messages import MSG, BTN, MAGIC_MESSAGES
from keyboards import get_main_menu
from utils.media import fetch_image_bytes
from aiogram.filters import Command, StateFilter
from aiogram.enums import ChatAction
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

from states.product_states import ProductSelection


router = Router()
logger = logging.getLogger(__name__)
kie_ai = KieService(os.getenv('KIE_API_KEY'))

@router.callback_query(F.data == "magic_tryon")
async def magic_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer(MSG["magic_ask_photo"])
    await state.set_state(ProductSelection.waiting_for_magic_photo)
    await callback.answer()

async def _animate_magic_msg(msg, stop_event: asyncio.Event):
    pool = list(MAGIC_MESSAGES[1:])
    next_sequential = pool.pop(0)
    shown = set()
    first_tick = True
    while not stop_event.is_set():
        await asyncio.sleep(5)
        if stop_event.is_set(): break
        if first_tick:
            pick = next_sequential
            shown.add(pick)
            first_tick = False
        else:
            remaining = [m for m in pool if m not in shown]
            if not remaining:
                shown.clear()
                remaining = pool
            pick = random.choice(remaining)
            shown.add(pick)
        try: await msg.edit_text(pick)
        except Exception: pass

@router.message(StateFilter(ProductSelection.waiting_for_magic_photo), F.photo)
async def magic_process(message: types.Message, state: FSMContext):
    data = await state.get_data()
    title = data.get("title", "Apple девайс")
    product_image_url = data.get("product_image_url", "")
    
    msg = await message.answer(MAGIC_MESSAGES[0])
    stop_event = asyncio.Event()
    animator = asyncio.create_task(_animate_magic_msg(msg, stop_event))

    try:
        file = await message.bot.get_file(message.photo[-1].file_id)
        user_photo_bytes = (await message.bot.download_file(file.file_path)).read()
        await message.bot.send_chat_action(message.chat.id, ChatAction.UPLOAD_PHOTO)

        product_image_bytes = None
        if product_image_url:
            product_image_bytes = await fetch_image_bytes(product_image_url)

        url = await kie_ai.generate_magic_image(user_photo_bytes, title, product_image_bytes=product_image_bytes)
        if not url: raise ValueError("API returned empty URL")

        stop_event.set(); animator.cancel()

        kb = InlineKeyboardBuilder().row(InlineKeyboardButton(text="🔮 Больше в vnxORACLE", url="https://t.me/vnxORACLE_bot")).row(InlineKeyboardButton(text=BTN["main_menu"], callback_data="back_to_main"))
        await msg.delete()
        await message.answer_photo(url, caption=MSG["magic_result"].format(title=html.escape(title)), reply_markup=kb.as_markup())
    except RuntimeError as e:
        stop_event.set(); animator.cancel()
        await msg.edit_text(MSG["magic_error_credits"] if str(e) == "CREDITS_INSUFFICIENT" else MSG["magic_error_generic"])
    except Exception as e:
        stop_event.set(); animator.cancel()
        logger.error(f"magic_process error: {e}")
        await msg.edit_text(MSG["magic_error_generic"])
    finally:
        await state.clear()

# ФИКС ОШИБКИ ЗДЕСЬ (используем ~StateFilter)
@router.message(F.photo, ~StateFilter(ProductSelection.waiting_for_magic_photo))
async def handle_photo_wrong_state(message: types.Message, state: FSMContext):
    current = await state.get_state()
    if current == ProductSelection.consulting:
        await message.answer(MSG["photo_in_consulting"])
    else:
        await message.answer(MSG["photo_wrong_state"])
