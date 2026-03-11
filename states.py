from aiogram.fsm.state import State, StatesGroup

class ProductSelection(StatesGroup):
    selecting = State() # Процесс выбора параметров товара
    waiting_for_magic_photo = State() # Ожидание фото для нейросети
