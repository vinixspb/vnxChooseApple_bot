"""
Каталог известных инцидентов: классификация ошибок в понятные коды.

Зачем это нужно. Раньше любая ошибка уходила в `logger.error(...)` и умирала
в journalctl. Классический пример: сервис-аккаунт потерял права Редактора на
таблицу, запись падала с 403, но бот продолжал бодро рапортовать «Прайс
опубликован» — потому что публикация идёт из памяти, а не из Sheets. Проблема
жила недели и была замечена только вручную.

Модуль превращает сырое исключение в инцидент с четырьмя полями:
  code     — машинный код, по нему инциденты группируются и дедуплицируются
  severity — насколько срочно
  title    — что случилось, одной строкой, по-русски
  fix      — что конкретно сделать руками, чтобы починить

Правило добавления нового кода: если ошибку нельзя починить конкретным
действием — не заводи для неё отдельный код, ей место в UNKNOWN. Код без
внятного поля `fix` бесполезен: он превращает алерт в шум.

Документация по кодам ошибок, на которой построена классификация Sheets:
  https://developers.google.com/workspace/sheets/api/limits
  https://developers.google.com/workspace/sheets/api/guides/concepts
  https://cloud.google.com/apis/design/errors
"""

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional

# ── Уровни серьёзности ───────────────────────────────────────────────────────
# CRITICAL — бизнес-процесс остановлен, деньги/товар не двигаются, чинить сейчас
# ERROR    — отдельная операция провалилась, система работает частично
# WARNING  — аномалия, сама по себе не ломает, но копится
# INFO     — событие для истории, уведомление не шлётся

CRITICAL = "critical"
ERROR    = "error"
WARNING  = "warning"
INFO     = "info"

_SEVERITY_ORDER = {CRITICAL: 0, ERROR: 1, WARNING: 2, INFO: 3}

SEVERITY_EMOJI = {
    CRITICAL: "🔴",
    ERROR:    "🟠",
    WARNING:  "🟡",
    INFO:     "🔵",
}

SEVERITY_LABEL = {
    CRITICAL: "КРИТИЧНО",
    ERROR:    "ОШИБКА",
    WARNING:  "ВНИМАНИЕ",
    INFO:     "ИНФО",
}


def severity_rank(severity: str) -> int:
    """Для сортировки: чем меньше число, тем серьёзнее."""
    return _SEVERITY_ORDER.get(severity, 9)


# ── Компоненты системы ───────────────────────────────────────────────────────

SHEETS    = "sheets"      # чтение/запись Google Sheets
PUBLISHER = "publisher"   # публикация прайса в канал
PARSER    = "parser"      # разбор сообщений поставщиков
TELEGRAM  = "telegram"    # отправка сообщений, права в канале
CONFIG    = "config"      # переменные окружения, ключи
CATALOG   = "catalog"     # состояние каталога в памяти


@dataclass
class IncidentRule:
    """Описание одного класса инцидентов."""
    code:     str
    severity: str
    title:    str
    fix:      str
    # Пояснение «почему это важно» — попадает в подробную карточку инцидента
    why:      str = ""
    # Ссылка на документацию
    docs:     str = ""
    # Инцидент этого типа гаснет сам при следующей успешной операции
    auto_resolves: bool = True


# ── Каталог правил ───────────────────────────────────────────────────────────

RULES: Dict[str, IncidentRule] = {}


def _rule(**kwargs) -> None:
    r = IncidentRule(**kwargs)
    RULES[r.code] = r


# ── Google Sheets: доступ и права ────────────────────────────────────────────

_rule(
    code="SHEETS_NO_CREDENTIALS",
    severity=CRITICAL,
    title="Нет ключа сервис-аккаунта Google",
    why="Без ключа бот не может ни читать каталог, ни писать прайс. "
        "Каталог останется пустым, покупатели увидят пустое меню.",
    fix="Проверь GOOGLE_CREDENTIALS_JSON в /opt/vnxChooseApple_bot/.env. "
        "Если переменной нет или JSON битый — залей ключ заново:\n"
        "python run_set_credentials.py /путь/к/ключу.json",
    auto_resolves=False,
)

