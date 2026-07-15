#!/usr/bin/env python3
"""
One-time backfill for existing vnxSHOP rows:
  1. Convert Google Drive share URLs in image_link to direct-download format
  2. Append pickup notice to description (if not already present)

Usage:
  python run_sheets_backfill.py          # dry run — preview changes, write nothing
  python run_sheets_backfill.py --apply  # write to Google Sheets
"""

import os
import re
import sys

from dotenv import load_dotenv
load_dotenv()

from services.sheets_manager import authorize_gspread
from services.sheets_writer import _PICKUP_NOTICE, _fix_image_link
from services.image_mapper import get_image_url

_GDRIVE_ANY_RE = re.compile(r"drive\.google\.com", re.IGNORECASE)


def _needs_desc_update(desc: str) -> bool:
    return _PICKUP_NOTICE not in str(desc)


def _needs_image_update(url: str) -> bool:
    """Fix Drive URLs OR fill empty image_link from model mapping."""
    if not url:
        return True   # empty → mapper will provide a URL
    return bool(_GDRIVE_ANY_RE.search(url))  # Drive URL → convert


def _resolve_image(old_url: str, title: str, item_group_id: str) -> str:
    if old_url and not _GDRIVE_ANY_RE.search(old_url):
        return old_url  # already good, no change needed (shouldn't reach here)
    if _GDRIVE_ANY_RE.search(old_url):
        return _fix_image_link(old_url)
    return get_image_url(item_group_id, title)


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
    ws = gc.open_by_key(spreadsheet_id).worksheet("vnxSHOP")

    all_values = ws.get_all_values()
    if not all_values:
        print("❌ Таблица пустая")
        sys.exit(1)

    header = all_values[0]

    try:
        desc_col_idx  = header.index("description")
        image_col_idx = header.index("image_link")
        title_col_idx = header.index("title")
    except ValueError as e:
        print(f"❌ Столбец не найден: {e}")
        sys.exit(1)

    # 1-based column letters for batch_update
    desc_col_letter  = chr(ord("A") + desc_col_idx)
    image_col_letter = chr(ord("A") + image_col_idx)

    desc_changes  = []   # (sheet_row, title, old_desc, new_desc)
    image_changes = []   # (sheet_row, title, old_url, new_url)

    for i, raw_row in enumerate(all_values[1:], start=2):
        def cell(idx):
            return raw_row[idx] if idx < len(raw_row) else ""

        row_id = cell(header.index("id")) if "id" in header else ""
        if not row_id:
            continue  # skip blank rows

        title     = cell(title_col_idx)
        old_desc  = cell(desc_col_idx)
        old_image = cell(image_col_idx)

        if _needs_desc_update(old_desc):
            new_desc = (old_desc + "\n" + _PICKUP_NOTICE).strip() if old_desc.strip() else _PICKUP_NOTICE
            desc_changes.append((i, title, old_desc, new_desc))

        group_id = cell(header.index("item_group_id")) if "item_group_id" in header else ""
        if _needs_image_update(old_image):
            new_image = _resolve_image(old_image, title, group_id)
            if new_image != old_image:
                image_changes.append((i, title, old_image, new_image))

    # ── Preview ──────────────────────────────────────────────────────────────

    print(f"\n{'='*64}")
    print(f"  Description — нужно обновить: {len(desc_changes)} строк")
    print(f"  Image link  — нужно заполнить/конвертировать: {len(image_changes)} строк")
    print(f"{'='*64}\n")

    if desc_changes:
        print(f"── Description (первые 10 из {len(desc_changes)}) ──")
        for sheet_row, title, old, new in desc_changes[:10]:
            print(f"\n  [стр {sheet_row}] {title[:55]}")
            old_preview = old if old else "(пусто)"
            print(f"  БЫЛО: {old_preview}")
            print(f"  БУДЕТ: {new}")
        if len(desc_changes) > 10:
            print(f"\n  ... и ещё {len(desc_changes) - 10} строк (все одинаковые)")

    if image_changes:
        print(f"\n── Image link ({len(image_changes)} строк) ──")
        for sheet_row, title, old, new in image_changes[:10]:
            print(f"\n  [стр {sheet_row}] {title[:55]}")
            print(f"  БЫЛО:  {old[:80]}")
            print(f"  БУДЕТ: {new[:80]}")

    if not desc_changes and not image_changes:
        print("✅ Все строки уже актуальны. Ничего менять не нужно.")
        return

    if not apply:
        print(f"\n{'='*64}")
        print("🔍 Это ПРЕДПРОСМОТР — изменений не внесено.")
        print("   Всё выглядит корректно? Запусти с --apply:")
        print("   python run_sheets_backfill.py --apply")
        print(f"{'='*64}")
        return

    # ── Apply ────────────────────────────────────────────────────────────────
    print("\n⏳ Записываем изменения...")

    updates = []

    for sheet_row, _, _, new_desc in desc_changes:
        updates.append({
            "range":  f"{desc_col_letter}{sheet_row}",
            "values": [[new_desc]],
        })

    for sheet_row, _, _, new_image in image_changes:
        updates.append({
            "range":  f"{image_col_letter}{sheet_row}",
            "values": [[new_image]],
        })

    # gspread batch_update limit is 1000 cells per request — chunk if needed
    chunk_size = 900
    for i in range(0, len(updates), chunk_size):
        ws.batch_update(updates[i:i + chunk_size], value_input_option="RAW")

    print(f"\n✅ Готово!")
    print(f"   Description обновлено: {len(desc_changes)} строк")
    print(f"   Image link  конвертировано: {len(image_changes)} строк")
    print("\n   Перезапусти бота:")
    print("   apple-restart")


if __name__ == "__main__":
    main()
