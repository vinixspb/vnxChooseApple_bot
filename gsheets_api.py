# gsheets_api.py

import gspread
import logging
import os
import json # <<< НОВЫЙ ИМПОРТ
from dotenv import load_dotenv

load_dotenv()

# Имя переменной, содержащей JSON-ключ
CREDENTIALS_JSON = os.getenv('GOOGLE_CREDENTIALS_JSON') 
SPREADSHEET_ID = os.getenv('SPREADSHEET_ID')

logging.basicConfig(level=logging.INFO)

def get_data_from_sheet(sheet_name: str) -> list[dict]:
    """
    Подключается к Google Таблице с помощью JSON-ключа из переменной окружения
    и считывает данные с указанного листа.
    """
    if not SPREADSHEET_ID:
        logging.error("❌ SPREADSHEET_ID не указан в .env")
        return []
        
    if not CREDENTIALS_JSON:
        logging.error("❌ GOOGLE_CREDENTIALS_JSON не найдена в .env")
        return []

    try:
        # 1. Загрузка учетных данных из переменной окружения
        credentials_dict = json.loads(CREDENTIALS_JSON)
        
        # 2. Авторизация с помощью словаря учетных данных
        gc = gspread.service_account_from_dict(credentials_dict)
        
        # 3. Открытие таблицы по ID
        spreadsheet = gc.open_by_key(SPREADSHEET_ID)
        
        # 4. Выбор листа (вкладки)
        worksheet = spreadsheet.worksheet(sheet_name)
        
        # 5. Получение всех записей
        data = worksheet.get_all_records()
        
        logging.info(f"✅ Успешно загружено {len(data)} записей из листа '{sheet_name}'.")
        return data

    except json.JSONDecodeError:
        logging.error("❌ Ошибка парсинга JSON-ключа. Проверьте, что значение GOOGLE_CREDENTIALS_JSON корректно скопировано и находится в одной строке.")
    except gspread.exceptions.SpreadsheetNotFound:
        logging.error(f"❌ Таблица с ID {SPREADSHEET_ID} не найдена или нет доступа. Проверьте ID и предоставьте доступ сервисному аккаунту.")
    except gspread.exceptions.WorksheetNotFound:
        logging.error(f"❌ Лист '{sheet_name}' не найден в таблице. Проверьте название листа (должно быть 'iPhone').")
    except Exception as e:
        logging.error(f"❌ Общая ошибка при работе с Google Sheets API: {e}")
        
    return []

# Пример использования (можно удалить после тестирования)
if __name__ == '__main__':
    iphone_data = get_data_from_sheet("iPhone")
    if iphone_data:
        print(f"Первая запись: {iphone_data[0]}")