_rule(
    code="SHEETS_AUTH_FAILED",
    severity=CRITICAL,
    title="Google отклонил ключ сервис-аккаунта (401)",
    why="Ключ отозван, удалён в Cloud Console или у него разъехались часы сервера. "
        "Ни чтение, ни запись не работают.",
    fix="1. Проверь, что ключ не удалён: Cloud Console → IAM → Сервисные аккаунты → Ключи\n"
        "2. Сверь время на сервере: timedatectl (расхождение >5 мин ломает подпись JWT)\n"
        "3. При необходимости создай новый ключ и залей: python run_set_credentials.py <файл>",
    docs="https://cloud.google.com/docs/authentication",
    auto_resolves=False,
)

_rule(
    code="SHEETS_PERMISSION_DENIED",
    severity=CRITICAL,
    title="У сервис-аккаунта нет прав на таблицу (403)",
    why="Самая коварная поломка: ЧТЕНИЕ при правах «Читатель» работает, а ЗАПИСЬ падает. "
        "Бот продолжает публиковать прайс в канал из памяти и выглядит здоровым, "
        "но таблица и фид Meta Commerce Manager замирают на старых данных.",
    fix="Открой таблицу → «Настройки доступа» → добавь email сервис-аккаунта "
        "(его показывает python run_sheets_check.py) с ролью «Редактор», "
        "сняв галочку «Уведомить пользователей».",
    docs="https://developers.google.com/workspace/sheets/api/guides/authorizing",
    auto_resolves=False,
)

_rule(
    code="SHEETS_API_DISABLED",
    severity=CRITICAL,
    title="Google Sheets API выключен в проекте",
    why="API не включён в том Cloud-проекте, которому принадлежит сервис-аккаунт. "
        "Любой запрос отклоняется до проверки прав.",
    fix="Cloud Console → APIs & Services → Library → включи «Google Sheets API» "
        "(и «Google Drive API») в проекте сервис-аккаунта. "
        "Точный проект и ссылка указаны в тексте ошибки от Google.",
    auto_resolves=False,
)

_rule(
    code="SHEETS_NOT_FOUND",
    severity=CRITICAL,
    title="Таблица не найдена (404)",
    why="Неверный SPREADSHEET_ID, либо файл удалён/перемещён в корзину, "
        "либо доступ к нему у сервис-аккаунта отсутствует полностью.",
    fix="Сверь SPREADSHEET_ID в .env с id из адресной строки таблицы "
        "(часть между /d/ и /edit). Проверь, что файл не в корзине.",
    auto_resolves=False,
)

_rule(
    code="SHEETS_WORKSHEET_NOT_FOUND",
    severity=ERROR,
    title="Лист внутри таблицы не найден",
    why="Лист переименовали или удалили. Бот работает с листами "
        "vnxSHOP, Settings, SyncLog — имена зашиты в коде.",
    fix="Верни листу прежнее имя либо поправь имя в коде. "
        "Ожидаемые листы: vnxSHOP, Settings, SyncLog.",
    auto_resolves=False,
)

# ── Google Sheets: запросы и лимиты ──────────────────────────────────────────

_rule(
    code="SHEETS_RANGE_INVALID",
    severity=ERROR,
    title="Некорректный диапазон ячеек (400)",
    why="Запрос вышел за границы листа или диапазон не разобран. "
        "Обычно это баг в коде, а не проблема доступа — "
        "важно не спутать его с отказом в правах.",
    fix="Смотри диапазон в тексте ошибки. Если он за пределами листа — "
        "либо в коде опечатка, либо лист меньше, чем ожидалось.",
    docs="https://developers.google.com/workspace/sheets/api/guides/concepts#cell",
)

