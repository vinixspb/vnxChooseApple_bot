"""
Система инцидентов: регистрация, дедупликация, хранение и уведомление.

Принципы, на которых она построена.

1. Сбой не должен быть тихим. Любая операция, от которой зависит бизнес
   (запись в Sheets, публикация в канал, разбор прайса), сообщает и об успехе,
   и о провале. Успех гасит открытый инцидент, провал его открывает.

2. Отчёт об инциденте никогда не ломает основной поток. report() не бросает
   исключений вообще — что бы внутри ни случилось. Система наблюдения,
   роняющая наблюдаемое, хуже её отсутствия.

3. Один инцидент — одно уведомление. Повторы схлопываются по отпечатку
   и копят счётчик. Напоминание приходит не чаще, чем раз в _REPEAT_AFTER.
   Алерт, приходящий каждую минуту, перестают читать за час.

4. Инцидент закрывается сам. Когда операция снова прошла успешно,
   resolve() гасит инцидент и шлёт «восстановлено» — но только если об
   открытии успели сообщить. Иначе владелец получал бы «всё починилось»
   на проблему, о которой не знал.

Работа из синхронного кода. sheets_writer синхронный, aiogram асинхронный,
поэтому report() только кладёт уведомление в очередь, а разбирает её
фоновая корутина dispatcher(), запущенная из main.py. Так синхронный код
сообщает об инциденте, ничего не зная про event loop.
"""

import json
import logging
import os
import threading
import traceback as _tb
from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional
from zoneinfo import ZoneInfo

from services.incident_rules import (
    CRITICAL, ERROR, WARNING, INFO,
    SEVERITY_EMOJI, SEVERITY_LABEL,
    classify, get_rule, severity_rank,
)

logger = logging.getLogger(__name__)

_MSK = ZoneInfo("Europe/Moscow")

# ── Настройки ────────────────────────────────────────────────────────────────

# Файл истории. Пишется построчно (JSONL), чтобы уцелеть при внезапном
# завершении процесса: недописанная последняя строка не портит остальные.
_STORE_PATH = Path(os.getenv(
    "INCIDENTS_FILE",
    str(Path(__file__).resolve().parent.parent / "data" / "incidents.jsonl"),
))

# Сколько записей держать в памяти и в файле
_HISTORY_LIMIT = int(os.getenv("INCIDENTS_HISTORY_LIMIT", "500"))

# Не напоминать о том же инциденте чаще, чем раз в N минут
_REPEAT_AFTER = timedelta(minutes=int(os.getenv("INCIDENTS_REPEAT_MINUTES", "60")))

# Уровни, о которых шлём уведомление владельцу. INFO копится молча.
_NOTIFY_LEVELS = {CRITICAL, ERROR, WARNING}

# Защита от шторма: не больше N уведомлений за окно
_BURST_LIMIT = int(os.getenv("INCIDENTS_BURST_LIMIT", "12"))
_BURST_WINDOW = timedelta(minutes=10)


# ── Модель ───────────────────────────────────────────────────────────────────

@dataclass
class Incident:
    """
    Один инцидент. Повторы одной и той же проблемы не создают новых записей —
    растёт count и обновляется last_seen.
    """
    fingerprint: str
    code:        str
    severity:    str
    component:   str
    title:       str
    detail:      str = ""
    context:     Dict[str, Any] = field(default_factory=dict)
    exc_type:    str = ""
    exc_message: str = ""
    traceback:   str = ""
    first_seen:  str = ""
    last_seen:   str = ""
    count:       int = 1
    notified:    bool = False
    resolved_at: Optional[str] = None

    @property
    def is_open(self) -> bool:
        return self.resolved_at is None

    def age(self) -> str:
        """Сколько инцидент открыт, человекочитаемо."""
        try:
            start = datetime.fromisoformat(self.first_seen)
        except (ValueError, TypeError):
            return "?"
        end = datetime.now(_MSK)
        if self.resolved_at:
            try:
                end = datetime.fromisoformat(self.resolved_at)
            except (ValueError, TypeError):
                pass
        return _humanize(end - start)


def _humanize(delta: timedelta) -> str:
    total = int(delta.total_seconds())
    if total < 60:
        return f"{total} сек"
    if total < 3600:
        return f"{total // 60} мин"
    if total < 86400:
        return f"{total // 3600} ч {(total % 3600) // 60} мин"
    return f"{total // 86400} дн {(total % 86400) // 3600} ч"


# ── Состояние ────────────────────────────────────────────────────────────────

_LOCK = threading.RLock()

# Открытые инциденты: отпечаток → инцидент
_OPEN: Dict[str, Incident] = {}

