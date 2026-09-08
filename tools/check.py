"""Диагностика разбора таблиц расписания.

    python tools/check.py             # по файлам из data/raw
    python tools/check.py --download  # предварительно скачав из облака

Печатает, сколько групп и занятий нашлось в каждом файле, и подсвечивает
подозрительные места: пустые группы, дни без пар, странные ФИО. Полезно
прогонять, когда в колледже изменили формат таблиц.
"""
from __future__ import annotations

import collections
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

from app import cloud                                  # noqa: E402
from app.config import RAW_DIR                         # noqa: E402
from app.parser import WEEKDAY_NAMES, parse_workbook   # noqa: E402


def collect() -> list[tuple[str, bytes]]:
    if "--download" in sys.argv:
        print("Скачиваем файлы из облака…\n")
        return [(meta.name, data) for meta, data in cloud.download_schedule_files()]
    files = sorted(RAW_DIR.glob("*.xlsx"))
    if not files:
        sys.exit(f"В {RAW_DIR} нет ни одного .xlsx — запустите с --download")
    return [(path.name, path.read_bytes()) for path in files]


def main() -> int:
    lessons = []
    problems: list[str] = []
    mondays: dict = {}

    for name, data in collect():
        try:
            result = parse_workbook(data, name)
        except Exception as error:
            problems.append(f"{name}: разбор не удался — {error}")
            print(f"{name:<38} ОШИБКА: {error}")
            continue

        lessons.extend(result.lessons)
        mondays.update(result.mondays)
        problems.extend(f"{name}: {w}" for w in result.warnings)
        print(f"{name:<38} групп {len(result.groups):>3} · "
              f"занятий {len(result.lessons):>5} · отсчёт чётности {result.anchor}")
        if not result.lessons:
            problems.append(f"{name}: не найдено ни одного занятия")

    if not lessons:
        print("\nНи одного занятия не разобрано — формат таблиц изменился.")
        return 1

    groups = sorted({l.group for l in lessons})
    teachers = sorted({l.teacher for l in lessons if l.teacher})
    print(f"\nИтого: {len(lessons)} занятий, {len(groups)} групп, "
          f"{len(teachers)} преподавателей")

    per_weekday = collections.Counter(l.weekday for l in lessons)
    print("\nПо дням недели:")
    for weekday in sorted(per_weekday):
        print(f"  {WEEKDAY_NAMES[weekday]:<13} {per_weekday[weekday]:>5}")

    per_week = collections.Counter(l.week for l in lessons)
    print("\nПо чётности:", ", ".join(
        f"{'каждую неделю' if w == 0 else f'{w}-я неделя'}: {n}"
        for w, n in sorted(per_week.items())))

    # Именно по этим неделям сайт разрешает листать: у них в таблицах стоят даты.
    print("\nОпубликованные недели (по датам в таблицах):")
    if mondays:
        for monday, week in sorted(mondays.items()):
            print(f"  {monday} — {week}-я неделя")
    else:
        print("  дат в шапках дней нет — сайт покажет только текущую неделю")
        problems.append("ни в одном файле не проставлены даты дней")

    empty = [g for g in groups if not any(l.group == g for l in lessons)]
    if empty:
        problems.append(f"группы без единого занятия: {', '.join(empty)}")

    thin = [g for g in groups
            if sum(1 for l in lessons if l.group == g) < 10]
    if thin:
        problems.append(f"подозрительно мало занятий у групп: {', '.join(thin)}")

    notes = collections.Counter(l.note for l in lessons if l.note)
    if notes:
        print("\nПометки в строке преподавателя:")
        for text, count in notes.most_common(10):
            print(f"  {count:>4} × {text}")

    print(f"\nБез аудитории: {sum(1 for l in lessons if not l.room)} из {len(lessons)}")
    print(f"Без преподавателя: {sum(1 for l in lessons if not l.teacher and l.pair)} "
          f"(не считая классных часов)")

    if problems:
        print("\nТребует внимания:")
        for problem in problems:
            print(f"  • {problem}")
    else:
        print("\nЗамечаний нет.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
