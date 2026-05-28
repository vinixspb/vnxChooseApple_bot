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


def _make_id(model_name: str, memory: str, sim: str, color: str) -> str:
    """
    Генерирует ID в формате таблицы:
    APPLEIPHONE17AIR-256GB-ESIM-CLOUDWHITE
    """
    def clean(s: str) -> str:
        return re.sub(r"[^A-Z0-9]", "", s.upper())

    model_key = clean(model_name)[:25] or "UNKNOWN"
    parts = [f"APPLE{model_key}"]

    for val in [memory, sim, color]:
        k = clean(val)
        if k and k != "-":
            parts.append(k[:15])

    return "-".join(parts)


def parse_price_list(text: str) -> List[Dict]:
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

            item_id = _make_id(model_name, "-", "-", color)
            if item_id in seen_ids:
                continue
            seen_ids.add(item_id)

            title_parts = [p for p in [model_name, color] if p and p != "-"]
            results.append(
                {
                    "id":           item_id,
                    "title":        " ".join(title_parts),
                    "availability": "in stock",
                    "price":        price,
                    "item_group_id": model_name,
                    "color":        color,
                    "sim":          "-",
                    "size":         "-",
                    "memory_ssd":   "-",
                    "region_custom": "-",
                }
            )
            continue

        # ── Телефоны ─────────────────────────────────────────────────────────
        mem_match = re.search(
            r"\b(64|128|256|512|1[Tt][Bb]|2[Tt][Bb]|4[Tt][Bb])\b", content
        )
        if not mem_match:
            continue

        memory    = _parse_memory(mem_match.group(1))
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

        # Нормализация названия модели (с префиксом iPhone)
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

        item_id = _make_id(model_name, memory, sim, color)
        if item_id in seen_ids:
            continue
        seen_ids.add(item_id)

        # item_group_id и title с "Apple" — как в таблице
        item_group = f"Apple {model_name}"
        title      = f"Apple {model_name} {memory} {color} {sim}".strip()

        results.append(
            {
                "id":            item_id,
                "title":         title,
                "availability":  "in stock",
                "price":         price,
                "item_group_id": item_group,
                "color":         color,
                "sim":           sim,
                "size":          "-",
                "memory_ssd":    memory,
                "region_custom": "-",
            }
        )

    return results


def looks_like_price_list(text: str) -> bool:
    """Эвристика: минимум 3 строки с ценой в конце."""
    hits = sum(1 for line in text.splitlines() if re.search(r"-\s*\d{4,}\s*$", line))
    return hits >= 3
