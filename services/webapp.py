"""
Mini App: каталог внутри Telegram.

Канал — витрина: его листают, но в нём нельзя искать и фильтровать.
Mini App закрывает именно это: одна кнопка открывает каталог с поиском
по модели, фильтрами по памяти и цене, и сразу ведёт к заказу.

Данные те же, что уходят в канал, — из той же таблицы и через те же
фильтры. Иначе получилось бы два разных прайса, и расхождение между ними
заметил бы покупатель, а не мы.

Устройство: лёгкий сервер на aiohttp слушает локальный порт, снаружи его
публикует nginx с сертификатом. Telegram открывает Mini App только по HTTPS
и только по адресу, который задан в WEBAPP_URL. Пока адрес не задан, кнопка
в боте не показывается, а сервер не поднимается — ничего не ломается.
"""

import json
import logging
import os
from pathlib import Path
from typing import Dict, List

from aiohttp import web

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parent.parent
_PAGE = _ROOT / "webapp" / "index.html"

# Публичный адрес Mini App (https://...). Пусто — приложение выключено.
PUBLIC_URL = os.getenv("WEBAPP_URL", "").strip()

_HOST = os.getenv("WEBAPP_HOST", "127.0.0.1")
_PORT = int(os.getenv("WEBAPP_PORT", "8081"))

# Телефон менеджера для кнопки «Написать»
MANAGER_USERNAME = os.getenv("MANAGER_USERNAME", "").lstrip("@")


def enabled() -> bool:
    return bool(PUBLIC_URL)


def _catalog_payload() -> Dict:
    """
    Каталог для приложения.

    Берём ровно то, что публикуется в канал: тот же отбор «в наличии»,
    та же чистка от чужих брендов, та же разбивка по категориям.
    """
    from handlers.price_watcher import _catalog_items_for_publish
    from services.price_publisher import _get_category, _display_group

    items: List[Dict] = []
    for row in _catalog_items_for_publish():
        cat = _get_category(row)
        group = _display_group(cat, str(row.get("item_group_id", "")))
        try:
            price = int(str(row.get("price", "0")).replace(" ", "") or 0)
        except ValueError:
            price = 0
        items.append({
            "id":     row.get("id", ""),
            "cat":    cat,
            "group":  group,
            "title":  row.get("title", ""),
            "memory": _clean(row.get("memory")),
            "color":  _clean(row.get("color")),
            "sim":    _clean(row.get("sim")),
            "region": _clean(row.get("region")),
            "image":  row.get("image", ""),
            "price":  price,
        })

    items.sort(key=lambda i: (i["cat"], i["group"], i["price"]))
    return {"items": items, "manager": MANAGER_USERNAME}


def _clean(value) -> str:
    v = str(value or "").strip()
    return "" if v in ("-", "0") else v


async def _index(request: web.Request) -> web.Response:
    try:
        return web.Response(text=_PAGE.read_text(encoding="utf-8"),
                            content_type="text/html")
    except FileNotFoundError:
        return web.Response(status=404, text="Mini App не собран")


async def _catalog(request: web.Request) -> web.Response:
    try:
        return web.json_response(_catalog_payload())
    except Exception as e:
        logger.error(f"webapp: каталог не отдан: {e}")
        return web.json_response({"items": [], "error": "catalog unavailable"},
                                 status=503)


async def _health(request: web.Request) -> web.Response:
    return web.json_response({"ok": True})


def build_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/", _index)
    app.router.add_get("/api/catalog", _catalog)
    app.router.add_get("/health", _health)
    return app


async def run() -> None:
    """Поднимает сервер. Вызывается из main.py фоновой задачей."""
    if not enabled():
        logger.info("webapp: WEBAPP_URL не задан — Mini App выключен")
        return

    runner = web.AppRunner(build_app())
    await runner.setup()
    site = web.TCPSite(runner, _HOST, _PORT)
    try:
        await site.start()
        logger.info(f"webapp: слушает {_HOST}:{_PORT}, публичный адрес {PUBLIC_URL}")
    except Exception as e:
        logger.error(f"webapp: не поднялся на {_HOST}:{_PORT}: {e}")
