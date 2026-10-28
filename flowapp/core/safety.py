"""Gas safety: links the MFCs to the vacuum system (no Qt).

Always on, once a card is configured:
- chamber pressure above p_max: every flow to 0, latched until the user acknowledges;
- no pressure data for longer than stale_s while gas flows: every flow to 0.
Rules the user can override with an extra confirmation (reset on disconnect):
- vent_zero:       every flow to 0 before a vent command;
- path_zero:       every flow to 0 when the pumping path of the main chamber closes;
- block_unpumped:  setpoints above 0 are refused while the main chamber is not pumped;
- confirm_valves:  switching a valve while gas flows asks for an extra confirmation.
Without a card (address not set) the vacuum rules cannot work: status() says so.
"""

import threading
from dataclasses import dataclass

from .vacuum import GAUGE_BY_KEY, chamber_pressure, closed_in_path, pump_path_open

RULES = {
    "vent_zero": "Set every flow to 0 before venting",
    "path_zero": "Set every flow to 0 when the pumping path closes",
    "block_unpumped": "Refuse gas while the main chamber is not pumped",
    "confirm_valves": "Ask again before switching a valve while gas flows",
}


class GasBlocked(Exception):
    def __init__(self, reason, rule):
        super().__init__(reason)
        self.reason = reason
        self.rule = rule            # "block_unpumped" (can be overridden) or "trip" (acknowledge first)

    @property
    def overridable(self):
        return self.rule in RULES


@dataclass(frozen=True)
class GasStatus:
    allowed: bool
    reason: str
    rule: str | None = None     # the rule that blocks, or None
    level: str = "good"         # "good", "warning" or "critical" for the display


def _fmt_pa(value):
    return "–" if value is None else f"{value:.1e} Pa"


class GasSupervisor:
    def __init__(self, config, zero_all, flowing, on_event=None, card_present=True):
        """`zero_all(reason)` sets every flow to 0 (thread-safe), `flowing()` tells whether gas flows."""
        self.config = config
        self.zero_all = zero_all
        self.flowing = flowing
        self.on_event = on_event or (lambda level, message: None)
        self.card_present = card_present
        self.overrides = set()
        self.tripped = None         # message of the latched p_max trip
        self.state = None
        self._path_was_open = None
        self._stale_handled = False
        self._lock = threading.Lock()

    # --- overrides ------------------------------------------------------------------------------

    def set_override(self, rule, on=True):
        if rule not in RULES:
            raise KeyError(rule)
        with self._lock:
            changed = (rule in self.overrides) != on
            (self.overrides.add if on else self.overrides.discard)(rule)
        if changed:
            if on:
                self.on_event("warning", f"Gas protection overridden: “{RULES[rule]}” is off until you "
                                         f"disconnect or switch it on again.")
            else:
                self.on_event("info", f"Gas protection on again: “{RULES[rule]}”.")

    def active(self, rule):
        return rule not in self.overrides

    def acknowledge_trip(self):
        with self._lock:
            was, self.tripped = self.tripped, None
        if was:
            self.on_event("info", "Pressure trip acknowledged: gas can be set again.")

    def reset(self):
        with self._lock:
            self.overrides.clear()
            self.tripped = None
            self.state = None
            self._path_was_open = None
            self._stale_handled = False

    # --- vacuum states (card worker thread) -----------------------------------------------------

    def on_state(self, state):
        if not self.card_present:
            return
        actions = []
        with self._lock:
            self.state = state
            if not state.ok:
                if state.stale and not self._stale_handled:
                    self._stale_handled = True
                    actions.append(f"no pressure data for {state.age_s:.1f} s ({state.error})")
            else:
                self._stale_handled = False
                p = chamber_pressure(state, self.config.trip_gauge)
                if p is not None and p > self.config.p_max_pa and self.tripped is None:
                    self.tripped = (f"chamber pressure {_fmt_pa(p)} above the limit "
                                    f"{_fmt_pa(self.config.p_max_pa)}")
                    actions.append(self.tripped)
                if state.register is not None:
                    path_open = pump_path_open(state.valves, self.config.pump_path)
                    if self._path_was_open and not path_open and "path_zero" not in self.overrides:
                        closed = ", ".join(closed_in_path(state.valves, self.config.pump_path))
                        actions.append(f"pumping path closed ({closed})")
                    self._path_was_open = path_open
        for reason in actions:
            if self.flowing():
                self.zero_all(reason)
            else:
                self.on_event("warning", f"Gas safety: {reason}.")

    # --- checks (UI thread) ---------------------------------------------------------------------

    def status(self):
        """Whether gas may be set now, and why not."""
        with self._lock:
            state, tripped, overrides = self.state, self.tripped, set(self.overrides)
        if not self.card_present:
            return GasStatus(True, "No pressure data (card not set up): vacuum protections are off.",
                             level="warning")
        if tripped:
            return GasStatus(False, f"Tripped: {tripped}. Acknowledge the trip to set gas again.", "trip",
                             "critical")
        reason = self._unpumped_reason(state)
        if reason is None:
            return GasStatus(True, "Gas allowed: main chamber pumped.")
        if "block_unpumped" in overrides:
            return GasStatus(True, f"Gas allowed (protection overridden): {reason}.", level="warning")
        return GasStatus(False, f"Gas blocked: {reason}.", "block_unpumped", "warning")

    def _unpumped_reason(self, state):
        if state is None:
            return "no pressure data yet"
        if not state.ok:
            return f"no pressure data ({state.error})"
        if state.register is None:
            return "valve states unknown"
        closed = closed_in_path(state.valves, self.config.pump_path)
        if closed:
            return f"pumping path closed ({', '.join(closed)})"
        p = chamber_pressure(state, self.config.trip_gauge)
        if p is None:
            return "no valid chamber pressure"
        if p > self.config.pumped_below_pa:
            gauge = GAUGE_BY_KEY.get(self.config.trip_gauge)
            return (f"main chamber not pumped ({gauge.short if gauge else 'chamber'} {_fmt_pa(p)} > "
                    f"{_fmt_pa(self.config.pumped_below_pa)})")
        return None

    def check_setpoint(self, value):
        """Raises GasBlocked when a setpoint above 0 must not be sent now."""
        if value is None or value <= 0:
            return
        status = self.status()
        if not status.allowed:
            raise GasBlocked(status.reason, status.rule)

    def before_vent(self, what, override=False):
        """Call before a vent command; sets every flow to 0 first unless overridden. True when it zeroed."""
        if not self.card_present or not self.flowing():
            return False
        if override or "vent_zero" in self.overrides:
            self.on_event("warning", f"Gas keeps flowing while you {what} (protection overridden).")
            return False
        self.zero_all(f"before you {what}")
        return True

    def valve_needs_confirmation(self):
        return self.flowing() and "confirm_valves" not in self.overrides
