import os
import logging
import json
import re
import gspread
import time
from typing import List, Dict, Any

from services import incidents
from services import incident_rules
from services import incident_rules as rules

logger = logging.getLogger(__name__)

# ─── Маппинг наборов флагов → название региона ──────────────────────────────
# Флаги зашиты в поле "id" по стандарту Facebook Commerce
_REGION_MAP = {
    frozenset(["🇧🇭","🇨🇦","🇯🇵","🇰🇼","🇲🇽","🇶🇦","🇸🇦","🇦🇪","🇺🇸"]): "International",
    frozenset(["🇷🇺"]):  "Россия",
    frozenset(["🇪🇺"]):  "Европа",
    frozenset(["🇨🇳"]):  "Китай",
    frozenset(["🇬🇧"]):  "UK",
}

# ─── Категории которые используют size как память ────────────────────────────
_MAC_KEYWORDS = {"mac", "imac", "macbook", "mac mini", "mac pro", "mac studio"}


def _is_mac(model_group: str) -> bool:
    return any(kw in model_group.lower() for kw in _MAC_KEYWORDS)


def _extract_region(row: dict) -> str:
    """
    Извлекаем регион из поля 'id' по флагам-эмодзи.
    Если флагов нет — смотрим кастомный столбец 'region_custom'.
    """
    raw_id = str(row.get("id", ""))
    flags = re.findall(r'[\U0001F1E0-\U0001F1FF]{2}', raw_id)

    if flags:
        flag_set = frozenset(flags)
        for known_set, label in _REGION_MAP.items():
            if flag_set == known_set:
                return label
        # Неизвестный набор — возвращаем сами флаги
        return " ".join(sorted(flags))

    # Нет флагов — пробуем кастомный столбец
    custom = str(row.get("region_custom", "")).strip()
    if custom and custom not in ("0", ""):
        return custom

    return "-"


def service_account_email() -> str:
    """Email сервис-аккаунта из ключа — нужен в инцидентах про права доступа."""
    raw = os.getenv("GOOGLE_CREDENTIALS_JSON", "")
    if raw.startswith("'") and raw.endswith("'"):
        raw = raw[1:-1]
    try:
        return json.loads(raw).get("client_email", "?")
    except Exception:
        return "?"


def authorize_gspread():
    credentials_json_str = os.getenv("GOOGLE_CREDENTIALS_JSON")
    if not credentials_json_str:
        incidents.report(
            component=rules.SHEETS,
            code="SHEETS_NO_CREDENTIALS",
            detail="Переменная GOOGLE_CREDENTIALS_JSON отсутствует в .env",
        )
        return None
    try:
        if credentials_json_str.startswith("'") and credentials_json_str.endswith("'"):
            credentials_json_str = credentials_json_str[1:-1]
        gc = gspread.service_account_from_dict(json.loads(credentials_json_str))
        incidents.resolve(rules.SHEETS, "SHEETS_NO_CREDENTIALS")
        return gc
    except json.JSONDecodeError as e:
        incidents.report(
            component=rules.SHEETS,
            code="SHEETS_NO_CREDENTIALS",
            exc=e,
            detail="GOOGLE_CREDENTIALS_JSON не разбирается как JSON — "
                   "скорее всего ключ вставлен в .env с переносами строк",
        )
        return None
    except Exception as e:
        incidents.report(
            component=rules.SHEETS,
            exc=e,
            detail="Не удалось авторизоваться по ключу сервис-аккаунта",
            context={"аккаунт": service_account_email()},
        )
        return None


