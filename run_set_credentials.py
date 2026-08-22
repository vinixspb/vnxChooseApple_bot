#!/usr/bin/env python3
"""
Безопасно прописывает ключ сервис-аккаунта в .env.

JSON-ключ Google — многострочный, при ручной вставке в .env он ломается.
Скрипт сжимает его в одну строку, оборачивает в одинарные кавычки и
заменяет строку GOOGLE_CREDENTIALS_JSON, не трогая остальные переменные.
Старый .env сохраняется как .env.bak.

Usage:
  python run_set_credentials.py /path/to/service-account-key.json
"""

import json
import os
import shutil
import sys

_ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
_KEY = "GOOGLE_CREDENTIALS_JSON"


def main():
    if len(sys.argv) < 2:
        print("Использование: python run_set_credentials.py /путь/к/ключу.json")
        sys.exit(1)

    key_path = sys.argv[1]
    if not os.path.isfile(key_path):
        print(f"❌ Файл не найден: {key_path}")
        sys.exit(1)

    with open(key_path, encoding="utf-8") as f:
        try:
            creds = json.load(f)
        except json.JSONDecodeError as e:
            print(f"❌ Это не валидный JSON: {e}")
            sys.exit(1)

    email = creds.get("client_email")
    if not email:
        print("❌ В файле нет client_email — это не ключ сервис-аккаунта")
        sys.exit(1)

    if creds.get("type") != "service_account":
        print(f"⚠️  type = {creds.get('type')!r}, ожидался 'service_account'")

    one_line = json.dumps(creds, ensure_ascii=False, separators=(",", ":"))
    if "'" in one_line:
        print("❌ В ключе есть одинарная кавычка — впиши переменную вручную")
        sys.exit(1)

    new_line = f"{_KEY}='{one_line}'\n"

    lines = []
    if os.path.exists(_ENV_PATH):
        shutil.copy2(_ENV_PATH, _ENV_PATH + ".bak")
        with open(_ENV_PATH, encoding="utf-8") as f:
            lines = f.readlines()

    old_email = None
    replaced = False
    for i, line in enumerate(lines):
        if line.lstrip().startswith(f"{_KEY}="):
            raw = line.split("=", 1)[1].strip()
            if raw.startswith("'") and raw.endswith("'"):
                raw = raw[1:-1]
            try:
                old_email = json.loads(raw).get("client_email")
            except Exception:
                pass
            lines[i] = new_line
            replaced = True
            break

    if not replaced:
        if lines and not lines[-1].endswith("\n"):
            lines[-1] += "\n"
        lines.append(new_line)

    with open(_ENV_PATH, "w", encoding="utf-8") as f:
        f.writelines(lines)
    os.chmod(_ENV_PATH, 0o600)

    if old_email:
        print(f"🔄 Было:  {old_email}")
    print(f"✅ Стало: {email}")
    print(f"   Записано в {_ENV_PATH} (бэкап: .env.bak, права 600)")
    print()
    print("Дальше:")
    print("  1. Выдай этому email роль «Редактор» на таблице vnxSHOP")
    print("  2. python run_sheets_check.py")
    print("  3. apple-restart")


if __name__ == "__main__":
    main()
