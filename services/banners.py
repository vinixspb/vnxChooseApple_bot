"""
Баннеры-шапки для блоков прайса.

Три источника, по убыванию удобства:

1. Файл в репозитории — assets/banners/<ключ>.jpg
   Лучший вариант. Картинка едет вместе с кодом через git pull, её видно
   в истории, она не зависит от того, публичный репозиторий или приватный,
   и нигде не выкладывается публично. Telegram получает файл напрямую.

2. file_id, сохранённый командой /banner
   Когда картинку проще отправить боту, чем коммитить. Идентификатор
   не протухает, но фото при этом видно в том чате, где его отправили.

3. Прямая ссылка из листа Settings
   Если баннер уже лежит на сайте.

Ключи именуют блок прайса, а не только категорию: «macbookair13»,
«macbookair15», «iphone». Для блока перебирается цепочка от частного
к общему — свой баннер у 13-дюймовых, иначе общий для Air, иначе
общий для Mac. Так можно поставить одну картинку на все маки и не
заводить четыре одинаковых.
"""

import json
import logging
import os
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parent.parent

# Картинки в репозитории — основной способ
ASSETS_DIR = Path(os.getenv("BANNERS_ASSETS_DIR", str(_ROOT / "assets" / "banners")))

# Картинки, присланные боту (file_id). Не в git — идентификаторы привязаны
# к конкретному боту и в чужой установке бесполезны.
_FILE = Path(os.getenv(
    "BANNERS_FILE",
    str(_ROOT / "data" / "banners.json"),
))

_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp")

# Ключи, которые имеет смысл заводить. Список подсказочный: команда
# принимает любой ключ, чтобы не пришлось править код под новую линейку.
KNOWN_KEYS = [
    "macbookair13", "macbookair15", "macbookair",
    "macbookpro14", "macbookpro16", "macbookpro",
    "mac", "iphone", "ipad", "watch", "airpods", "other",
]


def slug(name: str) -> str:
    """«MacBook Air 13″» → «macbookair13». Ключ не зависит от написания."""
    return re.sub(r"[^a-z0-9]+", "", str(name or "").lower())


# ── file_id, присланные боту ─────────────────────────────────────────────────

def _load() -> Dict[str, str]:
    try:
        return json.loads(_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    except Exception as e:
        logger.warning(f"banners: не прочитан {_FILE}: {e}")
        return {}


def all_file_ids() -> Dict[str, str]:
    return _load()


def save(key: str, file_id: str) -> None:
    data = _load()
    data[slug(key)] = file_id
    try:
        _FILE.parent.mkdir(parents=True, exist_ok=True)
        _FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info(f"banners: сохранён баннер '{key}'")
    except Exception as e:
        logger.error(f"banners: не сохранён баннер '{key}': {e}")


def remove(key: str) -> bool:
    data = _load()
    k = slug(key)
    if k not in data:
        return False
    del data[k]
    try:
        _FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return True
    except Exception as e:
        logger.error(f"banners: не удалён баннер '{key}': {e}")
        return False


# ── Файлы в репозитории ──────────────────────────────────────────────────────

def asset_path(key: str) -> Optional[Path]:
    """Путь к картинке в assets/banners, если она там есть."""
    k = slug(key)
    if not ASSETS_DIR.exists():
        return None
    for ext in _EXTENSIONS:
        p = ASSETS_DIR / f"{k}{ext}"
        if p.is_file():
            return p
    return None


def list_assets() -> List[str]:
    if not ASSETS_DIR.exists():
        return []
    return sorted(
        p.stem for p in ASSETS_DIR.iterdir()
        if p.is_file() and p.suffix.lower() in _EXTENSIONS
    )


# ── Разрешение источника ─────────────────────────────────────────────────────

def resolve(keys: List[str]) -> Optional[Tuple[str, str, object]]:
    """
    Первый найденный баннер по цепочке ключей от частного к общему.

    Возвращает (ключ, тип, значение), где тип — «file», «id» или «url».
    None, если баннера нет ни по одному ключу: это нормально, блок
    просто выйдет без картинки.
    """
    ids = _load()

    for key in keys:
        k = slug(key)
        if not k:
            continue

        path = asset_path(k)
        if path:
            return (k, "file", path)

        if k in ids:
            return (k, "id", ids[k])

        url = _settings_url(k)
        if url:
            return (k, "url", url)

    return None


def _settings_url(key: str) -> str:
    """Ссылка из листа Settings по ключу вида MACBOOKAIR13_HEADER_IMAGE."""
    try:
        import services.data_store as store
        val = str(store.SETTINGS.get(f"{key.upper()}_HEADER_IMAGE", "")).strip()
        if val:
            return val
    except Exception:
        pass
    return os.getenv(f"{key.upper()}_HEADER_IMAGE", "")
