"""
Maps Apple product model names to official high-resolution image URLs.

Priority:
  1. Exact model match in _MODEL_IMAGES
  2. Pattern match (contains check) in _PATTERN_IMAGES
  3. Category fallback in _CATEGORY_FALLBACK
  4. Generic Apple logo placeholder

All URLs use Apple CDN with wid=1000&hei=1000 to guarantee >= 500x500 px
as required by Meta Commerce Manager. Individual image paths are taken from
Apple's product pages (right-click image → Copy image address on apple.com).
"""

import re

# ── Exact group → URL ────────────────────────────────────────────────────────
# Key = item_group_id as it appears in the channel (already normalized,
# "Apple " prefix stripped). Case-insensitive match is done at lookup time.

_MODEL_IMAGES: dict[str, str] = {
    # ── iPhone Duo (складной, сентябрь 2026) ───────────────────────────────
    # У Duo цвет зашит в сам ID картинки, единого фото модели нет.
    # Берём Star White как основное — как и для остальных групп, одна
    # фотография на всю группу независимо от расцветки позиции.
    "iPhone Duo": "https://store.storeimages.cdn-apple.com/4982/as-images.apple.com/is/iphone-duo-finish-select-star-white-202609_AV2?wid=1000&hei=1000&fmt=jpeg&qlt=90",

    # ── iPhone 18 ──────────────────────────────────────────────────────────
    "iPhone 18 Pro": "https://store.storeimages.cdn-apple.com/4982/as-images.apple.com/is/iphone-18-pro-finish-select-202609?wid=1000&hei=1000&fmt=jpeg&qlt=90",

    # ── iPhone 17 ──────────────────────────────────────────────────────────
    "iPhone 17 Pro Max": "https://store.storeimages.cdn-apple.com/4982/as-images.apple.com/is/iphone-17-pro-max-finish-select-202509?wid=1000&hei=1000&fmt=jpeg&qlt=90",
    "iPhone 17 Pro":     "https://store.storeimages.cdn-apple.com/4982/as-images.apple.com/is/iphone-17-pro-finish-select-202509?wid=1000&hei=1000&fmt=jpeg&qlt=90",
    "iPhone 17 Plus":    "https://store.storeimages.cdn-apple.com/4982/as-images.apple.com/is/iphone-17-plus-finish-select-202509?wid=1000&hei=1000&fmt=jpeg&qlt=90",
    "iPhone 17 Air":     "https://store.storeimages.cdn-apple.com/4982/as-images.apple.com/is/iphone-17-air-finish-select-202509?wid=1000&hei=1000&fmt=jpeg&qlt=90",
    "iPhone 17":         "https://store.storeimages.cdn-apple.com/4982/as-images.apple.com/is/iphone-17-finish-select-202509?wid=1000&hei=1000&fmt=jpeg&qlt=90",

    # ── iPhone 16 ──────────────────────────────────────────────────────────
    "iPhone 16 Pro Max": "https://store.storeimages.cdn-apple.com/4982/as-images.apple.com/is/iphone-16-pro-max-finish-select-202409-6-9inch-desertitanium?wid=1000&hei=1000&fmt=jpeg&qlt=90",
    "iPhone 16 Pro":     "https://store.storeimages.cdn-apple.com/4982/as-images.apple.com/is/iphone-16-pro-finish-select-202409-6-3inch-desertitanium?wid=1000&hei=1000&fmt=jpeg&qlt=90",
    "iPhone 16 Plus":    "https://store.storeimages.cdn-apple.com/4982/as-images.apple.com/is/iphone-16-plus-finish-select-202409-6-7inch-black?wid=1000&hei=1000&fmt=jpeg&qlt=90",
    "iPhone 16":         "https://store.storeimages.cdn-apple.com/4982/as-images.apple.com/is/iphone-16-finish-select-202409-6-1inch-black?wid=1000&hei=1000&fmt=jpeg&qlt=90",

    # ── iPhone 15 ──────────────────────────────────────────────────────────
    "iPhone 15 Pro Max": "https://store.storeimages.cdn-apple.com/4982/as-images.apple.com/is/iphone-15-pro-max-black-titanium-select?wid=1000&hei=1000&fmt=jpeg&qlt=90",
    "iPhone 15 Pro":     "https://store.storeimages.cdn-apple.com/4982/as-images.apple.com/is/iphone-15-pro-black-titanium-select?wid=1000&hei=1000&fmt=jpeg&qlt=90",
    "iPhone 15 Plus":    "https://store.storeimages.cdn-apple.com/4982/as-images.apple.com/is/iphone-15-plus-black-select?wid=1000&hei=1000&fmt=jpeg&qlt=90",
    "iPhone 15":         "https://store.storeimages.cdn-apple.com/4982/as-images.apple.com/is/iphone-15-black-select?wid=1000&hei=1000&fmt=jpeg&qlt=90",

    # ── iPhone 14 ──────────────────────────────────────────────────────────
    "iPhone 14 Pro Max": "https://store.storeimages.cdn-apple.com/4982/as-images.apple.com/is/iphone-14-pro-max-spacenoir-select?wid=1000&hei=1000&fmt=jpeg&qlt=90",
    "iPhone 14 Pro":     "https://store.storeimages.cdn-apple.com/4982/as-images.apple.com/is/iphone-14-pro-spacenoir-select?wid=1000&hei=1000&fmt=jpeg&qlt=90",
    "iPhone 14 Plus":    "https://store.storeimages.cdn-apple.com/4982/as-images.apple.com/is/iphone-14-plus-midnight-select?wid=1000&hei=1000&fmt=jpeg&qlt=90",
    "iPhone 14":         "https://store.storeimages.cdn-apple.com/4982/as-images.apple.com/is/iphone-14-midnight-select?wid=1000&hei=1000&fmt=jpeg&qlt=90",

    # ── iPhone 13 ──────────────────────────────────────────────────────────
    "iPhone 13 Pro Max": "https://store.storeimages.cdn-apple.com/4982/as-images.apple.com/is/iphone-13-pro-max-graphite-select?wid=1000&hei=1000&fmt=jpeg&qlt=90",
    "iPhone 13 Pro":     "https://store.storeimages.cdn-apple.com/4982/as-images.apple.com/is/iphone-13-pro-graphite-select?wid=1000&hei=1000&fmt=jpeg&qlt=90",
    "iPhone 13 mini":    "https://store.storeimages.cdn-apple.com/4982/as-images.apple.com/is/iphone-13-mini-midnight-select?wid=1000&hei=1000&fmt=jpeg&qlt=90",
    "iPhone 13":         "https://store.storeimages.cdn-apple.com/4982/as-images.apple.com/is/iphone-13-midnight-select?wid=1000&hei=1000&fmt=jpeg&qlt=90",

    # ── iPhone SE ──────────────────────────────────────────────────────────
    "iPhone SE":  "https://store.storeimages.cdn-apple.com/4982/as-images.apple.com/is/iphone-se-select-202203?wid=1000&hei=1000&fmt=jpeg&qlt=90",

    # ── iPad ───────────────────────────────────────────────────────────────
    "iPad Pro M5":   "https://store.storeimages.cdn-apple.com/4982/as-images.apple.com/is/ipad-pro-m5-select-202505?wid=1000&hei=1000&fmt=jpeg&qlt=90",
    "iPad Pro M4":   "https://store.storeimages.cdn-apple.com/4982/as-images.apple.com/is/ipad-pro-m4-select-202405?wid=1000&hei=1000&fmt=jpeg&qlt=90",
    "iPad Air M3":   "https://store.storeimages.cdn-apple.com/4982/as-images.apple.com/is/ipad-air-m3-select-202503?wid=1000&hei=1000&fmt=jpeg&qlt=90",
    "iPad Air M2":   "https://store.storeimages.cdn-apple.com/4982/as-images.apple.com/is/ipad-air-m2-select-202405?wid=1000&hei=1000&fmt=jpeg&qlt=90",
    "iPad Mini M3":  "https://store.storeimages.cdn-apple.com/4982/as-images.apple.com/is/ipad-mini-m3-select-202410?wid=1000&hei=1000&fmt=jpeg&qlt=90",

    # ── Mac ────────────────────────────────────────────────────────────────
    "MacBook Air M4":    "https://store.storeimages.cdn-apple.com/4982/as-images.apple.com/is/mba-m4-select-202503?wid=1000&hei=1000&fmt=jpeg&qlt=90",
    "MacBook Air M3":    "https://store.storeimages.cdn-apple.com/4982/as-images.apple.com/is/mba-m3-select-202402?wid=1000&hei=1000&fmt=jpeg&qlt=90",
    "MacBook Air M2":    "https://store.storeimages.cdn-apple.com/4982/as-images.apple.com/is/mba-m2-select-202206?wid=1000&hei=1000&fmt=jpeg&qlt=90",
    "MacBook Pro M4 Pro":"https://store.storeimages.cdn-apple.com/4982/as-images.apple.com/is/mbp-m4-pro-14-select-202411?wid=1000&hei=1000&fmt=jpeg&qlt=90",
    "MacBook Pro M4":    "https://store.storeimages.cdn-apple.com/4982/as-images.apple.com/is/mbp-m4-14-select-202411?wid=1000&hei=1000&fmt=jpeg&qlt=90",
    "MacBook Pro M3 Pro":"https://store.storeimages.cdn-apple.com/4982/as-images.apple.com/is/mbp-m3-pro-14-select-202311?wid=1000&hei=1000&fmt=jpeg&qlt=90",
    "MacBook Pro M3":    "https://store.storeimages.cdn-apple.com/4982/as-images.apple.com/is/mbp-m3-14-select-202311?wid=1000&hei=1000&fmt=jpeg&qlt=90",
    "Mac Mini M4":       "https://store.storeimages.cdn-apple.com/4982/as-images.apple.com/is/mac-mini-m4-select-202411?wid=1000&hei=1000&fmt=jpeg&qlt=90",
    "Mac Mini M2":       "https://store.storeimages.cdn-apple.com/4982/as-images.apple.com/is/mac-mini-m2-select-202301?wid=1000&hei=1000&fmt=jpeg&qlt=90",
    "iMac M4":           "https://store.storeimages.cdn-apple.com/4982/as-images.apple.com/is/imac-m4-select-202410-pink?wid=1000&hei=1000&fmt=jpeg&qlt=90",

    # ── AirPods ────────────────────────────────────────────────────────────
    "AirPods Pro 2":  "https://store.storeimages.cdn-apple.com/4982/as-images.apple.com/is/MQTP3?wid=1000&hei=1000&fmt=jpeg&qlt=90",
    "AirPods 4":      "https://store.storeimages.cdn-apple.com/4982/as-images.apple.com/is/airpods-4-select-202409?wid=1000&hei=1000&fmt=jpeg&qlt=90",
    "AirPods Max":    "https://store.storeimages.cdn-apple.com/4982/as-images.apple.com/is/airpods-max-select-202409-midnight?wid=1000&hei=1000&fmt=jpeg&qlt=90",

    # ── Apple Watch ────────────────────────────────────────────────────────
    "Apple Watch Series 10": "https://store.storeimages.cdn-apple.com/4982/as-images.apple.com/is/watch-series-10-hero-select-202409?wid=1000&hei=1000&fmt=jpeg&qlt=90",
    "Apple Watch Ultra 2":   "https://store.storeimages.cdn-apple.com/4982/as-images.apple.com/is/watch-ultra2-hero-select-202309?wid=1000&hei=1000&fmt=jpeg&qlt=90",
    "Apple Watch SE":        "https://store.storeimages.cdn-apple.com/4982/as-images.apple.com/is/watch-se-hero-select-202309?wid=1000&hei=1000&fmt=jpeg&qlt=90",
}

