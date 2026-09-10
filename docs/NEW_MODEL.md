# Добавление новой модели Apple

Чек-лист на случай анонса. Порядок важен: пока не сделан шаг 1, позиции
от поставщика молча теряются, и никакие картинки уже не помогут.

## 1. Парсер — узнаёт ли он модель

Поставщики пишут сокращённо, без слова iPhone: `Duo 256 Star White eSim+eSim - 210000`.
Парсер сначала определяет бренд по началу строки, и незнакомое слово
отбрасывается как не-Apple **без единой ошибки в логах**.

В `services/price_parser.py`:

- `_APPLE_MODEL_RE` — добавить сокращение (`Duo\b`, `Air\b` и т.п.);
- ветка нормализации в `parse_price_list` — превратить сокращение
  в полное имя (`Duo 256` → `iPhone Duo`).

Модели с номером (`18 Pro Max`) работают сами: их ловит `1[5-9]` и `2\d`.

Проверить:

```bash
cd /opt/vnxChooseApple_bot && python -c "
from services.price_parser import parse_price_list
for i in parse_price_list('Duo 256 Star White eSim+eSim - 210000'):
    print(i)
"
```

Пусто — значит парсер модель не узнал, дальше идти бессмысленно.

## 2. SIM — если конфигурация новая

У iPhone Duo физической SIM нет вообще, только `eSIM + eSIM`. Затронуты
четыре места, и все нужны:

| Файл | Что |
|---|---|
| `services/price_parser.py` | альтернатива в `sim_match` — **двойные варианты раньше одиночного `eSim`**, иначе совпадёт голый `eSim` и вторая потеряется |
| `services/price_publisher.py` | `_SIM_LABELS` — подпись для канала |
| `handlers/price_watcher.py` | `_infer_sim_from_id` — восстановление SIM из ID после перезапуска, **проверка до голого `ESIM`** |
| `services/price_publisher.py` | `_sim_order` — порядок внутри группы, обычно менять не нужно |

## 3. Картинка — только проверенная ссылка

Ссылку подбирать вручную нельзя. Несуществующий ID выглядит рабочей строкой
в коде, но Meta отклоняет товар с недоступной картинкой — это хуже честной
заглушки с логотипом.

```bash
# Со страницы товара
cd /opt/vnxChooseApple_bot && python run_apple_images.py https://www.apple.com/shop/buy-iphone/iphone-duo

# Или перебор по шаблонам имён Apple
cd /opt/vnxChooseApple_bot && python run_apple_images.py --guess "iPhone Duo" --date 202609

# Или проверка конкретных ID
cd /opt/vnxChooseApple_bot && python run_apple_images.py --probe iphone-duo-finish-select-202609
```

Скрипт печатает готовые строки для двух мест — нужны **оба**:

| Файл | Когда работает |
|---|---|
| `services/image_mapper.py`, `_MODEL_IMAGES` | бот пишет **новую** строку в таблицу — картинка ставится сразу |
| `run_image_audit.py`, `_r(...)` | разовый прогон по **уже существующим** строкам |

Для аксессуаров с артикулом в названии (`(MW493)`) ничего добавлять не надо:
`run_image_audit.py` берёт фото по артикулу автоматически.

Ключи в `_MODEL_IMAGES` — без префикса `Apple `, он снимается при поиске.

## 4. Порядок в канале

`_iphone_group_sort_key` в `services/price_publisher.py` сортирует по номеру
поколения. У модели без номера (`iPhone Duo`) поколение считается нулевым, и
она всплывает **выше iPhone 13** — в самый верх, хотя это флагман. Список идёт
по возрастанию, а категория iPhone публикуется последней как самая заметная,
поэтому свежему флагману место внизу:

```python
if "duo" in name:
    gen = 999
```

## 5. Фильтры — не отсекают ли новинку

`_is_apple_product` в `handlers/price_watcher.py` и `_is_non_apple`
в `run_sheets_cleanup.py`. Осторожно с эвристикой дроби (`8/ 256GB`):
она ловит Honor и Samsung, но у Mac запись `16/256` законна и для них
сделано исключение. Новая модель с необычным написанием может попасть
под раздачу.

```bash
cd /opt/vnxChooseApple_bot && python -c "
from handlers.price_watcher import _is_apple_product
t='Apple iPhone Duo'
print('пропущен:', _is_apple_product({'item_group_id':t,'title':t}))
"
```

## 6. Прогон целиком

```bash
cd /opt/vnxChooseApple_bot && git pull origin claude/funny-shannon-bMuuR && apple-restart
cd /opt/vnxChooseApple_bot && python run_image_audit.py            # предпросмотр
cd /opt/vnxChooseApple_bot && python run_image_audit.py --apply
```

Затем `/health` в боте и глазами в канал: правильные ли эмодзи, порядок
и подписи SIM.

## Почему шаг 1 первый

Все остальные шаги влияют на то, **как** товар выглядит. Первый решает,
попадёт ли он в систему вообще. Незнакомая модель отбрасывается тихо:
ни ошибки, ни инцидента — строка просто не появляется в таблице. Инцидент
`PARSE_EMPTY` срабатывает, только если не разобралось **всё** сообщение;
пропажа отдельных строк на его фоне не видна.

## 7. Характеристики в базу

Ассистенту разрешено называть только те характеристики, которые есть в базе.
Пока модели там нет, на вопрос про железо он ответит «уточню у Андрея» —
это правильное поведение, но новинку стоит описать.

Правится `data/specs/iphone.json`, затем:

```bash
cd /opt/vnxChooseApple_bot && python run_specs.py --rebuild
cd /opt/vnxChooseApple_bot && python run_specs.py --show "iPhone Duo"
```

Цифры брать со страницы характеристик Apple, а не по памяти. Незаполненное
поле безопасно — ассистент честно скажет, что не знает. Неверно заполненное
опасно: он произнесёт его как факт.

Поле `source` фиксирует происхождение данных: `apple.com` — сверено,
`newsroom` — из анонса, `seed` — требует сверки, `unknown` — данных нет.
