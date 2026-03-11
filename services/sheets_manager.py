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
        # Защита от лишних кавычек (если они случайно попали из .env)
        if credentials_json_str.startswith("'") and credentials_json_str.endswith("'"):
            credentials_json_str = credentials_json_str[1:-1]
            
        credentials = json.loads(credentials_json_str)
        return gspread.service_account_from_dict(credentials)
    except Exception as e:
        logging.error(f"❌ Ошибка авторизации: {e}")
        return None

def get_data_from_sheet(sheet_name: str = "vnxSHOP") -> List[Dict[str, Any]]:
    """
    Загружает данные и адаптирует их под нужды бота (стандарт Facebook Feed).
    """
    gc = authorize_gspread()
    if not gc: return []

    spreadsheet_id = os.getenv("SPREADSHEET_ID")
    try:
        spreadsheet = gc.open_by_key(spreadsheet_id)
        worksheet = spreadsheet.worksheet(sheet_name)
        
        # Получаем сырые данные
        raw_data = worksheet.get_all_records()
        logging.info(f"✅ Загружено {len(raw_data)} строк из '{sheet_name}'.")

        cleaned_data = []
        for row in raw_data:
            # Если нет ID товара, пропускаем пустую строку
            if not row.get("id"): 
                continue

            # Маппинг столбцов Facebook (на английском) в понятные боту ключи (на русском)
            item = {
                "SKU": str(row.get("id", "")).strip(),
                "Полное_название": str(row.get("title", "")).strip(),
                "Наличие": str(row.get("availability", "out of stock")).strip(),
                "Цена": str(row.get("price", "0")).replace(" RUB", "").strip(),
                "Ссылка на фото": str(row.get("image_link", "")).strip(),
                "Бренд": str(row.get("brand", "Apple")).strip(),
                "Цвет": str(row.get("color", "-")).strip(),
                "Память": str(row.get("memory", "-")).strip(),
                "SIM": str(row.get("sim", "-")).strip(),
                # ВАЖНО: Используем item_group_id, так как наш AI парсер пишет модель именно туда
                "Модель": str(row.get("item_group_id", row.get("title"))).strip(),
                "Регион": str(row.get("region", "-")).strip()
            }
            cleaned_data.append(item)

        return cleaned_data

    except Exception as e:
        logging.error(f"❌ Ошибка загрузки данных: {e}")
        return []
