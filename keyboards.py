# keyboards.py

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from database import CATALOG

# Клавиатура категорий (iPhone, Mac, iPad)
def get_main_menu() -> InlineKeyboardMarkup:
    """Генерирует главное меню с категориями."""
    builder = InlineKeyboardBuilder()
    
    # Добавляем кнопки для каждой категории из CATALOG
    for key, value in CATALOG.items():
        # callback_data: cat_iphones, cat_macbooks, cat_ipads
        builder.button(text=value['label'], callback_data=f"cat_{key}")
    
    # Располагаем по 2 кнопки в ряд для компактности
    builder.adjust(2) 
    return builder.as_markup()

# Клавиатура моделей конкретной категории
def get_models_keyboard(category_key: str) -> InlineKeyboardMarkup:
    """Генерирует клавиатуру с моделями для выбранной категории."""
    builder = InlineKeyboardBuilder()
    
    # Получаем список моделей по ключу
    try:
        models = CATALOG[category_key]['models']
    except KeyError:
        # Обработка, если категория не найдена
        return get_main_menu()

    for model in models:
        # callback_data: item_iPhone 15 Pro Max
        builder.button(text=model, callback_data=f"item_{model}")
    
    # Добавляем кнопку "Назад" в конце списка
    builder.button(text="🔙 Назад к категориям", callback_data="back_to_main")
    
    # Располагаем модели по 1 кнопке в ряд
    builder.adjust(1)
    return builder.as_markup()
