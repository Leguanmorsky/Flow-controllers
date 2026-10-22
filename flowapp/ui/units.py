"""Number formatting and unit / % conversion for the UI (no Qt)."""

import math


def decimals_for(capacity):
    """Decimals that show about 1/10000 of full scale: 10 -> 3, 100 -> 2, 1 -> 4."""
    if not capacity or capacity <= 0:
        return 3
    return min(max(4 - math.floor(math.log10(capacity)), 0), 4)


def fmt(value, decimals=3, suffix=""):
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "–"
    return f"{value:.{decimals}f}{suffix}"


def to_pct(value, capacity):
    return None if value is None or not capacity else value / capacity * 100.0


def from_pct(pct, capacity):
    return pct / 100.0 * capacity


def fmt_duration(seconds):
    """3:05, 1:02:03, or '∞'."""
    if seconds is None or math.isinf(seconds):
        return "∞"
    seconds = int(round(max(seconds, 0)))
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def common_unit(channels):
    """The unit shared by all channels, or None when they differ."""
    units = {c.unit for c in channels}
    return units.pop() if len(units) == 1 else None
