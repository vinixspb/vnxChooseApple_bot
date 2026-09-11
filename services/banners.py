"""
Баннеры-шапки для блоков прайса.

Картинку не нужно никуда загружать и нигде хостить: владелец отправляет
фото боту, Telegram возвращает file_id, и этот идентификатор навсегда
годится для повторной отправки тем же ботом. Никаких ссылок, которые
могут протухнуть, и никакого стороннего хранилища.

Запасной вариант — прямая ссылка из листа Settings: пригодится, если
картинка уже лежит на сайте и её хочется менять, не трогая бота.
"""

import json
import logging
import os
from pathlib import Path
from typing import Dict, Optional

logger = logging.getLogger(__name__)

_FILE = Path(os.getenv(
    "BANNERS_FILE",
    str(Path(__file__).resolve().parent.parent / "data" / "banners.json"),
))

# Категории, для которых баннер имеет смысл
CATEGORIES = ["mac", "iphone", "ipad", "watch", "airpods", "other"]


def _load() -> Dict[str, str]:
    try:
        return json.loads(_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    except Exception as e:
        logger.warning(f"banners: не прочитан {_FILE}: {e}")
        return {}


def all_banners() -> Dict[str, str]:
    return _load()


def get(category: str) -> Optional[str]:
    """file_id баннера категории, либо None."""
    return _load().get(category)


def save(category: str, file_id: str) -> None:
    data = _load()
    data[category] = file_id
    try:
        _FILE.parent.mkdir(parents=True, exist_ok=True)
        _FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info(f"banners: сохранён баннер для '{category}'")
    except Exception as e:
        logger.error(f"banners: не сохранён баннер '{category}': {e}")


def remove(category: str) -> bool:
    data = _load()
    if category not in data:
        return False
    del data[category]
    try:
        _FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return True
    except Exception as e:
        logger.error(f"banners: не удалён баннер '{category}': {e}")
        return False
