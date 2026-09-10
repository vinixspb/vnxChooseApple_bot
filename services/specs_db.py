"""
База технических характеристик Apple.

Зачем. Ассистент получал в промпте только каталог: модель, память, цена.
На вопрос «какой процессор в 16 Pro» ответить было нечем — и языковая модель
отвечала правдоподобной выдумкой. Для магазина это хуже молчания: клиент
принимает решение по неверной цифре, а продавец узнаёт об этом при возврате.

База закрывает дыру с двух сторон:
  1. даёт ассистенту факты в промпте,
  2. позволяет прямо запретить ему отвечать про характеристики,
     которых в базе нет.

Хранилище — SQLite, отдельно от таблицы Sheets. Источник правды —
data/specs/*.json: он лежит в git, поэтому любое изменение характеристик
видно в истории и проходит ревью, а не появляется молча в бинарном файле.
База пересобирается из JSON автоматически, когда файл новее её.

ЧЕСТНОСТЬ ДАННЫХ. У каждой модели есть поле source:
  apple.com — сверено со страницей характеристик Apple
  newsroom  — из анонса, заполнены только объявленные поля
  seed      — заполнено при создании базы, требует сверки
  unknown   — характеристик нет
Пустое поле означает «не знаем», и ассистент обязан отвечать именно так.
Заполнять пропуски догадкой нельзя: неверная характеристика в базе опаснее
отсутствующей, потому что произносится уверенно.
"""

import json
import logging
import os
import re
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_ROOT      = Path(__file__).resolve().parent.parent
_JSON_DIR  = Path(os.getenv("SPECS_JSON_DIR", str(_ROOT / "data" / "specs")))
_DB_PATH   = Path(os.getenv("SPECS_DB", str(_ROOT / "data" / "specs.sqlite3")))

# Поля характеристик и их подписи для человека
_FIELDS: List[tuple] = [
    ("year",            "Год выхода",        ""),
    ("chip",            "Процессор",         ""),
    ("ram_gb",          "Оперативная память", " ГБ"),
    ("display_inches",  "Экран",             "″"),
    ("display_tech",    "Технология экрана", ""),
    ("refresh_hz",      "Частота обновления", " Гц"),
    ("resolution",      "Разрешение",        ""),
    ("brightness_nits", "Яркость",           " нит"),
    ("body_material",   "Корпус",            ""),
    ("camera_main_mp",  "Основная камера",   " Мп"),
    ("camera_ultra_mp", "Сверхширокоугольная", " Мп"),
    ("camera_tele_mp",  "Телефото",          " Мп"),
    ("tele_zoom",       "Зум",               ""),
    ("camera_front_mp", "Фронтальная камера", " Мп"),
    ("video_max",       "Видео",             ""),
    ("battery_video_h", "Видео от батареи",  " ч"),
    ("connector",       "Разъём",            ""),
    ("sim",             "SIM",               ""),
    ("water",           "Защита",            ""),
    ("weight_g",        "Вес",               " г"),
    ("dimensions_mm",   "Габариты",          " мм"),
    ("form_factor",     "Форм-фактор",       ""),
]

