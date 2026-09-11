"""
Анонсы: модели, которые уже представлены, но ещё не в продаже.

Данные лежат в data/coming_soon.json, а не в коде: даты предзаказа и цены
Apple меняются, и править их должно быть так же просто, как положить
картинку в assets/banners.

Пост снимается сам. Как только модель появляется в каталоге в наличии,
анонс перестаёт публиковаться — иначе рядом с реальной ценой в рублях
продолжал бы висеть «скоро в продаже», и это выглядело бы враньём.

Незаполненные поля не показываются вовсе. Дату выхода и цену выдумывать
нельзя: покупатель приходит с ней к продавцу.
"""

import json
import logging
import os
import re
from pathlib import Path
from typing import Dict, List

logger = logging.getLogger(__name__)

_FILE = Path(os.getenv(
    "COMING_SOON_FILE",
    str(Path(__file__).resolve().parent.parent / "data" / "coming_soon.json"),
))


def _normalize(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(name or "").lower())


def entries() -> List[Dict]:
    try:
        data = json.loads(_FILE.read_text(encoding="utf-8"))
        return [e for e in data if e.get("title")]
    except FileNotFoundError:
        return []
    except Exception as e:
        logger.warning(f"coming_soon: {_FILE} не разобран: {e}")
        return []


def pending(in_stock_groups: List[str]) -> List[Dict]:
    """
    Анонсы, которые ещё актуальны — то есть модели нет в наличии.

    Сравнение по нормализованному имени: в каталоге «iPhone 18 Pro»
    может лежать как «18 Pro» или «Apple iPhone 18 Pro».
    """
    on_sale = set()
    for g in in_stock_groups:
        key = _normalize(g)
        on_sale.add(key)
        # «18 Pro» и «iPhone 18 Pro» — одна и та же модель
        on_sale.add(_normalize("iphone " + str(g)))

    out = []
    for e in entries():
        title_key = _normalize(e["title"])
        if title_key in on_sale:
            logger.info(f"coming_soon: «{e['title']}» уже в продаже — анонс снят")
            continue
        out.append(e)
    return out


def format_post(entry: Dict, date_str: str) -> str:
    """Карточка анонса. Пустые поля пропускаются, а не заполняются прочерком."""
    lines = [
        f"🍏 <b>Актуальный прайс — {date_str}</b>",
        f"🔜 <b>{entry.get('status', 'Coming Soon')}</b>",
        "",
        f"📱 <b>{entry['title']}</b>",
    ]

    if entry.get("preorder"):
        lines.append(f"📝 Предзаказ: {entry['preorder']}")
    if entry.get("release"):
        lines.append(f"🚀 В продаже: {entry['release']}")

    prices = entry.get("prices_usd") or {}
    if prices:
        lines += ["", "<b>Цены Apple (США)</b>"]
        rows = [f"└ {cap} — ${value:,}".replace(",", " ") for cap, value in prices.items()]
        lines.append("<blockquote expandable>" + "\n".join(rows) + "</blockquote>")

    if entry.get("note"):
        lines += ["", f"<i>{entry['note']}</i>"]

    if not entry.get("preorder") and not prices:
        lines += ["", "<i>Дата выхода и цены будут объявлены.</i>"]

    lines += ["", "<i>Напишите нам — сообщим, как только появится в наличии.</i>"]
    return "\n".join(lines)
