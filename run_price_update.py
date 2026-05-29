#!/usr/bin/env python3
"""
Ручной запуск обновления прайса.

Запуск:
  python run_price_update.py              — интерактивный ввод
  python run_price_update.py < price.txt  — из файла
"""
import os
import sys

# Принудительно UTF-8 для stdin/stdout (решает проблему с русской раскладкой)
if sys.stdin.encoding and sys.stdin.encoding.lower() != "utf-8":
    sys.stdin = open(sys.stdin.fileno(), mode="r", encoding="utf-8", errors="replace", buffering=1)
sys.stdout = open(sys.stdout.fileno(), mode="w", encoding="utf-8", errors="replace", buffering=1)

# Загружаем .env до всех импортов
from dotenv import load_dotenv
load_dotenv()

from services.price_parser import parse_price_list, apply_markup, looks_like_price_list
from services.sheets_writer import sync_price_list
import services.data_store as store
from services.sheets_manager import get_data_from_sheet, get_settings


def _fmt(price: str) -> str:
    try:
        return f"{int(price):,}".replace(",", " ")
    except Exception:
        return price


def main():
    # Читаем текст — из stdin или интерактивно
    if not sys.stdin.isatty():
        text = sys.stdin.read()
    else:
        print("=" * 60)
        print("  vnxSHOP — Ручное обновление прайса")
        print("=" * 60)
        print("Вставь прайс-лист и нажми Enter дважды:\n")
        lines = []
        try:
            while True:
                line = input()
                if not line and lines and not lines[-1]:
                    break
                lines.append(line)
        except EOFError:
            pass
        text = "\n".join(lines)

    text = text.strip()
    if not text:
        print("❌ Пустой ввод")
        sys.exit(1)

    if not looks_like_price_list(text):
        print("❌ Не похоже на прайс-лист (нужно минимум 3 строки вида 'Название - Цена')")
        sys.exit(1)

    # Парсим
    raw = parse_price_list(text)
    if not raw:
        print("❌ Парсер не нашёл позиций")
        sys.exit(1)

    # Применяем наценку
    items = apply_markup(raw)

    # Показываем что получилось
    print(f"\n📋 Распознано позиций: {len(items)}\n")
    col_w = 52
    print(f"  {'Товар':<{col_w}} {'Закуп':>8}  {'Продажа':>9}")
    print("  " + "-" * (col_w + 22))
    for raw_item, item in zip(raw, items):
        title = item['title'][:col_w]
        print(f"  {title:<{col_w}} {_fmt(raw_item['price']):>8}  {_fmt(item['price']):>9} ₽")

    # Подтверждение
    print()
    if sys.stdin.isatty():
        try:
            confirm = input("Записать в Google Sheets (vnxSHOP)? [y/N]: ").strip().lower()
        except UnicodeDecodeError:
            confirm = "y"  # нажата 'у' с русской раскладки — считаем как подтверждение
        # принимаем латинскую y, кириллическую у, и да
        if confirm not in ("y", "у", "yes", "да"):
            print("Отменено.")
            sys.exit(0)
    else:
        print("Запись в Google Sheets...")

    # Пишем в Sheets
    result = sync_price_list(items)
    updated = result["updated"]
    added   = result["added"]

    if updated == 0 and added == 0:
        print("⚠️  Ничего не записано — проверь подключение к Google Sheets и SPREADSHEET_ID в .env")
        sys.exit(1)

    print(f"\n✅ Готово!")
    print(f"   Обновлено цен:   {updated}")
    print(f"   Добавлено новых: {added}")

    # Перезагружаем каталог в памяти (если запущен в том же процессе — не актуально,
    # но при перезапуске бота он сам подхватит из Sheets)
    print("\n💡 Перезапусти бота чтобы каталог подгрузился:")
    print("   systemctl restart vnx-apple-shop.service")


if __name__ == "__main__":
    main()
