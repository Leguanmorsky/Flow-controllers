"""Entry point: python -m flowapp (run.bat and main.py start the same thing)

  python -m flowapp                                   the app, start screen: instruments or test mode
  python -m flowapp --sim                             the app, straight into test mode (no gas flows)
  python -m flowapp COM9                              the app, connected to the instruments on COM9
  python -m flowapp --probe [--full] [COM9] [--sim]   list the connected instruments
  python -m flowapp --monitor [COM9] [--sim]          live readout in the console (Ctrl+C to stop)
"""

import argparse
import sys
import time
from datetime import datetime

from .config import load_settings, load_simulator
from .core.bronkhorst import BronkhorstBus
from .core.report import fmt, full_report, probe_table, save_report
from .core.simulator import SimBus
from .core.worker import InstrumentWorker


def build_bus(settings):
    return SimBus(**load_simulator()) if settings.simulate else BronkhorstBus(settings.port)


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
    parser = argparse.ArgumentParser(prog="python -m flowapp", description="Bronkhorst flow controllers")
    parser.add_argument("port", nargs="?", help="COM port, e.g. COM9: connect straight away (default: start screen)")
    parser.add_argument("--sim", action="store_true",
                        help="test mode: simulated instruments from config/simulator.json, real ones are disabled")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--probe", action="store_true", help="list the connected instruments and exit")
    mode.add_argument("--monitor", action="store_true", help="show live values in the console until Ctrl+C")
    parser.add_argument("--full", action="store_true",
                        help="with --probe: also read extra parameters and save the report in logs/")
    parser.add_argument("--set", action="append", default=[], metavar="ADDR=VALUE",
                        help="with --monitor: set a flow first, in the instrument's capacity unit")
    parser.add_argument("--duration", type=float, help="with --monitor: stop after this many seconds")
    parser.add_argument("--console", action="store_true", help=argparse.SUPPRESS)   # used by run.bat only
    args = parser.parse_args(argv)

    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")    # Windows consoles cannot print every character

    # A port or --sim on the command line skips the start screen.
    settings = load_settings({"port": args.port, "simulate": args.sim or None,
                              "auto_connect": True if (args.port or args.sim) else None})
    if not (args.probe or args.monitor):
        from .ui.app import run_gui     # Qt is only needed for the graphical app
        return run_gui(settings)

    bus = build_bus(settings)
    try:
        channels = bus.open()
    except Exception as e:
        print(f"Connection failed: {e}")
        return 1

    if args.probe:
        try:
            states = bus.read_states()
            lines = full_report(bus, channels, states) if args.full else probe_table(bus.port, channels, states)
        finally:
            bus.close()
        print("\n".join(lines))
        if args.full:
            print(f"\nReport saved to {save_report(lines)}")
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
