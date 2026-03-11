from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from aiogram.utils.keyboard import InlineKeyboardBuilder

def get_main_menu(web_app_url: str = None) -> InlineKeyboardMarkup:
    """
    Генерирует главное меню категорий.
    Поддерживает Web App и фиксированный список категорий Apple.
    """
    builder = InlineKeyboardBuilder()

    # 1. Кнопка Web App (если ссылка передана)
    if web_app_url:
        builder.row(InlineKeyboardButton(
            text="🚀 Открыть каталог (Beta)", 
            web_app=WebAppInfo(url=web_app_url)
        ))

    # 2. Главные категории поиска (с твоими эмодзи)
    categories = {
        "iPhone": "📱 iPhone",
        "iPad": "📟 iPad",
        "Mac": "💻 Mac",
        "Watch": "⌚️ Watch",
        "AirPods": "🎧 AirPods"
    }

    for key, label in categories.items():
        builder.row(InlineKeyboardButton(text=label, callback_data=f"cat_{key}"))

    return builder.as_markup()

def get_dynamic_keyboard(data: list, callback_prefix: str, back_callback: str = "back_to_main") -> InlineKeyboardMarkup:
    """
    Универсальный генератор кнопок (Модели, Память, Цвет).
    Поддерживает:
    - Простые списки: ["WiFi", "LTE"]
    - Списки с ценами: [["128GB", "85000"], ["256GB", "95000"]]
    """
    builder = InlineKeyboardBuilder()
    
    for item in data:
        # Если item - это кортеж/список [Значение, Цена]
        if isinstance(item, (list, tuple)) and len(item) == 2:
            text = f"{item[0]} — {item[1]} ₽"
            callback_value = str(item[0])
        # Если item - это просто строка (модель, цвет и т.д.)
        else:
            text = str(item)
            callback_value = str(item)
            
        # Формируем callback и защищаем его (как в твоем старом файле)
        # Заменяем пробелы на _ и слэши на -, обрезаем до 60 байт
        safe_callback = f"{callback_prefix}{callback_value}".replace(" ", "_").replace("/", "-")
        safe_callback = safe_callback[:60]
        
        builder.row(InlineKeyboardButton(text=text, callback_data=safe_callback))

    # Кнопка "Назад" (настраиваемая, по умолчанию в главное меню)
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data=back_callback))
    
    return builder.as_markup()
