# Flow controllers

Control software for Bronkhorst mass flow controllers (EL-FLOW Prestige, propar over RS232/USB).

> **Refactor in progress.** The new app (`flowapp/`) replaces the old Tkinter GUI block by block.
> The old app still starts with `run_legacy.bat` until the new one has passed a check on the real instruments.

## Setup (once per computer)
1. Install Python 3.11 from python.org (keep the "py launcher" option checked).
2. Install the Bronkhorst USB/RS232 driver so the device shows up as a COM port.
3. Double-click `run.bat`. The first start creates a local `.venv` and installs `requirements.txt`
   (about 70 MB, needs internet). After a `git pull` that changes `requirements.txt`, `run.bat`
   installs the new packages by itself.

The `.venv` folder is not synced through git. Each computer builds its own (`setup_env.bat` does it by hand).

## Run
- `run.bat` starts the app and connects to the port from the config, or finds the instruments automatically
  (COM9 is tried first, Bluetooth ports are skipped).
- `run.bat COM5` uses a specific port.

## Test mode (no gas flows)
Use test mode on any computer, including the lab PC, to try setpoints, ramps, mixtures and (later)
programs and presets without putting gas into the chamber.
- **`test_mode.bat`** starts a test-only session: the app uses simulated instruments and **never opens the
  real flow controllers** (the hardware ports are not offered and are refused). Same as `run.bat --sim`.
- In a normal session (`run.bat`) you can also pick **Test mode** in the port list (disconnect from the
  real instruments first; disconnecting sets their flows to 0).
- Test mode is marked by an orange **TEST MODE** strip and `[TEST MODE]` in the window title; exported
  files start with `TEST_`.
- The **Test mode** menu fakes faults: unplugged cable, an instrument not answering, analog mode,
  closed gas supply, noisy signal.
- `config/simulator.json` sets the simulated instruments (address, gas, capacity, unit, response time,
  noise). Add channels to try other mixtures. With a real `serial` number, a simulated channel uses that
  instrument's saved name, colour and max flow.

## Using the app
- **Cards (left):** one per instrument with measured flow, setpoint read back from the device, valve %,
  temperature and status.
  - Type a setpoint and press Enter or **Set**. The slider sends when you let go, **−/+** step by 1 % of
    full scale (adjustable), **0** sets that channel to 0.
  - **Ramp:** move the setpoint to a target at a rate per minute or over a given time. A manual setpoint
    stops the ramp.
  - **Identify** blinks the instrument's LEDs. **⚙** sets the name, colour, max flow and step; these are
    saved per serial number in `config/channels.json`.
  - Warnings appear on the card: no answer, instrument in a mode that ignores PC setpoints (with a button
    to switch it to PC control), flow not reaching the setpoint.
- **Graph (right):** flow (solid = measured, dashed = setpoint, thick grey = total), valve %, mixture %.
  Pick the time window, pause or zoom with the mouse wheel, hover to read values, export PNG or CSV
  (saved in `exports/` by default).
- **View menu:** flows in % of full scale, panels, theme (follows Windows, or light/dark).
- **Log (bottom):** connections, setpoints, ramps, warnings and errors. No popup windows for
  communication errors.

## Safety
- **ALL TO 0** (red button, F12) cancels all ramps and sets every flow to 0. It is a software command,
  not a hardware interlock.
- **Closing the app or disconnecting sets every flow to 0** (also when the console window is closed).
  If that cannot be confirmed (e.g. cable unplugged), the app asks before it closes.
- A max flow per channel can be set in **⚙**.

## Tools
- `probe.bat` lists the connected instruments: address, serial number, gas, capacity and unit, control
  mode and the current flow. `probe.bat --full` also reads extra parameters (firmware, fluid slot,
  setpoint slope, pressure/temperature sensors, ...) and saves the report in `logs/`.
  Everything the probe does is read-only. `probe.bat --sim` probes the test-mode instruments.
- `.venv\Scripts\python -m flowapp --monitor [COM9] [--sim]` shows live values in the console.
- `run_legacy.bat` starts the old Tkinter app (temporary fallback).

## Lab check (first run of the new app on the real instruments)
1. `git pull`, then `run.bat` (installs the new packages).
2. `probe.bat --full` and keep the output.
3. In the app: check the number of cards, gases and capacities; **Identify** each MFC and name it in **⚙**.
4. With the gas supply in a safe state: a small setpoint on each MFC, then **ALL TO 0**, then close the app
   and check that the flows are 0.
5. A ramp on one MFC; unplug and replug the USB cable (status turns red, then recovers).

## Configuration
- `config/settings.json`: shared defaults (port `auto`, poll rate, graph history). Synced through git.
- `config/local.json`: settings for this computer only, e.g. `{"port": "COM9"}`. Not synced.
- `config/channels.json`: name, gas, colour, max flow and step per instrument serial number.
- `config/simulator.json`: the instruments simulated in test mode.
- Window layout, theme and view options are remembered per computer (Windows registry).

## Tests
`.venv\Scripts\python -m pytest` runs on the simulator and a fake propar, never on hardware
(the UI tests run offscreen).

## Project layout
| Path | Content |
|---|---|
| `flowapp/core/` | Instrument layer: Bronkhorst driver, simulator, background worker, ramps, checks |
| `flowapp/ui/` | PySide6 + pyqtgraph user interface |
| `flowapp/config.py` | Settings and per-instrument configuration |
| `tests/` | pytest suite |
| `docs/` | Pressure-control integration brief and the UHV SEM card web page |
| `laboratory_gas_control/` | Old Tkinter app (removed in the next block) |

## Note
The Bronkhorst library on PyPI is `bronkhorst-propar`. The package named just `propar` is unrelated and
breaks `import propar`.

## Credits
Ideas were taken from these open-source projects:
[AutoFlow](https://github.com/EthanGYoung/AutoFlow),
[project-Anemoi](https://github.com/thithibaud/project-Anemoi),
[coldplasmas-unimib/flowcontroller](https://github.com/coldplasmas-unimib/flowcontroller).
