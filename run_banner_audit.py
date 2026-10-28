#!/usr/bin/env python3
"""
Какие блоки прайса остались без картинки.

Строит ровно ту же раскладку, что уходит в канал, и сверяет её с тем,
что лежит в assets/banners. Имена в колонке «файл» — готовые: положил
картинку с таким именем, и она подхватится без правки кода.

Usage:
  python run_banner_audit.py
"""

import sys

from dotenv import load_dotenv
load_dotenv()

from services import banners


def main():
    from handlers.price_watcher import _catalog_items_for_publish
    from services.price_publisher import (
        _get_category, _display_group, _format_category_messages,
        _category_keys, _CATEGORY_ORDER, _mac_line, _mac_split_ram,
        _group_key,
    )
    from services.sheets_manager import get_data_from_sheet
    from services import coming_soon
    import services.data_store as store
    from collections import defaultdict

    print("🔗 Читаем каталог...")
    # _catalog_items_for_publish() берёт каталог из памяти бота, а здесь
    # отдельный процесс и память пустая. Поэтому сначала тянем из Sheets.
    store.CATALOG = get_data_from_sheet()
    items = _catalog_items_for_publish()
    if not items:
        print("❌ Каталог пуст или Sheets недоступен")
        sys.exit(1)
    print(f"   позиций в наличии: {len(items)}\n")

    by_cat = defaultdict(list)
    for item in items:
        by_cat[_get_category(item)].append(item)

    rows = []   # (раздел, блок, имя найденного файла или "", ключ, обязательна ли)

    def source(found) -> str:
        """Имя файла из результата поиска. resolve() даёт кортеж, asset_path() — путь."""
        if not found:
            return ""
        if isinstance(found, tuple):
            key, kind, value = found
            return getattr(value, "name", str(value)) if kind == "file" else f"ссылка ({key})"
        return getattr(found, "name", str(found))

    for cat in _CATEGORY_ORDER:
        cat_items = by_cat.get(cat)
        if not cat_items:
            continue

        if cat == "mac":
            # У Mac цепочка от частного к общему: macbookpro14 → macbookpro → mac.
            # Проверять только точный ключ нельзя — иначе посоветуем создать
            # файл там, где общая картинка уже работает.
            import re as _re
            lines = sorted({_mac_line(_mac_split_ram(str(i.get("item_group_id", "")))[0])
                            for i in cat_items})
            for line in lines:
                family = _re.sub(r"\s*\d{2}″$", "", line)
                keys = [banners.slug(line), banners.slug(family), "mac"]
                rows.append(("Mac", line, source(banners.resolve(keys)), keys[0], True))

        elif cat in ("iphone", "ipad"):
            # Картинка группы не обязательна: без неё группа едет в общем
            # посте категории. Своя картинка поднимает её в отдельный пост.
            # Группируем ровно как публикация: по ключу без регистра,
            # имя берём наименьшее из написаний. Иначе аудит посоветует
            # два файла там, где в канале один блок.
            spellings = defaultdict(list)
            for i in cat_items:
                raw = str(i.get("item_group_id") or "").strip() or "Другое"
                spellings[_group_key(raw)].append(raw)
            groups = sorted(_display_group(cat, min(v)) for v in spellings.values())
            cat_banner = banners.resolve(_category_keys(cat))
            rows.append((cat, _CATEGORY_TITLE_RU.get(cat, cat) + " (общая)",
                         source(cat_banner), _category_keys(cat)[0], True))
            for g in groups:
                key = banners.slug(g)
                rows.append((cat, g, source(banners.asset_path(key)), key, False))
        else:
            found = banners.resolve(_category_keys(cat))
            rows.append((cat, _CATEGORY_TITLE_RU.get(cat, cat), source(found),
                         _category_keys(cat)[0], True))

    for entry in coming_soon.pending([str(i.get("item_group_id", "")) for i in items]):
        key = entry.get("key", "")
        rows.append(("Coming Soon", entry["title"], source(banners.resolve([key])), key, True))

    have = [r for r in rows if r[2]]
    need = [r for r in rows if not r[2] and r[4]]
    nice = [r for r in rows if not r[2] and not r[4]]

    print("=" * 72)
    print(f"  Блоков: {len(rows)}   с картинкой: {len(have)}   "
          f"нужно: {len(need)}   по желанию: {len(nice)}")
    print("=" * 72)

    if have:
        print("\n✅ Картинка есть\n")
        for section, name, src, key, _ in have:
            print(f"   {section:<12} {name[:34]:<35} {src}")

    if need:
        print("\n⚠️  НУЖНО СОЗДАТЬ — блок выходит без картинки\n")
        print(f"   {'раздел':<12} {'блок':<35} файл")
        for section, name, _, key, _r in need:
            print(f"   {section:<12} {name[:34]:<35} {key}.png")

    if nice:
        print("\n💡 ПО ЖЕЛАНИЮ — сейчас едут в общем посте категории,")
        print("   своя картинка поднимет модель в отдельный пост\n")
        print(f"   {'раздел':<12} {'блок':<35} файл")
        for section, name, _, key, _r in nice:
            print(f"   {section:<12} {name[:34]:<35} {key}.png")

    if need or nice:
        print("\n   Класть в assets/banners/. Пропорции 1.91:1 или 16:9;")
        print("   шире 2.2:1 Telegram обрежет по бокам. Формат любой.")
        print("   Каждая новая картинка добавляет пост в канал.")
    else:
        print("\n🟢 Все блоки с картинками.")


_CATEGORY_TITLE_RU = {
    "accessory": "Аксессуары",
    "audio":     "Наушники и звук",
    "watch":     "Apple Watch",
    "ipad":      "iPad",
    "iphone":    "iPhone",
}


if __name__ == "__main__":
    main()
