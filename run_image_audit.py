#!/usr/bin/env python3
"""
Reads all item_group_id + title values from vnxSHOP, resolves an image URL
for each via pattern matching, then batch-writes to image_link column.

Usage:
  python run_image_audit.py           # dry run — show mapping by group
  python run_image_audit.py --apply   # write to Sheets
  python run_image_audit.py --dump    # print all unique model names (for debugging)
"""

import os
import re
import sys

from dotenv import load_dotenv
load_dotenv()

from services.sheets_manager import authorize_gspread

# ── Image mapping ─────────────────────────────────────────────────────────────
# Apple CDN format: wid=1000&hei=1000 guarantees >=500x500 for Meta.
# URL segments below are taken from apple.com product page source.

_FALLBACK = "https://upload.wikimedia.org/wikipedia/commons/thumb/f/fa/Apple_logo_black.svg/1000px-Apple_logo_black.svg.png"

_BASE = "https://store.storeimages.cdn-apple.com/4982/as-images.apple.com/is/"
_Q    = "?wid=1000&hei=1000&fmt=jpeg&qlt=90"

def _u(path): return f"{_BASE}{path}{_Q}"


# Ordered list of (pattern, url) — first match wins.
# Patterns are applied to lowercase(title + " " + item_group_id).
_RULES: list[tuple[re.Pattern, str]] = []

def _r(pattern: str, url: str):
    _RULES.append((re.compile(pattern, re.IGNORECASE), url))


# ── iPhone 17 ─────────────────────────────────────────────────────────────────
_r(r"iphone\s*17\s*pro\s*max",  _u("iphone-17-pro-max-finish-select-202509"))
_r(r"iphone\s*17\s*pro\b",      _u("iphone-17-pro-finish-select-202509"))
_r(r"iphone\s*17\s*plus",       _u("iphone-17-plus-finish-select-202509"))
_r(r"iphone\s*17\s*air",        _u("iphone-17-air-finish-select-202509"))
_r(r"iphone\s*17\b",            _u("iphone-17-finish-select-202509"))

# ── iPhone 16 ─────────────────────────────────────────────────────────────────
_r(r"iphone\s*16\s*pro\s*max",  _u("iphone-16-pro-max-finish-select-202409-6-9inch-desertitanium"))
_r(r"iphone\s*16\s*pro\b",      _u("iphone-16-pro-finish-select-202409-6-3inch-desertitanium"))
_r(r"iphone\s*16\s*plus",       _u("iphone-16-plus-finish-select-202409-6-7inch-black"))
_r(r"iphone\s*16\s*e\b",        _u("iphone-16e-finish-select-202502-white"))
_r(r"iphone\s*16\b",            _u("iphone-16-finish-select-202409-6-1inch-black"))

# ── iPhone 15 ─────────────────────────────────────────────────────────────────
_r(r"iphone\s*15\s*pro\s*max",  _u("iphone-15-pro-max-black-titanium-select"))
_r(r"iphone\s*15\s*pro\b",      _u("iphone-15-pro-black-titanium-select"))
_r(r"iphone\s*15\s*plus",       _u("iphone-15-plus-black-select"))
_r(r"iphone\s*15\b",            _u("iphone-15-black-select"))

# ── iPhone 14 ─────────────────────────────────────────────────────────────────
_r(r"iphone\s*14\s*pro\s*max",  _u("iphone-14-pro-max-spacenoir-select"))
_r(r"iphone\s*14\s*pro\b",      _u("iphone-14-pro-spacenoir-select"))
_r(r"iphone\s*14\s*plus",       _u("iphone-14-plus-midnight-select"))
_r(r"iphone\s*14\b",            _u("iphone-14-midnight-select"))

# ── iPhone 13 ─────────────────────────────────────────────────────────────────
_r(r"iphone\s*13\s*pro\s*max",  _u("iphone-13-pro-max-graphite-select"))
_r(r"iphone\s*13\s*pro\b",      _u("iphone-13-pro-graphite-select"))
_r(r"iphone\s*13\s*mini",       _u("iphone-13-mini-midnight-select"))
_r(r"iphone\s*13\b",            _u("iphone-13-midnight-select"))

