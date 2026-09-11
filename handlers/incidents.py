"""
Команды владельца для работы с инцидентами.

/health     — короткая сводка: жив бот или нет
/incidents  — список открытых инцидентов
/incidents all — вместе с историей закрытых
/incident <код> — подробная карточка: почему сломалось и что делать
"""

import logging
import os

from aiogram import Router, types, F
from aiogram.filters import Command, CommandObject

from services import incidents
from services import incident_rules as rules
from services import specs_db
from services import banners
import services.data_store as store

logger = logging.getLogger(__name__)
router = Router()

MANAGER_ID = os.getenv("MANAGER_ID")


def _is_owner(message: types.Message) -> bool:
    return bool(MANAGER_ID) and str(message.from_user.id) == MANAGER_ID


def _esc(text) -> str:
    return (str(text).replace("&", "&amp;")
                     .replace("<", "&lt;")
                     .replace(">", "&gt;"))


@router.message(Command("health"))
async def cmd_health(message: types.Message):
    """Светофор состояния — то, что смотрят первым делом."""
    if not _is_owner(message):
        return

    h = incidents.health()
    counts = h["counts"]

    if h["healthy"] and h["open"] == 0:
        head = "🟢 <b>Всё работает</b>"
        body = "Открытых инцидентов нет."
    elif h["healthy"]:
        head = "🟡 <b>Работает с замечаниями</b>"
        body = f"Предупреждений: {counts.get(rules.WARNING, 0)}"
    else:
        head = "🔴 <b>Есть поломки</b>"
        parts = []
        if counts.get(rules.CRITICAL):
            parts.append(f"критичных: {counts[rules.CRITICAL]}")
        if counts.get(rules.ERROR):
            parts.append(f"ошибок: {counts[rules.ERROR]}")
        if counts.get(rules.WARNING):
            parts.append(f"предупреждений: {counts[rules.WARNING]}")
        body = " · ".join(parts)

    worst = h["worst"]
    worst_block = ""
    if worst:
        rule = rules.get_rule(worst.code)
        worst_block = (
            f"\n\n<b>Главное сейчас:</b>\n"
            f"{rules.SEVERITY_EMOJI.get(worst.severity, '⚪')} {_esc(rule.title)}\n"
            f"длится {worst.age()} · сбоев {worst.count}\n"
            f"<code>{_esc(worst.code)}</code>"
        )

    await message.answer(
        f"{head}\n{body}"
        f"{worst_block}\n\n"
        f"📋 Позиций в каталоге: {len(store.CATALOG)}\n\n"
        f"<i>Подробнее: /incidents</i>",
        parse_mode="HTML",
    )


@router.message(Command("incidents"))
async def cmd_incidents(message: types.Message, command: CommandObject):
    """Список инцидентов. С аргументом all — включая закрытые."""
    if not _is_owner(message):
        return

    show_all = (command.args or "").strip().lower() in ("all", "все", "-a")

    open_items = incidents.open_incidents()

    lines = ["<b>🚨 Открытые инциденты</b>", ""]
    if not open_items:
        lines.append("Пусто — ничего не сломано.")
    else:
        for inc in open_items:
            rule = rules.get_rule(inc.code)
            emoji = rules.SEVERITY_EMOJI.get(inc.severity, "⚪")
            lines.append(
                f"{emoji} <b>{_esc(rule.title)}</b>\n"
                f"   <code>{_esc(inc.code)}</code> · {inc.component} · "
                f"длится {inc.age()} · сбоев {inc.count}"
            )

    if show_all:
        past = [i for i in incidents.history(30) if not i.is_open]
        lines += ["", "<b>📕 Закрытые (последние)</b>", ""]
        if not past:
            lines.append("Нет записей.")
        for inc in past[:15]:
            rule = rules.get_rule(inc.code)
            lines.append(
                f"✅ {_esc(rule.title)} — держался {inc.age()}, "
                f"сбоев {inc.count}"
            )
    else:
        lines += ["", "<i>История закрытых: /incidents all</i>"]

    lines += ["", "<i>Разбор конкретного: /incident КОД</i>"]

    text = "\n".join(lines)
    await message.answer(text[:4000], parse_mode="HTML")