# ── Category-level fallbacks (when no model match found) ────────────────────
_CATEGORY_FALLBACK: dict[str, str] = {
    "iphone":  "https://store.storeimages.cdn-apple.com/4982/as-images.apple.com/is/iphone-16-finish-select-202409-6-1inch-black?wid=1000&hei=1000&fmt=jpeg&qlt=90",
    "ipad":    "https://store.storeimages.cdn-apple.com/4982/as-images.apple.com/is/ipad-air-m2-select-202405?wid=1000&hei=1000&fmt=jpeg&qlt=90",
    "mac":     "https://store.storeimages.cdn-apple.com/4982/as-images.apple.com/is/mba-m4-select-202503?wid=1000&hei=1000&fmt=jpeg&qlt=90",
    "airpods": "https://store.storeimages.cdn-apple.com/4982/as-images.apple.com/is/airpods-4-select-202409?wid=1000&hei=1000&fmt=jpeg&qlt=90",
    "watch":   "https://store.storeimages.cdn-apple.com/4982/as-images.apple.com/is/watch-series-10-hero-select-202409?wid=1000&hei=1000&fmt=jpeg&qlt=90",
    "beats":   "https://store.storeimages.cdn-apple.com/4982/as-images.apple.com/is/beats-studio-pro-black-select?wid=1000&hei=1000&fmt=jpeg&qlt=90",
}

