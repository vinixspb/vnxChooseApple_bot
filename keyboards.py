from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from database import CATALOG

# Клавиатура категорий (iPhone, Mac, iPad)
def get_main_menu():
    builder = InlineKeyboardBuilder()
    for key, value in CATALOG.items():
        # key = 'iphones', value['label'] = '📱 iPhone'
        builder.button(text=value['label'], callback_data=f"cat_{key}")
    builder.adjust(1) # 1 кнопка в ряд
    return builder.as_markup()

# Клавиатура моделей конкретной категории
def get_models_keyboard(category_key):
    builder = InlineKeyboardBuilder()
    models = CATALOG[category_key]['models']
    
    for model in models:
        # callback_data должен быть коротким!
        builder.button(text=model, callback_data=f"item_{model}")
    
    # Кнопка "Назад"
    builder.button(text="🔙 Назад", callback_data="back_to_main")
    
    builder.adjust(2) # 2 кнопки в ряд
    return builder.as_markup()
