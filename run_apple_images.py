#!/usr/bin/env python3
"""
Достаёт ID картинок Apple CDN для новой модели — со страницы apple.com
или проверкой заранее заданных кандидатов.

Зачем. При каждом анонсе Apple в прайсах появляется модель, для которой
в боте нет картинки, и товар уходит в Meta с логотипом-заглушкой. Подбирать
ID вручную нельзя: ссылка на несуществующий ID выглядит как рабочая строка
в коде, но Meta отклоняет товар с недоступной картинкой. Скрипт снимает
угадывание — ID берётся со страницы товара и проверяется запросом.

Режимы:

  # Разобрать страницу товара и показать найденные картинки
  python run_apple_images.py https://www.apple.com/shop/buy-iphone/iphone-duo

  # Проверить конкретные ID (когда страница недоступна)
  python run_apple_images.py --probe iphone-duo-finish-select-202609 \\
                                     iphone-18-pro-finish-select-202609

  # Кандидаты по шаблонам Apple для модели (перебор без страницы)
  python run_apple_images.py --guess "iPhone Duo" --date 202609

Скрипт ничего не записывает — он печатает готовые строки, которые
вставляются в services/image_mapper.py и run_image_audit.py.
"""

import re
import sys

_BASE = "https://store.storeimages.cdn-apple.com/4982/as-images.apple.com/is/"
_Q    = "?wid=1000&hei=1000&fmt=jpeg&qlt=90"

# Минимальный размер картинки для Meta Commerce Manager — 500×500.
# При wid=1000 такой ответ весит килобайты; совсем мелкий ответ означает
# заглушку или ошибку, отданную со статусом 200.
_MIN_BYTES = 5_000

# ID картинок в разметке страниц Apple
_ID_RE = re.compile(r"as-images\.apple\.com/is/([A-Za-z0-9][A-Za-z0-9_.\-]{3,80})")

# Служебные картинки, не относящиеся к товару
_SKIP_RE = re.compile(
    r"^(og-|social|favicon|apple-touch|chat|nav-|globalnav|store-card-)", re.IGNORECASE
)


def _url(image_id: str) -> str:
    return f"{_BASE}{image_id}{_Q}"


def verify(image_id: str) -> tuple[bool, str]:
    """Проверяет, что по ID действительно отдаётся картинка нужного размера."""
    try:
        import requests
    except ImportError:
        return False, "нет модуля requests"

    try:
        r = requests.get(_url(image_id), timeout=15, stream=True)
        if r.status_code != 200:
            r.close()
            return False, f"HTTP {r.status_code}"

        ctype = r.headers.get("Content-Type", "")
        if not ctype.startswith("image/"):
            r.close()
            return False, f"не картинка ({ctype or 'без типа'})"

        # Читаем начало, чтобы отличить настоящее фото от заглушки-крохи
        size = 0
        for chunk in r.iter_content(8192):
            size += len(chunk)
            if size >= _MIN_BYTES:
                break
        r.close()

        if size < _MIN_BYTES:
            return False, f"слишком мелкая ({size} байт)"
        return True, f"{ctype}, ≥{size // 1024} КБ"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def from_page(url: str) -> list[str]:
    """Собирает ID картинок со страницы товара, чаще встречающиеся — выше."""
    try:
        import requests
    except ImportError:
        print("❌ Нет модуля requests")
        sys.exit(1)

    print(f"🔗 Читаем {url}\n")
    try:
        r = requests.get(
            url, timeout=30,
            headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"},
        )
    except Exception as e:
        print(f"❌ Страница недоступна: {e}")
        print("   Попробуй режим --probe или --guess.")
        sys.exit(1)

    if r.status_code != 200:
        print(f"❌ Страница вернула HTTP {r.status_code}")
        sys.exit(1)

    counts: dict[str, int] = {}
    for m in _ID_RE.finditer(r.text):
        image_id = m.group(1).rstrip(".")
        if _SKIP_RE.search(image_id):
            continue
        counts[image_id] = counts.get(image_id, 0) + 1

    if not counts:
        print("⚠️  На странице не нашлось ссылок на картинки CDN.")
        print("   Apple могла отдать разметку, где картинки подгружаются скриптом.")
        print("   Открой страницу в браузере, правый клик по фото → «Копировать адрес»,")
        print("   и проверь ID режимом --probe.")
        return []

    return sorted(counts, key=lambda k: (-counts[k], k))


