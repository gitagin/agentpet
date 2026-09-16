from __future__ import annotations

import zoneinfo
from datetime import datetime, timedelta, timezone, tzinfo
from functools import lru_cache
from time import perf_counter, perf_counter_ns

try:
    from tzlocal import get_localzone_name
except ImportError:  # pragma: no cover - packaging fallback
    get_localzone_name = None  # type: ignore[assignment]


def local_timezone() -> tzinfo:
    """本机（机器）时区对象；Windows 上为 fixed-offset tz，Unix 上为 zoneinfo。"""
    try:
        return zoneinfo.ZoneInfo(local_timezone_name())
    except (zoneinfo.ZoneInfoNotFoundError, ValueError):
        return datetime.now().astimezone().tzinfo or timezone.utc


def local_timezone_label() -> str:
    """本机时区的友好标签：避免把非东八区用户标注成"北京时间"。"""
    offset = datetime.now().astimezone().utcoffset()
    if offset is None:
        return "本地时间"
    seconds = int(offset.total_seconds())
    sign = "+" if seconds >= 0 else "-"
    hours, remainder = divmod(abs(seconds), 3600)
    minutes = remainder // 60
    return f"本地时间（UTC{sign}{hours:02d}:{minutes:02d}）"


# 常见 UTC 偏移 → 首选 IANA 时区。偏移相同的时区行为等价（含 DST 地区
# 按"当前偏移"匹配，例如 America/New_York 冬 -5 / 夏 -4 都能命中同一行）。
_KNOWN_OFFSET_IANA: dict[int, tuple[str, ...]] = {
    0: ("UTC",),
    28800: ("Asia/Shanghai",),
    32400: ("Asia/Tokyo",),
    25200: ("Asia/Jakarta",),
    3600: ("Europe/Berlin",),
    7200: ("Europe/Helsinki",),
    10800: ("Europe/Moscow",),
    19800: ("Asia/Kolkata",),
    -14400: ("America/New_York",),
    -18000: ("America/New_York",),
    -21600: ("America/Chicago",),
    -25200: ("America/Denver",),
    -28800: ("America/Los_Angeles",),
    -36000: ("Pacific/Honolulu",),
}


@lru_cache(maxsize=1)
def local_timezone_name() -> str:
    """本机时区的 IANA 名称（尽力解析，结果永远可用于 ZoneInfo）。

    Windows 的 tzinfo 名字是"中国标准时间"这类本地化名，直接传给
    ZoneInfo 会抛 ZoneInfoNotFoundError（社区真实事故，如 bambuddy 的
    'No time zone found with key UTC'）。这里先按 UTC 偏移映射首选 IANA，
    再回退 zoneinfo 全表按偏移匹配，最后才退回 UTC。
    """
    if get_localzone_name is not None:
        try:
            name = str(get_localzone_name()).strip()
            if name:
                zoneinfo.ZoneInfo(name)
                return name
        except Exception:
            pass

    now = datetime.now()
    offset = now.astimezone().utcoffset()
    if offset is None:
        return "UTC"
    seconds = int(offset.total_seconds())
    for name in _KNOWN_OFFSET_IANA.get(seconds, ()):
        try:
            zoneinfo.ZoneInfo(name)
        except Exception:
            continue
        return name
    for name in zoneinfo.available_timezones():
        try:
            if zoneinfo.ZoneInfo(name).utcoffset(now) == offset:
                return name
        except Exception:
            continue
    return "UTC"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def elapsed_ms(started: float) -> int:
    """Milliseconds elapsed since a ``perf_counter()`` start (clamped to >= 0)."""
    return max(0, round((perf_counter() - started) * 1000))


def elapsed_ms_ns(started_ns: int) -> float:
    """Milliseconds elapsed since a ``perf_counter_ns()`` start (6-dp float)."""
    return round((perf_counter_ns() - started_ns) / 1_000_000, 6)


def coerce_datetime(value: datetime | str) -> datetime:
    """Parse a datetime or ISO string into a UTC-aware datetime."""
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