_TEXT_COLS = {
    "chip", "display_tech", "resolution", "body_material", "tele_zoom",
    "video_max", "connector", "sim", "water", "dimensions_mm",
    "form_factor", "note", "source", "storage_gb", "colors",
}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS specs (
    model            TEXT PRIMARY KEY,
    model_key        TEXT NOT NULL,
    year             INTEGER,
    chip             TEXT,
    ram_gb           INTEGER,
    display_inches   REAL,
    display_tech     TEXT,
    refresh_hz       INTEGER,
    resolution       TEXT,
    brightness_nits  INTEGER,
    body_material    TEXT,
    camera_main_mp   INTEGER,
    camera_ultra_mp  INTEGER,
    camera_tele_mp   INTEGER,
    tele_zoom        TEXT,
    camera_front_mp  INTEGER,
    video_max        TEXT,
    battery_video_h  INTEGER,
    connector        TEXT,
    sim              TEXT,
    water            TEXT,
    weight_g         INTEGER,
    dimensions_mm    TEXT,
    form_factor      TEXT,
    storage_gb       TEXT,
    colors           TEXT,
    note             TEXT,
    source           TEXT
);
CREATE INDEX IF NOT EXISTS idx_specs_key ON specs(model_key);
"""

_COLUMNS = [
    "model", "model_key", "year", "chip", "ram_gb", "display_inches",
    "display_tech", "refresh_hz", "resolution", "brightness_nits",
    "body_material", "camera_main_mp", "camera_ultra_mp", "camera_tele_mp",
    "tele_zoom", "camera_front_mp", "video_max", "battery_video_h",
    "connector", "sim", "water", "weight_g", "dimensions_mm",
    "form_factor", "storage_gb", "colors", "note", "source",
]

_APPLE_PREFIX_RE = re.compile(r"^apple\s+", re.IGNORECASE)


def normalize(name: str) -> str:
    """
    Ключ поиска: «Apple iPhone 16 Pro Max» и «16 pro max» → «iphone16promax».

    Поставщики, каталог и покупатели пишут одну и ту же модель по-разному,
    поэтому сравнивать сырые строки бессмысленно.
    """
    s = _APPLE_PREFIX_RE.sub("", str(name or "").strip().lower())
    s = s.replace("+", " plus ")
    s = re.sub(r"[^a-z0-9а-я]+", "", s)
    # Голый номер модели — это iPhone: «16 Pro» → «iphone16pro»
    if re.match(r"^\d", s):
        s = "iphone" + s
    return s


# ── Сборка базы ──────────────────────────────────────────────────────────────

def _connect() -> sqlite3.Connection:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _json_files() -> List[Path]:
    if not _JSON_DIR.exists():
        return []
    return sorted(_JSON_DIR.glob("*.json"))


def _needs_rebuild() -> bool:
    """База устарела, если её нет или какой-то JSON новее неё."""
    if not _DB_PATH.exists():
        return True
    db_mtime = _DB_PATH.stat().st_mtime
    return any(f.stat().st_mtime > db_mtime for f in _json_files())


def rebuild() -> Dict[str, int]:
    """Пересобирает базу из JSON. Возвращает счётчики."""
    files = _json_files()
    if not files:
        logger.warning(f"specs_db: нет файлов характеристик в {_JSON_DIR}")
        return {"models": 0, "files": 0}

    rows: List[tuple] = []
    for path in files:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            logger.error(f"specs_db: {path.name} не разобран: {e}")
            continue

        for entry in data:
            model = str(entry.get("model", "")).strip()
            if not model:
                continue
            values = [model, normalize(model)]
            for col in _COLUMNS[2:]:
                v = entry.get(col)
                if isinstance(v, (list, dict)):
                    v = json.dumps(v, ensure_ascii=False)
                values.append(v)
            rows.append(tuple(values))

    conn = _connect()
    try:
        conn.executescript(_SCHEMA)
        conn.execute("DELETE FROM specs")
        placeholders = ",".join("?" * len(_COLUMNS))
        conn.executemany(
            f"INSERT OR REPLACE INTO specs ({','.join(_COLUMNS)}) VALUES ({placeholders})",
            rows,
        )
        conn.commit()
    finally:
        conn.close()

    logger.info(f"specs_db: загружено моделей: {len(rows)} из файлов: {len(files)}")
    return {"models": len(rows), "files": len(files)}


def ensure_ready() -> None:
    """Пересобирает базу, если JSON изменился. Вызывается при старте бота."""
    try:
        if _needs_rebuild():
            rebuild()
    except Exception as e:
        logger.error(f"specs_db.ensure_ready: {e}")


# ── Чтение ───────────────────────────────────────────────────────────────────

def get(model_name: str) -> Optional[Dict[str, Any]]:
    """Характеристики модели, либо None. Точное совпадение по ключу."""
    key = normalize(model_name)
    if not key:
        return None
    try:
        conn = _connect()
        try:
            row = conn.execute(
                "SELECT * FROM specs WHERE model_key = ?", (key,)
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()
    except Exception as e:
        logger.error(f"specs_db.get({model_name}): {e}")
        return None


def find(model_name: str) -> Optional[Dict[str, Any]]:
    """
    Поиск с запасным вариантом: точное совпадение, иначе самый длинный
    ключ, с которого начинается запрос.

    Нужно потому, что в каталоге лежит «Apple iPhone 16 Pro Max 256GB
    Black Titanium», а в базе — «iPhone 16 Pro Max». Берём самый длинный
    совпавший ключ, иначе «16 Pro Max» нашло бы «iPhone 16».
    """
    exact = get(model_name)
    if exact:
        return exact

    key = normalize(model_name)
    if not key:
        return None

    # Короткое имя без слова iPhone: «Duo», «SE», «Air».
    # Владелец пишет /specs Duo, а в базе ключ iphoneduo.
    if not key.startswith("iphone"):
        by_family = get("iPhone " + model_name)
        if by_family:
            return by_family
    try:
        conn = _connect()
        try:
            rows = conn.execute("SELECT * FROM specs").fetchall()
        finally:
            conn.close()
    except Exception as e:
        logger.error(f"specs_db.find({model_name}): {e}")
        return None

    best = None
    for row in rows:
        k = row["model_key"]
        if key.startswith(k) and (best is None or len(k) > len(best["model_key"])):
            best = row
    return dict(best) if best else None


def all_models() -> List[Dict[str, Any]]:
    try:
        conn = _connect()
        try:
            rows = conn.execute(
                "SELECT * FROM specs ORDER BY year DESC, model"
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()
    except Exception as e:
        logger.error(f"specs_db.all_models: {e}")
        return []


# Поля, осмысленные не для каждой модели: их пустота — не пробел в данных.
# form_factor заполняется только у необычных корпусов (складной Duo),
# иначе он числился бы «пропуском» у всех остальных моделей и зашумлял отчёт.
_OPTIONAL_FIELDS = {"form_factor"}


def _gap_fields() -> List[tuple]:
    return [(f, label, u) for f, label, u in _FIELDS if f not in _OPTIONAL_FIELDS]


def filled_fields(row: Dict[str, Any]) -> int:
    """Сколько характеристик реально заполнено — для отчётов о полноте."""
    return sum(1 for f, _, _ in _gap_fields() if row.get(f) not in (None, ""))


def missing_fields(row: Dict[str, Any]) -> List[str]:
    """Названия незаполненных характеристик, без необязательных."""
    return [label for f, label, _ in _gap_fields() if row.get(f) in (None, "")]


# ── Форматирование ───────────────────────────────────────────────────────────

def _fmt_value(field: str, value: Any, unit: str) -> str:
    if field == "display_inches":
        return f"{value}{unit}"
    return f"{value}{unit}"


def format_card(row: Dict[str, Any]) -> str:
    """Полная карточка модели для команды /specs."""
    lines = [f"<b>{row['model']}</b>"]

    for field, label, unit in _FIELDS:
        v = row.get(field)
        if v in (None, ""):
            continue
        lines.append(f"· {label}: {_fmt_value(field, v, unit)}")

    storage = row.get("storage_gb")
    if storage:
        try:
            gb = json.loads(storage)
            pretty = ", ".join(f"{g // 1024} ТБ" if g >= 1024 else f"{g} ГБ" for g in gb)
            lines.append(f"· Объёмы памяти: {pretty}")
        except Exception:
            pass

    colors = row.get("colors")
    if colors:
        try:
            lines.append("· Цвета: " + ", ".join(json.loads(colors)))
        except Exception:
            pass

    if row.get("note"):
        lines.append(f"\n<i>{row['note']}</i>")

    missing = missing_fields(row)
    if missing:
        lines.append(f"\n⚠️ Нет данных: {', '.join(missing[:8])}")

    src = {
        "apple.com": "сверено с apple.com",
        "newsroom":  "из анонса Apple",
        "seed":      "заполнено при создании базы, требует сверки",
        "unknown":   "характеристик нет",
    }.get(row.get("source", ""), row.get("source", ""))
    lines.append(f"\n<code>источник: {src}</code>")

    return "\n".join(lines)


def format_for_prompt(row: Dict[str, Any]) -> str:
    """
    Компактная строка для системного промпта ассистента.
    Только заполненные поля — пустые не упоминаем, чтобы модели
    нечего было «дополнить» по смыслу.
    """
    parts = []
    if row.get("chip"):            parts.append(f"чип {row['chip']}")
    if row.get("ram_gb"):          parts.append(f"ОЗУ {row['ram_gb']}ГБ")
    if row.get("display_inches"):
        d = f"экран {row['display_inches']}\""
        if row.get("refresh_hz"):  d += f" {row['refresh_hz']}Гц"
        if row.get("display_tech"): d += f" {row['display_tech']}"
        parts.append(d)
    if row.get("body_material"):   parts.append(f"корпус {row['body_material']}")

    cams = []
    if row.get("camera_main_mp"):  cams.append(f"осн {row['camera_main_mp']}Мп")
    if row.get("camera_ultra_mp"): cams.append(f"ширик {row['camera_ultra_mp']}Мп")
    if row.get("camera_tele_mp"):  cams.append(f"теле {row['camera_tele_mp']}Мп")
    if row.get("tele_zoom"):       cams.append(f"зум {row['tele_zoom']}")
    if cams:                       parts.append("камеры: " + ", ".join(cams))
    if row.get("camera_front_mp"): parts.append(f"фронт {row['camera_front_mp']}Мп")

    if row.get("battery_video_h"): parts.append(f"видео {row['battery_video_h']}ч")
    if row.get("weight_g"):        parts.append(f"вес {row['weight_g']}г")
    if row.get("connector"):       parts.append(row["connector"])
    if row.get("water"):           parts.append(row["water"])
    if row.get("year"):            parts.append(str(row["year"]))

    return f"{row['model']}: " + "; ".join(parts) if parts else f"{row['model']}: данных нет"


def specs_block(model_groups: List[str], limit: int = 40) -> str:
    """
    Блок характеристик для промпта — только модели, которые есть в наличии.

    Каталог большой, а характеристики нужны лишь по тому, что реально можно
    купить. Модели без данных перечисляются отдельным списком: ассистент
    должен знать, о чём ему запрещено рассуждать.
    """
    seen: Dict[str, Dict[str, Any]] = {}
    unknown: List[str] = []

    for group in model_groups:
        row = find(group)
        if row:
            seen.setdefault(row["model"], row)
        else:
            name = _APPLE_PREFIX_RE.sub("", str(group).strip())
            if name and name not in unknown:
                unknown.append(name)

    lines = []
    for row in list(seen.values())[:limit]:
        lines.append("• " + format_for_prompt(row))

    out = "\n".join(lines) if lines else "нет данных"
    if unknown:
        out += ("\n\nХАРАКТЕРИСТИК НЕТ В БАЗЕ (о них говорить нельзя): "
                + ", ".join(unknown[:25]))
    return out
