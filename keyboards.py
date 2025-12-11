# keyboards.py

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

# ПРИМЕЧАНИЕ: Здесь не должно быть импорта CATALOG. 
# CATALOG будет передаваться в функции как аргумент.

def get_main_menu(catalog_data: dict) -> InlineKeyboardMarkup:
    """
    Генерирует главное меню с категориями, используя переданный словарь.
    
    :param catalog_data: Словарь с данными категорий (iPhone, Mac и т.д.)
    """
    builder = InlineKeyboardBuilder()
    
    # Добавляем кнопки для каждой категории
    for key, value in catalog_data.items():
        # callback_data: cat_iphones, cat_macbooks, cat_ipads, cat_watches
        builder.button(text=value['label'], callback_data=f"cat_{key}")
    
    # Располагаем по 2 кнопки в ряд
    builder.adjust(2) 
    return builder.as_markup()

def get_models_keyboard(catalog_data: dict, category_key: str) -> InlineKeyboardMarkup:
    """
    Генерирует клавиатуру с моделями для НЕ-iPhone категорий.
    Эта функция больше не используется для iPhone.
    """
    builder = InlineKeyboardBuilder()
    
    # Получаем список моделей по ключу
    try:
        models = catalog_data[category_key]['models']
    except KeyError:
        # Если категория не найдена, возвращаем главное меню
        return get_main_menu(catalog_data)

    for model in models:
        # callback_data: item_Модель
        builder.button(text=model, callback_data=f"item_{model}")
    
    # Добавляем кнопку "Назад"
    builder.button(text="🔙 Назад к категориям", callback_data="back_to_main")
    
    builder.adjust(1)
    return builder.as_markup()


def get_dynamic_keyboard(data: list[str], callback_prefix: str, back_callback: str) -> InlineKeyboardMarkup:
    """
    Генерирует клавиатуру из списка уникальных значений (для пошагового выбора iPhone).
    
    :param data: Список уникальных значений (напр., ['256 GB', '512 GB'])
    :param callback_prefix: Префикс для callback_data (напр., 'val_')
    :param back_callback: callback для кнопки "Назад"
    """
    builder = InlineKeyboardBuilder()
    
    for item in data:
        # ВАЖНО: Кодируем данные для использования в callback_data
        encoded_item = item.replace(" ", "_").replace("/", "-") 
        builder.button(text=item, callback_data=f"{callback_prefix}{encoded_item}")
    
    builder.button(text="🔙 Назад", callback_data=back_callback)
    builder.adjust(1)
    return builder.as_markup()
