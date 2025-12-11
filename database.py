# database.py

# ID пользователя-менеджера для получения заявок.
# Замените на свой Telegram ID (можно узнать через @userinfobot)
MANAGER_ID = 'ВАШ_ID_МЕНЕДЖЕРА' 

# Структура каталога: [Ключ для callback] -> {Label: Отображаемое имя, models: Список моделей}
CATALOG = {
    "iphones": {
        "label": "📱 iPhone",
        "models": ["iPhone 15 Pro Max", "iPhone 15 Pro", "iPhone 15", "iPhone 14 Pro", "iPhone 13"]
    },
    "macbooks": {
        "label": "💻 MacBook",
        "models": ["MacBook Air M3 13-inch", "MacBook Pro M3 Pro 14-inch", "MacBook Pro M3 Max 16-inch"]
    },
    "ipads": {
        "label": "📟 iPad",
        "models": ["iPad Pro M4 11-inch", "iPad Air M2 13-inch", "iPad Mini 6"]
    }
}