# Хроника: последние _HISTORY_LIMIT событий (открытия и закрытия)
_HISTORY: Deque[Incident] = deque(maxlen=_HISTORY_LIMIT)

# Очередь уведомлений, которую разбирает dispatcher()
_OUTBOX: Deque[str] = deque(maxlen=100)

# Отметки времени отправленных уведомлений — для защиты от шторма
_SENT_AT: Deque[datetime] = deque(maxlen=_BURST_LIMIT * 4)

# Когда последний раз напоминали о конкретном отпечатке
_LAST_NOTIFY: Dict[str, datetime] = {}


def _now() -> datetime:
    return datetime.now(_MSK)


def _fingerprint(code: str, component: str, key: str = "") -> str:
    """
    Отпечаток для схлопывания повторов.

    Ключ `key` разделяет инциденты одного кода, которые нужно вести раздельно
    (например, недоступны разные листы таблицы). Без него все повторы одного
    кода в одном компоненте — это один инцидент.
    """
    return "|".join(p for p in (code, component, key) if p)


# ── Хранилище ────────────────────────────────────────────────────────────────

def _persist(inc: Incident) -> None:
    """
    Дописывает запись в JSONL. Ошибки записи не должны никого ронять.

    default=str обязателен: в context может прилететь что угодно из
    вызывающего кода, и один несериализуемый объект не должен стоить
    нам всей записи об инциденте.
    """
    try:
        _STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with _STORE_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(inc), ensure_ascii=False, default=str) + "\n")
    except Exception as e:
        logger.warning(f"incidents: не удалось записать историю: {e}")


def load_history() -> None:
    """
    Поднимает историю с диска при старте.

    Открытые инциденты не восстанавливаются как открытые: после перезапуска
    состояние системы неизвестно, и честнее считать всё закрытым, чем
    показывать владельцу инциденты, которых, возможно, уже нет.
    Первая же неудачная операция откроет их заново.
    """
    if not _STORE_PATH.exists():
        return
    try:
        lines = _STORE_PATH.read_text(encoding="utf-8").splitlines()
    except Exception as e:
        logger.warning(f"incidents: история не прочитана: {e}")
        return

    restored = 0
    for line in lines[-_HISTORY_LIMIT:]:
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
            known = {f for f in Incident.__dataclass_fields__}
            _HISTORY.append(Incident(**{k: v for k, v in data.items() if k in known}))
            restored += 1
        except Exception:
            continue  # битая строка — пропускаем, остальные важнее

    if restored:
        logger.info(f"incidents: восстановлено записей истории: {restored}")


def _rotate_if_needed() -> None:
    """Подрезает файл истории, когда он перерастает лимит."""
    try:
        if not _STORE_PATH.exists():
            return
        lines = _STORE_PATH.read_text(encoding="utf-8").splitlines()
        if len(lines) <= _HISTORY_LIMIT * 2:
            return
        tail = lines[-_HISTORY_LIMIT:]
        _STORE_PATH.write_text("\n".join(tail) + "\n", encoding="utf-8")
        logger.info(f"incidents: история подрезана до {len(tail)} записей")
    except Exception as e:
        logger.warning(f"incidents: ротация не выполнена: {e}")


# ── Основное API ─────────────────────────────────────────────────────────────

def report(
    component: str,
    code: Optional[str] = None,
    exc: Optional[BaseException] = None,
    detail: str = "",
    key: str = "",
    context: Optional[Dict[str, Any]] = None,
    severity: Optional[str] = None,
) -> Optional[Incident]:
    """
    Регистрирует инцидент.

    component — компонент из incident_rules (SHEETS, PUBLISHER, ...)
    code      — код инцидента; если не задан, определяется по исключению
    exc       — исключение, если инцидент родился из него
    detail    — что именно происходило, человеческими словами
    key       — уточнение отпечатка, когда однотипные сбои нужно вести раздельно
    context   — любые данные для карточки инцидента (id, имена, счётчики)
    severity  — переопределение серьёзности из правила

    Никогда не бросает исключений. Возвращает инцидент либо None,
    если внутри что-то пошло не так.
    """
    try:
        return _report_unsafe(component, code, exc, detail, key, context, severity)
    except Exception as e:  # система наблюдения не имеет права ронять систему
        logger.error(f"incidents.report упал (это баг системы инцидентов): {e}")
        return None


