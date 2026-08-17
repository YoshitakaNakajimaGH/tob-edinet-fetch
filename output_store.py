#!/usr/bin/env python3
"""結果CSVの配置・日付付きスナップショット・ごみ箱ローテーション。"""

from __future__ import annotations

import re
import shutil
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from tob_common import CASE_FIELDS, LIST_FIELDS, merge_document_rows, read_csv, write_csv

KEEP_SNAPSHOTS = 20
KEEP_TRASH = 20
LIST_STEM = "tob_list"
CASES_STEM = "tob_cases"
SELF_LIST_STEM = "self_tob_list"
SELF_CASES_STEM = "self_tob_cases"

try:
    from zoneinfo import ZoneInfo

    _JST = ZoneInfo("Asia/Tokyo")
except Exception:  # noqa: BLE001 - tzdata が無い環境向け
    _JST = timezone(timedelta(hours=9))


def japan_today(now: datetime | None = None) -> date:
    current = now or datetime.now(tz=_JST)
    if current.tzinfo is None:
        current = current.replace(tzinfo=_JST)
    else:
        current = current.astimezone(_JST)
    return current.date()


def current_dir(root: Path) -> Path:
    return root / "current"


def snapshots_dir(root: Path) -> Path:
    return root / "snapshots"


def trash_dir(root: Path) -> Path:
    return snapshots_dir(root) / "trash"


def current_path(root: Path, stem: str) -> Path:
    return current_dir(root) / f"{stem}.csv"


def snapshot_path(root: Path, stem: str, day: date) -> Path:
    return snapshots_dir(root) / f"{day:%Y}" / f"{day:%m}" / f"{stem}_{day:%Y%m%d}.csv"


def _date_from_name(stem: str, name: str) -> date | None:
    match = re.fullmatch(rf"{re.escape(stem)}_(\d{{8}})\.csv", name)
    if not match:
        return None
    try:
        return datetime.strptime(match.group(1), "%Y%m%d").date()
    except ValueError:
        return None


def list_snapshot_files(root: Path, stem: str) -> list[tuple[date, Path]]:
    base = snapshots_dir(root)
    if not base.exists():
        return []
    found: list[tuple[date, Path]] = []
    for path in base.rglob(f"{stem}_*.csv"):
        if "trash" in path.parts:
            continue
        day = _date_from_name(stem, path.name)
        if day:
            found.append((day, path))
    found.sort(key=lambda item: item[0], reverse=True)
    return found


def list_trash_files(root: Path, stem: str) -> list[tuple[date, Path]]:
    base = trash_dir(root)
    if not base.exists():
        return []
    found: list[tuple[date, Path]] = []
    for path in base.glob(f"{stem}_*.csv"):
        day = _date_from_name(stem, path.name)
        if day:
            found.append((day, path))
    found.sort(key=lambda item: item[0], reverse=True)
    return found


def _remove_empty_parents(path: Path, stop: Path) -> None:
    current = path.parent
    while current != stop and current.is_dir():
        try:
            current.rmdir()
        except OSError:
            break
        current = current.parent


def rotate_stem(root: Path, stem: str, keep: int = KEEP_SNAPSHOTS, trash_keep: int = KEEP_TRASH) -> None:
    trash = trash_dir(root)
    trash.mkdir(parents=True, exist_ok=True)
    snapshots = snapshots_dir(root)

    live = list_snapshot_files(root, stem)
    for _, path in live[keep:]:
        dest = trash / path.name
        if dest.exists():
            dest.unlink()
        shutil.move(str(path), str(dest))
        _remove_empty_parents(path, snapshots)

    dumped = list_trash_files(root, stem)
    for _, path in dumped[trash_keep:]:
        path.unlink(missing_ok=True)


def publish_csv(root: Path, stem: str, rows: list[dict], fieldnames: list[str], day: date | None = None) -> Path:
    """Write current CSV plus a dated snapshot, then rotate older copies to trash."""
    day = day or japan_today()
    latest = current_path(root, stem)
    snap = snapshot_path(root, stem, day)
    write_csv(latest, rows, fieldnames)
    write_csv(snap, rows, fieldnames)
    rotate_stem(root, stem)
    return latest


def publish_tob_outputs(
    root: Path,
    list_rows: list[dict],
    case_rows: list[dict],
    day: date | None = None,
    self_list_rows: list[dict] | None = None,
    self_case_rows: list[dict] | None = None,
) -> tuple[Path, Path]:
    day = day or japan_today()
    list_path = publish_csv(root, LIST_STEM, list_rows, LIST_FIELDS, day)
    cases_path = publish_csv(root, CASES_STEM, case_rows, CASE_FIELDS, day)
    if self_list_rows is not None:
        publish_csv(root, SELF_LIST_STEM, self_list_rows, LIST_FIELDS, day)
    if self_case_rows is not None:
        publish_csv(root, SELF_CASES_STEM, self_case_rows, CASE_FIELDS, day)
    return list_path, cases_path


def load_all_list_rows(root: Path) -> list[dict]:
    """Load 他社株 + 自社株 list CSVs and upsert by DocID."""
    chunks: list[dict] = []
    for stem in (LIST_STEM, SELF_LIST_STEM):
        path = resolve_current_csv(root, stem)
        if path:
            chunks.extend(read_csv(path))
    if not chunks:
        return []
    rows, _, _ = merge_document_rows([], chunks)
    return rows


def resolve_current_csv(root: Path, stem: str) -> Path | None:
    latest = current_path(root, stem)
    if latest.exists():
        return latest
    legacy = root / f"{stem}.csv"
    if legacy.exists():
        return legacy
    snapshots = list_snapshot_files(root, stem)
    if snapshots:
        return snapshots[0][1]
    return None
