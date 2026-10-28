"""
Реестр сообщений прайса в канале.

Раньше публикация удаляла все посты и отправляла их заново. Для подписчика
это выглядело как три десятка новых сообщений за раз: звук мы убрали, но
счётчик непрочитанных остаётся — «28 новых сообщений» при каждом обновлении.

Поэтому реестр хранит не просто список ID, а слепок каждого поста: тип
(текст или фото) и отпечаток содержимого. Это позволяет при следующей
публикации не пересоздавать посты, а править их на месте: редактирование
не создаёт ни уведомления, ни непрочитанного, а пост, который не изменился,
не трогается вовсе.

Побочный, но важный эффект: ID сообщений перестают меняться. Ссылки вида
t.me/канал/123 на разделы прайса живут дольше часа, и на них наконец можно
строить навигацию.
"""

import hashlib
import json
import logging
from pathlib import Path
from typing import Dict, List, Optional

from aiogram import Bot

logger = logging.getLogger(__name__)

_IDS_FILE = Path(__file__).parent.parent / "data" / "price_msg_ids.json"

_VERSION = 2


def digest(payload: str) -> str:
    """Короткий отпечаток содержимого — по нему видно, менялся ли пост."""
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def load_manifest() -> Dict:
    """
    Реестр прошлой публикации.

    Старый формат (голый список ID) читается как слоты неизвестного типа:
    по ним нельзя редактировать, поэтому первая публикация после обновления
    пересоздаст посты один раз, а дальше пойдёт правка на месте.
    """
    try:
        raw = json.loads(_IDS_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {"version": _VERSION, "slots": [], "summary_id": None, "nav_id": None}
    except Exception as e:
        logger.warning(f"channel_manager: реестр не прочитан: {e}")
        return {"version": _VERSION, "slots": [], "summary_id": None, "nav_id": None}

    if isinstance(raw, list):
        return {
            "version": _VERSION,
            "slots": [{"kind": "legacy", "id": i, "hash": ""} for i in raw],
            "summary_id": None,
            "nav_id": None,
        }
    raw.setdefault("slots", [])
    raw.setdefault("summary_id", None)
    raw.setdefault("nav_id", None)
    return raw


def save_manifest(slots: List[Dict], summary_id: Optional[int] = None,
                  nav_id: Optional[int] = None) -> None:
    try:
        _IDS_FILE.parent.mkdir(parents=True, exist_ok=True)
        _IDS_FILE.write_text(
            json.dumps({"version": _VERSION, "slots": slots,
                        "summary_id": summary_id, "nav_id": nav_id},
                       ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception as e:
        logger.error(f"channel_manager: реестр не сохранён: {e}")


def message_ids() -> List[int]:
    return [s["id"] for s in load_manifest().get("slots", []) if s.get("id")]


async def delete_messages(bot: Bot, channel_id: str, ids: List[int]) -> int:
    deleted = 0
    for msg_id in ids:
        try:
            await bot.delete_message(channel_id, msg_id)
            deleted += 1
        except Exception:
            pass          # уже удалено вручную или слишком старое — не беда
    return deleted


async def delete_old_price_messages(bot: Bot, channel_id: str) -> int:
    """Полная очистка — используется, когда структура прайса изменилась."""
    ids = message_ids()
    if not ids:
        return 0
    deleted = await delete_messages(bot, channel_id, ids)
    logger.info(f"channel_manager: удалено {deleted}/{len(ids)} старых сообщений")
    return deleted


# Совместимость со старым вызовом
def save_message_ids(ids: List[int]) -> None:
    save_manifest([{"kind": "text", "id": i, "hash": ""} for i in ids])