_rule(
    code="SHEETS_QUOTA",
    severity=WARNING,
    title="Превышена квота запросов к Google Sheets (429)",
    why="Лимиты: 60 запросов чтения в минуту на пользователя и 300 запросов "
        "записи в минуту на проект. При обвале прайса от нескольких поставщиков "
        "разом лимит выбирается легко.",
    fix="Само пройдёт: запрос повторяется с экспоненциальной задержкой. "
        "Если повторяется постоянно — укрупняй batch_update и реже дёргай API.",
    docs="https://developers.google.com/workspace/sheets/api/limits",
)

_rule(
    code="SHEETS_BACKEND",
    severity=WARNING,
    title="Временный сбой на стороне Google (500/503)",
    why="Сбой инфраструктуры Google. Обычно живёт минуты.",
    fix="Ничего не делать — retry с задержкой уже встроен. "
        "Если держится больше часа — смотри https://www.google.com/appsstatus",
)

_rule(
    code="SHEETS_NETWORK",
    severity=ERROR,
    title="Сеть до Google недоступна",
    why="Сервер не достучался до googleapis.com: DNS, файрвол или провайдер.",
    fix="Проверь с сервера: curl -sS -o /dev/null -w '%{http_code}' https://sheets.googleapis.com",
)

# ── Бизнес-логика: тихие отказы ──────────────────────────────────────────────
# Эти инциденты не рождаются из исключений. Их поднимает код, когда результат
# операции формально успешен, но по сути неправильный. Именно такие поломки
# живут дольше всего — никто не видит ошибки, потому что ошибки и нет.

_rule(
    code="SYNC_WROTE_NOTHING",
    severity=CRITICAL,
    title="Прайс разобран, но в таблицу не записано ничего",
    why="Поставщик прислал позиции, парсер их понял, а синхронизация вернула "
        "0 обновлённых и 0 добавленных строк. Значит запись в Sheets молча "
        "провалилась — почти всегда это потеря прав Редактора. "
        "Именно этот случай не ловился раньше и портил фид Meta неделями.",
    fix="Запусти python run_sheets_check.py — он покажет, что именно сломано. "
        "Чаще всего лечится выдачей роли «Редактор» сервис-аккаунту.",
)

_rule(
    code="CATALOG_EMPTY",
    severity=CRITICAL,
    title="Каталог в памяти пуст",
    why="Из Sheets не пришло ни строки. Покупатель откроет бота и увидит пустоту, "
        "воронка выбора товара работать не будет.",
    fix="python run_sheets_check.py — проверить доступ. "
        "Затем /reset в боте, чтобы перезагрузить каталог.",
)

_rule(
    code="CATALOG_STALE",
    severity=WARNING,
    title="Давно не было обновлений прайса",
    why="От поставщиков давно не приходило разобранных прайсов. "
        "Либо бота выкинули из группы поставщика, либо изменился формат сообщений "
        "и парсер перестал их узнавать, либо поставщики действительно молчат.",
    fix="Проверь SUPPLIER_CHANNEL_ID в .env и что бот всё ещё состоит в этих чатах. "
        "Загляни в группу поставщика: приходят ли сообщения и в прежнем ли формате.",
)

_rule(
    code="PARSE_EMPTY",
    severity=WARNING,
    title="Сообщение похоже на прайс, но разобрать не удалось",
    why="Фильтр looks_like_price_list() признал сообщение прайсом, а парсер "
        "вернул ноль позиций. Обычно поставщик сменил формат.",
    fix="Открой сообщение в группе поставщика и сравни с форматом, "
        "который понимает services/price_parser.py.",
)

_rule(
    code="PUBLISH_FAILED",
    severity=ERROR,
    title="Прайс не опубликован в канал",
    why="Ни одно сообщение не ушло в канал. Витрина замерла на прошлой версии.",
    fix="Проверь PRICE_CHANNEL_ID в .env и что бот — администратор канала "
        "с правом отправки и удаления сообщений.",
)

