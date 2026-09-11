#!/usr/bin/env python3
"""
Приводит баннеры к пропорциям, которые Telegram показывает целиком.

Зачем. Telegram обрезает по бокам фотографии шире примерно 2.2:1 —
в ленте видно только середину. Баннер 2172×724 (ровно 3:1) превращается
в «ok Air 15» вместо «MacBook Air 15».

Что делает. Не трогает саму графику и ничего не сжимает: достраивает поля
сверху и снизу, продолжая крайние ряды пикселей. На градиентном фоне шва
не видно, а пропорции приходят в норму.

  python run_banner_fit.py              # предпросмотр, что будет сделано
  python run_banner_fit.py --apply      # переписать файлы
  python run_banner_fit.py --apply --ratio 2.0

Исходники сохраняются рядом с суффиксом .orig — на случай, если
результат не понравится.
"""

import shutil
import sys
from pathlib import Path

_ASSETS = Path(__file__).resolve().parent / "assets" / "banners"

# 1.91:1 — стандартные пропорции превью, Telegram показывает такое целиком
# на любом клиенте. Всё, что шире 2.2:1, на мобильном обрезается.
_DEFAULT_RATIO = 1.91
_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp")


def fit(src: Path, ratio: float, apply: bool) -> str:
    from PIL import Image

    im = Image.open(src)
    has_alpha = im.mode in ("RGBA", "LA")
    im = im.convert("RGBA" if has_alpha else "RGB")
    w, h = im.size
    current = w / h

    if current <= ratio + 0.01:
        return f"   ✅ {src.name:<22} {w}×{h} ({current:.2f}:1) — уже в норме"

    target_h = round(w / ratio)
    pad = target_h - h
    top = pad // 2
    bottom = pad - top

    if not apply:
        return (f"   ✂️  {src.name:<22} {w}×{h} ({current:.2f}:1) → "
                f"{w}×{target_h} ({ratio:.2f}:1), поля {top} сверху и {bottom} снизу")

    canvas = Image.new(im.mode, (w, target_h))
    # Продолжаем крайние ряды: на градиенте это незаметно,
    # на однотонном фоне — точное совпадение цвета.
    if top:
        canvas.paste(im.crop((0, 0, w, 1)).resize((w, top)), (0, 0))
    canvas.paste(im, (0, top))
    if bottom:
        canvas.paste(im.crop((0, h - 1, w, h)).resize((w, bottom)), (0, top + h))

    backup = src.with_suffix(src.suffix + ".orig")
    if not backup.exists():
        shutil.copy2(src, backup)

    canvas.save(src, optimize=True)
    size_mb = src.stat().st_size / 1024 / 1024
    return (f"   ✅ {src.name:<22} {w}×{h} → {w}×{target_h} "
            f"({ratio:.2f}:1), {size_mb:.2f} МБ, оригинал в {backup.name}")


def main():
    args = sys.argv[1:]
    apply = "--apply" in args
    ratio = _DEFAULT_RATIO
    if "--ratio" in args:
        ratio = float(args[args.index("--ratio") + 1])

    try:
        import PIL  # noqa: F401
    except ImportError:
        print("❌ Нужен Pillow: pip install Pillow")
        sys.exit(1)

    if not _ASSETS.exists():
        print(f"❌ Нет папки {_ASSETS}")
        sys.exit(1)

    files = sorted(
        p for p in _ASSETS.iterdir()
        if p.is_file() and p.suffix.lower() in _EXTENSIONS
    )
    if not files:
        print(f"Картинок в {_ASSETS} нет.")
        return

    print(f"🎯 Целевые пропорции: {ratio:.2f}:1\n")
    for p in files:
        try:
            print(fit(p, ratio, apply))
        except Exception as e:
            print(f"   ❌ {p.name}: {e}")

    if not apply:
        print("\n🔍 Это предпросмотр. Записать: python run_banner_fit.py --apply")
    else:
        print("\nДальше:")
        print("  git add assets/banners && git commit -m 'Fit banners' && git push")
        print("  на сервере: git pull и touch data/publish_now.flag")


if __name__ == "__main__":
    main()