def _report_unsafe(
    component: str,
    code: Optional[str],
    exc: Optional[BaseException],
    detail: str,
    key: str,
    context: Optional[Dict[str, Any]],
    severity: Optional[str],
) -> Incident:
    if not code:
        code = classify(exc, component) if exc else "UNKNOWN"

    rule = get_rule(code)
    sev = severity or rule.severity
    fp = _fingerprint(code, component, key)
    now = _now()

    with _LOCK:
        existing = _OPEN.get(fp)
        if existing:
            # Повтор известной проблемы — растим счётчик, новую запись не заводим
            existing.count += 1
            existing.last_seen = now.isoformat()
            if detail:
                existing.detail = detail
            if context:
                existing.context.update(context)
            inc = existing
            is_new = False
        else:
            inc = Incident(
                fingerprint=fp,
                code=code,
                severity=sev,
                component=component,
                title=rule.title,
                detail=detail,
                context=dict(context or {}),
                exc_type=type(exc).__name__ if exc else "",
                exc_message=str(exc)[:500] if exc else "",
                traceback=_short_traceback(exc),
                first_seen=now.isoformat(),
                last_seen=now.isoformat(),
            )
            _OPEN[fp] = inc
            _HISTORY.append(inc)
            is_new = True

        should_notify = _should_notify(inc, is_new, now)
        if should_notify:
            inc.notified = True
            _LAST_NOTIFY[fp] = now

    # Логируем всегда — journalctl остаётся вторым источником правды
    log = logger.critical if sev == CRITICAL else (
        logger.error if sev == ERROR else logger.warning
    )
    log(f"[{code}] {rule.title} | {component} | {detail} | {inc.exc_message}")

    if is_new:
        _persist(inc)
        _rotate_if_needed()

    if should_notify:
        _enqueue(_format_alert(inc, repeat=not is_new))

    return inc


def _should_notify(inc: Incident, is_new: bool, now: datetime) -> bool:
    """Решает, слать ли уведомление: по уровню, по частоте и по шторму."""
    if inc.severity not in _NOTIFY_LEVELS:
        return False

    if not is_new:
        last = _LAST_NOTIFY.get(inc.fingerprint)
        if last and now - last < _REPEAT_AFTER:
            return False

    # Защита от шторма: если за окно уже ушло слишком много — молчим.
    # Критичные пропускаем всегда: их мало и они важнее тишины.
    if inc.severity != CRITICAL:
        recent = [t for t in _SENT_AT if now - t < _BURST_WINDOW]
        if len(recent) >= _BURST_LIMIT:
            return False

    _SENT_AT.append(now)
    return True


def resolve(component: str, code: str, key: str = "", note: str = "") -> Optional[Incident]:
    """
    Закрывает инцидент — вызывается, когда операция снова прошла успешно.

    Уведомление о восстановлении уходит только если об открытии сообщали:
    иначе владелец получит «всё хорошо» на проблему, которой для него не было.
    """
    try:
        fp = _fingerprint(code, component, key)
        with _LOCK:
            inc = _OPEN.pop(fp, None)
            if not inc:
                return None
            inc.resolved_at = _now().isoformat()
            _LAST_NOTIFY.pop(fp, None)
            notify = inc.notified

        _persist(inc)
        logger.info(f"[{code}] восстановлено после {inc.age()} ({inc.count} сбоев)")

        if notify:
            rule = get_rule(inc.code)
            _enqueue(
                f"✅ <b>Восстановлено</b>\n\n"
                f"<b>{_esc(rule.title)}</b>\n"
                f"Компонент: {inc.component}\n"
                f"Длилось: {inc.age()} · сбоев: {inc.count}"
                + (f"\n{_esc(note)}" if note else "")
            )
        return inc
    except Exception as e:
        logger.error(f"incidents.resolve упал: {e}")
        return None


def ok(component: str, *codes: str, key: str = "") -> None:
    """
    Успешная операция: гасит перечисленные коды разом.

    Удобно ставить сразу после удачного вызова — один вызов вместо
    цепочки resolve() на каждый возможный код отказа.
    """
    for code in codes:
        resolve(component, code, key=key)


def _short_traceback(exc: Optional[BaseException], limit: int = 12) -> str:
    if not exc:
        return ""
    try:
        lines = _tb.format_exception(type(exc), exc, exc.__traceback__)
        text = "".join(lines)
        return text[-2000:]
    except Exception:
        return ""


# ── Уведомления ──────────────────────────────────────────────────────────────

def _esc(text: str) -> str:
    """Экранирование под HTML-разметку Telegram."""
    return (str(text).replace("&", "&amp;")
                     .replace("<", "&lt;")
                     .replace(">", "&gt;"))


def _enqueue(text: str) -> None:
    _OUTBOX.append(text)


