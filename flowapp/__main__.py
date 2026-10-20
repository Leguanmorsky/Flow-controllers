"""Command line entry point: python -m flowapp

  python -m flowapp --probe [COM9] [--sim]     list the connected instruments
  python -m flowapp --monitor [COM9] [--sim]   live readout (Ctrl+C to stop)

The graphical app still starts from run.bat (laboratory_gas_control) until the new UI is ready.
"""

import argparse
import sys
import time
from datetime import datetime

from .config import load_settings
from .core import dde
from .core.bronkhorst import BronkhorstBus
from .core.simulator import SimBus
from .core.worker import InstrumentWorker


def build_bus(settings):
    return SimBus() if settings.simulate else BronkhorstBus(settings.port)


def fmt(value, digits=3, suffix=""):
    return "-" if value is None else f"{value:.{digits}f}{suffix}"


def print_probe(bus, channels, states):
    print(f"Port {bus.port}: {len(channels)} instrument(s)\n")
    header = f"{'Addr':>4}  {'Serial':<12} {'Type':<18} {'Fluid':<8} {'Capacity':<16} {'Control mode':<16} " \
             f"{'Measure':>9} {'Setpoint':>9} {'Valve':>7} {'Temp':>8}"
    print(header)
    print("-" * len(header))
    by_address = {s.address: s for s in states}
    for c in channels:
        s = by_address.get(c.address)
        mode = f"{c.control_mode} {dde.control_mode_name(c.control_mode)}"
        print(f"{c.address:>4}  {c.serial:<12} {c.device_type:<18} {c.fluid:<8} "
              f"{fmt(c.capacity) + ' ' + c.unit:<16} {mode:<16} "
              f"{fmt(s.measure if s else None):>9} {fmt(s.setpoint if s else None):>9} "
              f"{fmt(s.valve_pct if s else None, 1, '%'):>7} {fmt(s.temperature if s else None, 1, ' C'):>8}")
        if s and not s.ok:
            print(f"      ! {s.error}")
        if not c.accepts_bus_setpoint:
            print("      ! this instrument ignores setpoints sent from the PC in its current control mode")


def monitor(worker, channels, duration):
    names = {c.address: c.fluid or str(c.address) for c in channels}
    units = {c.address: c.unit for c in channels}
    print("Measure / setpoint per instrument. Ctrl+C to stop (setpoints are left unchanged).")
    end = time.monotonic() + duration if duration else None
    while end is None or time.monotonic() < end:
        time.sleep(1.0)
        parts = []
        for address, s in sorted(worker.latest.items()):
            if s.ok:
                parts.append(f"{names[address]} {fmt(s.measure)}/{fmt(s.setpoint)} {units[address]}")
            else:
                parts.append(f"{names[address]} ! {s.error}")
        print(datetime.now().strftime("%H:%M:%S"), "  ".join(parts))


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m flowapp", description="Bronkhorst flow controller tools")
    parser.add_argument("port", nargs="?", help="COM port, e.g. COM9 (default: config, then auto-detect)")
    parser.add_argument("--sim", action="store_true", help="use simulated instruments instead of hardware")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--probe", action="store_true", help="list the connected instruments and exit")
    mode.add_argument("--monitor", action="store_true", help="show live values until Ctrl+C")
    parser.add_argument("--set", action="append", default=[], metavar="ADDR=VALUE",
                        help="with --monitor: set a flow first, in the instrument's capacity unit")
    parser.add_argument("--duration", type=float, help="with --monitor: stop after this many seconds")
    args = parser.parse_args(argv)

    if not (args.probe or args.monitor):
        parser.print_help()
        print("\nThe graphical app is started with run.bat.")
        return 0

    settings = load_settings({"port": args.port, "simulate": args.sim or None})
    bus = build_bus(settings)
    try:
        channels = bus.open()
    except Exception as e:
        print(f"Connection failed: {e}")
        return 1

    if args.probe:
        try:
            print_probe(bus, channels, bus.read_states())
        finally:
            bus.close()
        return 0

    worker = InstrumentWorker(bus, settings.poll_hz, settings.history_minutes)
    worker.start()
    try:
        for item in args.set:
            address, value = item.split("=", 1)
            sent = worker.set_setpoint(int(address), float(value)).result(timeout=5)
            print(f"Setpoint of {address} set to {sent:g}")
        monitor(worker, channels, args.duration)
    except KeyboardInterrupt:
        pass
    except Exception as e:
        print(f"Error: {e}")
        return 1
    finally:
        worker.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
