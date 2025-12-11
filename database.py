# database.py

# Этот файл содержит только структуру каталога товаров.
# Все секретные данные (токены, ID менеджеров) хранятся в .env.

# Структура: [Ключ для callback] -> {Label: Отображаемое имя, models: Список моделей}
CATALOG = {
    "iphones": {
        "label": "📱 iPhone",
        "models": [
            "iPhone 15 Pro Max", 
            "iPhone 15 Pro", 
            "iPhone 15", 
            "iPhone 14 Pro", 
            "iPhone 13",
            "iPhone SE (2022)" 
        ]
    },
    "macbooks": {
        "label": "💻 MacBook",
        "models": [
            "MacBook Air M3 13-inch", 
            "MacBook Air M3 15-inch",
            "MacBook Pro M3 Pro 14-inch", 
            "MacBook Pro M3 Max 16-inch"
        ]
    },
    "ipads": {
        "label": "📟 iPad",
        "models": [
            "iPad Pro M4 11-inch", 
            "iPad Air M2 13-inch", 
            "iPad 10th Gen",
            "iPad Mini 6"
        ]
    },
    "watches": {
        "label": "⌚ Apple Watch",
        "models": [
            "Apple Watch Series 9",
            "Apple Watch Ultra 2",
            "Apple Watch SE"
        ]
    }
}
