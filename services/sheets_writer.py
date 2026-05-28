import logging
import os
import time
from typing import List, Dict, Any

import gspread.utils as gu

from services.sheets_manager import authorize_gspread

logger = logging.getLogger(__name__)

# Полная схема столбцов vnxSHOP (31 столбец, Facebook Commerce формат)
_COLUMNS = [
    "id", "title", "description", "availability", "condition",
    "price", "link", "image_link", "brand", "google_product_category",
    "fb_product_category", "quantity_to_sell_on_facebook", "sale_price",
    "sale_price_effective_date", "item_group_id", "gender", "color",
    "size", "age_group", "material", "pattern", "shipping",
    "shipping_weight", "gtin", "video[0].url", "video[0].tag[0]",
    "product_tags[0]", "product_tags[1]", "style[0]",
    "memory_ssd", "region_custom",
]

_DEFAULTS: Dict[str, str] = {
    "description":                  "",
    "availability":                 "in stock",
    "condition":                    "new",
    "link":                         "",
    "image_link":                   "",
    "brand":                        "Apple",
    "google_product_category":      "Electronics > Communications > Telephony > Mobile Phones",
    "fb_product_category":          "",
    "quantity_to_sell_on_facebook": "",
    "sale_price":                   "",
    "sale_price_effective_date":    "",
    "gender":                       "",
    "size":                         "",
    "age_group":                    "",
    "material":                     "",
    "pattern":                      "",
    "shipping":                     "",
    "shipping_weight":              "",
    "gtin":                         "",
    "video[0].url":                 "",
    "video[0].tag[0]":              "",
    "product_tags[0]":              "",
    "product_tags[1]":              "",
    "style[0]":                     "",
    "region_custom":                "",
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
    - Существующие товары (совпадение по id): обновляет только цену и availability.
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
                # Лист пуст — создаём заголовок и добавляем всё как новое
                ws.update([_COLUMNS], value_input_option="USER_ENTERED")
                ws.append_rows(
                    [_build_row(item, _COLUMNS) for item in items],
                    value_input_option="USER_ENTERED",
                )
                return {"updated": 0, "added": len(items)}

            header = all_values[0]

            # Найдём индексы нужных столбцов (1-based для gspread)
            try:
                id_col    = header.index("id") + 1
                price_col = header.index("price") + 1
                avail_col = header.index("availability") + 1
            except ValueError as e:
                logger.error(f"Столбец не найден в заголовке: {e}")
                return {"updated": 0, "added": 0}

            # Карта: id → номер строки (1-based, строка 1 = заголовок)
            id_to_row: Dict[str, int] = {}
            for row_idx, row in enumerate(all_values[1:], start=2):
                cell_id = row[id_col - 1].strip() if len(row) >= id_col else ""
                if cell_id:
                    id_to_row[cell_id] = row_idx

            # Разделяем на обновления и новые строки
            price_updates: List[Dict] = []
            new_rows: List[List[str]] = []

            for item in items:
                item_id = item.get("id", "")
                if item_id in id_to_row:
                    row_num = id_to_row[item_id]
                    price_a1 = gu.rowcol_to_a1(row_num, price_col)
                    avail_a1 = gu.rowcol_to_a1(row_num, avail_col)
                    price_updates.append({"range": price_a1, "values": [[item["price"]]]})
                    price_updates.append({"range": avail_a1, "values": [["in stock"]]})
                else:
                    new_rows.append(_build_row(item, header))

            # Батч-обновление цен
            if price_updates:
                ws.batch_update(price_updates, value_input_option="USER_ENTERED")

            # Добавление новых строк
            if new_rows:
                ws.append_rows(new_rows, value_input_option="USER_ENTERED")

            updated = len(price_updates) // 2   # каждый товар = 2 ячейки (price + availability)
            added   = len(new_rows)
            logger.info(
                f"sync_price_list: обновлено {updated}, добавлено {added} строк в '{sheet_name}'"
            )
            return {"updated": updated, "added": added}

        except Exception as e:
            if attempt < retries - 1:
                logger.warning(f"Sheets sync retry {attempt + 1}: {e}")
                time.sleep(2 ** attempt)
            else:
                logger.error(f"Sheets sync error: {e}")

    return {"updated": 0, "added": 0}
