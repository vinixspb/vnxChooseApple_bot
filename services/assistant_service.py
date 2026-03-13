"""
Андрей.ai — цифровая субличность Андрея.
Свободный чат-консультант по технике Apple.

Архитектура:
- Системный промпт задаёт личность Андрея и алгоритм продажи
- История диалога хранится в FSM (не в API — мы stateless)
- При каждом запросе в промпт подмешивается актуальный каталог
- Используем Claude через Anthropic API (встроен в среду)
"""

import json
import logging
import re
from typing import List, Dict, Any

import os
import aiohttp

logger = logging.getLogger(__name__)

# ── Константы ────────────────────────────────────────────────────────────────
CLAUDE_MODEL    = "anthropic/claude-sonnet-4-5"
MAX_TOKENS      = 1024
API_URL         = "https://openrouter.ai/api/v1/chat/completions"
MAX_HISTORY     = 20   # сообщений (10 пар вопрос/ответ) — чтобы не раздувать контекст


# ── Системный промпт — личность Андрея ───────────────────────────────────────
def build_system_prompt(catalog: List[Dict[str, Any]]) -> str:
    """
    Строим системный промпт с актуальным каталогом.
    Каталог форматируем компактно: только то что нужно для рекомендации.
    """

    # Компактный прайс: только модель, память, sim, цвет, цена (в наличии)
    available = [
        item for item in catalog
        if item.get("availability", "").lower() == "in stock"
    ]

    catalog_lines = []
    for item in available:
        parts = [
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

    return f"""Ты — Андрей.ai, цифровая субличность Андрея — владельца vnxSHOP и эксперта по Apple с многолетним стажем. У Андрея 3000 постоянных клиентов которые ему лично доверяют. Ты — его цифровая копия: помогаешь выбрать технику так же как Андрей делает это лично.

═══ ТВОЯ ЛИЧНОСТЬ ═══
• Говори живо, тепло, с лёгким юмором — как Андрей в реальном разговоре
• Иногда мягко ссылайся на себя: «я — цифровой Андрей», «оригинал сейчас занят разбором поставки, но я знаю всё то же самое 😄», «Андрей бы сказал именно это»
• Никогда не будь роботом или занудой. Не перечисляй характеристики как Wikipedia
• Отвечай коротко — 2-4 предложения максимум если не просят подробнее
• Используй эмодзи умеренно — как в обычной переписке с другом

═══ АЛГОРИТМ ПРОДАЖИ (строго по шагам) ═══

ШАГ 1 — БЮДЖЕТ (всегда первый вопрос):
Мягко выясни бюджет. Пока не понял рамки — не предлагай конкретные модели с ценами.
Пример: «Первым делом — цифровой Андрей всегда спрашивает про бюджет 😄 Примерно на какую сумму рассчитываем?»

ШАГ 2 — КОМУ И ДЛЯ ЧЕГО:
Выясни кому берут устройство (себе, ребёнку, в подарок) и для каких задач.

ШАГ 3 — ПРЕДЫДУЩАЯ МОДЕЛЬ (ключевой вопрос):
Узнай с какого устройства переходит клиент.

ЗОЛОТОЕ ПРАВИЛО АНДРЕЯ:
• Переходит с Pro (любой версии) → рекомендуй актуальный Pro. Он привык к уровню — не даём деградировать
• Переходит с базового (12, 13, 14, 15 не-Pro) → рекомендуй новый базовый. Не пытайся продать Pro без явного запроса
• Переходит с Android → сначала выясни бюджет и ожидания, потом решай
• Берут первый iPhone или ребёнку → базовый или SE если бюджет позволяет

ШАГ 4 — РЕКОМЕНДАЦИЯ:
Предложи 1-2 варианта строго из каталога ниже. Назови точную цену. Объясни почему именно это — одним живым предложением.

ШАГ 5 — ПЕРЕХОД К ЗАКАЗУ:
После рекомендации предложи оформить. Скажи что-то вроде: «Нажми /start и выбери модель в каталоге — или напиши Андрею напрямую, он оформит сам»

═══ ВАЖНЫЕ ОГРАНИЧЕНИЯ ═══
• Предлагай ТОЛЬКО товары из каталога ниже. Если нужной модели нет — честно скажи
• Никогда не придумывай цены — только из каталога
• Если клиент уходит от темы или просит что-то не связанное с Apple — мягко верни к выбору техники
• Если спрашивают про конкурентов (Samsung, Xiaomi и т.д.) — не ругай, но мягко объясни преимущества экосистемы Apple

═══ АКТУАЛЬНЫЙ КАТАЛОГ (только в наличии) ═══
{catalog_str}
"""


# ── Основная функция ──────────────────────────────────────────────────────────
async def get_assistant_reply(
    user_message: str,
    history: List[Dict[str, str]],
    catalog: List[Dict[str, Any]],
) -> str:
    """
    Отправляет сообщение пользователя в Claude с историей диалога.

    history — список {"role": "user"/"assistant", "content": "..."}
    Возвращает текст ответа или сообщение об ошибке.
    """

    system_prompt = build_system_prompt(catalog)

    # Обрезаем историю если слишком длинная
    trimmed_history = history[-MAX_HISTORY:] if len(history) > MAX_HISTORY else history

    # Добавляем текущее сообщение
    messages = trimmed_history + [{"role": "user", "content": user_message}]

    # OpenRouter использует формат OpenAI: system как первое сообщение с role="system"
    or_messages = [{"role": "system", "content": system_prompt}] + messages

    payload = {
        "model":      CLAUDE_MODEL,
        "max_tokens": MAX_TOKENS,
        "messages":   or_messages,
    }

    api_key = os.environ.get("OPENROUTER_API_KEY_ANDREYAI", "")
    headers = {
        "Content-Type":  "application/json",
        "Authorization": f"Bearer {api_key}",
        "HTTP-Referer":  "https://t.me/vnxSHOP_AppleFinder_bot",
        "X-Title":       "vnxSHOP Андрей.ai",
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                API_URL,
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                if resp.status == 401:
                    logger.error("Claude API: неверный ключ")
                    return "⚠️ Цифровой Андрей временно недоступен — техническая пауза. Напиши напрямую!"
                if resp.status == 529:
                    return "😅 Слишком много запросов к Андрею.ai — попробуй через минуту!"

                data = await resp.json()

                if "error" in data:
                    logger.error(f"Claude API error: {data['error']}")
                    return "⚠️ Что-то пошло не так. Напиши Андрею напрямую — он поможет!"

                return data["choices"][0]["message"]["content"]

    except aiohttp.ClientTimeout:
        return "⏳ Андрей.ai думает слишком долго... Попробуй ещё раз!"
    except Exception as e:
        logger.error(f"assistant_service error: {e}")
        return "⚠️ Временная ошибка. Попробуй ещё раз или напиши Андрею напрямую."


def trim_history(history: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """Обрезает историю до MAX_HISTORY последних сообщений."""
    return history[-MAX_HISTORY:] if len(history) > MAX_HISTORY else history
