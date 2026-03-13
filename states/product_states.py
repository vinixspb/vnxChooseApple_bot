cat > /opt/vnxChooseApple_bot/states/product_states.py << 'EOF'
from aiogram.fsm.state import StatesGroup, State


class ProductSelection(StatesGroup):
    selecting               = State()   # воронка выбора товара (кнопки)
    waiting_for_magic_photo = State()   # ожидание фото для AI-магии
    consulting              = State()   # свободный чат с Андрей.ai
EOF
