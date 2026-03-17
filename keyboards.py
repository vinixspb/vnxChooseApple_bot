# keyboards.py
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from aiogram.utils.keyboard import InlineKeyboardBuilder
from services.messages import BTN

def get_main_menu(web_app_url: str = None) -> InlineKeyboardMarkup:
    """
    Генерирует главное меню категорий.
    Кнопка AI-консультанта теперь находится в самом низу.
    """
    builder = InlineKeyboardBuilder()

    if web_app_url:
        builder.row(InlineKeyboardButton(
            text="🚀 Открыть каталог (Beta)", 
            web_app=WebAppInfo(url=web_app_url)
        ))

    categories = {
        "iPhone": "📱 iPhone",
        "iPad": "📟 iPad",
        "Mac": "💻 Mac",
        "Watch": "⌚️ Watch",
        "AirPods": "🎧 AirPods"
    }

    for key, label in categories.items():
        builder.row(InlineKeyboardButton(text=label, callback_data=f"cat_{key}"))

    builder.row(InlineKeyboardButton(text=BTN["start_ai"], callback_data="start_consulting"))

    return builder.as_markup()

def get_dynamic_keyboard(data: list, callback_prefix: str, back_callback: str = "back_to_main", extra_btn: dict = None) -> InlineKeyboardMarkup:
    """
    Генерирует клавиатуру выбора (Модели, Памяти, SIM и т.д.).
    Поддерживает вставку дополнительной кнопки (extra_btn).
    """
    builder = InlineKeyboardBuilder()
    
    for item in data:
        if isinstance(item, (list, tuple)) and len(item) == 2:
            key, label = item
            callback_data = f"{callback_prefix}{key}"
            text = str(label)
        else:
            label = str(item)
            callback_data = f"{callback_prefix}{label}".replace(" ", "_")[:60]
            text = label
            
        builder.row(InlineKeyboardButton(text=text, callback_data=callback_data))

    # ДОБАВЛЯЕМ КНОПКУ РАЗВОРАЧИВАНИЯ (если она передана) ПЕРЕД КНОПКОЙ НАЗАД
    if extra_btn:
        builder.row(InlineKeyboardButton(text=extra_btn["text"], callback_data=extra_btn["callback_data"]))

    builder.row(InlineKeyboardButton(text=BTN["back"], callback_data=back_callback))
    
    return builder.as_markup()
