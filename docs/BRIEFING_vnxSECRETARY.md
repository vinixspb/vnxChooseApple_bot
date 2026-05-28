# Бриф: vnxChooseApple_bot — полная документация системы
> Документ подготовлен для передачи в vnxSECRETARY с целью настройки и управления.

---

## 1. Что это за система

**@vnxSHOP_AppleFinder_bot** — Telegram-бот для розничных покупателей.  
Помогает выбрать iPhone/iPad/Mac/AirPods через пошаговую воронку:  
категория → модель → память → цвет → SIM → карточка товара с ценой.

**@vnxSHOPprice** — Telegram-канал с прайс-листами для оптовых и розничных клиентов.

**Google Sheets (vnxSHOP)** — единый центр данных. Цены берутся оттуда в бота.

---

## 2. Сервер и окружение

```
Путь:        /opt/vnxChooseApple_bot/
Сервис:      vnx-apple-shop.service  (systemd)
Рестарт:     systemctl restart vnx-apple-shop.service
Логи:        journalctl -u vnx-apple-shop.service -f
Python:      /opt/vnxChooseApple_bot/venv/bin/python
Ветка:       claude/funny-shannon-bMuuR  (feature, не слита в main)
```

---

## 3. Переменные окружения (.env)

```env
# Обязательные
BOT_TOKEN=                    # токен @vnxSHOP_AppleFinder_bot
MANAGER_ID=                   # Telegram ID владельца (получает уведомления)
SPREADSHEET_ID=               # ID Google-таблицы vnxSHOP
GOOGLE_CREDENTIALS_JSON=      # JSON сервисного аккаунта Google (однострочный)

# AI-консультант
OPENROUTER_API_KEY=           # ключ OpenRouter для AI-ассистента в боте

# Автоматизация прайсов
SUPPLIER_CHANNEL_ID=-1001378091044,-1001562517847
#   -1001378091044 = BORODAPPLE (основной поставщик)
#   -1001562517847 = Multibrand (дополнительный поставщик)

PRICE_CHANNEL_ID=@vnxSHOPprice  # канал для публикации прайсов
```

---

## 4. Архитектура — полная схема потока данных

```
┌─────────────────────────────────────────────────────────────┐
│                    ПОСТАВЩИКИ (2 группы)                     │
│  BORODAPPLE (-1001378091044) | Multibrand (-1001562517847)  │
└─────────────────────┬───────────────────────────────────────┘
                      │ публикуют прайс (текст)
                      ▼
┌─────────────────────────────────────────────────────────────┐
│              handlers/price_watcher.py                       │
│  IsSupplierChat() — фильтр по SUPPLIER_CHANNEL_ID           │
│  Слушает: channel_post + group message                       │
│  Минимум 3 строки с ценой → looks_like_price_list()         │
└─────────────────────┬───────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────┐
│              services/price_parser.py                        │
│  parse_price_list() — парсит текст в структуру              │
│  apply_markup()    — применяет наценку (см. п.6)            │
└────────────┬────────────────────────────────────────────────┘
             │
     ┌───────┴────────┐
     ▼                ▼
┌─────────────┐  ┌──────────────────────────────────────────┐
│Google Sheets│  │   services/price_publisher.py            │
│ vnxSHOP     │  │   → @vnxSHOPprice                        │
│             │  │   11:00-13:00 МСК — со звуком            │
│ sync_price_ │  │   остальное время — тихо                 │
│ list():     │  │   (disable_notification)                 │
│ обновляет   │  └──────────────────────────────────────────┘
│ цену+наличие│
│ добавляет   │
│ новые строки│
└──────┬──────┘
       │
       ▼
┌─────────────────────────────────────────────────────────────┐
│         services/sheets_manager.py → store.CATALOG          │
│  get_data_from_sheet() — загружает в память бота            │
│  get_settings()       — настройки (ссылки на картинки)      │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────┐
│         @vnxSHOP_AppleFinder_bot (покупатели)               │
│  handlers/catalog.py — воронка выбора                       │
│  handlers/assistant.py — AI-консультант                     │
│  handlers/magic.py — примерка (AI)                          │
└─────────────────────────────────────────────────────────────┘
```

