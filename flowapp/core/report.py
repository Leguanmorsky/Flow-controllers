"""Instrument report ("probe"): what is connected and what it supports. Read-only."""

from datetime import datetime

from ..config import ROOT
from . import dde

REPORT_DIR = ROOT / "logs"


def fmt(value, digits=3, suffix=""):
    return "-" if value is None else f"{value:.{digits}f}{suffix}"


def probe_table(port, channels, states):
    """Lines with one row per instrument: identity, capacity, control mode and the current values."""
    lines = [f"Port {port}: {len(channels)} instrument(s)", ""]
    header = f"{'Addr':>4}  {'Serial':<12} {'Type':<18} {'Fluid':<8} {'Capacity':<16} {'Control mode':<16} " \
             f"{'Measure':>9} {'Setpoint':>9} {'Valve':>7} {'Temp':>8}"
    lines += [header, "-" * len(header)]
    by_address = {s.address: s for s in states}
    for c in channels:
        s = by_address.get(c.address)
        mode = f"{c.control_mode} {dde.control_mode_name(c.control_mode)}"
        lines.append(f"{c.address:>4}  {c.serial:<12} {c.device_type:<18} {c.fluid:<8} "
                     f"{fmt(c.capacity) + ' ' + c.unit:<16} {mode:<16} "
                     f"{fmt(s.measure if s else None):>9} {fmt(s.setpoint if s else None):>9} "
                     f"{fmt(s.valve_pct if s else None, 1, '%'):>7} {fmt(s.temperature if s else None, 1, ' C'):>8}")
        if s and not s.ok:
            lines.append(f"      ! {s.error}")
        if not c.accepts_bus_setpoint:
            lines.append("      ! this instrument ignores setpoints sent from the PC in its current control mode")
        if c.setpoint_slope:
            lines.append(f"      ! setpoint slope {c.setpoint_slope}: the instrument ramps setpoint changes internally")
    return lines


def probe_extra(bus, channels):
    """Reads more parameters one by one (read-only). Call on the thread that owns the bus."""
    lines = ["", "Extra parameters (read-only; '-' = not supported or no answer):"]
    for c in channels:
        lines += ["", f"  Address {c.address} ({c.serial})"]
        values = bus.read_extra(c.address, [nr for nr, _ in dde.PROBE_EXTRA])
        for nr, label in dde.PROBE_EXTRA:
            value = values.get(nr)
            text = value.strip() if isinstance(value, str) else ("-" if value is None else f"{value:g}")
            lines.append(f"    {f'{label} (DDE {nr})':<34} {text or '-'}")
    return lines


def full_report(bus, channels, states):
    """The complete report. Call on the thread that owns the bus."""
    return ([f"Instrument report {datetime.now():%Y-%m-%d %H:%M:%S}"] + probe_table(bus.port, channels, states)
            + probe_extra(bus, channels))


def save_report(lines, folder=REPORT_DIR):
    folder.mkdir(exist_ok=True)
    path = folder / f"probe_{datetime.now():%Y%m%d_%H%M%S}.txt"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path
