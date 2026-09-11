# Картинки-шапки прайса

Файл отсюда уходит в канал над соответствующим блоком прайса.

## Как добавить

Положить картинку с именем-ключом и закоммитить:

```
assets/banners/macbookair13.jpg
assets/banners/macbookair15.jpg
assets/banners/iphone.jpg
```

Затем на сервере:

```bash
cd /opt/vnxChooseApple_bot && git pull origin claude/funny-shannon-bMuuR && apple-restart
```

Картинка отправляется в канал **загрузкой файла**, а не по ссылке. Поэтому
неважно, открыт репозиторий наружу или нет, и нигде публично она не лежит.

## Ключи

Для каждого блока перебирается цепочка от частного к общему, побеждает
первый найденный файл:

| Блок в канале | Порядок поиска |
|---|---|
| MacBook Air 13″ | `macbookair13` → `macbookair` → `mac` |
| MacBook Air 15″ | `macbookair15` → `macbookair` → `mac` |
| MacBook Pro 14″ | `macbookpro14` → `macbookpro` → `mac` |
| MacBook Pro 16″ | `macbookpro16` → `macbookpro` → `mac` |
| iPhone | `iphone` |
| iPad | `ipad` |
| AirPods | `airpods` |
| Apple Watch | `watch` |

Одна картинка `mac.jpg` закроет все маки сразу. Хочешь разные —
заводи `macbookair13.jpg` и `macbookair15.jpg`.

Форматы: `.jpg`, `.jpeg`, `.png`, `.webp`.

Если один и тот же баннер выпадает нескольким блокам подряд, он
отправляется один раз, а не перед каждым.

## Размер

Telegram сжимает крупные фото. Разумно 1200–1600 пикселей по ширине,
пропорции близкие к 3:1 — как у баннера на всю ширину сообщения.