def get_data_from_sheet(sheet_name: str = "vnxSHOP", retries: int = 3) -> List[Dict[str, Any]]:
    gc = authorize_gspread()
    if not gc:
        return []

    spreadsheet_id = os.getenv("SPREADSHEET_ID")

    for attempt in range(retries):
        try:
            spreadsheet = gc.open_by_key(spreadsheet_id)
            worksheet   = spreadsheet.worksheet(sheet_name)
            raw_data    = worksheet.get_all_records()

            cleaned = []
            for row in raw_data:
                if not row.get("id"):
                    continue

                # ── Стандартные столбцы Facebook Commerce ─────────────────
                raw_price = str(row.get("price", "0"))
                price     = re.sub(r"[^\d]", "", raw_price) or "0"

                model_group = str(row.get("item_group_id", "")).strip()
                if not model_group:
                    model_group = str(row.get("title", "")).strip()

                color  = str(row.get("color", "")).strip() or "-"
                sim    = str(row.get("sim",   "")).strip() or "-"
                
                # Физический размер (диагональ / mm)
                size_val = str(row.get("size", "")).strip() or "-"

                # ── Память ────────────────────────────────────────────────────
                # Основной столбец по AiParser.gs: "memory"
                # Fallback 1: "memory_ssd" (старые листы)
                # Fallback 2: "size" если содержит только цифры (IPHC-строки с опечаткой)
                _size_raw = str(row.get("size", "")).strip()
                _size_as_mem = _size_raw if re.match(r"^\d+$", _size_raw) else ""
                memory_val = (
                    str(row.get("memory", "")).strip()
                    or str(row.get("memory_ssd", "")).strip()
                    or _size_as_mem
                    or "-"
                )
                memory_ram = str(row.get("memory_ram", "")).strip() or "-"

                # ── Регион ────────────────────────────────────────────────────
                # Основной столбец по AiParser.gs: "region"
                # Fallback: custom_label_0 → _extract_region
                region_val = (
                    str(row.get("region", "")).strip()
                    or str(row.get("region_custom", "")).strip()
                    or str(row.get("custom_label_0", "")).strip()
                    or _extract_region(row)
                    or "-"
                )
                if region_val in ("0", ""):
                    region_val = "-"

                entry = {
                    "id":           str(row.get("id", "")).strip(),
                    "title":        str(row.get("title", "")).strip(),
                    "availability": str(row.get("availability", "out of stock")).strip(),
                    "price":        price,
                    "image":        str(row.get("image_link", "")).strip(),
                    "color":        color,
                    "size":         size_val,
                    "memory":       memory_val,
                    "memory_ssd":   memory_val,
                    "memory_ram":   memory_ram,
                    "sim":          sim,
                    "model_group":  model_group,
                    "region":       region_val,
                }
                cleaned.append(entry)

            logger.info(
                f"Sheets: загружено {len(cleaned)} строк. "
            )

            # Чтение прошло — гасим все инциденты доступа к таблице
            incidents.ok(
                rules.SHEETS,
                "SHEETS_AUTH_FAILED", "SHEETS_PERMISSION_DENIED",
                "SHEETS_API_DISABLED", "SHEETS_NOT_FOUND",
                "SHEETS_WORKSHEET_NOT_FOUND", "SHEETS_QUOTA",
                "SHEETS_BACKEND", "SHEETS_NETWORK",
            )

            # Пустой каталог — не ошибка запроса, но полный отказ витрины
            if not cleaned:
                incidents.report(
                    component=rules.CATALOG,
                    code="CATALOG_EMPTY",
                    detail=f"Лист '{sheet_name}' прочитан, но не дал ни одной строки с id",
                    context={"строк в листе": len(raw_data)},
                )
            else:
                incidents.resolve(rules.CATALOG, "CATALOG_EMPTY")

            return cleaned

        except Exception as e:
            if attempt < retries - 1:
                logger.warning(f"Sheets retry {attempt + 1}: {e}")
                time.sleep(2)
                continue
            incidents.report(
                component=rules.SHEETS,
                exc=e,
                detail=f"Не удалось прочитать лист '{sheet_name}' за {retries} попытки",
                context={
                    "аккаунт": service_account_email(),
                    "таблица": spreadsheet_id or "не задана",
                },
            )

    return []


def check_access(sheet_name: str = "vnxSHOP") -> Dict[str, Any]:
    """
    Проверяет доступ к таблице: авторизация → открытие → чтение → запись.

    Проба записи неразрушающая: читаем A1 и записываем в неё то же самое
    значение. Смысл ячейки не меняется, но Google действительно выполняет
    операцию записи — а значит проверка честная.

    Важно: пробовать запись в заведомо далёкую ячейку (вроде ZZ1) нельзя.
    Google ответит 400 «exceeds grid limits» ещё до проверки прав, и это
    легко принять за отказ в доступе. Именно на этом однажды сломалась
    прошлая версия диагностики.

    Возвращает: {ok, stage, email, read_rows, error, code}
      stage — на чём остановились: auth / open / read / write / done
    """
    result: Dict[str, Any] = {
        "ok": False, "stage": "auth", "email": service_account_email(),
        "read_rows": 0, "error": "", "code": "",
    }

    gc = authorize_gspread()
    if not gc:
        result["error"] = "Не удалось авторизоваться по ключу"
        result["code"] = "SHEETS_NO_CREDENTIALS"
        return result

    spreadsheet_id = os.getenv("SPREADSHEET_ID")
    if not spreadsheet_id:
        result["stage"] = "config"
        result["error"] = "SPREADSHEET_ID не задан в .env"
        result["code"] = "CONFIG_MISSING"
        return result

    result["stage"] = "open"
    try:
        ss = gc.open_by_key(spreadsheet_id)
        result["title"] = ss.title
        result["sheets"] = [w.title for w in ss.worksheets()]
    except Exception as e:
        result["error"] = str(e)
        result["code"] = incident_rules.classify(e, incident_rules.SHEETS)
        return result

    result["stage"] = "read"
    try:
        ws = ss.worksheet(sheet_name)
        values = ws.get_all_values()
        result["read_rows"] = len(values)
    except Exception as e:
        result["error"] = str(e)
        result["code"] = incident_rules.classify(e, incident_rules.SHEETS)
        return result

    result["stage"] = "write"
    try:
        # Читаем и возвращаем то же значение — запись без изменения данных
        current = ws.acell("A1").value or ""
        ws.update_acell("A1", current)
    except Exception as e:
        result["error"] = str(e)
        result["code"] = incident_rules.classify(e, incident_rules.SHEETS)
        return result

    result["stage"] = "done"
    result["ok"] = True
    return result


def get_settings():
    gc = authorize_gspread()
    if not gc:
        return {}
    try:
        spreadsheet = gc.open_by_key(os.getenv("SPREADSHEET_ID"))
        rows = spreadsheet.worksheet("Settings").get_all_records()
        result = {}
        for r in rows:
            # Поддерживаем и английские (Key/Value), и русские заголовки
            k = r.get("Key") or r.get("Категория")
            v = r.get("Value") or r.get("Ссылка")
            if k:
                result[str(k)] = str(v)
        logger.info(f"Settings: загружено {len(result)} ключей")
        return result
    except Exception as e:
        logger.error(f"Settings error: {e}")
        return {}
