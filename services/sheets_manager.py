import os
import logging
import json
import re
import gspread
import time
from typing import List, Dict, Any

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


def authorize_gspread():
    credentials_json_str = os.getenv("GOOGLE_CREDENTIALS_JSON")
    if not credentials_json_str:
        logger.error("GOOGLE_CREDENTIALS_JSON не задан")
        return None
    try:
        if credentials_json_str.startswith("'") and credentials_json_str.endswith("'"):
            credentials_json_str = credentials_json_str[1:-1]
        return gspread.service_account_from_dict(json.loads(credentials_json_str))
    except Exception as e:
        logger.error(f"Auth error: {e}")
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
                # Fallback для старых листов: "memory_ssd"
                memory_val = (
                    str(row.get("memory", "")).strip()
                    or str(row.get("memory_ssd", "")).strip()
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
            return cleaned

        except Exception as e:
            if attempt < retries - 1:
                logger.warning(f"Sheets retry {attempt + 1}: {e}")
                time.sleep(2)
                continue
            logger.error(f"Sheets error: {e}")

    return []


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