# ── iPhone 12 ─────────────────────────────────────────────────────────────────
_r(r"iphone\s*12\s*pro\s*max",  _u("iphone-12-pro-max-graphite-select"))
_r(r"iphone\s*12\s*pro\b",      _u("iphone-12-pro-graphite-select"))
_r(r"iphone\s*12\s*mini",       _u("iphone-12-mini-black-select"))
_r(r"iphone\s*12\b",            _u("iphone-12-black-select"))

# ── iPhone SE ─────────────────────────────────────────────────────────────────
_r(r"iphone\s*se",              _u("iphone-se-select-202203"))

# ── iPad Pro ──────────────────────────────────────────────────────────────────
_r(r"ipad\s*pro.*(m5|2025)",    _u("ipad-pro-m5-select-202505"))
_r(r"ipad\s*pro.*(m4|2024)",    _u("ipad-pro-m4-select-202405"))
_r(r"ipad\s*pro.*(m2|2022)",    _u("ipad-pro-m2-select-202212"))
_r(r"ipad\s*pro",               _u("ipad-pro-m4-select-202405"))  # generic fallback

# ── iPad Air ──────────────────────────────────────────────────────────────────
_r(r"ipad\s*air.*(m3|2025)",    _u("ipad-air-m3-select-202503"))
_r(r"ipad\s*air.*(m2|2024)",    _u("ipad-air-m2-select-202405"))
_r(r"ipad\s*air.*(m1|2022)",    _u("ipad-air-5thgen-select-202203"))
_r(r"ipad\s*air",               _u("ipad-air-m2-select-202405"))  # generic fallback

# ── iPad Mini ─────────────────────────────────────────────────────────────────
_r(r"ipad\s*mini.*(m3|2024)",   _u("ipad-mini-m3-select-202410"))
_r(r"ipad\s*mini.*(a15|2021)",  _u("ipad-mini-select-202109"))
_r(r"ipad\s*mini",              _u("ipad-mini-m3-select-202410"))

# ── iPad (base, year-based naming) ───────────────────────────────────────────
_r(r"ipad\s*2025",              _u("ipad-select-202504"))         # 11th gen
_r(r"ipad\s*2024",              _u("ipad-select-202504"))         # 11th gen
_r(r"ipad\s*2022",              _u("ipad-10thgen-select-202210")) # 10th gen
_r(r"ipad\s*2021",              _u("ipad-9thgen-select-202109"))  # 9th gen
_r(r"ipad\s*2020",              _u("ipad-8thgen-select-202009"))  # 8th gen

# ── MacBook Air ───────────────────────────────────────────────────────────────
_r(r"macbook\s*air.*(m4|2025)", _u("mba-m4-select-202503"))
_r(r"macbook\s*air.*(m3|2024)", _u("mba-m3-select-202402"))
_r(r"macbook\s*air.*(m2|2022)", _u("mba-m2-select-202206"))
_r(r"macbook\s*air.*(m1|2020)", _u("mba-m1-select-202010"))
_r(r"macbook\s*air",            _u("mba-m4-select-202503"))

# ── MacBook Pro ───────────────────────────────────────────────────────────────
_r(r"macbook\s*pro.*m4\s*max",  _u("mbp-m4-max-16-select-202411"))
_r(r"macbook\s*pro.*m4\s*pro",  _u("mbp-m4-pro-14-select-202411"))
_r(r"macbook\s*pro.*m4\b",      _u("mbp-m4-14-select-202411"))
_r(r"macbook\s*pro.*m3\s*max",  _u("mbp-m3-max-16-select-202311"))
_r(r"macbook\s*pro.*m3\s*pro",  _u("mbp-m3-pro-14-select-202311"))
_r(r"macbook\s*pro.*m3\b",      _u("mbp-m3-14-select-202311"))
_r(r"macbook\s*pro.*m2",        _u("mbp-m2-pro-select-202301"))
_r(r"macbook\s*pro",            _u("mbp-m4-pro-14-select-202411"))

