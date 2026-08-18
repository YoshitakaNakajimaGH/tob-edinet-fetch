#!/usr/bin/env python3
"""結果CSVの配置・取得範囲別スナップショット・ごみ箱ローテーション。"""

from __future__ import annotations

import json
import re
import shutil
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from tob.tob_common import (
    CASE_FIELDS,
    LIST_FIELDS,
    SELF_CASE_FIELDS,
    SELF_LIST_FIELDS,
    merge_document_rows,
    read_csv,
    write_csv,
)

KEEP_SNAPSHOTS = 20
KEEP_TRASH = 20
LIST_STEM = "tob_list"
CASES_STEM = "tob_cases"
SELF_LIST_STEM = "self_tob_list"
SELF_CASES_STEM = "self_tob_cases"
FETCH_META_NAME = "fetch_meta.json"

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


def format_range_label(start: date, end: date) -> str:
    """Return YYYYMM-YYYYMM label for a fetch/enrich range."""
    return f"{start:%Y%m}-{end:%Y%m}"


def current_dir(root: Path) -> Path:
    return root / "current"


def snapshots_dir(root: Path) -> Path:
    return root / "snapshots"


def trash_dir(root: Path) -> Path:
    return snapshots_dir(root) / "trash"


def current_path(root: Path, stem: str) -> Path:
    return current_dir(root) / f"{stem}.csv"


def fetch_meta_path(root: Path) -> Path:
    return current_dir(root) / FETCH_META_NAME


def _range_snapshot_re(stem: str, range_label: str) -> re.Pattern[str]:
    return re.compile(rf"^{re.escape(stem)}_{re.escape(range_label)}_(\d{{4}})\.csv$")


def range_snapshot_filename(stem: str, range_label: str, sequence: int) -> str:
    return f"{stem}_{range_label}_{sequence:04d}.csv"


def range_snapshot_path(root: Path, stem: str, range_label: str, sequence: int) -> Path:
    return snapshots_dir(root) / range_snapshot_filename(stem, range_label, sequence)


def list_range_snapshot_files(root: Path, stem: str, range_label: str) -> list[tuple[int, Path]]:
    base = snapshots_dir(root)
    if not base.exists():
        return []
    pattern = _range_snapshot_re(stem, range_label)
    found: list[tuple[int, Path]] = []
    for path in base.glob(f"{stem}_{range_label}_*.csv"):
        if "trash" in path.parts:
            continue
        match = pattern.fullmatch(path.name)
        if match:
            found.append((int(match.group(1)), path))
    found.sort(key=lambda item: item[0])
    return found


def list_trash_range_files(root: Path, stem: str, range_label: str) -> list[tuple[int, Path]]:
    base = trash_dir(root)
    if not base.exists():
        return []
    pattern = _range_snapshot_re(stem, range_label)
    found: list[tuple[int, Path]] = []
    for path in base.glob(f"{stem}_{range_label}_*.csv"):
        match = pattern.fullmatch(path.name)
        if match:
            found.append((int(match.group(1)), path))
    found.sort(key=lambda item: item[0], reverse=True)
    return found


def next_range_sequence(root: Path, stem: str, range_label: str, day: date | None = None) -> int:
    """Next 0001-style suffix for this range (same JST day increments; new day continues after max)."""
    day = day or japan_today()
    live = list_range_snapshot_files(root, stem, range_label)
    if not live:
        return 1
    same_day = [
        seq
        for seq, path in live
        if japan_today(datetime.fromtimestamp(path.stat().st_mtime, tz=_JST)) == day
    ]
    if same_day:
        return max(same_day) + 1
    return max(seq for seq, _ in live) + 1


def rotate_range_stem(
    root: Path,
    stem: str,
    range_label: str,
    keep: int = KEEP_SNAPSHOTS,
    trash_keep: int = KEEP_TRASH,
) -> None:
    trash = trash_dir(root)
    trash.mkdir(parents=True, exist_ok=True)
    live = list_range_snapshot_files(root, stem, range_label)
    if len(live) > keep:
        for _, path in live[:-keep]:
            dest = trash / path.name
            if dest.exists():
                dest.unlink()
            shutil.move(str(path), str(dest))

    dumped = list_trash_range_files(root, stem, range_label)
    for _, path in dumped[trash_keep:]:
        path.unlink(missing_ok=True)


def write_fetch_meta(
    root: Path,
    *,
    range_label: str,
    start: date,
    end: date,
    mode: str,
    sequence: int,
) -> None:
    meta = {
        "range_label": range_label,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "mode": mode,
        "sequence": sequence,
        "updated_at": datetime.now(tz=_JST).isoformat(),
    }
    fetch_meta_path(root).write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


