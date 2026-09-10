"""Готовит картинки логотипа из большого исходника.

    python tools/make_logo.py "brand/Логотип 3. png.png"

Делает пять файлов:
  docs/assets/logo.png      логотип в шапке сайта (прозрачный фон)
  docs/assets/favicon.png   иконка вкладки браузера
  docs/favicon.ico          та же иконка в корне сайта — за ней ходят
                            поисковики, чтобы нарисовать значок в выдаче
  docs/assets/icon-192.png  иконки для установки сайта как приложения; они
  docs/assets/icon-512.png  квадратные и на белом фоне — на домашнем экране
                            прозрачность выглядит плохо

Обрезает прозрачные поля и уменьшает: браузеру незачем качать
многомегабайтную картинку ради значка 46x46 в шапке.

Иконки обязаны быть квадратными. Логотип колледжа — вытянутый ромб, и если
сохранить его как есть, получится 57x64; Google и Яндекс такую иконку
пропускают и показывают в выдаче стандартный глобус. Поэтому картинка
вписывается в квадрат и добирается прозрачными полями.
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

BASE = Path(__file__).resolve().parent.parent
WEB = BASE / "docs"
ASSETS = WEB / "assets"

# Google просит сторону, кратную 48. Размеры внутри .ico — те, что браузеры
# и поисковики спрашивают чаще всего.
FAVICON_SIZE = 96
ICO_SIZES = [(16, 16), (32, 32), (48, 48)]


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    source = Path(sys.argv[1])
    if not source.exists():
        print(f"Файл не найден: {source}")
        return 1

    image = Image.open(source).convert("RGBA")
    box = image.getbbox()          # убираем прозрачные поля по краям
    if box:
        image = image.crop(box)

    logo = image.copy()
    logo.thumbnail((512, 512), Image.LANCZOS)
    logo.save(ASSETS / "logo.png", optimize=True)

    favicon = square(image, FAVICON_SIZE)
    favicon.save(ASSETS / "favicon.png", optimize=True)
    # Отдельный файл в корне: поисковики и старые браузеры спрашивают
    # /favicon.ico, не заглядывая в разметку страницы.
    square(image, 48).save(WEB / "favicon.ico", sizes=ICO_SIZES)

    for size in (192, 512):
        square(image, size, background=(255, 255, 255, 255), padding=0.14).save(
            ASSETS / f"icon-{size}.png", optimize=True)

    print(f"logo.png {logo.size}, favicon.png {favicon.size}, favicon.ico, "
          f"icon-192.png и icon-512.png готовы")
    return 0


def square(image: Image.Image, size: int, background=(0, 0, 0, 0),
           padding: float = 0.0) -> Image.Image:
    """Вписывает картинку в квадрат size x size, не меняя пропорций."""
    canvas = Image.new("RGBA", (size, size), background)
    inner = round(size * (1 - 2 * padding))
    fitted = image.copy()
    fitted.thumbnail((inner, inner), Image.LANCZOS)
    canvas.paste(fitted, ((size - fitted.width) // 2, (size - fitted.height) // 2),
                 fitted)
    return canvas


if __name__ == "__main__":
    raise SystemExit(main())