# ── Mac Mini ──────────────────────────────────────────────────────────────────
_r(r"mac\s*mini.*(m4|2024)",    _u("mac-mini-m4-select-202411"))
_r(r"mac\s*mini.*(m2|2023)",    _u("mac-mini-m2-select-202301"))
_r(r"mac\s*mini",               _u("mac-mini-m4-select-202411"))

# ── iMac ──────────────────────────────────────────────────────────────────────
_r(r"imac.*(m4|2024)",          _u("imac-m4-select-202410-pink"))
_r(r"imac.*(m3|2023)",          _u("imac-m3-select-202310-pink"))
_r(r"imac",                     _u("imac-m4-select-202410-pink"))

# ── Mac Studio / Mac Pro ──────────────────────────────────────────────────────
_r(r"mac\s*studio",             _u("mac-studio-select-202503"))
_r(r"mac\s*pro",                _u("mac-pro-select-202312"))

# ── AirPods ───────────────────────────────────────────────────────────────────
_r(r"airpods\s*pro\s*2",        _u("MQTP3"))
_r(r"airpods\s*pro",            _u("MQTP3"))
_r(r"airpods\s*max",            _u("airpods-max-select-202409-midnight"))
_r(r"airpods\s*4",              _u("airpods-4-select-202409"))
_r(r"airpods",                  _u("airpods-4-select-202409"))

# ── Apple Watch ───────────────────────────────────────────────────────────────
_r(r"watch\s*ultra\s*2",        _u("watch-ultra2-hero-select-202309"))
_r(r"watch\s*ultra",            _u("watch-ultra2-hero-select-202309"))
_r(r"watch\s*(s|series)\s*10",  _u("watch-series-10-hero-select-202409"))
_r(r"watch\s*(s|series)\s*9",   _u("watch-series-9-hero-select-202309"))
_r(r"watch\s*(s|series)\s*8",   _u("watch-series-8-hero-select-202209"))
_r(r"watch\s*se",               _u("watch-se-hero-select-202309"))
_r(r"\baw\s*ultra\s*2",         _u("watch-ultra2-hero-select-202309"))
_r(r"\baw\s*10\b",              _u("watch-series-10-hero-select-202409"))
_r(r"\baw\s*9\b",               _u("watch-series-9-hero-select-202309"))
_r(r"\baw\s*se\b",              _u("watch-se-hero-select-202309"))
_r(r"apple\s*watch",            _u("watch-series-10-hero-select-202409"))

# ── Beats ─────────────────────────────────────────────────────────────────────
_r(r"beats\s*studio\s*pro",     _u("beats-studio-pro-black-select"))
_r(r"beats\s*studio\s*buds",    _u("beats-studio-buds-select"))
_r(r"beats\s*fit\s*pro",        _u("beats-fit-pro-select"))
_r(r"powerbeats\s*pro",         _u("powerbeats-pro-2-select-202503"))
_r(r"beats",                    _u("beats-studio-pro-black-select"))

# ── AirTag / HomePod ──────────────────────────────────────────────────────────
_r(r"airtag",                   _u("airtag-double-select-202104"))
_r(r"homepod\s*mini",           _u("homepod-mini-select-202110-yellow"))
_r(r"homepod",                  _u("homepod-2ndgen-select-202302-midnight"))


