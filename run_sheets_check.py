#!/usr/bin/env python3
"""
Диагностика доступа к Google Sheets.

Проходит ту же цепочку, что и бот: авторизация → открытие → чтение → запись,
и печатает, на каком шаге всё сломалось и что с этим делать.

Проверка использует services.sheets_manager.check_access() — ровно ту же
функцию, которой пользуется сторож внутри бота. Так диагностика и бот
не могут разойтись во мнениях о том, работает доступ или нет.

Usage:
  python run_sheets_check.py
"""

import os
import sys

from dotenv import load_dotenv
load_dotenv()

from services.sheets_manager import check_access
from services import incident_rules as rules


_STAGE_RU = {
    "auth":   "авторизация по ключу",
    "config": "конфигурация .env",
    "open":   "открытие таблицы",
    "read":   "чтение листа vnxSHOP",
    "write":  "запись в лист vnxSHOP",
    "done":   "всё пройдено",
}


def main():
    print("🔗 Проверяем доступ к Google Sheets...\n")

    res = check_access()

    print(f"👤 Сервис-аккаунт: {res.get('email', '?')}")
    print(f"📄 SPREADSHEET_ID:  {os.getenv('SPREADSHEET_ID') or '— не задан —'}")
    print()

    if res.get("title"):
        print(f"✅ Таблица открыта: {res['title']}")
    if res.get("sheets"):
        print(f"   Листы: {', '.join(res['sheets'])}")
    if res.get("read_rows"):
        print(f"✅ Чтение работает: {res['read_rows']} строк")

    if res["ok"]:
        print("✅ Запись работает — прав Редактора достаточно")
        print("\n🟢 Доступ в порядке.")
        return

    stage = _STAGE_RU.get(res["stage"], res["stage"])
    print(f"\n❌ Сломалось на шаге: {stage}")
    if res.get("error"):
        print(f"   Ответ Google: {res['error'][:300]}")

    code = res.get("code") or "UNKNOWN"
    rule = rules.get_rule(code)
    print(f"\n{rules.SEVERITY_EMOJI.get(rule.severity, '⚪')} {rule.title}")
    print(f"   код инцидента: {code}")
    if rule.why:
        print(f"\n   Почему это важно:\n   {rule.why}")
    print(f"\n   Что сделать:\n   {rule.fix}")
    if rule.docs:
        print(f"\n   📖 {rule.docs}")

    sys.exit(1)


if __name__ == "__main__":
    main()
