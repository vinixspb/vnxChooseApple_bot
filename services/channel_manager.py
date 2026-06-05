"""Tracks price message IDs in the channel — allows deleting old ones before republish."""
import json
import logging
from pathlib import Path

from aiogram import Bot

logger = logging.getLogger(__name__)

_IDS_FILE = Path(__file__).parent.parent / "data" / "price_msg_ids.json"


def load_message_ids() -> list[int]:
    try:
        return json.loads(_IDS_FILE.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def save_message_ids(ids: list[int]) -> None:
    _IDS_FILE.parent.mkdir(exist_ok=True)
    _IDS_FILE.write_text(json.dumps(ids))


async def delete_old_price_messages(bot: Bot, channel_id: str) -> int:
    ids = load_message_ids()
    if not ids:
        return 0
    deleted = 0
    for msg_id in ids:
        try:
            await bot.delete_message(channel_id, msg_id)
            deleted += 1
        except Exception:
            pass
    save_message_ids([])
    logger.info(f"channel_manager: удалено {deleted}/{len(ids)} старых сообщений")
    return deleted
