#!/usr/bin/env python3
"""
One-time cleanup: mark non-Apple items in vnxSHOP as "out of stock".

Detects:
  - Samsung (Galaxy, S24, A56, M55, Z Flip, etc.)
  - DJI, Sony, Xiaomi, Mi, Poco, Honor, Huawei, and other non-Apple brands

Items are NOT deleted — availability is set to "out of stock" so they stay
in Sheets for review but are excluded from channel publishing.

Usage:
  python run_sheets_cleanup.py          # dry run (preview only)
  python run_sheets_cleanup.py --apply  # actually write changes
"""

import os
import re
import sys

from dotenv import load_dotenv
load_dotenv()

from services.sheets_manager import authorize_gspread

# ── Non-Apple detection patterns ─────────────────────────────────────────────

_NON_APPLE_RE = re.compile(
    r"^("
    # Samsung
    r"Samsung\b|Galaxy\b|"
    r"S\d{1,2}\s|S\d{1,2}$|"    # S24, S25 Ultra — but not "SE"
    r"A\d{2}\b|"                  # A56, A16
    r"M\d{2}\b|"                  # M55, M56
    r"Z\s+(?:Flip|Fold)|"         # Z Flip6, Z Fold6
    # Other brands
    r"DJI\b|"
    r"Sony\b|"
    r"Xiaomi\b|Mi\s+\d|POCO\b|"
    r"Honor\b|Huawei\b|"
    r"OnePlus\b|Oppo\b|Vivo\b|Realme\b|"
    r"Garmin\b|Fitbit\b"
    r")", re.IGNORECASE
)

# Бренды, которые ловим в любом месте строки — поставщики часто пишут
# "Беспроводной микрофон DJI Mic 2", "Наушники Sony WH-1000XM5" и т.п.
_BRAND_ANYWHERE_RE = re.compile(
    r"\b(Samsung|Galaxy|DJI|Sony|Xiaomi|POCO|Honor|Huawei|OnePlus|"
    r"Oppo|Vivo|Realme|Garmin|Fitbit|Nothing\s+Phone|Tecno|Infinix|"
    r"Insta360|GoPro|Anker|Baseus|Ugreen|JBL|Marshall|Bose|Sennheiser|Pitaka|Spigen|Nillkin|Belkin|"
    # Honor Magic 8 Pro и т.п. Цифра сразу после "Magic" обязательна:
    # у Apple есть Magic Keyboard и Magic Mouse, их трогать нельзя.
    r"Magic\s+\d)\b",
    re.IGNORECASE,
)

# Samsung-style RAM/Storage notation: "12/256", "8/128" — never used by Apple.
# Catches disguised Samsung items like "Apple 9 Pro Fold 12/256".
_SAMSUNG_RAM_RE = re.compile(r"\b\d{1,2}/\d{1,4}\b")

# Та же запись, но с пробелом после дроби: "8/ 256GB", "16/ 1TB".
# Так поставщики пишут Honor и Xiaomi: "Apple Magic 8 Pro 16/ 512GB",
# "Apple 9 Pro Fold 16/ 256GB". Apple объём ОЗУ в названии не указывает
# вообще, поэтому дробь перед объёмом памяти — надёжный признак чужого бренда.
_RAM_STORAGE_RE = re.compile(r"\b\d{1,2}\s*/\s*\d{2,4}\s*(?:GB|TB)\b", re.IGNORECASE)

# Обрезанный item_group_id вида "Apple 7 8/", "Apple Magic 8 Pro 16/" —
# хвост той же записи, оставшийся после обрезки названия по объёму памяти.
_TRAILING_RAM_RE = re.compile(r"\b\d{1,2}\s*/\s*$")

# ИСКЛЮЧЕНИЕ из правила дроби: у компьютеров Mac запись "16/256" (ОЗУ/SSD)
# совершенно законна, её используют все продавцы — "MacBook Air M4 16/256".
# Без этой оговорки эвристика дроби вычищает из наличия все макбуки разом.
_MAC_RE = re.compile(r"\b(macbook|imac|mac\s*mini|mac\s*studio|mac\s*pro|mac\s+m\d)\b",
                     re.IGNORECASE)

# "Apple" brand is the default in _DEFAULTS, so non-Apple items often have
# brand set to "Apple" anyway. We detect by title/item_group_id instead.

_APPLE_PREFIX_RE = re.compile(r"^Apple\s+", re.IGNORECASE)

# Не-техника: тестовые и сувенирные позиции, попадающие от поставщиков
# ("Blue Facebook T-Shirt (Unisex)"). В фид Meta им тоже не место.
_NON_TECH_RE = re.compile(r"T-Shirt|Футболк|Одежд|Толстовк|Худи\b", re.IGNORECASE)


