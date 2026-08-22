#!/usr/bin/env python3
"""
Диагностика доступа к Google Sheets.

Показывает email сервис-аккаунта, проверяет чтение и запись в vnxSHOP.
Нужен когда скрипты падают с "APIError: [403]: The caller does not have permission".

Usage:
  python run_sheets_check.py
"""

import json
import os
import sys

from dotenv import load_dotenv
load_dotenv()

from services.sheets_manager import authorize_gspread


def _service_account_email() -> str:
    raw = os.getenv("GOOGLE_CREDENTIALS_JSON", "")
    if raw.startswith("'") and raw.endswith("'"):
        raw = raw[1:-1]
    try:
        return json.loads(raw).get("client_email", "?")
    except Exception:
        return "?"


def main():
    email = _service_account_email()
    spreadsheet_id = os.getenv("SPREADSHEET_ID")

    print(f"👤 Сервис-аккаунт: {email}")
    print(f"📄 SPREADSHEET_ID:  {spreadsheet_id}")
    print()

    if not spreadsheet_id:
        print("❌ SPREADSHEET_ID не задан в .env")
        sys.exit(1)

    gc = authorize_gspread()
    if not gc:
        print("❌ Не удалось авторизоваться — проверь GOOGLE_CREDENTIALS_JSON")
        sys.exit(1)

    try:
        ss = gc.open_by_key(spreadsheet_id)
    except Exception as e:
        print(f"❌ Не открывается таблица: {e}")
        sys.exit(1)

    print(f"✅ Таблица открыта: {ss.title}")
    print(f"   Листы: {', '.join(w.title for w in ss.worksheets())}")

    try:
        ws = ss.worksheet("vnxSHOP")
    except Exception as e:
        print(f"❌ Лист vnxSHOP не найден: {e}")
        sys.exit(1)

    rows = len(ws.get_all_values())
    print(f"✅ Чтение работает: {rows} строк")

    # Пробная запись в дальнюю пустую ячейку, потом очищаем
    probe = "ZZ1"
    try:
        ws.update_acell(probe, "probe")
        ws.update_acell(probe, "")
        print("✅ Запись работает — прав Редактора достаточно")
    except Exception as e:
        print(f"❌ Запись НЕ работает: {e}")
        print()
        print("   Открой таблицу в браузере → «Настройки доступа» →")
        print(f"   добавь {email} с ролью «Редактор».")
        sys.exit(1)


if __name__ == "__main__":
    main()
