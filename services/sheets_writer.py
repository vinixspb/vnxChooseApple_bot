import logging
import time
from typing import List, Dict, Any

from services.sheets_manager import authorize_gspread
import os

logger = logging.getLogger(__name__)

# Порядок столбцов в листе vnxSHOP (Facebook Commerce формат + кастомные)
_COLUMNS = [
    "id",
    "title",
    "availability",
    "price",
    "image_link",
    "item_group_id",
    "color",
    "sim",
    "size",
    "memory_ssd",
    "memory_ram",
    "custom_label_0",
    "custom_label_1",
    "custom_label_2",
]


def _row(item: Dict[str, Any]) -> list:
    return [str(item.get(col, "")).strip() for col in _COLUMNS]


def write_price_list(
    items: List[Dict[str, Any]],
    sheet_name: str = "vnxSHOP",
    retries: int = 3,
) -> bool:
    """
    Полностью перезаписывает лист sheet_name новыми данными.
    Возвращает True при успехе.
    """
    if not items:
        logger.warning("write_price_list: пустой список — пропускаю")
        return False

    gc = authorize_gspread()
    if not gc:
        return False

    spreadsheet_id = os.getenv("SPREADSHEET_ID")

    for attempt in range(retries):
        try:
            spreadsheet = gc.open_by_key(spreadsheet_id)
            try:
                ws = spreadsheet.worksheet(sheet_name)
            except Exception:
                ws = spreadsheet.add_worksheet(title=sheet_name, rows=1000, cols=20)

            rows = [_COLUMNS] + [_row(item) for item in items]

            ws.clear()
            ws.update(rows, value_input_option="USER_ENTERED")

            logger.info(f"Sheets: записано {len(items)} строк в '{sheet_name}'")
            return True

        except Exception as e:
            if attempt < retries - 1:
                logger.warning(f"Sheets write retry {attempt + 1}: {e}")
                time.sleep(2 ** attempt)
            else:
                logger.error(f"Sheets write error: {e}")

    return False
