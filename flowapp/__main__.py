"""Entry point: python -m flowapp (run.bat and main.py start the same thing)

  python -m flowapp                                   the app, start screen: instruments or test mode
  python -m flowapp --sim                             the app, straight into test mode (no gas flows)
  python -m flowapp COM9                              the app, connected to the instruments on COM9
  python -m flowapp --probe [--full] [COM9] [--sim]   list the connected instruments
  python -m flowapp --monitor [COM9] [--sim]          live readout in the console (Ctrl+C to stop)
  python -m flowapp --card-probe [ADDRESS] [--sim]    read the vacuum control card once (read-only)
"""

import argparse
import json
import sys
import time
from datetime import datetime

from .config import load_card_config, load_settings, load_simulator
from .core import card as cardrpc
from .core.bronkhorst import BronkhorstBus
from .core.card_sim import SimCard
from .core.vacuum import GAUGES
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


def card_probe(address, simulate, rounds=10):
    """Reads the card with read-only requests: the decoded values, the raw reply and the latency."""
    config = load_card_config()
    address = address or config.address
    if simulate:
        transport, where = SimCard(), "simulated card (test mode)"
    elif not address:
        print("No card address: give it (run.bat --card-probe 192.168.1.10) or set it in Vacuum > Advanced.")
        return 1
    else:
        try:
            transport = cardrpc.HttpTransport(address, config.timeout_s)
        except cardrpc.CardError as e:
            print(e)
            return 1
        where = f"card at http://{transport.address}{transport.path}"
    client = cardrpc.CardClient(transport, allow_control=False)
    requests = ([cardrpc.pressure(g.key) for g in GAUGES]
                + [cardrpc.valve_register(), cardrpc.chamber_status(), cardrpc.gun_status(), cardrpc.ups_state()])
    print(f"Reading the {where} (read-only requests only).")
    try:
        replies = client.call(requests)
    except cardrpc.CardError as e:
        print(f"Failed: {e}")
        return 1
    for request, (result, error) in zip(requests, replies):
        print(f"  {request.text:28} {json.dumps(result) if error is None else 'ERROR: ' + error}")
    print("\nRaw reply:")
    print(json.dumps(client.last_raw, indent=1))
    try:
        state = client.read_all()
        print("\nDecoded: " + ", ".join(f"{g.short} {'–' if state.pressures[g.key] is None else f'{state.pressures[g.key]:.2e}'}"
                                        for g in GAUGES))
        open_valves = [name for name, is_open in state.valves.items() if is_open]
        print(f"Open valves: {', '.join(open_valves) or 'none'}; valve supply "
              f"{'24 V' if state.supply_24v else '12 V'}")
        times = []
        for _ in range(rounds):
            started = time.perf_counter()
            client.read_all()
            times.append((time.perf_counter() - started) * 1000)
        print(f"Latency of one full read ({rounds}x): min {min(times):.0f} ms, "
              f"average {sum(times) / len(times):.0f} ms, max {max(times):.0f} ms")
    except cardrpc.CardError as e:
        print(f"Failed: {e}")
        return 1
    finally:
        client.close()
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m flowapp", description="Bronkhorst flow controllers")
    parser.add_argument("port", nargs="?", help="COM port, e.g. COM9: connect straight away (default: start screen)")
    parser.add_argument("--sim", action="store_true",
                        help="test mode: simulated instruments from config/simulator.json, real ones are disabled")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--probe", action="store_true", help="list the connected instruments and exit")
    mode.add_argument("--monitor", action="store_true", help="show live values in the console until Ctrl+C")
    mode.add_argument("--card-probe", nargs="?", const="", metavar="ADDRESS",
                      help="read the vacuum control card once with read-only requests (address from the "
                           "settings when not given) and show the raw replies and the latency")
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

    if args.card_probe is not None:
        return card_probe(args.card_probe, args.sim)

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
