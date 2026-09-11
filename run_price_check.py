#!/usr/bin/env python3
"""
Сверка присланного прайса с тем, что лежит в таблице.

Отвечает на вопрос «а совпадают ли наши цены с прайсом поставщика».
Проверяет три вещи:
  1. разобралась ли строка вообще (иначе позиция молча не доедет до таблицы);
  2. есть ли такая позиция в vnxSHOP;
  3. совпадает ли цена, и если нет — на сколько и почему.

Usage:
  python run_price_check.py прайс.txt
  python run_price_check.py прайс.txt --markup 6000   # ожидаемая наценка
  cat прайс.txt | python run_price_check.py -

Флаг --markup задаёт наценку, которую ожидаешь увидеть. Без него сравнение
идёт с наценкой по шкале из services/price_parser.py.
"""

import sys

from dotenv import load_dotenv
load_dotenv()

from services.price_parser import parse_price_list, calculate_markup
from services.sheets_manager import get_data_from_sheet


def _fmt(n) -> str:
    try:
        return f"{int(n):,}".replace(",", " ")
    except (ValueError, TypeError):
        return str(n)


def main():
    args = [a for a in sys.argv[1:]]
    if not args:
        print(__doc__)
        sys.exit(1)

    flat_markup = None
    if "--markup" in args:
        i = args.index("--markup")
        flat_markup = int(args[i + 1])
        del args[i:i + 2]

    src = args[0]
    text = sys.stdin.read() if src == "-" else open(src, encoding="utf-8").read()

    raw_lines = [l for l in text.splitlines() if l.strip()]
    items = parse_price_list(text)

    print(f"📄 Строк в файле: {len(raw_lines)}")
    print(f"✅ Разобрано позиций: {len(items)}")
    if len(items) < len(raw_lines):
        print(f"⚠️  Не разобрано строк: {len(raw_lines) - len(items)} "
              f"(пустые строки и заголовки — это нормально)")
    if not items:
        print("\n❌ Ни одна строка не разобрана. Проверь формат: "
              "в конце строки должно быть « - ЦЕНА».")
        sys.exit(1)

    print("\n🔗 Читаем каталог...")
    catalog = {row["id"]: row for row in get_data_from_sheet()}
    if not catalog:
        print("❌ Каталог пуст или Sheets недоступен")
        sys.exit(1)
    print(f"   позиций в таблице: {len(catalog)}\n")

    missing, matched, mismatched = [], [], []

    for item in items:
        buy = int(item["price"])                       # цена поставщика, без наценки
        expect = buy + flat_markup if flat_markup else calculate_markup(buy)

        row = catalog.get(item["id"])
        if not row:
            missing.append((item, buy, expect))
            continue

        try:
            actual = int(row.get("price", 0))
        except (ValueError, TypeError):
            actual = 0

        if actual == expect:
            matched.append((item, actual))
        else:
            mismatched.append((item, buy, expect, actual))

    print("=" * 72)
    print(f"  ✅ Цена совпадает:     {len(matched)}")
    print(f"  ⚠️  Цена расходится:   {len(mismatched)}")
    print(f"  ❌ Нет в таблице:      {len(missing)}")
    print("=" * 72)

    if mismatched:
        print(f"\n⚠️  РАСХОЖДЕНИЯ В ЦЕНЕ\n")
        print(f"{'модель':<40}{'закупка':>10}{'ждём':>10}{'в таблице':>11}{'разница':>10}")
        for item, buy, expect, actual in mismatched[:40]:
            name = f"{item['item_group_id']} {item['memory']} {item['color']}"
            print(f"{name[:39]:<40}{_fmt(buy):>10}{_fmt(expect):>10}"
                  f"{_fmt(actual):>11}{actual - expect:>+10}")

        diffs = {a - e for _, _, e, a in mismatched}
        if len(diffs) == 1:
            d = diffs.pop()
            print(f"\n   Разница одинаковая у всех позиций: {d:+}.")
            print("   Значит дело не в отдельных строках, а в шкале наценки.")
            print("   Шкала живёт в calculate_markup() в services/price_parser.py.")

    if missing:
        print(f"\n❌ НЕТ В ТАБЛИЦЕ (ожидаемая цена — с наценкой)\n")
        for item, buy, expect in missing[:40]:
            name = f"{item['item_group_id']} {item['memory']} {item['color']}"
            print(f"   {name[:52]:<53} закупка {_fmt(buy):>8} → {_fmt(expect):>8}")
        print("\n   Причины: позиция ещё не приходила от поставщика в группу,")
        print("   либо помечена «out of stock», либо отличается написание —")
        print("   тогда у неё другой id и она лежит в таблице отдельной строкой.")

    if matched and not mismatched and not missing:
        print("\n🟢 Всё сходится.")


if __name__ == "__main__":
    main()
