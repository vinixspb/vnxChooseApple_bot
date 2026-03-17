# handlers/assistant.py
import html
import logging
import os
import re
import aiohttp
from aiogram import Router, F, types
from aiogram.filters import Command, StateFilter
from aiogram.enums import ChatAction
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

from states.product_states import ProductSelection
import services.data_store as store
from services.assistant_service import get_assistant_reply, trim_history
from services.messages import MSG
from keyboards import get_main_menu
# Импортируем finalize из каталога, чтобы кнопка ИИ вела сразу в карточку товара
from handlers.catalog import finalize 

router = Router()
logger = logging.getLogger(__name__)

def extract_recommendations(reply: str, kb: InlineKeyboardBuilder):
    """Ищет тег [RECOMMEND: id1, id2], удаляет его из текста и добавляет инлайн-кнопки."""
    match = re.search(r'\[RECOMMEND:\s*(.+?)\]', reply)
    if match:
        ids_str = match.group(1)
        item_ids = [i.strip() for i in ids_str.split(',')]
        
        # Вырезаем тег из текста ответа (чтобы клиент его не видел)
        reply = reply[:match.start()] + reply[match.end():]
        reply = reply.strip()
        
        for item_id in item_ids:
            # Ищем товар по ID
            item = next((x for x in store.CATALOG if str(x.get("id")) == item_id), None)
            if item:
                # Генерируем красивое название для кнопки
                btn_text = f"👉 Смотреть: {item.get('title')} {item.get('memory', '')}".replace(" -", "").strip()
                
                # Безопасно обрезаем строку, пока она не станет легче 60 байт.
                cb_data = f"rec_{item_id}"
                while len(cb_data.encode('utf-8')) > 60:
                    cb_data = cb_data[:-1]
                    
                kb.row(InlineKeyboardButton(text=btn_text, callback_data=cb_data))
                
    return reply, kb

async def _launch_assistant(target, state: FSMContext):
    data = await state.get_data()
    history = data.get("chat_history", [])
    
    await state.set_state(ProductSelection.consulting)
    kb = InlineKeyboardBuilder().row(InlineKeyboardButton(text="⬅️ Назад в меню", callback_data="ai_pause"))
    msg = target.message if hasattr(target, 'message') else target

    if history:
        # Если история уже есть — приветствуем контекстно и НЕ перезаписываем память
        await msg.answer("🧠 <b>AI-Genius</b>\n\nМы снова в чате! На чём мы остановились?", reply_markup=kb.as_markup())
    else:
        # Лечим амнезию: записываем первое приветствие в историю
        history = [{"role": "assistant", "content": MSG["assistant_greeting"]}]
        await state.update_data(chat_history=history)
        await msg.answer(MSG["assistant_greeting"], reply_markup=kb.as_markup())

# ФИКС: Ограничиваем команду /ai только личными сообщениями
@router.message(F.chat.type == "private", Command("ai"))
async def cmd_ai(message: types.Message, state: FSMContext):
    await _launch_assistant(message, state)

@router.callback_query(F.data == "start_consulting")
async def start_assistant(callback: types.CallbackQuery, state: FSMContext):
    await _launch_assistant(callback, state)
    await callback.answer()

@router.callback_query(F.data == "ai_pause")
async def ai_pause(callback: types.CallbackQuery, state: FSMContext):
    """Скрытая магия: перекидываем в меню, но сохраняем историю диалога в памяти!"""
    await state.set_state(None) 
    await callback.message.answer(
        "🍏 <b>Главное меню</b>\n\n"
        "<i>Кстати, наш диалог сохранен! Вы можете свободно изучать товары, "
        "а когда захотите продолжить общение — просто снова нажмите кнопку ✨ Идеальный подбор (AI).</i> 👇",
        reply_markup=get_main_menu()
    )
    await callback.answer()

@router.callback_query(F.data.startswith("rec_"))
async def handle_recommendation_click(callback: types.CallbackQuery, state: FSMContext):
    item_id_prefix = callback.data.replace("rec_", "")
    item = next((x for x in store.CATALOG if str(x.get("id")).startswith(item_id_prefix)), None)
    
    if item:
        await callback.answer("Загружаю карточку товара...")
        await finalize(callback, item, state)
    else:
        await callback.answer("❌ Товар не найден или уже продан", show_alert=True)

# ФИКС: Ограничиваем режим консультации только личными сообщениями
@router.message(F.chat.type == "private", StateFilter(ProductSelection.consulting), F.text)
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
    reply, kb = extract_recommendations(reply, kb)
    kb.row(InlineKeyboardButton(text="⬅️ Назад в меню", callback_data="ai_pause"))
    
    await message.answer(reply, reply_markup=kb.as_markup())

# ФИКС: Ограничиваем голосовые сообщения только личными сообщениями
@router.message(F.chat.type == "private", F.voice)
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
        await state.update_data(chat_history=[{"role": "assistant", "content": MSG["assistant_greeting"]}])

    data = await state.get_data()
    history = data.get("chat_history", [])
    reply = await get_assistant_reply(user_message=user_text, history=history, catalog=store.CATALOG)
    history.extend([{"role": "user", "content": user_text}, {"role": "assistant", "content": reply}])
    await state.update_data(chat_history=trim_history(history))

    kb = InlineKeyboardBuilder()
    reply, kb = extract_recommendations(reply, kb)
    kb.row(InlineKeyboardButton(text="⬅️ Назад в меню", callback_data="ai_pause"))
    await message.answer(reply, reply_markup=kb.as_markup())

# ФИКС: Ограничиваем свободный ввод текста только личными сообщениями
@router.message(F.chat.type == "private", ~StateFilter(ProductSelection.selecting), ~StateFilter(ProductSelection.waiting_for_magic_photo), ~StateFilter(ProductSelection.consulting), F.text)
async def handle_free_text(message: types.Message, state: FSMContext):
    text = (message.text or "").strip()
    if text.startswith("🤖") or text.startswith("🏠") or text.startswith("🔄") or text.startswith("✨"): return

    await _launch_assistant(message, state)
    await message.bot.send_chat_action(message.chat.id, ChatAction.TYPING)
    reply = await get_assistant_reply(user_message=text, history=[], catalog=store.CATALOG)
    
    await state.update_data(chat_history=[{"role": "user", "content": text}, {"role": "assistant", "content": reply}])
    
    kb = InlineKeyboardBuilder()
    reply, kb = extract_recommendations(reply, kb)
    kb.row(InlineKeyboardButton(text="⬅️ Назад в меню", callback_data="ai_pause"))
    await message.answer(reply, reply_markup=kb.as_markup())
