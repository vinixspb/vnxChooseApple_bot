# handlers/assistant.py
import html
import logging
import os
import aiohttp
from aiogram import Router, F, types
from aiogram.filters import Command, StateFilter
from aiogram.enums import ChatAction
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder

from states.product_states import ProductSelection
import services.data_store as store
from services.assistant_service import get_assistant_reply, trim_history
from services.messages import MSG, BTN
from keyboards import get_main_menu
from aiogram.filters import Command, StateFilter
from aiogram.enums import ChatAction
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

from states.product_states import ProductSelection

router = Router()
logger = logging.getLogger(__name__)

async def _launch_assistant(target, state: FSMContext):
    await state.clear()
    await state.set_state(ProductSelection.consulting)
    await state.update_data(chat_history=[])
    kb = InlineKeyboardBuilder().row(InlineKeyboardButton(text=BTN["exit_assistant"], callback_data="exit_assistant"))
    msg = target.message if hasattr(target, 'message') else target
    await msg.answer(MSG["assistant_greeting"], reply_markup=kb.as_markup())

@router.message(Command("ai"))
async def cmd_ai(message: types.Message, state: FSMContext):
    await _launch_assistant(message, state)

@router.callback_query(F.data == "start_assistant")
async def start_assistant(callback: types.CallbackQuery, state: FSMContext):
    await _launch_assistant(callback, state)
    await callback.answer()

@router.callback_query(F.data == "exit_assistant")
async def exit_assistant(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.answer(MSG["assistant_exit"], reply_markup=get_main_menu())
    await callback.answer()

@router.message(StateFilter(ProductSelection.consulting), F.text)
async def assistant_message(message: types.Message, state: FSMContext):
    user_text = (message.text or "").strip()
    if not user_text: return

    data = await state.get_data()
    history = data.get("chat_history", [])

    await message.bot.send_chat_action(message.chat.id, ChatAction.TYPING)
    reply = await get_assistant_reply(user_message=user_text, history=history, catalog=store.CATALOG)

    history.extend([{"role": "user", "content": user_text}, {"role": "assistant", "content": reply}])
    await state.update_data(chat_history=trim_history(history))

    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text=BTN["catalog"], callback_data="back_to_main"))
    kb.row(InlineKeyboardButton(text=BTN["exit_assistant"], callback_data="exit_assistant"))
    await message.answer(reply, reply_markup=kb.as_markup())

@router.message(F.voice)
async def handle_voice(message: types.Message, state: FSMContext):
    openai_key = os.getenv("OPENAI_API_KEY", "")
    if not openai_key:
        return await message.answer(MSG["voice_no_key"])

    await message.bot.send_chat_action(message.chat.id, ChatAction.TYPING)
    voice_file = await message.bot.get_file(message.voice.file_id)
    file_bytes = await message.bot.download_file(voice_file.file_path)

    try:
        async with aiohttp.ClientSession() as session:
            data = aiohttp.FormData()
            data.add_field("file", file_bytes, filename="voice.ogg", content_type="audio/ogg")
            data.add_field("model", "whisper-1")
            data.add_field("language", "ru")
            async with session.post(
                "https://api.openai.com/v1/audio/transcriptions",
                headers={"Authorization": f"Bearer {openai_key}"},
                data=data, timeout=aiohttp.ClientTimeout(total=30)
            ) as resp:
                result = await resp.json()
                user_text = result.get("text", "").strip()
    except Exception as e:
        logger.error(f"Whisper error: {e}")
        return await message.answer(MSG["voice_failed"])

    if not user_text: return await message.answer(MSG["voice_failed"])

    await message.answer(MSG["voice_recognized"].format(text=html.escape(user_text)))

    if await state.get_state() != ProductSelection.consulting:
        await state.set_state(ProductSelection.consulting)
        await state.update_data(chat_history=[])

    data = await state.get_data()
    history = data.get("chat_history", [])
    reply = await get_assistant_reply(user_message=user_text, history=history, catalog=store.CATALOG)
    history.extend([{"role": "user", "content": user_text}, {"role": "assistant", "content": reply}])
    await state.update_data(chat_history=trim_history(history))

    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text=BTN["catalog"], callback_data="back_to_main"))
    kb.row(InlineKeyboardButton(text=BTN["exit_assistant"], callback_data="exit_assistant"))
    await message.answer(reply, reply_markup=kb.as_markup())

# Ловим свободный текст вне режимов
@router.message(~StateFilter(ProductSelection.selecting), ~StateFilter(ProductSelection.waiting_for_magic_photo), ~StateFilter(ProductSelection.consulting), F.text)
async def handle_free_text(message: types.Message, state: FSMContext):
    text = (message.text or "").strip()
    if text.startswith("🤖") or text.startswith("🏠") or text.startswith("🔄"): return

    await _launch_assistant(message, state)
    await message.bot.send_chat_action(message.chat.id, ChatAction.TYPING)
    reply = await get_assistant_reply(user_message=text, history=[], catalog=store.CATALOG)
    
    await state.update_data(chat_history=[{"role": "user", "content": text}, {"role": "assistant", "content": reply}])
    kb = InlineKeyboardBuilder().row(InlineKeyboardButton(text=BTN["catalog"], callback_data="back_to_main")).row(InlineKeyboardButton(text=BTN["exit_assistant"], callback_data="exit_assistant"))
    await message.answer(reply, reply_markup=kb.as_markup())