---

## 5. Структура файлов

```
vnxChooseApple_bot/
├── main.py                     # точка входа, регистрация роутеров
├── keyboards.py                # клавиатуры (главное меню, динамические)
├── database.py                 # пустой (зарезервирован)
├── requirements.txt            # aiogram>=3.0, gspread, python-dotenv
│
├── handlers/
│   ├── catalog.py              # воронка выбора товара (FSM)
│   ├── assistant.py            # AI-консультант (текст + голос)
│   ├── magic.py                # примерка чехла/цвета (AI + фото)
│   ├── group.py                # обработка группового чата
│   ├── channel.py              # добавление кнопок к постам своего канала
│   └── price_watcher.py        # ★ слушает поставщиков, запускает парсинг
│
├── services/
│   ├── sheets_manager.py       # чтение данных из Google Sheets
│   ├── sheets_writer.py        # ★ запись/обновление в Google Sheets
│   ├── price_parser.py         # ★ парсинг прайс-листов + наценка
│   ├── price_publisher.py      # ★ публикация прайса в канал
│   ├── assistant_service.py    # AI (OpenRouter API)
│   ├── kie_service.py          # вспомогательный AI-сервис
│   ├── messages.py             # тексты сообщений и кнопок
│   └── data_store.py           # глобальное хранилище в памяти
│
├── states/
│   └── product_states.py       # FSM-состояния (selecting, consulting)
│
├── utils/
│   └── media.py                # работа с изображениями товаров
│
└── docs/
    ├── AiParser.gs             # Google Apps Script (ручной парсер через Gemini)
    └── BRIEFING_vnxSECRETARY.md   # этот файл
```

★ — файлы, добавленные/изменённые в рамках автоматизации

---

## 6. Алгоритм наценки (price_parser.py → calculate_markup)

### Техника Apple (телефоны, планшеты, ноутбуки)
| Закупочная цена | Наценка |
|---|---|
| < 30 000 ₽ | +2 000 ₽ |
| 30 000 – 39 999 ₽ | +3 000 ₽ |
| 40 000 – 79 999 ₽ | +4 000 ₽ |
| 80 000 – 99 999 ₽ | +5 000 ₽ |
| 100 000 – 139 999 ₽ | +6 000 ₽ |
| 140 000 – 199 999 ₽ | +7 000 ₽ |
| ≥ 200 000 ₽ | +8 000 ₽ |

### Аксессуары (чехлы, кабели, AirTag и т.д.)
- Наценка: **+20%** (calculate_markup_accessory)
- Определяется автоматически: если поле `memory == "-"` → аксессуар

### Применение
```python
# В price_watcher.py:
items = apply_markup(raw_items)  # автоматически выбирает алгоритм
```

---

## 7. Google Sheets — структура таблицы vnxSHOP

### Лист vnxSHOP (основной каталог, 27 столбцов)
Совпадает с HEADERS в AiParser.gs:
```
id | title | description | availability | condition | price | link |
image_link | brand | google_product_category | fb_product_category |
quantity_to_sell_on_facebook | sale_price | sale_price_effective_date |
item_group_id | gender | color | size | age_group | material |
pattern | shipping | shipping_weight | gtin | memory | sim | region
```

### Ключевые поля
| Поле | Пример | Назначение |
|---|---|---|
| `id` | `APPLEIPHONE17AIR-256GB-ESIM-CLOUDWHITE` | Уникальный ключ |
| `title` | `Apple iPhone 17 Air 256GB Cloud White eSim` | Полное название |
| `availability` | `in stock` / `out of stock` | Наличие |
| `price` | `79500` | Цена с наценкой (числом) |
| `item_group_id` | `Apple iPhone 17 Air` | Группа для воронки бота |
| `memory` | `256GB` | Объём памяти |
| `sim` | `eSim` / `Nano + eSim` | Тип SIM |
| `color` | `Cloud White` | Цвет |
| `region` | `-` / `Европа` / `Китай` | Регион устройства |

