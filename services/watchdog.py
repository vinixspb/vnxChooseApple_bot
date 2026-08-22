"""
Сторож: активные проверки состояния системы.

Инциденты из sheets_writer и price_publisher — реактивные: они рождаются,
когда операция уже провалилась. Этого мало. Часть поломок не порождает
ни одной ошибки: бота выкинули из группы поставщика — прайсы просто
перестают приходить, и в логах идеальная тишина.

Сторож закрывает эту дыру двумя способами:

  1. Проверка при старте — сразу после запуска убеждается, что доступ
     к таблице есть на запись, а не только на чтение. Сломанные права
     обнаруживаются в первую минуту, а не через недели.

  2. Периодический обход — раз в час смотрит на возраст последней
     синхронизации и на размер каталога. Отсутствие событий тоже событие.
"""

import asyncio
import logging
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from services import incidents
from services import incident_rules as rules
from services.sheets_manager import check_access
import services.data_store as store

logger = logging.getLogger(__name__)
_MSK = ZoneInfo("Europe/Moscow")

# Через сколько часов молчания поставщиков считать каталог протухшим
_STALE_HOURS = int(os.getenv("WATCHDOG_STALE_HOURS", "24"))

# Как часто обходить систему
_INTERVAL = int(os.getenv("WATCHDOG_INTERVAL_MINUTES", "60")) * 60

# Переменные окружения, без которых часть бота молча не работает
_REQUIRED_ENV = {
    "BOT_TOKEN":               "бот вообще не запустится",
    "SPREADSHEET_ID":          "нет каталога и записи прайса",
    "GOOGLE_CREDENTIALS_JSON": "нет доступа к Google Sheets",
    "PRICE_CHANNEL_ID":        "прайс не публикуется в канал",
    "SUPPLIER_CHANNEL_ID":     "прайсы поставщиков не принимаются",
    "MANAGER_ID":              "владелец не получает уведомлений",
}


def check_config() -> None:
    """Проверяет обязательные переменные окружения."""
    missing = [name for name in _REQUIRED_ENV if not os.getenv(name)]
    if missing:
        incidents.report(
            component=rules.CONFIG,
            code="CONFIG_MISSING",
            detail="Не заданы переменные: " + ", ".join(missing),
            context={name: _REQUIRED_ENV[name] for name in missing},
        )
    else:
        incidents.resolve(rules.CONFIG, "CONFIG_MISSING")


def check_sheets() -> dict:
    """
    Проверяет доступ к таблице на чтение И на запись.

    Ключевой момент: проверять только чтение бессмысленно. При правах
    «Читатель» чтение проходит, каталог загружается, бот выглядит здоровым —
    и всё это время прайс не попадает ни в таблицу, ни в фид Meta.
    """
    res = check_access()

    if res["ok"]:
        incidents.ok(
            rules.SHEETS,
            "SHEETS_NO_CREDENTIALS", "SHEETS_AUTH_FAILED",
            "SHEETS_PERMISSION_DENIED", "SHEETS_API_DISABLED",
            "SHEETS_NOT_FOUND", "SHEETS_WORKSHEET_NOT_FOUND",
            "SHEETS_NETWORK", "SHEETS_BACKEND",
        )
        logger.info(
            f"watchdog: доступ к Sheets в порядке "
            f"(чтение и запись, {res['read_rows']} строк)"
        )
        return res

    stage_ru = {
        "auth":   "авторизация по ключу",
        "config": "конфигурация",
        "open":   "открытие таблицы",
        "read":   "чтение листа",
        "write":  "запись в лист",
    }.get(res["stage"], res["stage"])

    incidents.report(
        component=rules.SHEETS,
        code=res.get("code") or "UNKNOWN",
        detail=f"Самопроверка доступа не прошла на шаге: {stage_ru}",
        context={
            "аккаунт": res.get("email", "?"),
            "ответ Google": (res.get("error") or "")[:200],
        },
    )
    return res


def check_freshness() -> None:
    """Смотрит, давно ли приходили прайсы, и не опустел ли каталог."""
    if not store.CATALOG:
        incidents.report(
            component=rules.CATALOG,
            code="CATALOG_EMPTY",
            detail="Каталог в памяти пуст при плановой проверке",
        )
        return
    incidents.resolve(rules.CATALOG, "CATALOG_EMPTY")

    last = store.LAST_SYNC.get("time")
    reference = last or store.START_TIME
    age = datetime.now(_MSK) - reference

    # Пока бот работает меньше порога, тишина ещё ни о чём не говорит
    if age < timedelta(hours=_STALE_HOURS):
        incidents.resolve(rules.CATALOG, "CATALOG_STALE")
        return

    hours = int(age.total_seconds() // 3600)
    incidents.report(
        component=rules.CATALOG,
        code="CATALOG_STALE",
        detail=(
            f"Последний разобранный прайс был {hours} ч назад"
            if last else
            f"За {hours} ч с момента запуска не пришло ни одного прайса"
        ),
        context={
            "порог, ч":      _STALE_HOURS,
            "позиций":       len(store.CATALOG),
            "источник":      store.LAST_SYNC.get("source", "—"),
        },
    )


async def startup_check() -> None:
    """
    Разовая проверка при запуске бота.

    Выполняется в отдельном потоке: обращения к Google синхронные и
    блокирующие, а тормозить старт polling из-за диагностики не нужно.
    """
    try:
        check_config()
        await asyncio.to_thread(check_sheets)
        logger.info("watchdog: стартовая проверка завершена")
    except Exception as e:
        logger.error(f"watchdog.startup_check: {e}")


async def run() -> None:
    """Периодический обход. Живёт всё время работы бота."""
    # Даём боту подняться и загрузить каталог
    await asyncio.sleep(60)
    await startup_check()

    while True:
        try:
            await asyncio.sleep(_INTERVAL)
            check_config()
            check_freshness()
            await asyncio.to_thread(check_sheets)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"watchdog.run: {e}")