def read_fetch_meta(root: Path) -> dict | None:
    path = fetch_meta_path(root)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def resolve_range_label(root: Path, range_label: str | None = None) -> str | None:
    if range_label:
        return range_label
    meta = read_fetch_meta(root)
    if meta:
        return str(meta.get("range_label") or "") or None
    return None


def publish_csv(
    root: Path,
    stem: str,
    rows: list[dict],
    fieldnames: list[str],
    *,
    range_label: str | None = None,
    day: date | None = None,
    sequence: int | None = None,
) -> Path:
    """Write current CSV and a range-labelled snapshot with 0001-style suffix."""
    if not range_label:
        raise ValueError("range_label is required")
    day = day or japan_today()
    seq = sequence if sequence is not None else next_range_sequence(root, stem, range_label, day)
    latest = current_path(root, stem)
    snap = range_snapshot_path(root, stem, range_label, seq)
    latest.parent.mkdir(parents=True, exist_ok=True)
    snap.parent.mkdir(parents=True, exist_ok=True)
    write_csv(latest, rows, fieldnames)
    write_csv(snap, rows, fieldnames)
    rotate_range_stem(root, stem, range_label)
    return latest


def publish_tob_outputs(
    root: Path,
    list_rows: list[dict],
    case_rows: list[dict],
    *,
    range_label: str,
    day: date | None = None,
    sequence: int | None = None,
    self_list_rows: list[dict] | None = None,
    self_case_rows: list[dict] | None = None,
    fetch_meta: dict | None = None,
) -> tuple[Path, Path]:
    day = day or japan_today()
    seq = sequence
    if seq is None:
        seq = next_range_sequence(root, LIST_STEM, range_label, day)
    list_path = publish_csv(
        root,
        LIST_STEM,
        list_rows,
        LIST_FIELDS,
        range_label=range_label,
        day=day,
        sequence=seq,
    )
    publish_csv(
        root,
        CASES_STEM,
        case_rows,
        CASE_FIELDS,
        range_label=range_label,
        day=day,
        sequence=seq,
    )
    if self_list_rows is not None:
        publish_csv(
            root,
            SELF_LIST_STEM,
            self_list_rows,
            SELF_LIST_FIELDS,
            range_label=range_label,
            day=day,
            sequence=seq,
        )
    if self_case_rows is not None:
        publish_csv(
            root,
            SELF_CASES_STEM,
            self_case_rows,
            SELF_CASE_FIELDS,
            range_label=range_label,
            day=day,
            sequence=seq,
        )
    if fetch_meta:
        write_fetch_meta(
            root,
            range_label=range_label,
            start=fetch_meta["start"],
            end=fetch_meta["end"],
            mode=fetch_meta["mode"],
            sequence=seq,
        )
    return list_path, current_path(root, CASES_STEM)


def load_range_list_rows(root: Path, range_label: str) -> list[dict]:
    """Load the latest snapshot for a fetch range (other + self list CSVs)."""
    chunks: list[dict] = []
    for stem in (LIST_STEM, SELF_LIST_STEM):
        snapshots = list_range_snapshot_files(root, stem, range_label)
        if not snapshots:
            continue
        _, path = snapshots[-1]
        chunks.extend(read_csv(path))
    if chunks:
        rows, _, _ = merge_document_rows([], chunks)
        return rows
    return []


def load_all_list_rows(root: Path) -> list[dict]:
    """Load 他社株 + 自社株 list CSVs from current/ and upsert by DocID."""
    chunks: list[dict] = []
    for stem in (LIST_STEM, SELF_LIST_STEM):
        path = resolve_current_csv(root, stem)
        if path:
            chunks.extend(read_csv(path))
    if not chunks:
        return []
    rows, _, _ = merge_document_rows([], chunks)
    return rows


def publish_context_from_meta(root: Path) -> dict:
    """Build publish_tob_outputs kwargs from current/fetch_meta.json."""
    meta = read_fetch_meta(root)
    if not meta or not meta.get("range_label"):
        raise SystemExit(
            "fetch_meta.json がありません。先に Fetch TOB を実行して取得範囲を確定してください。",
        )
    return {
        "range_label": str(meta["range_label"]),
        "fetch_meta": {
            "start": date.fromisoformat(str(meta["start"])),
            "end": date.fromisoformat(str(meta["end"])),
            "mode": str(meta.get("mode") or ""),
        },
    }


def resolve_current_csv(root: Path, stem: str) -> Path | None:
    latest = current_path(root, stem)
    if latest.exists():
        return latest
    legacy = root / f"{stem}.csv"
    if legacy.exists():
        return legacy
    return None
