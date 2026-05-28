import re
from typing import List, Dict


def _strip_emoji(text: str) -> str:
    return re.sub(
        r"[\U0001F300-\U0001F9FF☀-➿\U0001FA00-\U0001FA9F®©™]+",
        "",
        text,
    ).strip()


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
    Генерирует ID, идентичный generateDeterministicId() из AiParser.gs:
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


def calculate_markup(price: int | float) -> int:
    """
    Наценка для телефонов (фиксированная сумма):
    ≤ 40 000  → +4 000
    < 80 000  → +5 000
    ≥ 80 000  → +6 000
    """
    price = float(price)
    if price <= 40_000:
        return int(price) + 4_000
    elif price < 80_000:
        return int(price) + 5_000
    else:
        return int(price) + 6_000


def calculate_markup_accessory(price: int | float) -> int:
    """Наценка для аксессуаров: +20%."""
    return round(float(price) * 1.20)


def apply_markup(items: List[Dict]) -> List[Dict]:
    """
    Применяет наценку ко всему списку:
    - телефоны (memory != '-') → calculate_markup
    - аксессуары (memory == '-') → +20%
    Возвращает новые копии словарей.
    """
    import copy
    result = []
    for item in items:
        ic = copy.copy(item)
        try:
            raw = int(ic["price"])
            if ic.get("memory", "-") == "-":
                ic["price"] = str(calculate_markup_accessory(raw))
            else:
                ic["price"] = str(calculate_markup(raw))
        except (ValueError, TypeError):
            pass
        result.append(ic)
    return result


def parse_price_list(text: str) -> List[Dict]:
    """
    Парсит текст оптового прайс-листа в структурированные записи.
    Поля соответствуют HEADERS из AiParser.gs.
    Цены — RAW (без наценки). Наценку применяет вызывающий код.
    """
    results = []
    seen_ids = set()

    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue

        # Цена — цифры (с пробелами) в конце строки после тире
        price_match = re.search(r"-\s*([\d\s]{4,})$", line)
        if not price_match:
            continue
        price = re.sub(r"\s", "", price_match.group(1))
        if not price.isdigit():
            continue

        content = line[: price_match.start()].strip()
        content = _strip_emoji(content)
        if not content:
            continue

        # ── Аксессуары ──────────────────────────────────────────────────────
        if re.search(r"Чехол|Case|AirTag|кабель|Cable|Зарядк", content, re.IGNORECASE):
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
            results.append(
                {
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
                }
            )
            continue

        # ── Телефоны ─────────────────────────────────────────────────────────
        mem_match = re.search(
            r"\b(64|128|256|512|1[Tt][Bb]|2[Tt][Bb]|4[Tt][Bb])\b", content
        )
        if not mem_match:
            continue

        memory     = _parse_memory(mem_match.group(1))
        model_part = content[: mem_match.start()].strip(" ,")
        rest       = content[mem_match.end() :].strip()

        # SIM
        sim_match = re.search(
            r"(Nano\s*\+\s*eSim|Nano\s*\+\s*Nano|eSim)", rest, re.IGNORECASE
        )
        if sim_match:
            sim   = sim_match.group(1).strip()
            color = rest[: sim_match.start()].strip().strip(",")
        else:
            sim   = "-"
            color = rest.strip().strip(",")

        # Нормализация модели
        if re.match(r"^1[5-9](\s|$)", model_part) or re.match(r"^2\d(\s|$)", model_part):
            model_name = "iPhone " + model_part
        elif re.match(r"Air\b", model_part, re.IGNORECASE):
            model_name = "iPhone 17 Air"
        elif model_part.lower().startswith("pro max"):
            model_name = "iPhone Pro Max"
        else:
            model_name = model_part if model_part else "iPhone"

        model_name = model_name.strip()
        color      = color.strip() or "-"
        sim        = sim.strip() or "-"

        item_group_id = f"Apple {model_name}"
        item_id       = _make_id(item_group_id, memory, sim, color)

        if item_id in seen_ids:
            continue
        seen_ids.add(item_id)

        results.append(
            {
                "id":            item_id,
                "title":         f"Apple {model_name} {memory} {color} {sim}".strip(),
                "availability":  "in stock",
                "price":         price,
                "brand":         "Apple",
                "item_group_id": item_group_id,
                "color":         color,
                "sim":           sim,
                "size":          "-",
                "memory":        memory,
                "region":        "-",
            }
        )

    return results


def looks_like_price_list(text: str) -> bool:
    """Эвристика: минимум 3 строки с ценой в конце."""
    hits = sum(1 for line in text.splitlines() if re.search(r"-\s*\d{4,}\s*$", line))
    return hits >= 3