def guess_candidates(model: str, date: str) -> list[str]:
    """
    Кандидаты по шаблонам имён, которые Apple использует на страницах покупки.
    Проверка всё равно обязательна — это лишь способ сузить перебор.
    """
    slug = re.sub(r"[^a-z0-9]+", "-", model.lower()).strip("-")
    return [
        f"{slug}-finish-select-{date}",
        f"{slug}-finish-unselect-{date}",
        f"{slug}-select-{date}",
        f"{slug}-hero-select-{date}",
        f"{slug}-model-unselect-gallery-1-{date}",
        f"{slug}-finish-select",
        f"{slug}-select",
    ]


def report(ids: list[str], limit: int = 25) -> list[str]:
    """Проверяет ID и печатает результат. Возвращает рабочие."""
    if not ids:
        return []

    print(f"⏳ Проверяем {min(len(ids), limit)} ID...\n")
    good: list[str] = []
    for image_id in ids[:limit]:
        ok, note = verify(image_id)
        print(f"  {'✅' if ok else '❌'}  {image_id[:58]:<58}  {note}")
        if ok:
            good.append(image_id)
    return good


def print_snippets(model: str, good: list[str]) -> None:
    if not good:
        print("\n⚠️  Ни один ID не подтвердился — вставлять в код нечего.")
        print("   Ссылку без проверки добавлять нельзя: Meta отклонит товар,")
        print("   у которого картинка не открывается.")
        return

    best = good[0]
    print(f"\n{'='*72}")
    print(f"  Готово. Рабочих ID: {len(good)}, берём первый: {best}")
    print(f"{'='*72}")

    print("\n── В services/image_mapper.py, в _MODEL_IMAGES ──")
    print(f'    "{model}": "{_url(best)}",')

    slug = re.sub(r"[^a-z0-9]+", r"\\s*", model.lower()).strip()
    print("\n── В run_image_audit.py, рядом с правилами того же семейства ──")
    print(f'_r(r"{slug}", _u("{best}"))')

    if len(good) > 1:
        print("\n── Остальные рабочие ID (пригодятся для расцветок) ──")
        for image_id in good[1:]:
            print(f"   {image_id}")


def main():
    args = [a for a in sys.argv[1:] if a]
    if not args:
        print(__doc__)
        sys.exit(1)

    if args[0] == "--probe":
        ids = args[1:]
        if not ids:
            print("❌ Укажи хотя бы один ID после --probe")
            sys.exit(1)
        good = report(ids, limit=len(ids))
        print_snippets("МОДЕЛЬ", good)
        return

    if args[0] == "--guess":
        if len(args) < 2:
            print('❌ Укажи модель: --guess "iPhone Duo" --date 202609')
            sys.exit(1)
        model = args[1]
        date = "202609"
        if "--date" in args:
            date = args[args.index("--date") + 1]
        ids = guess_candidates(model, date)
        print(f"🎲 Кандидаты по шаблонам Apple для «{model}» ({date}):\n")
        good = report(ids, limit=len(ids))
        print_snippets(model, good)
        return

    url = args[0]
    ids = from_page(url)
    if ids:
        print(f"Найдено уникальных ID: {len(ids)}\n")
        good = report(ids)
        model = re.sub(r"[-_]+", " ", url.rstrip("/").split("/")[-1]).title()
        print_snippets(model, good)


if __name__ == "__main__":
    main()
