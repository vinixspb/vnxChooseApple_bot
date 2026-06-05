import re
from typing import List, Dict

# Compiled once — strips all emoji, flags, variation selectors
_EMOJI_RE = re.compile(
    r"[\U0001F1E6-\U0001F1FF]{2}"   # country flags  🇺🇸 🇷🇺
    r"|[\U0001F300-\U0001F9FF]"      # misc symbols & pictographs
    r"|[\U0001FA00-\U0001FA9F]"      # extended pictographs
    r"|[☀-➿]"             # dingbats / misc symbols (☀ ⚫ ✅ ...)
    r"|[︀-️]"             # variation selectors (️ after ⚫)
    r"|[®©™]+",
    re.UNICODE,
)

# ── Brand detection ───────────────────────────────────────────────────────────
# Known Apple device prefixes / shorthand patterns
_APPLE_MODEL_RE = re.compile(
    r"^("
    r"iPad|iPhone|MacBook|Mac\s|Mac$|iMac|AirPods|HomePod|Beats|"
    r"Mini\b|"           # iPad Mini shorthand
    r"Air\b|"            # iPad Air / iPhone 17 Air shorthand
    r"Pro\s+M\d|"        # iPad Pro M4/M5
    r"Pro\s+Max|"        # iPhone Pro Max shorthand
    r"1[5-9](?:\s|$)|"  # iPhone 15, 16, 17, 18, 19
    r"2\d(?:\s|$)"       # iPhone 20+
    r")", re.IGNORECASE
)

# Known non-Apple brand patterns (Samsung, etc.)
_SAMSUNG_RE = re.compile(
    r"^("
    r"Samsung\b|Galaxy\b|"
    r"S\d{1,2}\b|"       # Galaxy S10, S24, S25, S26
    r"A\d{2}\b|"         # Galaxy A16, A56
    r"M\d{2}\b|"         # Galaxy M55, M56  (NOT M4/M5 Apple chip: requires 2 digits)
    r"Z\s+(?:Flip|Fold)" # Galaxy Z Flip6, Z Fold
    r")", re.IGNORECASE
)


def _detect_brand(model_part: str) -> str:
    """
    Returns 'Apple', 'Samsung', or 'Unknown'.
    Apple whitelist-first: if it looks like an Apple device, it's Apple.
    Then Samsung patterns. Everything else is Unknown and gets skipped.
    """
    mp = model_part.strip()
    if _APPLE_MODEL_RE.match(mp):
        return "Apple"
    if _SAMSUNG_RE.match(mp):
        return "Samsung"
    return "Unknown"


def _strip_emoji(text: str) -> str:
    return _EMOJI_RE.sub("", text).strip()


def _parse_memory(token: str) -> str:
    """'256' → '256GB', '1Tb' → '1TB'"""
    token = token.strip()
    if re.match(r"^\d+$", token):
        return token + "GB"
    tb = re.match(r"^(\d+)[Tt][Bb]$", token)
    if tb:
        return tb.group(1) + "TB"
    return token.upper().replace(" ", "")


def _make_id(item_group_id: str, memory: str, sim: str, color: str, region: str = "") -> str:
    """
    Generates an ID identical to generateDeterministicId() in AiParser.gs:
    APPLEIPHONE17AIR-256GB-ESIM-CLOUDWHITE
    """
    def clean(s: str) -> str:
        return re.sub(r"[^A-Z0-9]", "", s.upper())

    parts = [clean(item_group_id)[:25]]
    for val in [memory, sim, color, region]:
        k = clean(val)
        if k and k not in ("-", ""):
            parts.append(k[:15])
    return "-".join(filter(None, parts))


def _region_from_sim(sim: str) -> str:
    """Infer iPhone region from SIM configuration (mirrors AiParser.gs rule 11)."""
    s = sim.lower().replace(" ", "").replace("+", "")
    if s == "esim":
        return "Америка"
    if "nanoesim" in s:
        return "Европа"
    if "nanonano" in s:
        return "Китай"
    return "-"


def calculate_markup(price: int | float) -> int:
    """
    Graduated markup for Apple hardware (fixed amounts):
    <  30 000 → +2 000
    <  40 000 → +3 000
    <  80 000 → +4 000
    < 100 000 → +5 000
    < 140 000 → +6 000
    < 200 000 → +7 000
    ≥ 200 000 → +8 000
    """
    p = float(price)
    if p < 30_000:
        return int(p) + 2_000
    elif p < 40_000:
        return int(p) + 3_000
    elif p < 80_000:
        return int(p) + 4_000
    elif p < 100_000:
        return int(p) + 5_000
    elif p < 140_000:
        return int(p) + 6_000
    elif p < 200_000:
        return int(p) + 7_000
    else:
        return int(p) + 8_000


