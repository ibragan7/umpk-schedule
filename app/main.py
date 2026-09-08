"""HTTP-сервис расписания УМПК: JSON-API + отдача сайта."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import COLLEGE_FULL, COLLEGE_SHORT, REFRESH_INTERVAL, WEB_DIR
from .store import store

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
)
log = logging.getLogger("umpk")

NO_CACHE = {"Cache-Control": "no-cache"}


def web_version() -> str:
    """Время правки самого свежего файла сайта — видно на странице «О расписании».

    По нему сразу понятно, догрузил телефон новую версию или сидит на старой.
    """
    stamps = [f.stat().st_mtime for f in WEB_DIR.rglob("*") if f.is_file()]
    if not stamps:
        return ""
    return datetime.fromtimestamp(max(stamps)).astimezone().isoformat(timespec="seconds")


@asynccontextmanager
async def lifespan(_: FastAPI):
    store.load_cached()          # сайт отвечает сразу, ещё до первой загрузки
    store.start_background_refresh()
    yield
    store.stop()


app = FastAPI(title="Расписание УМПК", lifespan=lifespan, docs_url="/api/docs")


@app.get("/api/meta")
def meta() -> dict:
    snapshot = store.snapshot
    today = date.today()
    return {
        "college": {"short": COLLEGE_SHORT, "full": COLLEGE_FULL},
        "updated_at": snapshot.updated_at,
        "refresh_interval": REFRESH_INTERVAL,
        "groups": snapshot.groups,
        "teachers": snapshot.teachers,
        "files": snapshot.files,
        "warnings": snapshot.warnings,
        "today": today.isoformat(),
        "current_week": store.week_number(today),
        "anchor_monday": snapshot.anchor_monday,
        "weeks": store.published_weeks(today),
        "web_version": web_version(),
        "last_error": store.last_error,
        "ready": not store.is_empty,
    }


@app.get("/api/schedule")
def schedule(
    kind: str = Query("group", pattern="^(group|teacher)$"),
    name: str = Query(..., min_length=1),
    start: str | None = None,
    days: int = Query(1, ge=1, le=31),
    align_week: bool = False,
) -> dict:
    try:
        first = date.fromisoformat(start) if start else date.today()
    except ValueError:
        raise HTTPException(400, "Некорректная дата, ожидается ГГГГ-ММ-ДД")
    if align_week:                      # неделя всегда начинается с понедельника
        first -= timedelta(days=first.weekday())
    return store.schedule(kind, name, first, days)


@app.post("/api/refresh")
def refresh() -> dict:
    # Не чаще раза в минуту: ручка открыта всем в сети, а каждое обновление —
    # пять скачиваний из облака.
    snapshot = store.refresh(cooldown=60)
    return {
        "updated_at": snapshot.updated_at,
        "lessons": len(snapshot.lessons),
        "groups": len(snapshot.groups),
        "teachers": len(snapshot.teachers),
        "error": store.last_error,
    }


@app.get("/healthz")
def healthz() -> JSONResponse:
    ready = not store.is_empty
    return JSONResponse(
        {"ready": ready, "updated_at": store.snapshot.updated_at,
         "error": store.last_error},
        status_code=200 if ready else 503,
    )


@app.get("/")
def index() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html", headers=NO_CACHE)


class RevalidatingStatic(StaticFiles):
    """Отдаёт файлы сайта с обязательной проверкой актуальности.

    Без заголовка `Cache-Control` браузеры выбирают время жизни кэша сами,
    по косвенным признакам. Мобильные делают это особенно щедро: после
    обновления сайта телефон может ещё сутками работать на старом `app.js`,
    пока компьютер уже показывает новую версию.

    `no-cache` не запрещает кэш — он требует каждый раз спросить сервер.
    Если файл не менялся, ответ будет пустой 304, это дёшево.
    """

    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        response.headers.setdefault("Cache-Control", NO_CACHE["Cache-Control"])
        return response


app.mount("/", RevalidatingStatic(directory=WEB_DIR, html=True), name="web")
