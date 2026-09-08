"""Хранилище расписания: скачивание, разбор, кэш и выборки по датам."""
from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from . import cloud
from .config import RAW_DIR, REFRESH_INTERVAL, SNAPSHOT_FILE
from .parser import WEEKDAY_NAMES, Lesson, parse_workbook

log = logging.getLogger(__name__)

MONTHS = {
    1: "января", 2: "февраля", 3: "марта", 4: "апреля", 5: "мая", 6: "июня",
    7: "июля", 8: "августа", 9: "сентября", 10: "октября", 11: "ноября", 12: "декабря",
}
DEFAULT_ANCHOR = date(2026, 8, 31)


@dataclass
class Snapshot:
    updated_at: str = ""
    anchor_monday: str = DEFAULT_ANCHOR.isoformat()
    groups: list[str] = field(default_factory=list)
    teachers: list[str] = field(default_factory=list)
    files: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    weeks: list[dict] = field(default_factory=list)   # опубликованные недели
    lessons: list[dict] = field(default_factory=list)

    @property
    def anchor(self) -> date:
        try:
            return date.fromisoformat(self.anchor_monday)
        except ValueError:
            return DEFAULT_ANCHOR

    def to_json(self) -> dict:
        return {
            "updated_at": self.updated_at,
            "anchor_monday": self.anchor_monday,
            "groups": self.groups,
            "teachers": self.teachers,
            "files": self.files,
            "warnings": self.warnings,
            "weeks": self.weeks,
            "lessons": self.lessons,
        }

    @classmethod
    def from_json(cls, payload: dict) -> "Snapshot":
        return cls(
            updated_at=payload.get("updated_at", ""),
            anchor_monday=payload.get("anchor_monday", DEFAULT_ANCHOR.isoformat()),
            groups=payload.get("groups", []),
            teachers=payload.get("teachers", []),
            files=payload.get("files", []),
            warnings=payload.get("warnings", []),
            weeks=payload.get("weeks", []),
            lessons=payload.get("lessons", []),
        )


def natural_group_key(name: str) -> tuple:
    """Сортировка групп: сперва специальность, затем курс («1 БД» < «2 БД»)."""
    parts = name.split(maxsplit=1)
    if len(parts) == 2 and parts[0].isdigit():
        return (parts[1].lower(), int(parts[0]))
    return (name.lower(), 0)


def format_date(day: date) -> str:
    return f"{day.day} {MONTHS[day.month]}"


