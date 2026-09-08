"""Собирает файл расписания для статического сайта.

    python tools/build_data.py

Скачивает таблицы из облака, разбирает их и кладёт результат в
`docs/data/schedule.json` — именно этот файл читает сайт на GitHub Pages.
Сервер для работы сайта не нужен: весь семестр весит около 50 КБ в сжатом
виде, и браузер забирает его одним запросом.

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

from app import cloud                                    # noqa: E402
from app.config import RAW_DIR, SITE_DATA_FILE           # noqa: E402
from app.parser import parse_workbook                    # noqa: E402
from app.store import DEFAULT_ANCHOR, natural_group_key  # noqa: E402


def build() -> dict:
    lessons = []
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

        lessons.extend(result.lessons)
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
        print("  %-40s групп %2d, занятий %5d" % (meta.name, len(result.groups), len(result.lessons)))

    if not lessons:
        raise RuntimeError("Файлы скачаны, но ни одного занятия не разобрано")

    return {
        # Дата сборки, а не время: файл коммитится в репозиторий, и точное
        # время правки видно в истории git.
        "built_on": date.today().isoformat(),
        "anchor_monday": (anchor or DEFAULT_ANCHOR).isoformat(),
        "groups": sorted(set(groups), key=natural_group_key),
        "teachers": sorted(teachers),
        "weeks": [{"monday": m.isoformat(), "week": w} for m, w in sorted(mondays.items())],
        "files": files,
        "warnings": warnings,
        # Занятия без поля source: на сайте оно не нужно, а место занимает.
        "lessons": [
            {k: v for k, v in l.as_dict().items() if k != "source"}
            for l in lessons
        ],
    }


def main() -> int:
    print("Скачиваем таблицы из облака…")
    try:
        payload = build()
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
