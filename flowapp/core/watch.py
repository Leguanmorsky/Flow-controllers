"""Checks on the polled values that the UI warns about."""


class SetpointWatch:
    """Flags an instrument whose measured flow stays away from its setpoint, e.g. a closed gas supply.

    update() returns None, "low" (flow below setpoint) or "high" once the difference has been
    larger than `tolerance_pct` of full scale for `delay_s` without interruption.
    A setpoint change or a running ramp restarts the timer.
    """

    def __init__(self, tolerance_pct=2.0, delay_s=10.0):
        self.tolerance_pct = tolerance_pct
        self.delay_s = delay_s
        self._since = None
        self._setpoint = None

    def update(self, state, now, suspended=False):
        if not state.ok or state.measure_pct is None or state.setpoint_pct is None:
            self._since = self._setpoint = None
            return None
        setpoint_changed = self._setpoint is None or abs(state.setpoint_pct - self._setpoint) > self.tolerance_pct
        self._setpoint = state.setpoint_pct
        deviation = state.measure_pct - state.setpoint_pct
        if abs(deviation) <= self.tolerance_pct:
            self._since = None
            return None
        if suspended or setpoint_changed or self._since is None:
            self._since = now
        if now - self._since >= self.delay_s:
            return "low" if deviation < 0 else "high"
        return None
