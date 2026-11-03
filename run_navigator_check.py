#!/usr/bin/env python3
"""
Почему в канале нет кнопок навигации.

Навигатор молчит сразу по нескольким причинам, и по логу их не отличить:
нет файла с кнопками, не из чего собрать ссылку на канал, не нашлось ни
одного якоря, не хватило прав на отправку или закрепление. Скрипт
проходит ту же цепочку, что и публикация, и показывает, где она рвётся.

Ничего не отправляет и не меняет — только читает.

Usage:
  python run_navigator_check.py
"""

import asyncio
import os
import sys

from dotenv import load_dotenv
load_dotenv()

from services import channel_manager, navigator


def main() -> int:
    channel = os.getenv("PRICE_CHANNEL_ID", "")
    username = os.getenv("PRICE_CHANNEL_USERNAME", "")

    print("=" * 68)
    print("  Навигатор в канале")
    print("=" * 68)

    # ── 1. Файл с кнопками ───────────────────────────────────────────────
    cfg = navigator.config()
    print(f"\n1. Файл кнопок: {navigator._CONFIG}")
    if not cfg:
        print("   ❌ не прочитан или пуст")
        print("      Проверь, что файл на месте: git pull его приносит.")
        return 1
    rows = cfg.get("rows") or []
    total = sum(len(r) for r in rows)
    print(f"   ✅ рядов {len(rows)}, кнопок {total}, закреплять: "
          f"{'да' if cfg.get('pin') else 'нет'}")
    if not rows:
        print("   ❌ кнопок нет — навигатор выключен")
        return 1

    # ── 2. Основа ссылок ─────────────────────────────────────────────────
    print(f"\n2. Канал: PRICE_CHANNEL_ID={channel or '(не задан)'}"
          f"  PRICE_CHANNEL_USERNAME={username or '(не задан)'}")
    base = navigator._channel_base(channel)
    if base:
        print(f"   ✅ ссылки вида {base}/<id>")
    else:
        print("   ❌ собрать ссылки не из чего")
        print("      Добавь в .env: PRICE_CHANNEL_USERNAME=vnxSHOPprice")
        print("      Кнопки с якорями работать не будут, только start/url.")

    # ── 3. Якоря последней публикации ────────────────────────────────────
    manifest = channel_manager.load_manifest()
    slots = manifest.get("slots", [])
    anchors = {s["anchor"]: s["id"] for s in slots if s.get("anchor")}
    print(f"\n3. Реестр: {channel_manager._IDS_FILE}")
    print(f"   постов {len(slots)}, якорей {len(anchors)}, "
          f"пост навигатора: {manifest.get('nav_id') or 'ещё не создан'}")
    if not slots:
        print("   ❌ прайс ни разу не публиковался после обновления")
        print("      touch /opt/vnxChooseApple_bot/data/publish_now.flag")
        return 1
    if anchors:
        print("\n   Что есть:")
        for anchor, msg_id in sorted(anchors.items()):
            print(f"     {anchor:<28} → сообщение {msg_id}")

    # ── 4. Имя бота для кнопок start ─────────────────────────────────────
    bot_username = asyncio.run(_bot_username())
    print(f"\n4. Имя бота: {bot_username or '(не получено)'}")
    if not bot_username:
        print("   ⚠️  кнопки со start нарисованы не будут")

    # ── 5. Что получится ─────────────────────────────────────────────────
    title, markup = navigator.build(channel, anchors, bot_username)
    print("\n5. Кнопки, которые уйдут в канал:\n")
    if not markup:
        print("   ❌ ни одной рабочей кнопки — пост не публикуется")
    else:
        for row in markup.inline_keyboard:
            print("   " + " | ".join(f"[{b.text}]" for b in row))
            for b in row:
                print(f"       {b.text}  →  {b.url}")

    dropped = _dropped(cfg, base, anchors, bot_username)
    if dropped:
        print("\n   ⚠️  Отброшены:\n")
        for text, reason in dropped:
            print(f"     {text}")
            print(f"       {reason}")
        print("\n   Кнопка на несуществующий раздел хуже, чем её отсутствие.")
        print("   Якорь появится сам, когда появится блок.")

    print(f"\n   Заголовок поста: {title}")
    print("\n" + "=" * 68)
    if markup and manifest.get("nav_id"):
        print("  Пост навигатора существует. Если его не видно — он в самом")
        print("  низу канала и закреплён; проверь закреплённые сообщения.")
    elif markup:
        print("  Кнопки собираются, но поста ещё нет. Опубликуй прайс:")
        print("  touch /opt/vnxChooseApple_bot/data/publish_now.flag")
    return 0


async def _bot_username() -> str:
    token = os.getenv("BOT_TOKEN", "")
    if not token:
        return ""
    from aiogram import Bot
    bot = Bot(token=token)
    try:
        me = await bot.get_me()
        return me.username or ""
    except Exception as e:
        print(f"   ⚠️  get_me не ответил: {e}")
        return ""
    finally:
        await bot.session.close()


def _dropped(cfg, base, anchors, bot_username) -> list:
    """Кнопки, для которых не нашлось цели, и почему именно."""
    out = []
    for row in cfg.get("rows") or []:
        for item in row:
            text = str(item.get("text", "")).strip()
            if not text:
                continue
            if navigator._resolve(item, base, anchors, bot_username):
                continue

            want = item.get("anchors") or []
            if want and not base:
                reason = "ссылки на канал не собираются — см. пункт 2"
            elif want:
                reason = f"ни одного блока: {', '.join(want)}"
            elif item.get("start") and not bot_username:
                reason = "нужно имя бота — см. пункт 4"
            else:
                reason = "в кнопке не указано ни anchors, ни start, ни url"
            out.append((text, reason))
    return out


if __name__ == "__main__":
    sys.exit(main())
