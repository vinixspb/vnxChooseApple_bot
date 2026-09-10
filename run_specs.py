#!/usr/bin/env python3
"""
Управление базой характеристик Apple.

  python run_specs.py                     # состояние базы и полнота данных
  python run_specs.py --rebuild           # пересобрать из data/specs/*.json
  python run_specs.py --show "16 Pro Max" # карточка модели
  python run_specs.py --gaps              # что не заполнено и требует сверки
  python run_specs.py --catalog           # каких моделей каталога нет в базе

Заполнять пропуски догадкой нельзя. Неверная характеристика в базе опаснее
отсутствующей: ассистенту разрешено произносить только то, что в базе есть,
поэтому пустое поле он честно назовёт неизвестным, а неверное — уверенно
выдаст клиенту за факт.
"""

import json
import re
import sys

from dotenv import load_dotenv
load_dotenv()

from services import specs_db


def _plain(html: str) -> str:
    return re.sub(r"<[^>]+>", "", html)


def cmd_status():
    rows = specs_db.all_models()
    if not rows:
        print("❌ База пуста. Собери её: python run_specs.py --rebuild")
        sys.exit(1)

    total_fields = len(specs_db._gap_fields())
    print(f"📊 Моделей в базе: {len(rows)}\n")
    print(f"{'модель':<22}{'заполнено':<12}{'источник'}")
    for r in rows:
        filled = specs_db.filled_fields(r)
        bar = "█" * round(filled / total_fields * 10)
        print(f"{r['model']:<22}{filled:>2}/{total_fields} {bar:<10} {r.get('source','')}")

    seed = [r for r in rows if r.get("source") == "seed"]
    if seed:
        print(f"\n⚠️  Требуют сверки с apple.com (source=seed): {len(seed)}")
        print("   Данные внесены при создании базы. Сверь выборочно —")
        print("   особенно яркость, вес и габариты.")


def cmd_rebuild():
    res = specs_db.rebuild()
    print(f"✅ Пересобрано. Моделей: {res['models']}, файлов: {res['files']}")
    print(f"   База: {specs_db._DB_PATH}")


def cmd_show(name: str):
    row = specs_db.find(name)
    if not row:
        print(f"❌ «{name}» в базе нет.")
        print("\nЧто есть:")
        for r in specs_db.all_models():
            print(f"   • {r['model']}")
        sys.exit(1)
    print(_plain(specs_db.format_card(row)))
    print("\n── строка, которую увидит ассистент в промпте ──")
    print(specs_db.format_for_prompt(row))


def cmd_gaps():
    rows = specs_db.all_models()
    holes = []
    for r in rows:
        missing = specs_db.missing_fields(r)
        if missing:
            holes.append((r["model"], r.get("source", ""), missing))

    if not holes:
        print("✅ Все характеристики заполнены.")
        return

    print(f"⚠️  Моделей с пропусками: {len(holes)}\n")
    for model, source, missing in holes:
        print(f"  {model}  ({source})")
        print(f"     нет: {', '.join(missing)}")

    print("\nЗаполнять — правкой data/specs/iphone.json, затем --rebuild.")
    print("Брать цифры со страницы характеристик Apple, а не по памяти.")


def cmd_catalog():
    """Сверяет базу с реальным каталогом — что покупатель может спросить."""
    from services.sheets_manager import get_data_from_sheet

    print("🔗 Читаем каталог...")
    catalog = get_data_from_sheet()
    if not catalog:
        print("❌ Каталог пуст или Sheets недоступен")
        sys.exit(1)

    groups = {}
    for item in catalog:
        if str(item.get("availability", "")).strip().lower() != "in stock":
            continue
        g = item.get("model_group") or item.get("title", "")
        if g:
            groups[g] = groups.get(g, 0) + 1

    have, missing = [], []
    for g, count in groups.items():
        (have if specs_db.find(g) else missing).append((g, count))

    print(f"\n✅ Есть характеристики: {len(have)} групп")
    if missing:
        missing.sort(key=lambda p: -p[1])
        print(f"\n⚠️  Нет характеристик: {len(missing)} групп "
              f"({sum(c for _, c in missing)} позиций)\n")
        for g, count in missing[:40]:
            print(f"   {count:>4} шт  {g}")
        print("\nПо этим моделям ассистент обязан отвечать «уточню у Андрея».")
        print("Аксессуары в этом списке — это нормально, характеристики нужны")
        print("для устройств, про которые спрашивают железо.")


def main():
    args = sys.argv[1:]

    if not args:
        specs_db.ensure_ready()
        cmd_status()
    elif args[0] == "--rebuild":
        cmd_rebuild()
    elif args[0] == "--show":
        if len(args) < 2:
            print('Укажи модель: --show "16 Pro Max"')
            sys.exit(1)
        specs_db.ensure_ready()
        cmd_show(" ".join(args[1:]))
    elif args[0] == "--gaps":
        specs_db.ensure_ready()
        cmd_gaps()
    elif args[0] == "--catalog":
        specs_db.ensure_ready()
        cmd_catalog()
    else:
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
