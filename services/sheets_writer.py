import logging
import os
import time
from typing import List, Dict, Any

import gspread.utils as gu

from services.sheets_manager import authorize_gspread

logger = logging.getLogger(__name__)

# Столбцы таблицы vnxSHOP (27 столбцов).
# purchase_price (M) = закупочная цена без наценки.
# price          (F) = продажная цена (с наценкой) — то что видит покупатель.
_COLUMNS = [
    "id", "title", "description", "availability", "condition",
    "price", "link", "image_link", "brand", "google_product_category",
    "fb_product_category", "quantity_to_sell_on_facebook", "purchase_price",
    "sale_price_effective_date", "item_group_id", "gender", "color",
    "size", "age_group", "material", "pattern", "shipping",
    "shipping_weight", "gtin", "memory", "sim", "region",
]

_DEFAULTS: Dict[str, str] = {
    "description":                  "",
    "availability":                 "in stock",
    "condition":                    "new",
    "link":                         "https://www.apple.com",
    "image_link":                   "",
    "brand":                        "Apple",
    "google_product_category":      "Electronics",
    "fb_product_category":          "",
    "quantity_to_sell_on_facebook": "",
    "purchase_price":               "",
    "sale_price_effective_date":    "",
    "gender":                       "",
    "size":                         "",
    "age_group":                    "",
    "material":                     "",
    "pattern":                      "",
    "shipping":                     "",
    "shipping_weight":              "",
    "gtin":                         "",
    "region":                       "",
}


def _build_row(item: Dict[str, Any], header: List[str]) -> List[str]:
    merged = {**_DEFAULTS, **item}
    return [str(merged.get(col, "")).strip() for col in header]


def sync_price_list(
    items: List[Dict[str, Any]],
    sheet_name: str = "vnxSHOP",
    retries: int = 3,
) -> Dict[str, int]:
    """
    Умная синхронизация прайса с листом vnxSHOP:
    - Существующие товары (по id): обновляет цену и availability.
    - Новые товары: дописывает в конец листа.

    Возвращает {'updated': N, 'added': M}.
    """
    if not items:
        logger.warning("sync_price_list: пустой список")
        return {"updated": 0, "added": 0}

    gc = authorize_gspread()
    if not gc:
        return {"updated": 0, "added": 0}

    spreadsheet_id = os.getenv("SPREADSHEET_ID")

    for attempt in range(retries):
        try:
            spreadsheet = gc.open_by_key(spreadsheet_id)
            ws = spreadsheet.worksheet(sheet_name)

            all_values = ws.get_all_values()
            if not all_values:
                ws.update([_COLUMNS], value_input_option="USER_ENTERED")
                ws.append_rows(
                    [_build_row(item, _COLUMNS) for item in items],
                    value_input_option="USER_ENTERED",
                )
                return {"updated": 0, "added": len(items)}

            header = all_values[0]

            try:
                id_col       = header.index("id") + 1
                price_col    = header.index("price") + 1
                avail_col    = header.index("availability") + 1
                purchase_col = header.index("purchase_price") + 1 if "purchase_price" in header else None
            except ValueError as e:
                logger.error(f"Столбец не найден: {e}")
                return {"updated": 0, "added": 0}

            # Карта: id → номер строки (1-based)
            id_to_row: Dict[str, int] = {}
            for row_idx, row in enumerate(all_values[1:], start=2):
                cell_id = row[id_col - 1].strip() if len(row) >= id_col else ""
                if cell_id:
                    id_to_row[cell_id] = row_idx

            batch_updates: List[Dict] = []
            new_rows: List[List[str]] = []

            for item in items:
                item_id = item.get("id", "")
                if item_id in id_to_row:
                    row_num = id_to_row[item_id]
                    # Обновляем продажную цену, закупочную и наличие
                    batch_updates.append({
                        "range": gu.rowcol_to_a1(row_num, price_col),
                        "values": [[item["price"]]],
                    })
                    batch_updates.append({
                        "range": gu.rowcol_to_a1(row_num, avail_col),
                        "values": [["in stock"]],
                    })
                    if purchase_col and item.get("purchase_price"):
                        batch_updates.append({
                            "range": gu.rowcol_to_a1(row_num, purchase_col),
                            "values": [[item["purchase_price"]]],
                        })
                else:
                    new_rows.append(_build_row(item, header))

            if batch_updates:
                ws.batch_update(batch_updates, value_input_option="USER_ENTERED")

            if new_rows:
                ws.append_rows(new_rows, value_input_option="USER_ENTERED")

            # Считаем уникальные обновлённые строки (не ячейки)
            updated = len({b["range"][1:] for b in batch_updates})
            added   = len(new_rows)
            logger.info(f"sync: обновлено {updated}, добавлено {added} строк в '{sheet_name}'")
            return {"updated": updated, "added": added}

        except Exception as e:
            if attempt < retries - 1:
                logger.warning(f"Sheets sync retry {attempt + 1}: {e}")
                time.sleep(2 ** attempt)
            else:
                logger.error(f"Sheets sync error: {e}")

    return {"updated": 0, "added": 0}
