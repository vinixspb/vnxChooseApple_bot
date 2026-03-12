from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from aiogram.utils.keyboard import InlineKeyboardBuilder

def get_main_menu(web_app_url: str = None) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if web_app_url:
        builder.row(InlineKeyboardButton(text="🚀 Каталог (Web)", web_app=WebAppInfo(url=web_app_url)))

    categories = {"iPhone": "📱 iPhone", "iPad": "📟 iPad", "Mac": "💻 Mac", "Watch": "⌚️ Watch", "AirPods": "🎧 AirPods"}
    for key, label in categories.items():
        builder.row(InlineKeyboardButton(text=label, callback_data=f"cat_{key}"))
    return builder.as_markup()

def get_dynamic_keyboard(data: list, callback_prefix: str, back_callback: str = "back_to_main") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for item in data:
        if isinstance(item, (list, tuple)) and len(item) == 2:
            # Используем индекс для callback_data (ФИКС #2)
            key, label = item
            callback_data = f"{callback_prefix}{key}"
            text = str(label)
        else:
            label = str(item)
            callback_data = f"{callback_prefix}{label}".replace(" ", "_")[:60]
            text = label
        builder.row(InlineKeyboardButton(text=text, callback_data=callback_data))
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data=back_callback))
    return builder.as_markup()