@router.message(Command("incident"))
async def cmd_incident(message: types.Message, command: CommandObject):
    """Подробная карточка: что сломалось, почему важно, что делать."""
    if not _is_owner(message):
        return

    arg = (command.args or "").strip()
    if not arg:
        known = sorted(rules.RULES)
        await message.answer(
            "Укажи код инцидента: <code>/incident SHEETS_PERMISSION_DENIED</code>\n\n"
            "<b>Все известные коды:</b>\n"
            + "\n".join(f"· <code>{c}</code>" for c in known),
            parse_mode="HTML",
        )
        return

    found = incidents.find(arg)
    if found:
        # Показываем самый свежий инцидент с этим кодом
        await message.answer(incidents.card(found[0]), parse_mode="HTML")
        return

    # Инцидента не было — показываем справку по коду из каталога
    code = arg.upper()
    if code in rules.RULES:
        rule = rules.RULES[code]
        await message.answer(
            f"{rules.SEVERITY_EMOJI.get(rule.severity, '⚪')} "
            f"<b>{_esc(rule.title)}</b>\n"
            f"<i>Такого инцидента ещё не случалось.</i>\n\n"
            f"<b>Почему это важно</b>\n{_esc(rule.why)}\n\n"
            f"<b>Что сделать</b>\n{_esc(rule.fix)}"
            + (f"\n\n📖 {_esc(rule.docs)}" if rule.docs else ""),
            parse_mode="HTML",
        )
        return

    await message.answer(f"Код <code>{_esc(arg)}</code> не найден.", parse_mode="HTML")


@router.message(Command("specs"))
async def cmd_specs(message: types.Message, command: CommandObject):
    """
    Характеристики модели из базы — то же, что видит ассистент.

    Команда нужна, чтобы проверять базу глазами: если здесь пусто,
    значит и ассистент про это железо говорить не станет.
    """
    if not _is_owner(message):
        return

    arg = (command.args or "").strip()
    if not arg:
        rows = specs_db.all_models()
        if not rows:
            await message.answer(
                "База характеристик пуста.\n"
                "Собери её на сервере: <code>python run_specs.py --rebuild</code>",
                parse_mode="HTML",
            )
            return
        total = len(specs_db._gap_fields())
        lines = ["<b>📐 Модели в базе характеристик</b>", ""]
        for r in rows:
            lines.append(f"· {_esc(r['model'])} — {specs_db.filled_fields(r)}/{total} полей")
        lines += ["", "<i>Подробно: /specs 16 Pro Max</i>"]
        await message.answer("\n".join(lines)[:4000], parse_mode="HTML")
        return

    row = specs_db.find(arg)
    if not row:
        await message.answer(
            f"❌ «{_esc(arg)}» в базе нет — про эту модель ассистент "
            f"характеристики называть не будет.\n\n"
            f"<i>Список моделей: /specs</i>",
            parse_mode="HTML",
        )
        return

    await message.answer(specs_db.format_card(row)[:4000], parse_mode="HTML")


@router.message(F.photo, F.caption.func(lambda c: (c or "").strip().lower().startswith("/banner")))
async def cmd_banner_photo(message: types.Message):
    """
    Сохраняет присланное фото как шапку блока прайса.

    Способ на случай, когда коммитить картинку неудобно. Учти: фото
    останется видимым в том чате, куда его отправили. Если это нежелательно,
    лучше положить файл в assets/banners в репозитории — тогда он никуда
    не публикуется.
    """
    if not _is_owner(message):
        return

    parts = (message.caption or "").split()
    key = banners.slug(parts[1]) if len(parts) > 1 else ""

    if not key:
        await message.answer(
            "Укажи ключ в подписи к фото: <code>/banner macbookair13</code>\n\n"
            "Частые ключи: " + ", ".join(f"<code>{k}</code>" for k in banners.KNOWN_KEYS),
            parse_mode="HTML",
        )
        return

    banners.save(key, message.photo[-1].file_id)
    await message.answer(
        f"✅ Баннер <b>{_esc(key)}</b> сохранён — появится над блоком "
        f"при следующей публикации.\n\n"
        f"<i>Что стоит: /banners · убрать: /banner_off {_esc(key)}</i>",
        parse_mode="HTML",
    )


