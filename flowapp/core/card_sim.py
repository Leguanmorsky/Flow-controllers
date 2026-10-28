"""Simulated control card + vacuum system for test mode and tests.

SimCard answers the same JSON-RPC batches as the real card (it is a CardClient transport), and
simulates the pressures from the valves, pumps, vents and the MFC gas flow.

The model is coarse but behaves like the real system where it matters for the app:
- parts joined by open valves share one pressure; pumps and vents act on the joined group;
- steady state p = (gas load + Σ S·p_ultimate) / Σ S, approached with the time constant V/S;
- calibrated to the lab: 0.01 sccm into the main chamber pumped by TMP1 gives about 1e-3 Pa;
- IMG300 and HFIG read null above 1e-2 Pa, like the real gauges.
"""

import math
import random
import threading
import time

from .card import CardError
from .vacuum import GAUGES, SUPPLY_24V_BIT, VALVE_BY_NAME, VALVES, parse_register

SCCM = 1.689e-3                # 1 sccm in Pa·m³/s
ATMOSPHERE = 1.0e5
VALVE_DELAY_S = 0.3

VOLUMES = {"main": 0.05, "prep": 0.02, "carousel": 0.01, "loadlock": 0.005, "airlock": 0.001,
           "gun": 0.0005, "column": 0.001}                              # m³
OUTGASSING = {"main": 1.7e-7, "prep": 5e-8, "carousel": 2e-8, "loadlock": 1e-7, "airlock": 1e-6,
              "gun": 1e-11, "column": 2e-9}                             # Pa·m³/s
EDGES = {"V17": ("main", "prep"), "V16": ("main", "carousel"), "V15": ("carousel", "loadlock"),
         "V14": ("airlock", "loadlock")}

# Valves open at the start: the main chamber pumped by TMP1 through the prep chamber, the load lock
# by TMP2, the ion pump on the main chamber.
START_OPEN = ("FV1", "V04", "V17", "V16", "V10", "V13", "V19")

FAULTS = {
    "unreachable": "Card not reachable",
    "slow": "Card answers too slowly (timeout)",
    "gauge_off": "Chamber FRG off (null)",
    "valves_ignored": "Card ignores valve commands",
    "leak": "Leak into the main chamber",
}

CHAMBER_STATES = ("ready", "pumping", "vented", "off")


def _gauge_value(p, low, high):
    return p if low <= p <= high else None