class ScheduleStore:
    """Держит последнее разобранное расписание и обновляет его в фоне."""

    def __init__(self, interval: int = REFRESH_INTERVAL) -> None:
        self.interval = interval
        self._lock = threading.RLock()
        self._snapshot = Snapshot()
        self._by_group: dict[str, list[dict]] = {}
        self._by_teacher: dict[str, list[dict]] = {}
        self._last_error: str = ""
        self._refreshing = False
        self._last_attempt = 0.0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # ------------------------------------------------------------ состояние

    @property
    def snapshot(self) -> Snapshot:
        with self._lock:
            return self._snapshot

    @property
    def last_error(self) -> str:
        return self._last_error

    @property
    def is_empty(self) -> bool:
        return not self._snapshot.lessons

    def _reindex(self, snapshot: Snapshot) -> None:
        by_group: dict[str, list[dict]] = {}
        by_teacher: dict[str, list[dict]] = {}
        for lesson in snapshot.lessons:
            by_group.setdefault(lesson["group"], []).append(lesson)
            if lesson.get("teacher"):
                by_teacher.setdefault(lesson["teacher"], []).append(lesson)
        with self._lock:
            self._snapshot = snapshot
            self._by_group = by_group
            self._by_teacher = by_teacher

    # ---------------------------------------------------------------- диск

    def load_cached(self) -> bool:
        """Поднимает последнее сохранённое расписание, чтобы сайт работал сразу."""
        if not SNAPSHOT_FILE.exists():
            return False
        try:
            payload = json.loads(SNAPSHOT_FILE.read_text(encoding="utf-8"))
            self._reindex(Snapshot.from_json(payload))
            log.info("Загружен кэш от %s (%d занятий)",
                     self._snapshot.updated_at, len(self._snapshot.lessons))
            return True
        except Exception:
            log.exception("Не удалось прочитать кэш %s", SNAPSHOT_FILE)
            return False

    def _save(self, snapshot: Snapshot) -> None:
        temporary = SNAPSHOT_FILE.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(snapshot.to_json(), ensure_ascii=False), encoding="utf-8"
        )
        temporary.replace(SNAPSHOT_FILE)

    # ----------------------------------------------------------- обновление

    def refresh(self, cooldown: int = 0) -> Snapshot:
        """Скачивает файлы из облака и заново разбирает расписание.

        `cooldown` защищает от частых ручных обновлений через API: если с
        прошлой попытки прошло меньше указанного числа секунд, ничего не делаем.
        """
        with self._lock:
            if self._refreshing:
                return self._snapshot
            if cooldown and time.monotonic() - self._last_attempt < cooldown:
                return self._snapshot
            self._refreshing = True
            self._last_attempt = time.monotonic()
        try:
            downloaded = cloud.download_schedule_files()
            lessons: list[Lesson] = []
            groups: list[str] = []
            warnings: list[str] = []
            files: list[dict] = []
            mondays: dict[date, int] = {}
            anchor: date | None = None

            for meta, data in downloaded:
                (RAW_DIR / meta.name).write_bytes(data)
                try:
                    result = parse_workbook(data, meta.name)
                except Exception as error:
                    log.exception("Ошибка разбора %s", meta.name)
                    warnings.append(f"{meta.name}: не удалось разобрать ({error})")
                    continue
                lessons.extend(result.lessons)
                groups.extend(result.groups)
                warnings.extend(result.warnings)
                if result.anchor and (anchor is None or result.anchor < anchor):
                    anchor = result.anchor
                for monday, week in result.mondays.items():
                    mondays.setdefault(monday, week)
                files.append({
                    "name": meta.name,
                    "size": meta.size,
                    "mtime": meta.mtime.isoformat(),
                    "lessons": len(result.lessons),
                    "groups": len(result.groups),
                })

            if not lessons:
                raise RuntimeError("Файлы скачаны, но ни одного занятия не разобрано")

            snapshot = Snapshot(
                updated_at=datetime.now().astimezone().isoformat(timespec="seconds"),
                anchor_monday=(anchor or DEFAULT_ANCHOR).isoformat(),
                groups=sorted(set(groups), key=natural_group_key),
                teachers=sorted({l.teacher for l in lessons if l.teacher}),
                files=files,
                warnings=warnings,
                weeks=[{"monday": m.isoformat(), "week": w}
                       for m, w in sorted(mondays.items())],
                lessons=[l.as_dict() for l in lessons],
            )
            self._reindex(snapshot)
            self._save(snapshot)
            self._last_error = ""
            log.info("Расписание обновлено: %d занятий, %d групп, %d преподавателей",
                     len(snapshot.lessons), len(snapshot.groups), len(snapshot.teachers))
            return snapshot
        except Exception as error:
            self._last_error = f"{type(error).__name__}: {error}"
            log.exception("Обновление расписания не удалось")
            return self._snapshot
        finally:
            self._refreshing = False

    def start_background_refresh(self) -> None:
        if self._thread and self._thread.is_alive():
            return

        def loop() -> None:
            while not self._stop.is_set():
                self.refresh()
                self._stop.wait(self.interval)

        self._stop.clear()
        self._thread = threading.Thread(target=loop, name="schedule-refresh", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    # ------------------------------------------------------------- выборки

    def week_number(self, day: date) -> int:
        """1 — нечётная («1 неделя»), 2 — чётная («2 неделя»)."""
        monday = day - timedelta(days=day.weekday())
        delta = (monday - self.snapshot.anchor).days // 7
        return 1 if delta % 2 == 0 else 2

    def published_weeks(self, today: date | None = None) -> list[dict]:
        """Недели, которые колледж действительно выложил — у них в таблице стоят даты.

        Листать имеет смысл только по ним: расписание за пределами этих недель
        колледж не публиковал. Список берётся из файлов, поэтому появятся новые
        листы с датами — недели добавятся сами.

        Текущую неделю включаем всегда. Иначе, когда таблицы отстанут от
        календаря, сайт показывал бы пары на сегодня, но не давал открыть
        эту же неделю целиком.
        """
        today = today or date.today()
        weeks = {item["monday"]: item["week"] for item in self.snapshot.weeks}
        monday = today - timedelta(days=today.weekday())
        weeks.setdefault(monday.isoformat(), self.week_number(today))

        result = []
        for iso, number in sorted(weeks.items()):
            start = date.fromisoformat(iso)
            end = start + timedelta(days=5)          # понедельник — суббота
            result.append({
                "monday": iso,
                "week": number,
                "label": f"{format_date(start)} — {format_date(end)}",
                # Короткий вид для кнопок выбора недели: на телефоне полные
                # названия месяцев в ряд не помещаются.
                "short": f"{start:%d.%m} — {end:%d.%m}",
            })
        return result

    def schedule(self, kind: str, name: str, start: date, days: int) -> dict:
        """Расписание группы или преподавателя на несколько дней подряд."""
        with self._lock:
            source = (self._by_group if kind == "group" else self._by_teacher).get(name, [])

        result_days = []
        for offset in range(days):
            day = start + timedelta(days=offset)
            weekday = day.isoweekday()
            week = self.week_number(day)
            if weekday == 7:
                lessons = []
            else:
                lessons = [
                    l for l in source
                    if l["weekday"] == weekday and l["week"] in (0, week)
                ]
                lessons.sort(key=lambda l: (l["pair"], l.get("subgroup") or 0))
            result_days.append({
                "date": day.isoformat(),
                "weekday": weekday,
                "weekday_name": WEEKDAY_NAMES[weekday],
                "date_label": format_date(day),
                "week": week,
                "lessons": lessons,
            })
        return {
            "kind": kind,
            "name": name,
            "found": bool(source),
            "days": result_days,
            "updated_at": self.snapshot.updated_at,
        }


store = ScheduleStore()