# Generic Apple logo fallback (hosted on Wikipedia Commons — public, stable)
_GENERIC_FALLBACK = (
    "https://upload.wikimedia.org/wikipedia/commons/thumb/f/fa/"
    "Apple_logo_black.svg/1000px-Apple_logo_black.svg.png"
)

# Pre-process lookup table with lowercase keys for fast case-insensitive matching
_MODEL_LOOKUP: dict[str, str] = {k.lower(): v for k, v in _MODEL_IMAGES.items()}


def _detect_category(text: str) -> str:
    t = text.lower()
    if "iphone" in t:         return "iphone"
    if "airpods" in t:        return "airpods"
    if "ipad" in t:           return "ipad"
    if "macbook" in t or "mac" in t or "imac" in t: return "mac"
    if "watch" in t:          return "watch"
    if "beats" in t:          return "beats"
    return ""


_APPLE_PREFIX_RE = re.compile(r"^Apple\s+", re.IGNORECASE)


def get_image_url(item_group_id: str, title: str = "") -> str:
    """
    Return a >=500x500 Apple image URL for the given product.
    Falls back through: exact model → category → generic Apple logo.

    Префикс "Apple " снимается перед поиском. Парсер собирает
    item_group_id как "Apple iPhone 17 Pro Max", а ключи словаря — без
    префикса. Без снятия ни точное, ни префиксное совпадение не срабатывало,
    и КАЖДЫЙ iPhone проваливался в категорийную заглушку с фото iPhone 16.
    """
    probe = (item_group_id or title or "").strip()
    probe = _APPLE_PREFIX_RE.sub("", probe).strip()
    probe_lc = probe.lower()

    # 1. Exact match
    if probe_lc in _MODEL_LOOKUP:
        return _MODEL_LOOKUP[probe_lc]

    # 2. Longest prefix match (e.g. "iPhone 16 Pro 256GB Blue" → "iPhone 16 Pro")
    best_key = ""
    for key in _MODEL_LOOKUP:
        if probe_lc.startswith(key) and len(key) > len(best_key):
            best_key = key
    if best_key:
        return _MODEL_LOOKUP[best_key]

    # 3. Category fallback
    cat = _detect_category(probe)
    if cat and cat in _CATEGORY_FALLBACK:
        return _CATEGORY_FALLBACK[cat]

    # 4. Generic Apple logo
    return _GENERIC_FALLBACK
