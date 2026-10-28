"""
Пост-навигатор: кнопки-ссылки на разделы прайса.

Канал длинный, и пролистать его до нужного раздела тяжело. Навигатор
решает это одним закреплённым постом с кнопками.

Почему именно ссылки, а не обычные кнопки с обратным вызовом: пост
в канале общий для всех подписчиков. Нажатие изменило бы его сразу у
всех, поэтому для личной навигации такие кнопки не годятся. Ссылки
вида t.me/канал/<id> открывают нужное сообщение лично у нажавшего.

Это стало возможно только после перехода на правку постов на месте:
раньше ID менялись при каждой публикации, и ссылки жили меньше часа.

Состав кнопок лежит в data/navigator.json — менять его можно без правки
кода. Кнопка, для которой не нашлось ни одного блока, не рисуется:
мёртвая ссылка хуже отсутствующей.
"""

import json
import logging
import os
import re
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

_CONFIG = Path(os.getenv(
    "NAVIGATOR_FILE",
    str(Path(__file__).resolve().parent.parent / "data" / "navigator.json"),
))

# Публичное имя канала для ссылок. Если не задано, берём из PRICE_CHANNEL_ID,
# когда он указан как @username.
_CHANNEL_USERNAME = os.getenv("PRICE_CHANNEL_USERNAME", "").lstrip("@")


def config() -> Dict:
    try:
        return json.loads(_CONFIG.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except Exception as e:
        logger.warning(f"navigator: {_CONFIG} не разобран: {e}")
        return {}


def enabled() -> bool:
    return bool(config().get("rows"))


def _channel_base(channel_id: str) -> Optional[str]:
    """
    Основа ссылки на сообщение канала.

    У публичного канала это t.me/<имя>, у приватного — t.me/c/<внутренний id>,
    и такая ссылка открывается только у подписчиков.
    """
    if _CHANNEL_USERNAME:
        return f"https://t.me/{_CHANNEL_USERNAME}"

    cid = str(channel_id or "").strip()
    if cid.startswith("@"):
        return f"https://t.me/{cid[1:]}"

    m = re.match(r"^-100(\d+)$", cid)
    if m:
        return f"https://t.me/c/{m.group(1)}"

    logger.warning(
        "navigator: не удалось собрать ссылки на канал — "
        "задай PRICE_CHANNEL_USERNAME в .env"
    )
    return None


def build(channel_id: str, anchors: Dict[str, int],
          bot_username: str = "") -> tuple:
    """
    Текст и клавиатура навигатора.

    anchors — карта «якорь → message_id», собранная при публикации.
    Возвращает (текст, разметка) либо (текст, None), если ни одной
    рабочей кнопки не осталось.
    """
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

    cfg = config()
    rows_cfg = cfg.get("rows") or []
    base = _channel_base(channel_id)

    keyboard: List[List[InlineKeyboardButton]] = []
    dropped: List[str] = []

    for row_cfg in rows_cfg:
        row: List[InlineKeyboardButton] = []
        for item in row_cfg:
            text = str(item.get("text", "")).strip()
            if not text:
                continue
            url = _resolve(item, base, anchors, bot_username)
            if url:
                row.append(InlineKeyboardButton(text=text, url=url))
            else:
                dropped.append(text)
        if row:
            keyboard.append(row)

    if dropped:
        logger.info("navigator: нет блока для кнопок — " + ", ".join(dropped))

    title = cfg.get("title") or "🍏 <b>Навигация по прайсу</b>"
    if not keyboard:
        return title, None
    return title, InlineKeyboardMarkup(inline_keyboard=keyboard)


def _resolve(item: Dict, base: Optional[str], anchors: Dict[str, int],
             bot_username: str) -> Optional[str]:
    """Первая сработавшая ссылка: якорь на пост, затем бот, затем прямой url."""
    if base:
        for anchor in item.get("anchors") or []:
            msg_id = anchors.get(anchor)
            if msg_id:
                return f"{base}/{msg_id}"

    start = str(item.get("start", "")).strip()
    if start and bot_username:
        return f"https://t.me/{bot_username}?start={start}"

    url = str(item.get("url", "")).strip()
    return url or None


def digest_of(title: str, markup) -> str:
    """Отпечаток навигатора — по нему видно, менялись ли ссылки."""
    from services.channel_manager import digest

    rows = []
    if markup:
        for row in markup.inline_keyboard:
            rows.append([(b.text, b.url) for b in row])
    return digest(title + json.dumps(rows, ensure_ascii=False))
