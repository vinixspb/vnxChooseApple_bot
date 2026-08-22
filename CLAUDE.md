# vnxChooseApple_bot

Telegram-бот магазина Apple: поставщики публикуют прайсы в группах → бот парсит →
применяет наценку → пишет в Google Sheets `vnxSHOP` → публикует прайс в канал `@vnxSHOPprice`.

## Продакшн-сервер

| Что | Значение |
|---|---|
| Хост | `2060665-ca78651.twc1.net` |
| Рабочая папка | `/opt/vnxChooseApple_bot` |
| systemd-сервис | `vnx-apple-shop.service` |
| Рестарт | `apple-restart` |
| Логи | `journalctl -u vnx-apple-shop.service -f` |
| Бот | `@vnxSHOP_AppleFinder_bot` (id 7707127201) |
| Ветка разработки | `claude/funny-shannon-bMuuR` |
| Python | 3.10, пакеты в `/usr/local/lib/python3.10/dist-packages` |

Все команды для сервера выдавать с полным путём `/opt/vnxChooseApple_bot`,
пользователь часто находится в других папках (`/opt/vnxMATRIX_system_bot`,
`/opt/vnxSECRETARY` и т.д.).

Стандартный деплой:

```bash
cd /opt/vnxChooseApple_bot && git pull origin claude/funny-shannon-bMuuR && apple-restart
```

Соседние проекты на том же сервере: `vnxMATRIX_system_bot`, `vnxMATRIX_support`,
`vnxSECRETARY`, `vnxORACLE_system`, `vnxVPN_system`, `SunnyStorage_bot`,
`KegPro_system`, `SHOROHI_system`.

## Секреты

`.env` живёт только на сервере и никогда не коммитится. Токены и ключи
(`SECRETARY_BOT_TOKEN`, `GOOGLE_CREDENTIALS_JSON`, `BOT_TOKEN`) не должны
попадать ни в код, ни в git, ни в сообщения.

## Служебные скрипты

```bash
cd /opt/vnxChooseApple_bot && python run_sheets_check.py     # диагностика доступа к Sheets
cd /opt/vnxChooseApple_bot && python run_sheets_cleanup.py   # предпросмотр не-Apple товаров
cd /opt/vnxChooseApple_bot && python run_sheets_cleanup.py --apply
cd /opt/vnxChooseApple_bot && python run_image_audit.py      # предпросмотр image_link
cd /opt/vnxChooseApple_bot && python run_image_audit.py --apply
```

Для записи в таблицу сервис-аккаунт должен иметь права **Редактор** на файле
`SPREADSHEET_ID`. При правах «Читатель» чтение работает, а запись падает с
`APIError: [403]: The caller does not have permission`.

Правильный сервис-аккаунт для этого проекта — `sheets-access-bot@vnxchooseapple`.
У каждого проекта свой аккаунт, чужие (например `vnxvpn-service`) использовать нельзя.
Смена ключа: `python run_set_credentials.py /путь/к/ключу.json`.

## Система инцидентов

Полная документация: `docs/INCIDENTS.md`.

Сбои не должны быть тихими. Любая ошибка Sheets, Telegram или парсера
превращается в инцидент с кодом, причиной и инструкцией по починке, и
уходит владельцу в Telegram. Успешная операция гасит инцидент сама.

Команды владельца в боте: `/health`, `/incidents`, `/incidents all`,
`/incident КОД`.

Ключевой код — `SYNC_WROTE_NOTHING`: прайс разобран, а в таблицу записано
0 строк. Ловит потерю прав Редактора, которая раньше жила незамеченной
неделями, потому что публикация в канал идёт из памяти и выглядит здоровой.

При добавлении нового кода в `services/incident_rules.py` обязательно
заполнять `fix` — конкретное действие. Код без внятной инструкции по
починке превращает алерт в шум.
