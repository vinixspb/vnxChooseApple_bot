from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from aiogram.utils.keyboard import InlineKeyboardBuilder


def get_main_menu(web_app_url: str = None) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    if web_app_url:
        builder.row(InlineKeyboardButton(
            text="🚀 Открыть каталог (Beta)",
            web_app=WebAppInfo(url=web_app_url)
        ))

    categories = {
        "iPhone": "📱 iPhone",
        "iPad":   "📟 iPad",
        "Mac":    "💻 Mac",
        "Watch":  "⌚️ Watch",
        "AirPods":"🎧 AirPods",
    }
    for key, label in categories.items():
        builder.row(InlineKeyboardButton(text=label, callback_data=f"cat_{key}"))

    return builder.as_markup()


def get_dynamic_keyboard(
    data: list,
    callback_prefix: str,
    back_callback: str = "back_to_main"
) -> InlineKeyboardMarkup:
    """
    data — список кортежей (ключ, метка):
        [("0", "128GB"), ("1", "256GB"), ...]
    Ключи — числовые индексы из val_map, поэтому callback_data
    всегда безопасен (нет спецсимволов, длина < 20 байт).
    """
    builder = InlineKeyboardBuilder()

    for key, label in data:
        # callback_data вида: stg_0, stg_1, stg_2 — никаких _ из данных таблицы
        callback_data = f"{callback_prefix}{key}"
        builder.row(InlineKeyboardButton(text=str(label), callback_data=callback_data))

    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data=back_callback))
    return builder.as_markup()
