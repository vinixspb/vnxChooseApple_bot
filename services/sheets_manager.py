import os
import logging
import json
import gspread
from typing import List, Dict, Any

def authorize_gspread():
    """Авторизация через JSON-строку из переменной окружения."""
    credentials_json_str = os.getenv("GOOGLE_CREDENTIALS_JSON")
    if not credentials_json_str:
        logging.error("❌ Переменная GOOGLE_CREDENTIALS_JSON не найдена.")
        return None

    try:
        credentials = json.loads(credentials_json_str)
        return gspread.service_account_from_dict(credentials)
    except Exception as e:
        logging.error(f"❌ Ошибка авторизации: {e}")
        return None

def get_data_from_sheet(sheet_name: str) -> List[Dict[str, Any]]:
    """Загружает данные. Теперь учитываем столбцы: Модель, Память, Цвет, SIM, Цена, Ссылка на фото, Описание, Бренд."""
    gc = authorize_gspread()
    if not gc: return []

    spreadsheet_id = os.getenv("SPREADSHEET_ID")
    try:
        spreadsheet = gc.open_by_key(spreadsheet_id)
        worksheet = spreadsheet.worksheet(sheet_name)
        data = worksheet.get_all_records()
        logging.info(f"✅ Загружено {len(data)} позиций из '{sheet_name}'.")
        return data
    except Exception as e:
        logging.error(f"❌ Ошибка загрузки данных: {e}")
        return []
