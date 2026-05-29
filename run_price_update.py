#!/usr/bin/env python3
"""
Ручной запуск обновления прайса.

Запуск:
  python run_price_update.py              — интерактивный ввод (Ctrl+D для завершения)
  python run_price_update.py < price.txt  — из файла
"""
import os
import sys

# Принудительно UTF-8 для stdout
sys.stdout = open(sys.stdout.fileno(), mode="w", encoding="utf-8", errors="replace", buffering=1)

# Загружаем .env до всех импортов
from dotenv import load_dotenv
load_dotenv()

from services.price_parser import parse_price_list, apply_markup, looks_like_price_list
from services.sheets_writer import sync_price_list


def _fmt(price: str) -> str:
    try:
        return f"{int(price):,}".replace(",", " ")
    except Exception:
        return price


def _read_tty_line(prompt: str) -> str:
    """Читает строку напрямую из /dev/tty, минуя stdin (не подвержен буферу вставки)."""
    try:
        with open("/dev/tty", "r") as tty:
            sys.stderr.write(prompt)
            sys.stderr.flush()
            return tty.readline().strip()
    except OSError:
        # /dev/tty недоступен (например, в CI/CD) — возвращаем пустую строку
        return ""


def main():
    is_tty = sys.stdin.isatty()

    if is_tty:
        print("=" * 60)
        print("  vnxSHOP — Ручное обновление прайса")
        print("=" * 60)
        print("Вставь прайс-лист и нажми Ctrl+D в новой строке:\n")

    try:
        text = sys.stdin.read()
    except KeyboardInterrupt:
        print("\nОтменено.")
        sys.exit(0)

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

    print()

    # Подтверждение — читаем из /dev/tty чтобы избежать буфера вставки
    if is_tty:
        answer = _read_tty_line("Записать в Google Sheets (vnxSHOP)? [y/N]: ").lower()
        # принимаем латинскую y, кириллическую у, и да
        if answer not in ("y", "у", "yes", "да"):
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
    print("\n💡 Перезапусти бота чтобы каталог подгрузился:")
    print("   systemctl restart vnx-apple-shop.service")


if __name__ == "__main__":
    main()
