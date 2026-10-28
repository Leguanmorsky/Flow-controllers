"""Model of the UHV SEM vacuum system behind the control card (no Qt, no I/O).

Everything here comes from the card's own web page (docs/card_webpage/indexsvg.html):
the gauges it reads, the valve register bits, the valve labels and its interlock rules.
"""

import math
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Gauge:
    key: str
    method: str         # JSON-RPC method on the card
    index: int          # its "value" parameter
    label: str
    short: str
    volume: str         # the part of the system it measures


GAUGES = (
    Gauge("chamber_frg", "chbr.prs?", 0, "Chamber FRG", "FRG", "main"),
    Gauge("chamber_img", "chbr.prs?", 1, "Chamber IMG300", "IMG300", "main"),
    Gauge("chamber_hfig", "chbr.prs?", 2, "Chamber HFIG", "HFIG", "main"),
    Gauge("loadlock_frg", "chbr.prs?", 3, "Load-lock FRG", "LL FRG", "loadlock"),
    Gauge("gun", "sem.prs?", 0, "FEG gun", "Gun", "gun"),
    Gauge("column", "sem.prs?", 1, "FEG column", "Column", "column"),
)
GAUGE_BY_KEY = {g.key: g for g in GAUGES}
CHAMBER_GAUGES = ("chamber_frg", "chamber_img", "chamber_hfig")     # IMG300/HFIG read only below ~1e-2 Pa


@dataclass(frozen=True)
class Valve:
    name: str
    bit: int            # bit in the valve register (set = open)
    function: str       # "pump", "vent" or "separation"
    between: tuple      # the two parts it connects ("n2" = nitrogen vent supply)
    label: str


# The valves the web page operates (V07, V08, V11, V12 and V18 are commented out there).
VALVES = (
    Valve("FV1", 0, "pump", ("tmp1", "fore"), "TMP1 fore-vacuum valve"),
    Valve("VV1", 1, "vent", ("n2", "tmp1"), "TMP1 vent valve (N₂)"),
    Valve("V04", 4, "pump", ("prep", "tmp1"), "TMP1 gate valve (SVL)"),
    Valve("V05", 5, "vent", ("n2", "airlock"), "Air-lock vent (N₂)"),
    Valve("V06", 6, "pump", ("airlock", "fore"), "Air-lock roughing"),
    Valve("V09", 9, "vent", ("n2", "tmp2"), "TMP2 vent valve (VVL, N₂)"),
    Valve("V10", 10, "pump", ("tmp2", "fore"), "TMP2 fore-vacuum valve (FVL)"),
    Valve("V13", 13, "pump", ("loadlock", "tmp2"), "TMP2 gate valve (SVL)"),
    Valve("V14", 14, "separation", ("airlock", "loadlock"), "Air-lock separation valve (ASV)"),
    Valve("V15", 15, "separation", ("carousel", "loadlock"), "Load-lock separation valve (LSV)"),
    Valve("V16", 16, "separation", ("main", "carousel"), "Carousel separation valve (SSV)"),
    Valve("V17", 17, "separation", ("main", "prep"), "Prep-chamber separation valve (PSV)"),
    Valve("V19", 19, "pump", ("main", "ionpump"), "Ion-pump separation valve (ISV)"),
)
VALVE_BY_NAME = {v.name: v for v in VALVES}
VENT_VALVES = tuple(v.name for v in VALVES if v.function == "vent")
SUPPLY_24V_BIT = 31     # set: valve supply on 24 V; cleared: power save (12 V hold)


def parse_register(value):
    """Valve register (hex text or int) -> {valve name: open}."""
    register = int(value, 16) if isinstance(value, str) else int(value)
    return {v.name: bool(register >> v.bit & 1) for v in VALVES}


def interlock_reason(valves, name):
    """Why the closed valve `name` may not be opened now, or None. Closing is always allowed.

    A port of interlocks() in the card's web page, which the user wants always on.
    """
    def is_open(n):
        return bool(valves.get(n))

    if name not in VALVE_BY_NAME:
        return f"Unknown valve {name}."
    if is_open(name):
        return None
    if name == "V06" and any(is_open(n) for n in ("FV1", "V05", "V10", "V14")):
        return "To open V06, FV1, V05, V10 and V14 must be closed."
    if name in ("FV1", "V10") and is_open("V06"):
        return f"To open {name}, V06 must be closed."
    if name == "V05" and (is_open("V06") or is_open("V14")):
        return "To open V05, V06 and V14 must be closed."
    if name == "V14" and (is_open("V05") or is_open("V06") or (is_open("V15") and is_open("V16"))):
        return "To open V14, V05 and V06 must be closed and V15 and V16 must not both be open."
    if name in ("V15", "V16") and is_open("V14"):
        other = "V16" if name == "V15" else "V15"
        if is_open(other):
            return f"To open {name}, V14 must be closed ({other} is open)."
    return None


def pump_path_open(valves, path):
    """True when every valve of the pumping path is open."""
    return bool(valves) and all(valves.get(name) for name in path)


def closed_in_path(valves, path):
    return [name for name in path if not valves.get(name)]


def valid_pressure(value):
    """A gauge value in Pa, or None for off / out of range / invalid."""
    if isinstance(value, dict):
        value = value.get("value")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    return value if math.isfinite(value) and value > 0 else None


def to_sccm(value, unit):
    """MFC flow in its capacity unit -> sccm (unknown units are taken as sccm)."""
    if value is None:
        return 0.0
    unit = (unit or "").strip().lower()
    if unit.startswith(("ln/", "sl/", "l/", "slm")):
        return value * 1000.0
    if unit.startswith(("mln/h", "ml/h", "ccm/h")):
        return value / 60.0
    return value


@dataclass
class VacuumState:
    """One poll of the card."""
    t: float                        # time.time()
    ok: bool = True
    error: str = ""
    pressures: dict = field(default_factory=dict)   # gauge key -> Pa or None
    register: int | None = None     # valve register, None when unknown
    chamber_status: object = None   # raw replies of chbr.stat? / sem.stat? (format not documented)
    gun_status: object = None
    age_s: float = 0.0              # seconds since the last good reading
    stale: bool = False

    @property
    def valves(self):
        return parse_register(self.register) if self.register is not None else {}

    @property
    def supply_24v(self):
        return None if self.register is None else bool(self.register >> SUPPLY_24V_BIT & 1)

    def pressure(self, key):
        return self.pressures.get(key)


def chamber_pressure(state, preferred="chamber_frg"):
    """Main-chamber pressure: the preferred gauge, else another chamber gauge that reads, else None."""
    if state is None:
        return None
    for key in (preferred,) + tuple(k for k in CHAMBER_GAUGES if k != preferred):
        value = state.pressures.get(key)
        if value is not None:
            return value
    return None