_rule(
    code="PUBLISH_NOTHING_TO_SHOW",
    severity=ERROR,
    title="После фильтрации не осталось ни одной позиции",
    why="Каталог не пуст, но фильтр «только Apple» отсеял всё. "
        "Либо фильтр стал слишком жадным, либо в каталоге действительно "
        "не осталось товаров Apple в наличии.",
    fix="Проверь регулярки _NON_APPLE_PUB_RE и _BRAND_ANYWHERE_PUB_RE "
        "в handlers/price_watcher.py — не отсекают ли они лишнее.",
)

# ── Telegram ─────────────────────────────────────────────────────────────────

_rule(
    code="TG_FORBIDDEN",
    severity=CRITICAL,
    title="Бот лишён прав в канале или группе",
    why="Бота исключили или сняли с администраторов. Публикация прайса невозможна.",
    fix="Верни бота @vnxSHOP_AppleFinder_bot в администраторы канала "
        "с правами «Отправлять сообщения» и «Удалять сообщения».",
    auto_resolves=False,
)

_rule(
    code="TG_RATE_LIMIT",
    severity=WARNING,
    title="Telegram просит подождать (flood control)",
    why="Слишком много сообщений подряд. Telegram притормаживает отправку.",
    fix="Ничего не делать. Если повторяется каждый раз — "
        "укрупняй сообщения, чтобы их было меньше.",
)

_rule(
    code="TG_BAD_REQUEST",
    severity=ERROR,
    title="Telegram отклонил сообщение",
    why="Чаще всего — битая HTML-разметка или превышение лимита 4096 символов.",
    fix="Смотри текст ошибки. При 'can't parse entities' виноват HTML "
        "в названии товара — его нужно экранировать.",
)

_rule(
    code="TG_NETWORK",
    severity=WARNING,
    title="Сеть до Telegram недоступна",
    why="Временная потеря связи с api.telegram.org.",
    fix="Обычно проходит само. Если нет — проверь сеть на сервере "
        "и что api.telegram.org не заблокирован.",
)

# ── Конфигурация ─────────────────────────────────────────────────────────────

_rule(
    code="CONFIG_MISSING",
    severity=CRITICAL,
    title="Не задана обязательная переменная окружения",
    why="Без неё соответствующая часть бота молча не работает.",
    fix="Добавь переменную в /opt/vnxChooseApple_bot/.env и перезапусти: apple-restart",
    auto_resolves=False,
)

# ── Запасной вариант ─────────────────────────────────────────────────────────

_rule(
    code="UNKNOWN",
    severity=ERROR,
    title="Неклассифицированная ошибка",
    why="Ошибка, для которой пока нет правила в каталоге.",
    fix="Посмотри трассировку в карточке инцидента и в journalctl. "
        "Если ошибка повторяется — заведи для неё правило "
        "в services/incident_rules.py.",
)


# ── Классификатор ────────────────────────────────────────────────────────────

@dataclass
class _Matcher:
    """Одно правило сопоставления исключения с кодом инцидента."""
    code:      str
    component: Optional[str] = None
    # Имена классов исключений (без модуля)
    exc_names: tuple = ()
    # HTTP-статус из тела ошибки
    statuses:  tuple = ()
    # Регулярка по тексту ошибки
    pattern:   Optional[re.Pattern] = None
    predicate: Optional[Callable[[BaseException, str], bool]] = None


# Статус вида "APIError: [403]: The caller does not have permission"
_STATUS_IN_TEXT = re.compile(r"\[(\d{3})\]")


def http_status(exc: BaseException) -> Optional[int]:
    """
    Достаёт HTTP-статус из исключения gspread.

    gspread по-разному хранит статус в разных версиях, поэтому пробуем
    несколько мест и в последнюю очередь разбираем текст.
    """
    resp = getattr(exc, "response", None)
    code = getattr(resp, "status_code", None)
    if isinstance(code, int):
        return code

    code = getattr(exc, "code", None)
    if isinstance(code, int):
        return code

    m = _STATUS_IN_TEXT.search(str(exc))
    if m:
        return int(m.group(1))
    return None


