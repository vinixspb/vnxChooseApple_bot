import logging
import os
import re
import time
from typing import List, Dict, Any

import gspread
import gspread.utils as gu

from services.sheets_manager import authorize_gspread
from services.image_mapper import get_image_url

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

# Meta Commerce Manager requirement: quantity must not be empty when in stock.
_IN_STOCK_QTY = "10"

# Required by Meta to bypass courier delivery requirement check.
_PICKUP_NOTICE = (
    "⚠️ Внимание: Товар доступен только для самовывоза. "
    "Доставка курьерскими службами не осуществляется."
)

_DEFAULTS: Dict[str, str] = {
    "description":                  _PICKUP_NOTICE,
    "availability":                 "in stock",
    "condition":                    "new",
    "link":                         "https://www.apple.com",
    "image_link":                   "",
    "brand":                        "Apple",
    "google_product_category":      "Electronics",
    "fb_product_category":          "",
    "quantity_to_sell_on_facebook": _IN_STOCK_QTY,
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

# Google Drive share link patterns → direct-download URL
_GDRIVE_FILE_RE = re.compile(
    r"https?://drive\.google\.com/file/d/([^/?#]+)", re.IGNORECASE
)
_GDRIVE_OPEN_RE = re.compile(
    r"https?://drive\.google\.com/open\?id=([^&]+)", re.IGNORECASE
)


def _fix_image_link(url: str) -> str:
    """
    Convert Google Drive share URLs to direct-download format so Meta
    crawlers can fetch the file (status 200, raw image bytes).
    Other URLs are returned unchanged.
    """
    if not url:
        return url
    m = _GDRIVE_FILE_RE.search(url) or _GDRIVE_OPEN_RE.search(url)
    if m:
        return f"https://drive.google.com/uc?export=download&id={m.group(1)}"
    return url


def _build_row(item: Dict[str, Any], header: List[str]) -> List[str]:
    merged = {**_DEFAULTS, **item}

    # quantity: in stock → _IN_STOCK_QTY, out of stock → 0
    avail = str(merged.get("availability", "")).strip().lower()
    if avail == "out of stock":
        merged["quantity_to_sell_on_facebook"] = "0"
    elif not merged.get("quantity_to_sell_on_facebook"):
        merged["quantity_to_sell_on_facebook"] = _IN_STOCK_QTY

    # description: append pickup notice if not already present
    desc = str(merged.get("description", "")).strip()
    if _PICKUP_NOTICE not in desc:
        merged["description"] = (desc + "\n" + _PICKUP_NOTICE).strip() if desc else _PICKUP_NOTICE

    # image_link: convert Drive share URLs; auto-fill from model mapping if empty
    image = _fix_image_link(str(merged.get("image_link", "")))
    if not image:
        image = get_image_url(
            str(merged.get("item_group_id", "")),
            str(merged.get("title", "")),
        )
    merged["image_link"] = image

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
                qty_col      = header.index("quantity_to_sell_on_facebook") + 1 if "quantity_to_sell_on_facebook" in header else None
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
                    # Обновляем продажную цену, закупочную, наличие и количество
                    batch_updates.append({
                        "range": gu.rowcol_to_a1(row_num, price_col),
                        "values": [[item["price"]]],
                    })
                    batch_updates.append({
                        "range": gu.rowcol_to_a1(row_num, avail_col),
                        "values": [["in stock"]],
                    })
                    if qty_col:
                        batch_updates.append({
                            "range": gu.rowcol_to_a1(row_num, qty_col),
                            "values": [[_IN_STOCK_QTY]],
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


_SYNCLOG_HEADERS = ["timestamp", "source", "updated", "added", "catalog_size"]


def write_sync_log(
    timestamp: str,
    source: str,
    updated: int,
    added: int,
    catalog_size: int,
) -> None:
    """
    Appends one row to the SyncLog sheet.
    Non-critical: errors are logged but never raised.
    """
    gc = authorize_gspread()
    if not gc:
        return

    spreadsheet_id = os.getenv("SPREADSHEET_ID")
    for attempt in range(2):
        try:
            spreadsheet = gc.open_by_key(spreadsheet_id)
            try:
                ws = spreadsheet.worksheet("SyncLog")
            except gspread.exceptions.WorksheetNotFound:
                ws = spreadsheet.add_worksheet("SyncLog", rows=500, cols=6)
                ws.update([_SYNCLOG_HEADERS], value_input_option="USER_ENTERED")
                ws.format("A1:E1", {"textFormat": {"bold": True}})

            ws.append_rows(
                [[timestamp, source, updated, added, catalog_size]],
                value_input_option="USER_ENTERED",
            )
            return
        except Exception as e:
            if attempt == 0:
                time.sleep(1)
            else:
                logger.warning(f"write_sync_log: {e}")


def get_last_sync_log() -> dict:
    """
    Returns the last row of SyncLog as a dict, or {} if unavailable.
    Used by /status when LAST_SYNC is empty (fresh restart).
    """
    gc = authorize_gspread()
    if not gc:
        return {}

    spreadsheet_id = os.getenv("SPREADSHEET_ID")
    try:
        ws = gc.open_by_key(spreadsheet_id).worksheet("SyncLog")
        rows = ws.get_all_values()
        if len(rows) < 2:
            return {}
        last = rows[-1]
        return {
            "time_str": last[0] if len(last) > 0 else "",
            "source":   last[1] if len(last) > 1 else "",
            "updated":  last[2] if len(last) > 2 else "0",
            "added":    last[3] if len(last) > 3 else "0",
            "catalog":  last[4] if len(last) > 4 else "0",
        }
    except Exception:
        return {}
