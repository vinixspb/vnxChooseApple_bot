# gsheets_api.py

import os
import logging
from typing import List, Dict, Any
import gspread
import json # <--- ДОБАВЬТЕ ЭТОТ ИМПОРТ

# ... (Остальной код, константы и прочее)

# --- ИСПРАВЛЕННАЯ ФУНКЦИЯ АВТОРИЗАЦИИ ---
def authorize_gspread():
    """Авторизация Gspread с использованием JSON-строки из переменной окружения."""
    
    # 1. Получаем JSON-строку из .env
    credentials_json_str = os.getenv("GOOGLE_CREDENTIALS_JSON")
    
    if not credentials_json_str:
        logging.error("❌ Переменная GOOGLE_CREDENTIALS_JSON не найдена в .env.")
        return None

    # 2. Парсим JSON-строку в словарь
    try:
        # json.loads обрабатывает длинную строку
        credentials = json.loads(credentials_json_str) 
    except json.JSONDecodeError as e:
        # Эта ошибка происходит, если формат JSON нарушен (например, лишние кавычки, неправильные символы \n)
        logging.error(f"❌ Ошибка парсинга JSON-ключа: {e}")
        return None

    # 3. Используем gspread.service_account_from_dict для авторизации
    try:
        gc = gspread.service_account_from_dict(credentials) 
        return gc
    except Exception as e:
        logging.error(f"❌ Ошибка авторизации Gspread: {e}")
        return None

# --- ИСПРАВЛЕННАЯ ФУНКЦИЯ ЗАГРУЗКИ ДАННЫХ ---
def get_data_from_sheet(sheet_name: str) -> List[Dict[str, Any]]:
    """Загружает данные с указанного листа."""
    
    # Авторизуемся
    gc = authorize_gspread() # <--- ИСПОЛЬЗУЕМ НОВУЮ ФУНКЦИЮ
    
    if gc is None:
        return []

    spreadsheet_id = os.getenv("SPREADSHEET_ID")
    if not spreadsheet_id:
        logging.error("❌ SPREADSHEET_ID не найден в .env.")
        return []
        
    try:
        # Открываем таблицу по ID
        spreadsheet = gc.open_by_key(spreadsheet_id)
        
        # Открываем лист по имени
        worksheet = spreadsheet.worksheet(sheet_name)
        
        # Получаем данные в виде списка словарей
        data = worksheet.get_all_records()
        logging.info(f"✅ Loaded {len(data)} items from sheet '{sheet_name}'.")
        return data

    except gspread.exceptions.SpreadsheetNotFound:
        logging.error(f"❌ Таблица с ID {spreadsheet_id} не найдена или нет доступа.")
        return []
    except gspread.exceptions.WorksheetNotFound:
        logging.error(f"❌ Лист '{sheet_name}' не найден в таблице.")
        return []
    except Exception as e:
        logging.error(f"❌ Неизвестная ошибка Gspread: {e}")
        return []

# ... (Остальной код)