class SimCard:
    simulated = True

    def __init__(self, seed=None, clock=time.monotonic, settle_s=120.0):
        self.clock = clock
        self._random = random.Random(seed)
        self._lock = threading.Lock()
        self.register = sum(1 << VALVE_BY_NAME[n].bit for n in START_OPEN)
        self.physical = parse_register(self.register)
        self._pending = []                  # (time, valve, open) for valves still moving
        self.pressures = {name: 1e-5 for name in VOLUMES}
        self.flow_sccm = 0.0
        self.chamber_vent = False
        self.chamber_pumping = False
        self.chamber_state = "ready"
        self.gun_vent = False
        self.gun_state = "ready"
        self.beam = False
        self.decontaminator = False
        self.faults = set()
        self.requests = []                  # every request received, for tests
        self._t = clock()
        self._settle(settle_s)

    # --- test-mode controls -------------------------------------------------------------------

    def set_flow(self, sccm):
        with self._lock:
            self.flow_sccm = max(float(sccm), 0.0)

    def set_fault(self, name, on=True):
        if name not in FAULTS:
            raise KeyError(name)
        with self._lock:
            (self.faults.add if on else self.faults.discard)(name)

    def has_fault(self, name):
        return name in self.faults

    def close(self):
        pass

    # --- physics --------------------------------------------------------------------------------

    def _settle(self, seconds):
        for _ in range(int(seconds / 0.5)):
            self._step(0.5)

    def _advance(self):
        now = self.clock()
        dt, self._t = now - self._t, now
        for t, name, state in list(self._pending):
            if now >= t:
                self.physical[name] = state
                self._pending.remove((t, name, state))
        while dt > 0:
            step = min(dt, 0.5)
            self._step(step)
            dt -= step

    def _groups(self):
        parent = {name: name for name in VOLUMES}

        def find(n):
            while parent[n] != n:
                n = parent[n]
            return n
        for valve, (a, b) in EDGES.items():
            if self.physical.get(valve):
                parent[find(a)] = find(b)
        groups = {}
        for name in VOLUMES:
            groups.setdefault(find(name), []).append(name)
        return list(groups.values())

    def _pumps(self, volume, p):
        """(S m³/s, ultimate Pa) of the pumps acting on `volume` at pressure p."""
        v = self.physical
        pumps = []
        if volume == "prep" and v["V04"] and v["FV1"] and not v["VV1"]:
            pumps.append((0.017, 0.0) if p < 100 else (0.02, 1.0))     # TMP1, or roughing through it
        if volume == "loadlock" and v["V13"] and v["V10"] and not v["V09"]:
            pumps.append((0.05, 0.0) if p < 100 else (0.02, 1.0))      # TMP2
        if volume == "airlock" and v["V06"]:
            pumps.append((0.01, 1.0))                                   # fore pump
        if volume == "main" and v["V19"] and p < 1e-2:
            pumps.append((0.01, 0.0))                                   # ion pump
        if volume == "carousel" and p < 1e-2:
            pumps.append((0.005, 0.0))                                  # carousel ion pump
        if volume == "main" and self.chamber_pumping:
            pumps.append((0.05, 1e-6))                                  # the card's own pump sequence
        if volume in ("gun", "column") and not self.gun_vent and p < 1e-2:
            pumps.append((0.001 if volume == "gun" else 0.002, 0.0))
        if volume in ("gun", "column") and self.gun_state == "pumping" and p >= 1e-2:
            pumps.append((0.01, 1e-3))
        return pumps

    def _vented(self, volume):
        v = self.physical
        return ((volume == "prep" and v["VV1"] and v["V04"]) or (volume == "loadlock" and v["V09"] and v["V13"])
                or (volume == "airlock" and v["V05"]) or (volume == "main" and self.chamber_vent)
                or (volume in ("gun", "column") and self.gun_vent))

    def _step(self, dt):
        for group in self._groups():
            volume = sum(VOLUMES[n] for n in group)
            p = sum(self.pressures[n] * VOLUMES[n] for n in group) / volume     # gas spreads instantly
            load = sum(OUTGASSING[n] for n in group)
            if "main" in group:
                load += self.flow_sccm * SCCM + (5e-4 if "leak" in self.faults else 0.0)
            pumps = [pump for n in group for pump in self._pumps(n, p)]
            if any(self._vented(n) for n in group):
                target, tau = ATMOSPHERE, 1.0
            elif pumps:
                speed = sum(s for s, _ in pumps)
                target = (load + sum(s * u for s, u in pumps)) / speed
                tau = min(max(volume / speed, 0.05), 30.0)
            else:
                target, tau = None, None
            if target is None:
                p += load / volume * dt
            else:
                p = target + (p - target) * math.exp(-dt / tau)
            p = min(max(p, 1e-9), ATMOSPHERE)
            for n in group:
                self.pressures[n] = p
        if self.chamber_pumping and self.pressures["main"] < 1e-3:
            self.chamber_pumping = False
            self.chamber_state = "ready"
        if self.gun_state == "pumping" and self.pressures["gun"] < 1e-6:
            self.gun_state = "ready"

    def _reading(self, gauge):
        p = self.pressures[gauge.volume] * (1 + self._random.gauss(0.0, 0.02))
        if gauge.key == "chamber_frg":
            return None if "gauge_off" in self.faults else _gauge_value(p, 5e-9, 1.1e5)
        if gauge.key in ("chamber_img", "chamber_hfig"):
            return _gauge_value(p, 1e-10, 1e-2)
        return _gauge_value(p, 5e-9, 1.1e5) if gauge.key == "loadlock_frg" else _gauge_value(p, 1e-11, 1e-2)

    # --- JSON-RPC ---------------------------------------------------------------------------------

    def post(self, payload):
        if "unreachable" in self.faults:
            raise ConnectionError("card not reachable (simulated)")
        if "slow" in self.faults:
            raise CardError("No answer from the card within 1 s (simulated).")
        with self._lock:
            self._advance()
            items = payload if isinstance(payload, list) else [payload]
            replies = [self._answer(item) for item in items]
        return replies if isinstance(payload, list) else replies[0]

    def _answer(self, item):
        method, params, rid = item.get("method"), item.get("params"), item.get("id")
        self.requests.append((method, params))
        try:
            result = self._dispatch(method, params)
        except ValueError as e:
            return {"jsonrpc": "2.0", "id": rid, "error": {"code": -32602, "message": str(e)}}
        except KeyError:
            return {"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": "Method not found"}}
        return {"jsonrpc": "2.0", "id": rid, "result": result}

    def _tsc_reply(self, value, rlen):
        width = 8 if rlen == "4" else 4
        return {"status": "tscOK", "rdata": f"{value & (1 << 4 * width) - 1:0{width}x}"}

    def _dispatch(self, method, params):
        for gauge in GAUGES:
            if method == gauge.method and isinstance(params, dict) and params.get("value") == gauge.index:
                return self._reading(gauge)
        if method == "tsc.wrd":
            return self._tsc(*params)
        if method == "chbr.stat?":
            return self.chamber_state
        if method == "sem.stat?":
            return {"state": self.gun_state, "beam": self.beam}
        if method == "chbr.vent":
            self.chamber_vent, self.chamber_pumping, self.chamber_state = True, False, "vented"
        elif method == "chbr.pump":
            self.chamber_vent, self.chamber_pumping, self.chamber_state = False, True, "pumping"
        elif method == "chbr.off":
            self.chamber_vent, self.chamber_pumping, self.chamber_state = False, False, "off"
        elif method in ("chbr.clear", "sem.clear", "sem.ions"):
            pass
        elif method == "sem.vent":
            self.gun_vent, self.beam, self.gun_state = True, False, "vented"
        elif method == "sem.pump":
            hours = float(params.get("value", 0)) / 3600 if isinstance(params, dict) else 0.0
            self.gun_vent, self.gun_state = False, "pumping"
            if hours:
                self.gun_state = f"bake-out {hours:g} h"
        elif method == "sem.off":
            self.gun_state, self.beam = "off", False
        elif method == "sem.beam":
            on = bool(params.get("value")) if isinstance(params, dict) else False
            if on and self.pressures["gun"] > 1e-6:
                raise ValueError("beam interlock: gun pressure too high")
            self.beam = on
        else:
            raise KeyError(method)
        return True

    def _tsc(self, addr, wdata, rlen):
        if addr == "40":
            return self._tsc_reply(self.register, rlen)
        if addr == "64":
            return self._tsc_reply(0xC000, rlen)            # AC ok, battery ok
        if addr in ("32", "36"):
            bits = int(wdata, 16)
            if "valves_ignored" not in self.faults:
                before = parse_register(self.register)
                self.register = self.register | bits if addr == "32" else self.register & ~bits
                after = parse_register(self.register)
                for valve in VALVES:
                    if before[valve.name] != after[valve.name]:
                        self._pending.append((self.clock() + VALVE_DELAY_S, valve.name, after[valve.name]))
            return self._tsc_reply(self.register, rlen)
        if addr in ("128", "132"):
            return self._tsc_reply(0, rlen)
        if addr in ("48", "50"):
            self.decontaminator = addr == "48"
            return self._tsc_reply(0x0200 if self.decontaminator else 0, rlen)
        raise KeyError(addr)

    @property
    def supply_24v(self):
        return bool(self.register >> SUPPLY_24V_BIT & 1)