@router.message(Command("banners"))
async def cmd_banners(message: types.Message):
    """Показывает все баннеры и откуда каждый берётся."""
    if not _is_owner(message):
        return

    assets = banners.list_assets()
    ids = banners.all_file_ids()

    lines = ["<b>🖼 Баннеры прайса</b>", ""]

    if assets:
        lines.append("<b>Из репозитория</b> <i>(assets/banners)</i>")
        for k in assets:
            lines.append(f"  📁 <code>{_esc(k)}</code>")
        lines.append("")
    if ids:
        lines.append("<b>Присланы боту</b>")
        for k in ids:
            lines.append(f"  📨 <code>{_esc(k)}</code>")
        lines.append("")
    if not assets and not ids:
        lines.append("Пока ни одного.\n")

    lines += [
        "<b>Как поставить</b>",
        "Положить файл <code>assets/banners/macbookair13.jpg</code> "
        "в репозиторий и сделать git pull на сервере — картинка нигде "
        "не публикуется.",
        "",
        "Либо отправить сюда фото с подписью <code>/banner macbookair13</code>.",
        "",
        "<b>Ключи блоков:</b> " + ", ".join(
            f"<code>{k}</code>" for k in banners.KNOWN_KEYS[:6]
        ),
        "<i>Для блока ищется свой ключ, затем общий: "
        "macbookair13 → macbookair → mac</i>",
    ]

    await message.answer("\n".join(lines)[:4000], parse_mode="HTML")

    for key, file_id in ids.items():
        try:
            await message.answer_photo(file_id, caption=f"Баннер: {key}")
        except Exception:
            await message.answer(f"⚠️ Баннер «{key}» не открывается — переустанови.")


@router.message(Command("banner_off"))
async def cmd_banner_off(message: types.Message, command: CommandObject):
    """Убирает баннер, присланный боту. Файлы в репозитории не трогает."""
    if not _is_owner(message):
        return

    key = banners.slug((command.args or "").strip())
    if not key:
        await message.answer(
            "Укажи ключ: <code>/banner_off macbookair13</code>", parse_mode="HTML"
        )
        return

    if banners.remove(key):
        await message.answer(f"✅ Баннер «{_esc(key)}» убран.", parse_mode="HTML")
    elif banners.asset_path(key):
        await message.answer(
            f"Баннер «{_esc(key)}» лежит файлом в репозитории — "
            f"удаляется вместе с файлом, не командой.",
            parse_mode="HTML",
        )
    else:
        await message.answer(f"Баннера «{_esc(key)}» и не было.", parse_mode="HTML")


@router.message(Command("banner"))
async def cmd_banner_help(message: types.Message):
    """Подсказка, когда команду прислали текстом без фото."""
    if not _is_owner(message):
        return
    await message.answer(
        "<b>Картинка над блоком прайса</b>\n\n"
        "<b>Способ 1 — файл в репозитории (не публикуется нигде):</b>\n"
        "положи картинку в <code>assets/banners/</code> с именем-ключом, "
        "например <code>macbookair13.jpg</code>, закоммить и сделай "
        "git pull на сервере.\n\n"
        "<b>Способ 2 — прислать боту:</b>\n"
        "отправь фото и напиши в подписи <code>/banner macbookair13</code>. "
        "Быстрее, но фото останется видимым в этом чате.\n\n"
        "<b>Ключи:</b> " + ", ".join(f"<code>{k}</code>" for k in banners.KNOWN_KEYS[:8]) +
        "\n\n<i>Что уже стоит: /banners</i>",
        parse_mode="HTML",
    )