def calculate_markup_accessory(price: int | float) -> int:
    """Accessories markup: +20%."""
    return round(float(price) * 1.20)


def apply_markup(items: List[Dict]) -> List[Dict]:
    """
    Applies markup to all items.
    - Saves raw price as purchase_price (→ column M in Sheets).
    - Phones → tiered markup; accessories (memory='-') → +20%.
    """
    import copy
    result = []
    for item in items:
        ic = copy.copy(item)
        try:
            raw = int(ic["price"])
            ic["purchase_price"] = str(raw)
            if ic.get("memory", "-") == "-":
                ic["price"] = str(calculate_markup_accessory(raw))
            else:
                ic["price"] = str(calculate_markup(raw))
        except (ValueError, TypeError):
            ic.setdefault("purchase_price", "")
        result.append(ic)
    return result


def parse_price_list(text: str) -> List[Dict]:
    """
    Parses wholesale price list text into structured records.
    Field names match HEADERS in AiParser.gs.
    Prices are RAW (without markup). Caller applies markup via apply_markup().
    """
    results = []
    seen_ids: set = set()

    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue

        # Price — digits (with spaces) at end of line after dash
        price_match = re.search(r"-\s*([\d\s]{4,})$", line)
        if not price_match:
            continue
        price = re.sub(r"\s", "", price_match.group(1))
        if not price.isdigit():
            continue

        content = line[: price_match.start()].strip()
        content = _strip_emoji(content)
        content = content.strip(" -")   # drop any leading/trailing dashes left after emoji strip
        if not content:
            continue

        # ── Accessories ──────────────────────────────────────────────────────
        if re.search(
            r"Чехол|Case|AirTag|кабель|Cable|Зарядк|Стекло|Glass|Защитн|Tempered|Screen"
            r"|AirPods|AirPod|Apple Watch|HomePod|Beats",
            content, re.IGNORECASE,
        ):
            # Skip obvious non-Apple accessories (DJI, Sony, etc.)
            if re.search(r"\bDJI\b|\bSony\b|\bSamsung\b|\bXiaomi\b|\bHuawei\b|\bAnker\b|\bBaseus\b",
                          content, re.IGNORECASE):
                continue
            model_name = content
            color = "-"
            if " - " in model_name:
                parts = model_name.rsplit(" - ", 1)
                model_name, color = parts[0].strip(), parts[1].strip()

            item_group_id = model_name
            item_id = _make_id(item_group_id, "-", "-", color)
            if item_id in seen_ids:
                continue
            seen_ids.add(item_id)

            title_parts = [p for p in [model_name, color] if p and p != "-"]
            results.append({
                "id":            item_id,
                "title":         " ".join(title_parts),
                "availability":  "in stock",
                "price":         price,
                "brand":         "Apple",
                "item_group_id": item_group_id,
                "color":         color,
                "sim":           "-",
                "size":          "-",
                "memory":        "-",
                "region":        "-",
            })
            continue

        # ── Phones & Tablets ─────────────────────────────────────────────────
        mem_match = re.search(
            r"\b(64|128|256|512|1[Tt][Bb]|2[Tt][Bb]|4[Tt][Bb])\b", content
        )
        if not mem_match:
            continue

        memory     = _parse_memory(mem_match.group(1))
        model_part = content[: mem_match.start()].strip(" ,")
        rest       = content[mem_match.end() :].strip()

        # ── Brand filter: skip non-Apple items immediately ────────────────────
        # Strip WiFi/LTE temporarily to check the actual model name
        _model_clean = re.sub(r"\b(Wi[-\s]?Fi|WiFi|LTE)\b", "", model_part,
                               flags=re.IGNORECASE).strip(" ,/")
        if _detect_brand(_model_clean) != "Apple":
            continue

        # ── Detect WiFi / LTE (for tablets) ──────────────────────────────────
        # Check model_part first (e.g., "Pro M4 13 2024 Wi-Fi")
        _wifi_re = re.compile(r"\b(Wi[-\s]?Fi|WiFi|LTE)\b", re.IGNORECASE)

        conn_in_model = _wifi_re.search(model_part)
        if conn_in_model:
            raw_conn = conn_in_model.group(1)
            connectivity = "WiFi" if re.search(r"fi", raw_conn, re.IGNORECASE) else "LTE"
            model_part = (
                model_part[: conn_in_model.start()] + model_part[conn_in_model.end() :]
            ).strip(" ,")
        else:
            conn_in_rest = _wifi_re.search(rest)
            if conn_in_rest:
                raw_conn = conn_in_rest.group(1)
                connectivity = "WiFi" if re.search(r"fi", raw_conn, re.IGNORECASE) else "LTE"
                rest = (
                    rest[: conn_in_rest.start()] + rest[conn_in_rest.end() :]
                ).strip(" ,")
            else:
                connectivity = ""

        # ── Detect SIM type (for phones) ─────────────────────────────────────
        sim_match = re.search(
            r"(Nano\s*\+\s*eSim|Nano\s*\+\s*Nano|eSim)", rest, re.IGNORECASE
        )
        if sim_match:
            sim   = sim_match.group(1).strip()
            color = rest[: sim_match.start()].strip().strip(",")
        else:
            # Tablets → connectivity is the SIM field; phones without SIM → "-"
            sim   = connectivity if connectivity else "-"
            color = rest.strip().strip(",")

        # ── Model name normalisation ──────────────────────────────────────────
        if re.match(r"^iPad\b", model_part, re.IGNORECASE):
            # "iPad 2025", "iPad 2021 10.2"
            model_name = model_part

        elif re.match(r"^Mini\b", model_part, re.IGNORECASE):
            # "Mini 6" → "iPad Mini 6"
            suffix = re.sub(r"^Mini\s*", "", model_part, flags=re.IGNORECASE).strip()
            model_name = "iPad Mini " + suffix if suffix else "iPad Mini"

        elif re.match(r"^Air\s+M\d", model_part, re.IGNORECASE):
            # "Air M3 11 2025" → "iPad Air M3 11 2025"
            suffix = re.sub(r"^Air\s+", "", model_part, flags=re.IGNORECASE).strip()
            model_name = "iPad Air " + suffix

        elif re.match(r"^Pro\s+M\d", model_part, re.IGNORECASE):
            # "Pro M4 11 2024" → "iPad Pro M4 11 2024"
            suffix = re.sub(r"^Pro\s+", "", model_part, flags=re.IGNORECASE).strip()
            model_name = "iPad Pro " + suffix

        elif re.match(r"^1[5-9](\s|$)", model_part) or re.match(r"^2\d(\s|$)", model_part):
            # "17 128" → "iPhone 17", "16 Pro Max" → "iPhone 16 Pro Max"
            model_name = "iPhone " + model_part

        elif re.match(r"^Air$", model_part.strip(), re.IGNORECASE):
            # Shorthand "Air" in iPhone price list = iPhone 17 Air
            model_name = "iPhone 17 Air"

        elif model_part.strip().lower().startswith("pro max"):
            model_name = "iPhone Pro Max"

        else:
            model_name = model_part.strip() if model_part.strip() else "iPhone"

        model_name = model_name.strip()
        color      = color.strip() or "-"
        sim        = sim.strip() or "-"

        # ── Region ────────────────────────────────────────────────────────────
        is_tablet = any(
            kw in model_name.lower()
            for kw in ("ipad", "ipad mini", "ipad air", "ipad pro")
        )
        region = "-" if is_tablet else _region_from_sim(sim)

        item_group_id = f"Apple {model_name}"
        item_id       = _make_id(item_group_id, memory, sim, color)

        if item_id in seen_ids:
            continue
        seen_ids.add(item_id)

        # ── Title: skip fields that are "-" ───────────────────────────────────
        title_parts = [f"Apple {model_name}", memory]
        if color and color != "-":
            title_parts.append(color)
        if sim and sim != "-":
            title_parts.append(sim)

        results.append({
            "id":            item_id,
            "title":         " ".join(title_parts),
            "availability":  "in stock",
            "price":         price,
            "brand":         "Apple",
            "item_group_id": item_group_id,
            "color":         color,
            "sim":           sim,
            "size":          "-",
            "memory":        memory,
            "region":        region,
        })

    return results


def looks_like_price_list(text: str) -> bool:
    """Heuristic: at least 3 lines ending with '- NNN' (3+ digits)."""
    hits = sum(1 for line in text.splitlines() if re.search(r"-\s*\d{3,}\s*$", line))
    return hits >= 3
