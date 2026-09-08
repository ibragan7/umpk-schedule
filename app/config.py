"""Настройки сервиса расписания УМПК."""
from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
# Папка называется docs, потому что GitHub Pages умеет раздавать сайт только
# из корня репозитория или из /docs. Внутри — обычные файлы сайта.
WEB_DIR = BASE_DIR / "docs"
SITE_DATA_FILE = WEB_DIR / "data" / "schedule.json"   # то, что читает сайт
DATA_DIR = BASE_DIR / "data"
RAW_DIR = DATA_DIR / "raw"          # последние скачанные .xlsx
SNAPSHOT_FILE = DATA_DIR / "schedule.json"   # рабочий кэш сервиса

# Публичная папка облака Mail.ru со всеми файлами расписания.
CLOUD_PUBLIC_LINK = os.getenv("UMPK_CLOUD_LINK", "KRh4/Q5UoGDxkv")

# Как часто перекачивать и заново разбирать файлы (секунды).
REFRESH_INTERVAL = int(os.getenv("UMPK_REFRESH_INTERVAL", str(60 * 60)))

# Сеть
HOST = os.getenv("UMPK_HOST", "0.0.0.0")
PORT = int(os.getenv("UMPK_PORT", "8000"))
HTTP_TIMEOUT = int(os.getenv("UMPK_HTTP_TIMEOUT", "60"))

# Название учебного заведения (выводится в шапке сайта).
COLLEGE_SHORT = "УМПК"
COLLEGE_FULL = "Уфимский многопрофильный профессиональный колледж"

# Ручные исправления опечаток в названиях групп.
# Ключ — как разбор назвал повторяющийся столбец, значение — как правильно.
# В «ДИ ТИК ПК.xlsx» две разные группы подписаны «3 ТИК А»; вторая из них —
# на самом деле «3 ТИК Б». Когда опечатку поправят в самой таблице, строку
# отсюда можно убрать: разбор перестанет находить дубль и правило не сработает.
GROUP_RENAMES = {
    "3 ТИК А (2)": "3 ТИК Б",
}

# Какой лист брать, если в книге несколько листов на одну и ту же неделю.
# Так бывает, когда в Excel продублировали вкладку: рядом с «2 неделя»
# появляется «2 неделя (2)». Складывать их нельзя — все пары удвоятся,
# поэтому берём ровно один, а про остальные пишем предупреждение.
#   "last"  — последний по порядку (обычно это копия со свежими правками)
#   "first" — первый, с исходным именем листа
SHEET_PREFERENCE = "last"

for _d in (DATA_DIR, RAW_DIR):
    _d.mkdir(parents=True, exist_ok=True)
