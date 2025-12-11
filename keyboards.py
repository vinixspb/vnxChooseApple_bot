# keyboards.py

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from database import CATALOG
# Примечание: Вся логика для iPhone будет использовать get_dynamic_keyboard

def get_main_menu() -> InlineKeyboardMarkup:
    """Генерирует главное меню с категориями (iPhone, Mac, iPad, Watch)."""
    builder = InlineKeyboardBuilder()
    
    # Добавляем кнопки для каждой категории из CATALOG
    for key, value in CATALOG.items():
        # callback_data: cat_iphones, cat_macbooks, cat_ipads, cat_watches
        builder.button(text=value['label'], callback_data=f"cat_{key}")
    
    # Располагаем по 2 кнопки в ряд
    builder.adjust(2) 
    return builder.as_markup()

def get_models_keyboard(category_key: str) -> InlineKeyboardMarkup:
    """
    Генерирует клавиатуру с моделями для НЕ-iPhone категорий (старый, статический метод).
    Для iPhone используем динамическую клавиатуру.
    """
    builder = InlineKeyboardBuilder()
    
    # Получаем список моделей по ключу
    try:
        models = CATALOG[category_key]['models']
    except KeyError:
        return get_main_menu()

    for model in models:
        # callback_data: item_iPhone 15 Pro Max
        builder.button(text=model, callback_data=f"item_{model}")
    
    # Добавляем кнопку "Назад"
    builder.button(text="🔙 Назад к категориям", callback_data="back_to_main")
    
    builder.adjust(1)
    return builder.as_markup()


def get_dynamic_keyboard(data: list[str], callback_prefix: str, back_callback: str) -> InlineKeyboardMarkup:
    """
    Генерирует клавиатуру из списка уникальных значений (для пошагового выбора).
    
    :param data: Список уникальных значений (напр., ['256 GB', '512 GB'])
    :param callback_prefix: Префикс для callback_data (напр., 'mem_')
    :param back_callback: callback для кнопки "Назад"
    """
    builder = InlineKeyboardBuilder()
    
    for item in data:
        # ВАЖНО: Кодируем данные для использования в callback_data
        # Заменяем пробелы на нижние подчеркивания, чтобы избежать ошибок при парсинге
        encoded_item = item.replace(" ", "_").replace("/", "-") 
        builder.button(text=item, callback_data=f"{callback_prefix}{encoded_item}")
    
    builder.button(text="🔙 Назад", callback_data=back_callback)
    builder.adjust(1)
    return builder.as_markup()