def resolve_image(title: str, group_id: str) -> tuple[str, str]:
    """
    Returns (url, match_type) where match_type describes how the URL was found.
    """
    probe = f"{title} {group_id}".strip()
    for pattern, url in _RULES:
        if pattern.search(probe):
            return url, "matched"
    return _FALLBACK, "fallback"


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    apply = "--apply" in sys.argv
    dump  = "--dump"  in sys.argv

    gc = authorize_gspread()
    if not gc:
        print("❌ Google Sheets недоступен")
        sys.exit(1)

    spreadsheet_id = os.getenv("SPREADSHEET_ID")
    print("🔗 Читаем vnxSHOP...")
    ws = gc.open_by_key(spreadsheet_id).worksheet("vnxSHOP")
    all_values = ws.get_all_values()
    header = all_values[0]

    def col(name):
        return header.index(name) if name in header else None

    id_idx    = col("id")
    title_idx = col("title")
    group_idx = col("item_group_id")
    image_idx = col("image_link")
    avail_idx = col("availability")

    if None in (id_idx, title_idx, image_idx):
        print("❌ Не найдены обязательные столбцы (id, title, image_link)")
        sys.exit(1)

    image_col_letter = chr(ord("A") + image_idx)

    # ── Collect rows needing images ──────────────────────────────────────────
    to_update = []

    for i, row in enumerate(all_values[1:], start=2):
        def cell(idx):
            return row[idx].strip() if idx is not None and idx < len(row) else ""

        row_id  = cell(id_idx)
        avail   = cell(avail_idx).lower()
        if not row_id or avail == "out of stock":
            continue

        old_image = cell(image_idx)
        if old_image:           # already has an image — skip
            continue

        title    = cell(title_idx)
        group_id = cell(group_idx) if group_idx else ""

        url, match_type = resolve_image(title, group_id)
        to_update.append((i, title, group_id, url, match_type))

    # ── Dump mode ────────────────────────────────────────────────────────────
    if dump:
        print(f"\n{'='*72}")
        print(f"  Строк без image_link (in stock): {len(to_update)}")
        print(f"{'='*72}")
        seen = {}
        for _, title, group_id, url, mtype in to_update:
            key = group_id or title
            if key not in seen:
                seen[key] = (url, mtype)
        for name, (url, mtype) in sorted(seen.items()):
            flag = "✅" if mtype == "matched" else "⚠️ FALLBACK"
            print(f"  {flag}  {name[:50]:<50}  {url[-50:]}")
        return

    # ── Preview ──────────────────────────────────────────────────────────────
    matched  = [r for r in to_update if r[4] == "matched"]
    fallback = [r for r in to_update if r[4] == "fallback"]

    print(f"\n{'='*72}")
    print(f"  Строк для заполнения: {len(to_update)}")
    print(f"  ✅ Matched:  {len(matched)}")
    print(f"  ⚠️  Fallback: {len(fallback)}")
    print(f"{'='*72}")

    if fallback:
        print(f"\n⚠️  Не распознаны (получат заглушку Apple logo):")
        seen_fb = set()
        for _, title, group_id, _, _ in fallback:
            key = group_id or title
            if key not in seen_fb:
                seen_fb.add(key)
                print(f"   • {key}")

    print(f"\n── Примеры matched (первые 5) ──")
    for _, title, group_id, url, _ in matched[:5]:
        print(f"  {title[:55]}")
        print(f"  → {url}")
        print()

    if not to_update:
        print("✅ Все строки уже имеют image_link. Ничего делать не нужно.")
        return

    if not apply:
        print(f"\n{'='*72}")
        print("🔍 Предпросмотр. Запусти с --apply для записи в Sheets:")
        print("   python run_image_audit.py --apply")
        print(f"{'='*72}")
        return

    # ── Apply ────────────────────────────────────────────────────────────────
    print(f"\n⏳ Записываем {len(to_update)} image_link...")

    updates = [
        {"range": f"{image_col_letter}{sheet_row}", "values": [[url]]}
        for sheet_row, _, _, url, _ in to_update
    ]

    chunk = 900
    for i in range(0, len(updates), chunk):
        ws.batch_update(updates[i:i + chunk], value_input_option="RAW")

    print(f"\n✅ Готово! Обновлено: {len(to_update)} строк")
    print(f"   Matched:  {len(matched)}")
    print(f"   Fallback: {len(fallback)}")
    if fallback:
        fb_names = {r[2] or r[1] for r in fallback}
        print(f"\n   Добавь в _RULES паттерны для этих моделей:")
        for name in sorted(fb_names):
            print(f"   • {name}")
    print("\n   Перезапусти бота: apple-restart")


if __name__ == "__main__":
    main()