### Формат ID (детерминированный)
```
APPLE + {item_group_id без пробелов} + - + {memory} + - + {sim} + - + {color без пробелов}
Пример: APPLEIPHONE17AIR-256GB-ESIM-CLOUDWHITE
```

### Другие листы
- `Draft` — куда вставляют сырой текст прайса для ручной обработки
- `Import` — куда Gemini кладёт обработанный JSON (AiParser.gs)
- `Settings` — настройки бота (ссылки на картинки по категориям)

---

## 8. Логика синхронизации с Google Sheets (sheets_writer.py)

```python
sync_price_list(items, sheet_name="vnxSHOP")
```

**Алгоритм:**
1. Загружает все строки листа
2. Строит карту `id → номер строки`
3. Для **существующих** товаров (по id): обновляет только `price` + `availability`
4. Для **новых** товаров: дописывает полную строку в конец листа
5. Использует `batch_update` для минимального числа API-запросов

**Результат:** `{'updated': N, 'added': M}`

---

## 9. Публикация прайса в канал (price_publisher.py)

### Расписание уведомлений (МСК)
| Время | Режим |
|---|---|
| 11:00 – 13:00 | 🔔 Со звуком |
| Остальное | 🔕 Тихо (disable_notification=True) |

### Формат поста
```
🍏 Актуальный прайс — 28.05.2026
📦 Источник: BORODAPPLE

📱 Apple iPhone 17 Air
[сворачиваемая цитата]
└ 256GB | Cloud White | eSIM — 79 500 ₽
└ 256GB | Light gold | eSIM — 77 000 ₽
[/цитата]

📱 Apple iPhone 17 Pro Max
[сворачиваемая цитата]
└ 1TB | Silver | eSIM — 139 500 ₽
[/цитата]

🔄 Обновляется автоматически
```

---

## 10. Порядок роутеров (main.py) — критичен

```python
dp.include_router(price_watcher.router)  # 1. Поставщики — первым
dp.include_router(group.router)          # 2. Группы
dp.include_router(channel.router)        # 3. Свой канал (кнопки к постам)
dp.include_router(catalog.router)        # 4. Воронка выбора
dp.include_router(magic.router)          # 5. AI примерка
dp.include_router(assistant.router)      # 6. Catch-all — ВСЕГДА ПОСЛЕДНИМ
```

---

## 11. Управление сервисом на сервере

```bash
# Перезапуск после изменений в .env или коде
systemctl restart vnx-apple-shop.service

# Статус
systemctl status vnx-apple-shop.service

# Логи в реальном времени
journalctl -u vnx-apple-shop.service -f

# Обновить код с ветки
cd /opt/vnxChooseApple_bot
git pull origin claude/funny-shannon-bMuuR
systemctl restart vnx-apple-shop.service
```

---

## 12. Ручной парсер (AiParser.gs) — для Google Sheets

Файл: `docs/AiParser.gs` — Google Apps Script, устанавливается в таблицу.

**Меню в таблице:** `🍏 AI ПАРСЕР`
1. Очистить Import
2. Запустить парсинг (Gemini 2.5 Flash → JSON → лист Import)
3. Синхронизировать прайс (Import → целевой лист, с наценкой)

**Нужна переменная в Script Properties:** `GEMINI_API_KEY`

---

## 13. Что планируется добавить (backlog)

- [ ] Интеграция с vnxSecretary для управления обновлениями каталога
- [ ] Поддержка дополнительных поставщиков (структура уже готова — достаточно добавить ID в SUPPLIER_CHANNEL_ID через запятую)
- [ ] Слияние ветки `claude/funny-shannon-bMuuR` в `main`
- [ ] Установка зависимостей при деплое (если изменится requirements.txt)

---

## 14. Контакт и бизнес-контекст

- Владелец: продажа техники Apple в России
- Бот для покупателей: @vnxSHOP_AppleFinder_bot
- Канал с прайсами: @vnxSHOPprice
- Поставщики: BORODAPPLE (основной), Multibrand (дополнительный)
- Язык интерфейса: русский
