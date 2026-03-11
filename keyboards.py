# keyboards.py
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from aiogram.utils.keyboard import InlineKeyboardBuilder

def get_main_menu(web_app_url: str = None) -> InlineKeyboardMarkup:
    """
    Генерирует главное меню категорий.
    Теперь категории фиксированы, а бот сам ищет их внутри vnxSHOP.
    """
    builder = InlineKeyboardBuilder()

    # 1. Кнопка Web App (если ссылка передана)
    if web_app_url:
        builder.row(InlineKeyboardButton(
            text="🚀 Открыть каталог (Beta)", 
            web_app=WebAppInfo(url=web_app_url)
        ))

    # 2. Главные категории поиска
    categories = {
        "iPhone": "📱 iPhone",
        "iPad": "📟 iPad",
        "Mac": "💻 Mac",
        "Watch": "⌚️ Watch",
        "AirPods": "🎧 AirPods"
    }

    for key, label in categories.items():
        # callback_data будет вида "cat_iPhone", "cat_iPad" и т.д.
        builder.row(InlineKeyboardButton(text=label, callback_data=f"cat_{key}"))

    return builder.as_markup()

def get_dynamic_keyboard(data: list, callback_prefix: str, back_callback: str = "back_to_main") -> InlineKeyboardMarkup:
    """
    Генерирует клавиатуру выбора (Модели, Памяти, SIM и т.д.).
    Поддерживает как простой список ["WiFi", "LTE"], 
    так и список с ценами [["128GB", "80000"], ["256GB", "95000"]].
    """
    builder = InlineKeyboardBuilder()
    
    for item in data:
        # Если item - это просто строка (например, модель "iPad 2021 10.2")
        if isinstance(item, str):
            text = item
            callback_value = item
        # Если item - это кортеж/список [Значение, Цена]
        elif isinstance(item, (list, tuple)) and len(item) == 2:
            text = f"{item[0]} — {item[1]} ₽"
            callback_value = item[0]
        else:
            continue
            
        # Формируем callback и защищаем его от спецсимволов и пробелов
        callback = f"{callback_prefix}{callback_value}"
        safe_callback = callback.replace(" ", "_").replace("/", "-")
        
        # Ограничение Telegram для callback_data — 64 байта! Обрезаем до 60 для безопасности.
        safe_callback = safe_callback[:60]
        
        builder.row(InlineKeyboardButton(text=text, callback_data=safe_callback))

    # Кнопка "Назад"
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data=back_callback))
    
    return builder.as_markup()

# Функцию get_models_keyboard мы удалили, так как get_dynamic_keyboard 
# теперь полностью универсальна и заменяет её.
