"""Собирает файл расписания для статического сайта.

    python tools/build_data.py

Скачивает таблицы из облака, разбирает их и кладёт результат в
`docs/data/schedule.json` — именно этот файл читает сайт на GitHub Pages.
Сервер для работы сайта не нужен: весь семестр весит около 50 КБ в сжатом
виде, и браузер забирает его одним запросом.

Заодно сравнивает новое расписание с предыдущей сборкой и помечает,
что изменилось: появившиеся и переехавшие пары получают отметку, снятые
попадают в отдельный список. Отметки живут CHANGE_MARK_DAYS дней,
потом сами пропадают.

Этот же скрипт запускает GitHub Actions раз в час (.github/workflows/update.yml).
Код возврата 0 — файл собран, 1 — что-то пошло не так и старый файл не тронут.
"""
from __future__ import annotations

import json
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

from app import cloud                                              # noqa: E402
from app.config import (CHANGE_MARK_DAYS, DEFAULT_ANCHOR,          # noqa: E402
                        RAW_DIR, SITE_DATA_FILE)
from app.parser import natural_group_key, parse_workbook           # noqa: E402

# Чем пара «та же самая»: место в сетке расписания.
SLOT_FIELDS = ("group", "week", "weekday", "pair", "subgroup")
# Что в ней может поменяться.
CONTENT_FIELDS = ("subject", "teacher", "room", "time", "note")


def slot_of(lesson: dict) -> str:
    return "|".join(str(lesson.get(f) or "") for f in SLOT_FIELDS)


def content_of(lesson: dict) -> tuple:
    return tuple(lesson.get(f) or "" for f in CONTENT_FIELDS)


def collect() -> dict:
    """Скачивает и разбирает все таблицы."""
    lessons: list[dict] = []
    groups: list[str] = []
    teachers: set[str] = set()
    warnings: list[str] = []
    files: list[dict] = []
    mondays: dict[date, int] = {}
    anchor: date | None = None

    for meta, data in cloud.download_schedule_files():
        RAW_DIR.mkdir(parents=True, exist_ok=True)
        (RAW_DIR / meta.name).write_bytes(data)
        result = parse_workbook(data, meta.name)

        lessons.extend(
            {k: v for k, v in l.as_dict().items() if k != "source"}
            for l in result.lessons
        )
        groups.extend(result.groups)
        warnings.extend(result.warnings)
        teachers.update(l.teacher for l in result.lessons if l.teacher)
        if result.anchor and (anchor is None or result.anchor < anchor):
            anchor = result.anchor
        for monday, week in result.mondays.items():
            mondays.setdefault(monday, week)
        files.append({
            "name": meta.name,
            "mtime": meta.mtime.isoformat(),
            "lessons": len(result.lessons),
            "groups": len(result.groups),
        })
        print("  %-40s групп %2d, занятий %5d"
              % (meta.name, len(result.groups), len(result.lessons)))

    if not lessons:
        raise RuntimeError("Файлы скачаны, но ни одного занятия не разобрано")

    return {
        # Дата сборки, а не время: файл коммитится в репозиторий, точное
        # время правки видно в истории git.
        "built_on": date.today().isoformat(),
        "anchor_monday": (anchor or DEFAULT_ANCHOR).isoformat(),
        "groups": sorted(set(groups), key=natural_group_key),
        "teachers": sorted(teachers),
        "weeks": [{"monday": m.isoformat(), "week": w} for m, w in sorted(mondays.items())],
        "files": files,
        "warnings": warnings,
        "lessons": lessons,
    }


def previous() -> dict:
    """Прошлая сборка — с ней сравниваем. Нет файла или он битый — считаем, что её не было."""
    if not SITE_DATA_FILE.exists():
        return {}
    try:
        return json.loads(SITE_DATA_FILE.read_text(encoding="utf-8"))
    except Exception as error:
        print("  предыдущий файл не прочитался (%s), отметки начнём заново" % error)
        return {}


def mark_changes(payload: dict, old: dict) -> dict:
    """Проставляет отметки «новая» и «изменилась», собирает снятые пары.

    Первая сборка ничего не помечает: сравнивать не с чем, иначе всё
    расписание разом стало бы «новым».
    """
    today = date.today()
    fresh = (today - timedelta(days=CHANGE_MARK_DAYS)).isoformat()

    payload["removed"] = []
    if not old.get("lessons"):
        return payload

    was = {slot_of(l): l for l in old["lessons"]}
    added = changed = 0

    for lesson in payload["lessons"]:
        before = was.pop(slot_of(lesson), None)
        if before is None:
            lesson["mark"] = "new"
            lesson["mark_on"] = today.isoformat()
            added += 1
        elif content_of(before) != content_of(lesson):
            lesson["mark"] = "changed"
            lesson["mark_on"] = today.isoformat()
            changed += 1
        elif before.get("mark") and before.get("mark_on", "") >= fresh:
            # Отметка со старой сборки ещё не истекла — переносим.
            lesson["mark"] = before["mark"]
            lesson["mark_on"] = before["mark_on"]

    # Всё, что осталось в was, из расписания пропало.
    for lesson in was.values():
        entry = dict(lesson)
        entry["mark"] = "removed"
        entry["mark_on"] = today.isoformat()
        payload["removed"].append(entry)

    # Снятые пары с прошлых сборок держим, пока не истечёт срок.
    for entry in old.get("removed", []):
        if entry.get("mark_on", "") >= fresh and slot_of(entry) not in {
            slot_of(l) for l in payload["lessons"]
        }:
            payload["removed"].append(entry)

    print("\nизменения против прошлой сборки: новых %d, изменённых %d, снятых %d"
          % (added, changed, len(payload["removed"])))
    return payload


def main() -> int:
    print("Скачиваем таблицы из облака…")
    try:
        old = previous()
        payload = mark_changes(collect(), old)
    except Exception as error:
        print("ОШИБКА: %s" % error)
        print("Файл сайта не тронут — останется предыдущая версия расписания.")
        return 1

    SITE_DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    SITE_DATA_FILE.write_text(text, encoding="utf-8")

    weeks = ", ".join("%s (%d-я)" % (w["monday"], w["week"]) for w in payload["weeks"])
    print("\n%s: %.0f КБ" % (SITE_DATA_FILE.name, len(text.encode()) / 1024))
    print("занятий %d, групп %d, преподавателей %d"
          % (len(payload["lessons"]), len(payload["groups"]), len(payload["teachers"])))
    print("опубликованные недели: %s" % (weeks or "нет"))
    for warning in payload["warnings"]:
        print("  замечание: %s" % warning)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
