# services/assistant_service.py
import json
import logging
import re
from typing import List, Dict, Any
import os
import aiohttp

logger = logging.getLogger(__name__)

CLAUDE_MODEL = "anthropic/claude-sonnet-4-5"
MAX_TOKENS = 1024
API_URL = "https://openrouter.ai/api/v1/chat/completions"
MAX_HISTORY = 20

def build_system_prompt(catalog: List[Dict[str, Any]]) -> str:
    available = [
        item for item in catalog
        if item.get("availability", "").lower() == "in stock"
    ]

    catalog_lines = []
    for item in available:
        # ДОБАВЛЯЕМ ID ТОВАРА В ПРАЙС ДЛЯ ИИ
        parts = [
            f"[ID: {item.get('id', '')}]",
            item.get("title", ""),
            f"{item.get('memory', '')}",
            item.get("sim", ""),
            item.get("color", ""),
            f"{item.get('price', '')} ₽",
        ]
        line = " | ".join(p for p in parts if p and p != "-")
        if line:
            catalog_lines.append(f"• {line}")

    catalog_str = "\n".join(catalog_lines) if catalog_lines else "каталог временно недоступен"

    return f"""Ты — AI-Genius, цифровой консультант магазина vnxSHOP. У тебя философия Стива Джобса и сотрудников Apple Genius Bar. 
Ты не впариваешь железки, ты подбираешь инструмент для ума, который изменит жизнь клиента.

═══ АЛГОРИТМ КОНСУЛЬТАЦИИ (СТРОГОЕ ИНТЕРВЬЮ) ═══
Твоя задача — вести диалог шаг за шагом. 
ЗАПРЕЩЕНО рекомендовать конкретные модели и цены, пока не узнаешь ВСЕ 3 факта:
1. Бюджет клиента.
2. Для кого и для каких задач берется устройство.
3. Предыдущий опыт (с какого устройства переходит клиент).

ПРАВИЛО 1: Задавай строго ОДИН уточняющий вопрос за одно сообщение! Не вываливай на клиента кучу текста. Веди его за руку. Диалог уже начат, поэтому НИКОГДА не здоровайся (никаких "Привет!" или "Здравствуйте!"). Сразу переходи к делу.

ПРАВИЛО 2 (ФОРМАТИРОВАНИЕ): Свой вопрос к клиенту (он всегда должен быть в конце сообщения) ОБЯЗАТЕЛЬНО выделяй **жирным шрифтом** с помощью Markdown, чтобы он сразу бросался в глаза. 
Пример правильного форматирования:
Отличный выбор, этот процессор справится с вашими задачами. **Для каких конкретно программ вы планируете использовать Mac?**

ШАГ 4 — РЕКОМЕНДАЦИЯ (ТОЛЬКО ПОСЛЕ СБОРА ВСЕХ ФАКТОВ):
Когда все 3 факта собраны, выбери 1 или максимум 2 идеальных варианта из каталога ниже. 
Опиши, почему именно эта модель идеальна для него.

❗ ВАЖНОЕ ПРАВИЛО ДЛЯ КНОПОК ❗
Когда ты рекомендуешь товары в финале, в самом конце своего ответа ты ОБЯЗАТЕЛЬНО должен написать скрытый технический тег с ID этих товаров.
Формат тега (на новой строке в конце): [RECOMMEND: ID_товара_1, ID_товара_2]
Например: [RECOMMEND: IPHONE15PRO256GBESIM, IPHONE15128GB]

Бот сам превратит этот тег в красивые кнопки для клиента. Тебе не нужно писать "Нажмите на кнопку ниже". Просто вставь тег.

═══ АКТУАЛЬНЫЙ КАТАЛОГ (только в наличии) ═══
{catalog_str}
"""

async def get_assistant_reply(
    user_message: str,
    history: List[Dict[str, str]],
    catalog: List[Dict[str, Any]],
) -> str:
    system_prompt = build_system_prompt(catalog)
    trimmed_history = history[-MAX_HISTORY:] if len(history) > MAX_HISTORY else history
    messages = trimmed_history + [{"role": "user", "content": user_message}]
    or_messages = [{"role": "system", "content": system_prompt}] + messages

    payload = {
        "model": CLAUDE_MODEL,
        "max_tokens": MAX_TOKENS,
        "messages": or_messages,
    }

    api_key = os.environ.get("OPENROUTER_API_KEY_ANDREYAI", "")
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
        "HTTP-Referer": "https://t.me/vnxSHOP_AppleFinder_bot",
        "X-Title": "vnxSHOP Андрей.ai",
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                API_URL, json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=30)
            ) as resp:
                if resp.status == 401: return "⚠️ AI-Genius временно недоступен — техническая пауза. Напиши напрямую!"
                if resp.status == 529: return "😅 Слишком много запросов — попробуй через минуту!"
                data = await resp.json()
                if "error" in data: return "⚠️ Что-то пошло не так. Напиши Андрею напрямую — он поможет!"
                return data["choices"][0]["message"]["content"]
    except Exception as e:
        logger.error(f"assistant_service error: {e}")
        return "⚠️ Временная ошибка. Попробуй ещё раз."

def trim_history(history: List[Dict[str, str]]) -> List[Dict[str, str]]:
    return history[-MAX_HISTORY:] if len(history) > MAX_HISTORY else history