# Порядок важен: первое совпадение выигрывает.
# Более узкие правила стоят выше более общих.
_MATCHERS = [
    # ── Sheets: сначала различаем разные 403 по тексту ───────────────────────
    _Matcher(
        code="SHEETS_API_DISABLED",
        statuses=(403,),
        pattern=re.compile(r"has not been used in project|is disabled|SERVICE_DISABLED", re.I),
    ),
    _Matcher(
        code="SHEETS_PERMISSION_DENIED",
        statuses=(403,),
        pattern=re.compile(r"does not have permission|PERMISSION_DENIED|insufficient", re.I),
    ),
    _Matcher(code="SHEETS_PERMISSION_DENIED", statuses=(403,)),
    _Matcher(code="SHEETS_AUTH_FAILED",       statuses=(401,)),
    _Matcher(code="SHEETS_QUOTA",             statuses=(429,)),
    _Matcher(code="SHEETS_BACKEND",           statuses=(500, 502, 503, 504)),

    # 400 — почти всегда диапазон. Отдельный код, чтобы не путать с 403.
    _Matcher(
        code="SHEETS_RANGE_INVALID",
        statuses=(400,),
        pattern=re.compile(r"exceeds grid limits|Unable to parse range|INVALID_ARGUMENT", re.I),
    ),
    _Matcher(code="SHEETS_RANGE_INVALID", statuses=(400,)),

    # ── Sheets: типизированные исключения gspread ────────────────────────────
    _Matcher(code="SHEETS_NOT_FOUND",
             exc_names=("SpreadsheetNotFound", "NoValidUrlKeyFound")),
    _Matcher(code="SHEETS_WORKSHEET_NOT_FOUND",
             exc_names=("WorksheetNotFound",)),
    _Matcher(code="SHEETS_NOT_FOUND", statuses=(404,)),

    # ── Telegram ─────────────────────────────────────────────────────────────
    _Matcher(code="TG_FORBIDDEN",   exc_names=("TelegramForbiddenError",)),
    _Matcher(code="TG_RATE_LIMIT",  exc_names=("TelegramRetryAfter",)),
    _Matcher(code="TG_BAD_REQUEST", exc_names=("TelegramBadRequest",)),
    _Matcher(code="TG_NETWORK",     exc_names=("TelegramNetworkError",)),

    # ── Сеть ─────────────────────────────────────────────────────────────────
    _Matcher(
        code="SHEETS_NETWORK",
        component=SHEETS,
        exc_names=("ConnectionError", "Timeout", "ReadTimeout", "ConnectTimeout",
                   "SSLError", "ProxyError", "socket.gaierror", "gaierror"),
    ),
    _Matcher(
        code="TG_NETWORK",
        component=TELEGRAM,
        exc_names=("ConnectionError", "Timeout", "ClientConnectorError",
                   "ServerDisconnectedError", "ClientOSError"),
    ),
]


def classify(exc: BaseException, component: str = "") -> str:
    """
    Определяет код инцидента по исключению.

    Возвращает код из RULES; при отсутствии совпадений — "UNKNOWN".
    Классификация построена так, чтобы разные причины с одинаковым
    HTTP-статусом (403 «нет прав» против 403 «API выключен») попадали
    в разные коды: у них разные инструкции по починке.
    """
    text = str(exc)
    name = type(exc).__name__
    status = http_status(exc)

    for m in _MATCHERS:
        if m.component and m.component != component:
            continue
        if m.exc_names and name not in m.exc_names:
            continue
        if m.statuses and status not in m.statuses:
            continue
        if m.pattern and not m.pattern.search(text):
            continue
        if m.predicate and not m.predicate(exc, component):
            continue
        # Пустой матчер ничего не значит — требуем хотя бы одно условие
        if not (m.exc_names or m.statuses or m.pattern or m.predicate):
            continue
        return m.code

    return "UNKNOWN"


def get_rule(code: str) -> IncidentRule:
    """Правило по коду; для неизвестного кода — UNKNOWN."""
    return RULES.get(code, RULES["UNKNOWN"])
