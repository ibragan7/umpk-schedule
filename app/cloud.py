"""Загрузка файлов расписания из публичной папки cloud.mail.ru.

Публичное API облака не требует авторизации:
  * список файлов  — /api/v4/public/list?weblink=<ссылка>
  * адрес отдачи   — /api/v2/dispatcher -> body.weblink_get[0].url
  * сам файл       — <weblink_get>/<url-encoded weblink файла>
"""
from __future__ import annotations

import json
import logging
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone

from .config import CLOUD_PUBLIC_LINK, HTTP_TIMEOUT

log = logging.getLogger(__name__)

API_LIST = "https://cloud.mail.ru/api/v4/public/list?weblink={wl}&limit=500"
API_DISPATCHER = "https://cloud.mail.ru/api/v2/dispatcher"
USER_AGENT = "Mozilla/5.0 (compatible; UMPK-Schedule/1.0)"


@dataclass(frozen=True)
class CloudFile:
    name: str
    weblink: str
    size: int
    mtime: datetime

    @property
    def is_xlsx(self) -> bool:
        return self.name.lower().endswith((".xlsx", ".xlsm"))


def _fetch(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT) as response:
        return response.read()


def list_files(weblink: str = CLOUD_PUBLIC_LINK, recursive: bool = False) -> list[CloudFile]:
    raw = _fetch(API_LIST.format(wl=urllib.parse.quote(weblink, safe="")))
    payload = json.loads(raw)
    files: list[CloudFile] = []
    for item in payload.get("list", []):
        if item.get("type") == "folder":
            if recursive:
                files.extend(list_files(item["weblink"], recursive=True))
            continue
        files.append(
            CloudFile(
                name=item["name"],
                weblink=item["weblink"],
                size=int(item.get("size") or 0),
                mtime=datetime.fromtimestamp(int(item.get("mtime") or 0), tz=timezone.utc),
            )
        )
    return files


def download_base_url() -> str:
    payload = json.loads(_fetch(API_DISPATCHER))
    return payload["body"]["weblink_get"][0]["url"].rstrip("/")


def download(file: CloudFile, base_url: str | None = None) -> bytes:
    base = base_url or download_base_url()
    url = f"{base}/{urllib.parse.quote(file.weblink)}"
    data = _fetch(url)
    if file.size and len(data) != file.size:
        raise IOError(
            f"{file.name}: скачано {len(data)} байт вместо ожидаемых {file.size}"
        )
    return data


def download_schedule_files(weblink: str = CLOUD_PUBLIC_LINK) -> list[tuple[CloudFile, bytes]]:
    """Скачивает все таблицы расписания из публичной папки.

    Нужны все файлы до единого. Недостача — это не «расписание без одного
    файла», а расписание без доброй пятой части групп: студенты этих групп
    увидели бы «расписание не найдено», а в Actions был бы зелёный запуск.
    Поэтому при любой недокачке поднимаем ошибку и оставляем предыдущий
    файл сайта нетронутым.

    Перебираем все файлы, прежде чем упасть: в отчёте лучше видеть сразу
    весь список неудач, а не первую из них.
    """
    files = [f for f in list_files(weblink) if f.is_xlsx]
    if not files:
        raise RuntimeError("В публичной папке облака не найдено ни одного .xlsx")
    base = download_base_url()
    result: list[tuple[CloudFile, bytes]] = []
    failed: list[str] = []
    for file in sorted(files, key=lambda f: f.name):
        try:
            result.append((file, download(file, base)))
            log.info("Скачан %s (%d байт)", file.name, file.size)
        except Exception as error:
            log.exception("Не удалось скачать %s", file.name)
            failed.append(f"{file.name} ({error})")
    if failed:
        raise RuntimeError(
            "не скачались файлы расписания: %s. Скачано %d из %d — "
            "неполное расписание не публикуем"
            % ("; ".join(failed), len(result), len(files))
        )
    return result
