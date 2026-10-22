"""Bronkhorst FlowDDE parameter numbers used by the app.

Numbers, process/parameter indexes and types come from propar's own database
(`propar.database().get_parameter(nr)`).
"""

IDENT_STRING = 1        # string, also used by propar's wink()
MEASURE = 8             # 0..32000 = 0..100 % of capacity (can overshoot to 41942)
SETPOINT = 9            # 0..32000 = 0..100 % of capacity
CONTROL_MODE = 12       # see CONTROL_MODES
CAPACITY = 21           # float, flow at 100 % in CAPACITY_UNIT
FLUID_NAME = 25         # string
VALVE_OUTPUT = 55       # 0..16777215 (24-bit)
DEVICE_TYPE = 90        # string, e.g. "DMFC"
SERIAL_NUMBER = 92      # string
USER_TAG = 115          # string stored on the instrument
CAPACITY_UNIT = 129     # string, e.g. "mln/min"
TEMPERATURE = 142       # float, deg C (not supported by every instrument)
FMEASURE = 205          # float, measured flow in CAPACITY_UNIT
FSETPOINT = 206         # float, setpoint in CAPACITY_UNIT

# Read only by the extended probe (python -m flowapp --probe --full), never written.
SETPOINT_SLOPE = 10     # > 0: the instrument ramps its setpoint internally
FLUIDSET_INDEX = 24     # active fluid slot on multi-fluid instruments (EL-FLOW Prestige)
ALARM_INFO = 28
FIRMWARE_VERSION = 105
COUNTER_VALUE = 122
COUNTER_UNIT = 128
PRESSURE = 143
DENSITY = 170
CALIBRATION_DATE = 172
PRESSURE_INLET = 178
PRESSURE_OUTLET = 179
FLUID_TEMPERATURE = 181
VALVE_SAFE_STATE = 301

PROBE_EXTRA = [
    (IDENT_STRING, "Identification"),
    (FIRMWARE_VERSION, "Firmware version"),
    (USER_TAG, "User tag"),
    (FLUIDSET_INDEX, "Fluid slot (index)"),
    (FLUID_NAME, "Fluid name"),
    (SETPOINT_SLOPE, "Setpoint slope"),
    (ALARM_INFO, "Alarm info"),
    (TEMPERATURE, "Temperature"),
    (FLUID_TEMPERATURE, "Fluid temperature"),
    (PRESSURE, "Pressure"),
    (PRESSURE_INLET, "Inlet pressure"),
    (PRESSURE_OUTLET, "Outlet pressure"),
    (DENSITY, "Density"),
    (COUNTER_VALUE, "Counter value"),
    (COUNTER_UNIT, "Counter unit"),
    (VALVE_SAFE_STATE, "Valve safe state"),
    (CALIBRATION_DATE, "Calibration date"),
]

FULL_SCALE = 32000      # raw value of 100 % for MEASURE / SETPOINT
VALVE_FULL_SCALE = 16777215

CONTROL_MODES = {
    0: "Bus/RS232",
    1: "Analog input",
    2: "FLOW-BUS slave",
    3: "Valve closed",
    4: "Controller idle",
    7: "Setpoint 100%",
    8: "Valve fully open",
    9: "Calibration",
    10: "Analog slave",
    12: "Setpoint 0%",
    18: "RS232",
    20: "Valve steering",
    22: "Valve safe state",
}

# Modes in which the instrument follows a setpoint written over the serial bus.
BUS_SETPOINT_MODES = {0, 18}
BUS_CONTROL = 0         # the only mode the app switches to


def control_mode_name(mode):
    if mode is None:
        return "unknown"
    return CONTROL_MODES.get(mode, f"mode {mode}")
