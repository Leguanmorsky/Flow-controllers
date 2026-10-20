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


def control_mode_name(mode):
    if mode is None:
        return "unknown"
    return CONTROL_MODES.get(mode, f"mode {mode}")
