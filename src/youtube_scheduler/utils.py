from __future__ import annotations

import hashlib
from datetime import datetime, time, timedelta
from pathlib import Path

try:
    from zoneinfo import ZoneInfo  # py3.9+
except Exception:  # pragma: no cover
    ZoneInfo = None  # type: ignore


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def parse_hhmm(value: str) -> time:
    value = value.strip()
    parts = value.split(":")
    if len(parts) != 2:
        raise ValueError("Expected HH:MM")
    hh = int(parts[0])
    mm = int(parts[1])
    if hh < 0 or hh > 23 or mm < 0 or mm > 59:
        raise ValueError("Invalid time")
    return time(hour=hh, minute=mm)


def to_rfc3339_utc(dt: datetime) -> str:
    if dt.tzinfo is None:
        raise ValueError("datetime must be timezone-aware")
    utc = dt.astimezone(ZoneInfo("UTC") if ZoneInfo else None)
    s = utc.isoformat().replace("+00:00", "Z")
    if not s.endswith("Z"):
        # Fallback if ZoneInfo is unavailable
        s = utc.replace(tzinfo=None).isoformat() + "Z"
    return s


def generate_schedule_slots(
    *,
    start_local_date: datetime,
    timezone: str,
    videos_per_day: int,
    day_start_hhmm: str,
    count: int,
    reserved_rfc3339: set[str] | None = None,
) -> list[str]:
    """
    Returns a list of RFC3339 timestamps (UTC) for future publish times.

    Slots are spaced evenly across a 24h day, starting at day_start_hhmm.
    Already-reserved slots are skipped.
    """
    if videos_per_day <= 0:
        raise ValueError("videos_per_day must be >= 1")
    if count <= 0:
        return []

    if ZoneInfo is None:
        raise RuntimeError("Timezone support requires Python 3.9+ (zoneinfo).")

    tz = ZoneInfo(timezone)
    reserved_rfc3339 = reserved_rfc3339 or set()
    start_time = parse_hhmm(day_start_hhmm)
    interval = timedelta(seconds=int(24 * 3600 / videos_per_day))

    # Normalize start date to local day boundary + start time
    local_start = start_local_date.astimezone(tz)
    base_day = datetime(local_start.year, local_start.month, local_start.day, tzinfo=tz)
    cursor = base_day.replace(hour=start_time.hour, minute=start_time.minute, second=0, microsecond=0)
    if cursor <= local_start:
        # If start time already passed "now", move forward one interval until in the future
        while cursor <= local_start:
            cursor += interval

    out: list[str] = []
    safety = 0
    while len(out) < count:
        safety += 1
        if safety > count * 20:
            raise RuntimeError("Unable to find enough free schedule slots; check reserved slots.")
        rfc3339 = to_rfc3339_utc(cursor)
        if rfc3339 not in reserved_rfc3339:
            out.append(rfc3339)
            reserved_rfc3339.add(rfc3339)
        cursor += interval
    return out


