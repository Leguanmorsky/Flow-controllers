"""Data passed between the instrument layer and the rest of the app."""

from dataclasses import dataclass

from . import dde


@dataclass
class ChannelInfo:
    """Static information about one instrument, read once on connect."""
    address: int
    serial: str = ""
    device_type: str = ""
    fluid: str = ""
    capacity: float = 0.0       # flow at 100 %, in `unit`
    unit: str = ""
    user_tag: str = ""
    control_mode: int | None = None     # updated by every poll
    firmware: str = ""
    setpoint_slope: int | None = None   # > 0: the instrument ramps its setpoint internally

    @property
    def key(self):
        """Stable identifier used for saved settings (aliases, gases, colours)."""
        return self.serial or f"address-{self.address}"

    @property
    def accepts_bus_setpoint(self):
        """False when the instrument ignores setpoints sent over the serial bus."""
        return self.control_mode is None or self.control_mode in dde.BUS_SETPOINT_MODES


@dataclass
class ChannelState:
    """One poll of one instrument. Values are None when they could not be read."""
    address: int
    t: float                    # time.time() of the poll
    ok: bool = True
    error: str = ""
    measure: float | None = None        # in capacity unit
    setpoint: float | None = None       # in capacity unit
    measure_pct: float | None = None
    setpoint_pct: float | None = None
    valve_pct: float | None = None
    temperature: float | None = None    # deg C
    control_mode: int | None = None