def _format_alert(inc: Incident, repeat: bool = False) -> str:
    """
    Собирает карточку инцидента.

    Порядок полей выбран под чтение с телефона: сначала что сломалось,
    потом почему это важно, и последним — что нажать, чтобы починить.
    Инструкция внизу, потому что именно к ней возвращаются повторно.
    """
    rule = get_rule(inc.code)
    emoji = SEVERITY_EMOJI.get(inc.severity, "⚪")
    label = SEVERITY_LABEL.get(inc.severity, inc.severity.upper())

    head = f"{emoji} <b>{label}: {_esc(rule.title)}</b>"
    if repeat:
        head += f"\n<i>повторяется, всего сбоев: {inc.count}, длится {inc.age()}</i>"

    parts = [head, ""]

    if inc.detail:
        parts.append(f"📍 {_esc(inc.detail)}")

    if inc.exc_message:
        parts.append(f"<code>{_esc(inc.exc_message[:300])}</code>")

    if inc.context:
        ctx = "\n".join(f"· {_esc(k)}: {_esc(v)}" for k, v in list(inc.context.items())[:6])
        parts.append(ctx)

    if rule.why:
        parts.append(f"\n<b>Почему это важно</b>\n{_esc(rule.why)}")

    if rule.fix:
        parts.append(f"\n<b>Что сделать</b>\n{_esc(rule.fix)}")

    if rule.docs:
        parts.append(f"\n📖 {_esc(rule.docs)}")

    parts.append(f"\n<code>{_esc(inc.code)}</code> · {inc.component}")

    text = "\n".join(p for p in parts if p is not None)
    return text[:4000]


async def dispatcher(bot, poll_seconds: int = 5) -> None:
    """
    Фоновая корутина: разбирает очередь уведомлений и шлёт их владельцу.

    Живёт весь срок жизни бота. Любая ошибка отправки гасится внутри —
    диспетчер не имеет права умереть, иначе система замолчит целиком
    ровно тогда, когда она нужнее всего.
    """
    import asyncio

    owner = os.getenv("MANAGER_ID")
    secretary_token = os.getenv("SECRETARY_BOT_TOKEN")

    if not owner:
        logger.warning("incidents: MANAGER_ID не задан — уведомления отключены")

    while True:
        try:
            if owner and _OUTBOX:
                batch: List[str] = []
                while _OUTBOX and len(batch) < 5:
                    batch.append(_OUTBOX.popleft())
                for text in batch:
                    await _send(bot, owner, secretary_token, text)
        except Exception as e:
            logger.error(f"incidents.dispatcher: {e}")
        await asyncio.sleep(poll_seconds)


async def _send(bot, owner: str, secretary_token: Optional[str], text: str) -> None:
    """
    Шлёт уведомление. Приоритет — секретарский бот (у владельца он под рукой),
    при неудаче падаем на основного бота: сообщение важнее канала доставки.
    """
    if secretary_token:
        try:
            from aiogram import Bot
            sec = Bot(token=secretary_token)
            try:
                await sec.send_message(owner, text, parse_mode="HTML")
                return
            finally:
                await sec.session.close()
        except Exception as e:
            logger.warning(f"incidents: секретарь не доставил ({e}), пробуем основного бота")

    try:
        await bot.send_message(owner, text, parse_mode="HTML")
    except Exception as e:
        logger.error(f"incidents: уведомление не доставлено: {e}")


# ── Чтение состояния (для команд /incidents, /health) ────────────────────────

def open_incidents() -> List[Incident]:
    """Открытые инциденты, самые серьёзные первыми."""
    with _LOCK:
        items = list(_OPEN.values())
    return sorted(items, key=lambda i: (severity_rank(i.severity), i.first_seen))


def history(limit: int = 20) -> List[Incident]:
    """Последние события, свежие первыми."""
    with _LOCK:
        return list(_HISTORY)[-limit:][::-1]


def find(code_or_prefix: str) -> List[Incident]:
    """Поиск по коду среди открытых и в истории."""
    needle = code_or_prefix.upper()
    with _LOCK:
        pool = list(_OPEN.values()) + list(_HISTORY)
    seen, out = set(), []
    for inc in pool:
        if inc.code.upper().startswith(needle) and inc.fingerprint not in seen:
            seen.add(inc.fingerprint)
            out.append(inc)
    return out


def health() -> Dict[str, Any]:
    """Сводка состояния: сколько инцидентов какого уровня открыто."""
    items = open_incidents()
    counts = {CRITICAL: 0, ERROR: 0, WARNING: 0, INFO: 0}
    for i in items:
        counts[i.severity] = counts.get(i.severity, 0) + 1
    return {
        "healthy":  counts[CRITICAL] == 0 and counts[ERROR] == 0,
        "counts":   counts,
        "open":     len(items),
        "worst":    items[0] if items else None,
    }


def card(inc: Incident) -> str:
    """Подробная карточка инцидента для команды /incident."""
    return _format_alert(inc, repeat=inc.count > 1)
