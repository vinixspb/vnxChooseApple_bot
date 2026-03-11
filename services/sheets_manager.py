import os
import logging
import json
import gspread
import time
from typing import List, Dict, Any

def authorize_gspread():
    credentials_json_str = os.getenv("GOOGLE_CREDENTIALS_JSON")
    if not credentials_json_str: return None
    try:
        if credentials_json_str.startswith("'") and credentials_json_str.endswith("'"):
            credentials_json_str = credentials_json_str[1:-1]
        return gspread.service_account_from_dict(json.loads(credentials_json_str))
    except Exception as e:
        logging.error(f"Auth error: {e}")
        return None

def get_data_from_sheet(sheet_name: str = "vnxSHOP", retries: int = 3) -> List[Dict[str, Any]]:
    gc = authorize_gspread()
    if not gc: return []
    spreadsheet_id = os.getenv("SPREADSHEET_ID")
    
    for attempt in range(retries):
        try:
            spreadsheet = gc.open_by_key(spreadsheet_id)
            worksheet = spreadsheet.worksheet(sheet_name)
            raw_data = worksheet.get_all_records()
            
            cleaned = []
            for row in raw_data:
                if not row.get("id"): continue
                cleaned.append({
                    "id": str(row.get("id", "")).strip(),
                    "title": str(row.get("title", "")).strip(),
                    "availability": str(row.get("availability", "out of stock")).strip(),
                    "price": str(row.get("price", "0")).replace(" RUB", "").strip(),
                    "image": str(row.get("image_link", "")).strip(),
                    "color": str(row.get("color", "-")).strip(),
                    "memory": str(row.get("memory", "-")).strip(),
                    "sim": str(row.get("sim", "-")).strip(),
                    "model_group": str(row.get("item_group_id", row.get("title"))).strip(),
                    "region": str(row.get("region", "-")).strip()
                })
            return cleaned
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(2)
                continue
            logging.error(f"Sheets error: {e}")
    return []

def get_settings():
    gc = authorize_gspread()
    if not gc: return {}
    try:
        spreadsheet = gc.open_by_key(os.getenv("SPREADSHEET_ID"))
        rows = spreadsheet.worksheet("Settings").get_all_records()
        return {str(r.get("Категория")): str(r.get("Ссылка")) for r in rows if r.get("Категория")}
    except: return {}