def _is_non_apple(row: dict) -> bool:
    """
    Returns True if the row is clearly a non-Apple product.
    Checks title and item_group_id against non-Apple brand patterns.
    Also detects Samsung items mislabeled as "Apple S24", "Apple Z Flip7", etc.
    """
    brand = str(row.get("brand", "")).strip()
    # Explicit non-Apple brand field
    if brand and brand.lower() not in ("apple", ""):
        text = brand
        if _NON_APPLE_RE.match(text):
            return True

    # Check item_group_id and title
    for field in ("item_group_id", "title"):
        val = str(row.get(field, "")).strip()
        if not val:
            continue

        if _NON_TECH_RE.search(val):
            return True

        if _NON_APPLE_RE.match(val):
            return True

        if _BRAND_ANYWHERE_RE.search(val):
            return True

        # Запись ОЗУ через дробь — чужой бренд независимо от префикса "Apple".
        # Кроме Mac: там "16/256" означает ОЗУ/SSD и совершенно законно.
        if not _MAC_RE.search(val):
            if _RAM_STORAGE_RE.search(val) or _TRAILING_RAM_RE.search(val):
                return True

        # Also strip "Apple " prefix and re-check.
        # Catches "Apple S24 8/", "Apple Z Flip7", "Apple M55 8/" etc.
        val_stripped = _APPLE_PREFIX_RE.sub("", val).strip()
        if val_stripped != val:
            if _NON_APPLE_RE.match(val_stripped):
                return True
            # Samsung-style RAM/storage notation not used by Apple —
            # но у Mac "16/256" это ОЗУ/SSD и писать так нормально
            if _SAMSUNG_RAM_RE.search(val_stripped) and not _MAC_RE.search(val):
                return True

    return False


def main():
    apply = "--apply" in sys.argv

    gc = authorize_gspread()
    if not gc:
        print("❌ Нет доступа к Google Sheets — проверь GOOGLE_CREDENTIALS_JSON в .env")
        sys.exit(1)

    spreadsheet_id = os.getenv("SPREADSHEET_ID")
    if not spreadsheet_id:
        print("❌ SPREADSHEET_ID не задан в .env")
        sys.exit(1)

    print("🔗 Подключаемся к Google Sheets...")
    spreadsheet = gc.open_by_key(spreadsheet_id)
    ws = spreadsheet.worksheet("vnxSHOP")

    all_values = ws.get_all_values()
    if not all_values:
        print("❌ Таблица пустая")
        sys.exit(1)

    header = all_values[0]
    try:
        avail_col_idx = header.index("availability")  # 0-based
        avail_col_letter = chr(ord("A") + avail_col_idx)  # e.g. "D"
    except ValueError:
        print("❌ Столбец 'availability' не найден в первой строке")
        sys.exit(1)

    # Build dict rows (same as get_all_records but with sheet row numbers)
    to_mark: list[tuple[int, dict]] = []   # (sheet_row_1indexed, row_dict)

    for i, raw_row in enumerate(all_values[1:], start=2):  # sheet row 2..N
        row = {}
        for j, col in enumerate(header):
            row[col] = raw_row[j] if j < len(raw_row) else ""

        if not row.get("id"):
            continue  # skip blank rows

        if str(row.get("availability", "")).strip().lower() == "out of stock":
            continue  # already excluded

        if _is_non_apple(row):
            to_mark.append((i, row))

    if not to_mark:
        print("✅ Не найдено не-Apple товаров в статусе 'in stock'. Таблица чиста.")
        return

    # Preview
    print(f"\n{'='*60}")
    print(f"  Найдено не-Apple товаров: {len(to_mark)}")
    print(f"{'='*60}")
    for sheet_row, row in to_mark:
        group  = row.get("item_group_id") or row.get("title", "?")
        title  = row.get("title", "")
        status = row.get("availability", "")
        print(f"  [строка {sheet_row:>3}]  {group[:45]:<45}  ({status})")
        if title and title != group:
            print(f"             title: {title[:60]}")
    print()

    if not apply:
        print("🔍 Это ПРЕДПРОСМОТР — изменений не внесено.")
        print("   Запусти с флагом --apply чтобы пометить как 'out of stock':")
        print("   python run_sheets_cleanup.py --apply")
        return

    # Apply: batch-update the availability column
    print("⏳ Записываем изменения...")

    # Build batch update: list of {'range': 'D5', 'values': [['out of stock']]}
    updates = []
    for sheet_row, _ in to_mark:
        cell = f"{avail_col_letter}{sheet_row}"
        updates.append({"range": cell, "values": [["out of stock"]]})

    # gspread batch_update expects format: ws.batch_update([{range, values}, ...])
    ws.batch_update(updates, value_input_option="RAW")

    print(f"\n✅ Готово! Помечено 'out of stock': {len(to_mark)} строк.")
    print("   Перезапусти бота чтобы каталог перегрузился:")
    print("   systemctl restart vnx-apple-shop.service")


if __name__ == "__main__":
    main()
