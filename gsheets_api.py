# gsheets_api.py

import gspread
import logging
import os
from dotenv import load_dotenv

load_dotenv()

# Имя файла JSON с ключом сервисного аккаунта
SERVICE_ACCOUNT_FILE = os.getenv('GSHEETS_KEY_FILE', 'service_account.json') 
SPREADSHEET_ID = os.getenv('SPREADSHEET_ID')

logging.basicConfig(level=logging.INFO)

def get_data_from_sheet(sheet_name: str) -> list[dict]:
    """
    Подключается к Google Таблице и считывает данные с указанного листа.
    Возвращает список словарей, где ключ — это заголовок столбца.
    """
    if not SPREADSHEET_ID:
        logging.error("SPREADSHEET_ID не указан в .env")
        return []

    try:
        # Авторизация
        gc = gspread.service_account(filename=SERVICE_ACCOUNT_FILE)
        
        # Открытие таблицы по ID
        spreadsheet = gc.open_by_key(SPREADSHEET_ID)
        
        # Выбор листа (вкладки)
        worksheet = spreadsheet.worksheet(sheet_name)
        
        # Получение всех записей как списка словарей
        data = worksheet.get_all_records()
        
        logging.info(f"Успешно загружено {len(data)} записей из листа '{sheet_name}'.")
        return data

    except gspread.exceptions.SpreadsheetNotFound:
        logging.error(f"Таблица с ID {SPREADSHEET_ID} не найдена или нет доступа.")
    except gspread.exceptions.WorksheetNotFound:
        logging.error(f"Лист '{sheet_name}' не найден в таблице.")
    except Exception as e:
        logging.error(f"Ошибка при работе с Google Sheets API: {e}")
        
    return []

# Пример использования (можно удалить после тестирования)
if __name__ == '__main__':
    # Для теста: убедитесь, что в .env есть SPREADSHEET_ID
    iphone_data = get_data_from_sheet("iPhone")
    # print(iphone_data[:2])
