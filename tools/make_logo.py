"""Готовит картинки логотипа из большого исходника.

    python tools/make_logo.py "web/assets/Логотип 3. png.png"

Делает четыре файла:
  logo.png      логотип в шапке сайта (прозрачный фон)
  favicon.png   иконка вкладки браузера
  icon-192.png  иконки для установки сайта как приложения; они квадратные
  icon-512.png  и на белом фоне — на домашнем экране прозрачность выглядит плохо

Обрезает прозрачные поля и уменьшает: браузеру незачем качать
многомегабайтную картинку ради значка 46x46 в шапке.
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

ASSETS = Path(__file__).resolve().parent.parent / "web" / "assets"


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

    favicon = image.copy()
    favicon.thumbnail((64, 64), Image.LANCZOS)
    favicon.save(ASSETS / "favicon.png", optimize=True)

    for size in (192, 512):
        app_icon(image, size).save(ASSETS / f"icon-{size}.png", optimize=True)

    print(f"logo.png {logo.size}, favicon.png {favicon.size}, "
          f"icon-192.png и icon-512.png готовы")
    return 0


def app_icon(image: Image.Image, size: int, padding: float = 0.14) -> Image.Image:
    """Квадратная иконка на белом фоне с полями — для домашнего экрана."""
    canvas = Image.new("RGBA", (size, size), (255, 255, 255, 255))
    inner = round(size * (1 - 2 * padding))
    logo = image.copy()
    logo.thumbnail((inner, inner), Image.LANCZOS)
    canvas.paste(logo, ((size - logo.width) // 2, (size - logo.height) // 2), logo)
    return canvas


if __name__ == "__main__":
    raise SystemExit(main())
