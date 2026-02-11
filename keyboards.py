# keyboards.py
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from aiogram.utils.keyboard import InlineKeyboardBuilder

def get_main_menu(catalog_data: dict, web_app_url: str = None) -> InlineKeyboardMarkup:
    """
    Генерирует главное меню категорий.
    Теперь поддерживает кнопку Web App!
    """
    builder = InlineKeyboardBuilder()

    # 1. Кнопка Web App (если ссылка передана)
    if web_app_url:
        builder.row(InlineKeyboardButton(
            text="🚀 Открыть каталог (Beta)", 
            web_app=WebAppInfo(url=web_app_url)
        ))

    # 2. Кнопки категорий из каталога (для старого режима)
    for key, value in catalog_data.items():
        # value может быть словарем {"label": "..."} или строкой
        label = value.get("label", key) if isinstance(value, dict) else value
        builder.row(InlineKeyboardButton(text=label, callback_data=f"cat_{key}"))

    return builder.as_markup()

def get_dynamic_keyboard(data: list, callback_prefix: str, back_callback: str = "back_to_main") -> InlineKeyboardMarkup:
    """Генерирует клавиатуру выбора (Модели, Памяти и т.д.) с ценами."""
    builder = InlineKeyboardBuilder()
    
    for item in data:
        # Если item - это просто строка (например, цвет "Black")
        if isinstance(item, str):
            text = item
            callback = f"{callback_prefix}{item}"
        # Если item - это кортеж/список [Значение, Цена] (например, ["128 GB", "80000"])
        elif isinstance(item, (list, tuple)) and len(item) == 2:
            text = f"{item[0]} — {item[1]} ₽"
            # В callback кладем только значение, чтобы не ломать логику
            callback = f"{callback_prefix}{item[0]}"
        else:
            continue
            
        # Заменяем пробелы на _ для callback_data (защита от длинных строк)
        safe_callback = callback.replace(" ", "_").replace("/", "-")
        # Обрезаем, если слишком длинный (ограничение Telegram 64 байта)
        safe_callback = safe_callback[:60]
        
        builder.row(InlineKeyboardButton(text=text, callback_data=safe_callback))

    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data=back_callback))
    return builder.as_markup()

def get_models_keyboard(catalog, category_key):
    """Старая функция для MacBook/iPad (если нужна)"""
    builder = InlineKeyboardBuilder()
    models = catalog.get(category_key, {}).get("models", [])
    for model in models:
        builder.row(InlineKeyboardButton(text=model, callback_data=f"model_{model}"))
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_main"))
    return builder.as_markup()
