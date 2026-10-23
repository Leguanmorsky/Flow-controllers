# Flow controllers

<img src="flowapp/assets/logo.png" width="72" align="right" alt="logo">

Control software for Bronkhorst mass flow controllers (EL-FLOW Prestige, propar over RS232/USB),
with a **test mode** that simulates the instruments so everything can be tried without gas flowing.

## Setup (once per computer)
1. Install Python 3.11 from python.org (keep the "py launcher" option checked).
2. Install the Bronkhorst USB/RS232 driver so the instruments show up as a COM port.
3. Double-click **`run.bat`**. The first start creates a local `.venv` and installs `requirements.txt`
   (about 70 MB, needs internet), then opens the app. The app puts a **Flow controllers** shortcut on the
   desktop at its first start (Help → Create desktop shortcut makes it again).

After a `git pull` that changes `requirements.txt`, `run.bat` installs the new packages by itself.
The `.venv` folder is not synced through git; each computer builds its own.

## Start
- **Desktop shortcut** or **`run.bat`**: the start screen asks how to start:
  - **Connect to the instruments**: pick the port (Auto-detect finds them; COM9 is tried first,
    Bluetooth ports are skipped). Setpoints make real gas flow.
  - **Test mode**: simulated instruments, nothing is sent to the real flow controllers, no gas flows.
- From code: `python main.py`, `python -m flowapp`, or the VS Code launch entries
  *Flow controllers* / *Flow controllers (test mode)*.
- Options for `run.bat`, `main.py` and `python -m flowapp`:
  `--sim` (straight into test mode), `COM9` (connect straight away),
  `--console` (run.bat only: keep the console open with the log, for troubleshooting).

`run.bat` starts the app without a console window; its log is in the app and in `logs/last_run.log`.

## Test mode
Use it on any computer, including the lab PC, to try setpoints, ramps, mixtures and (later) programs,
presets and the pressure regulation without putting gas into the chamber.
- Marked by an orange **TEST MODE** strip and `[TEST MODE]` in the title; exported files start with `TEST_`.
- A session started with `--sim` cannot connect to the real instruments at all.
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
  Pick the time window, zoom with the mouse wheel (Live returns to following), hover to read values,
  export PNG or CSV (saved in `exports/` by default).
- **Instruments → Instrument report:** a read-only report of the connected instruments (identity,
  capacity, control mode, firmware, fluid slot, setpoint slope, extra sensors), saved in `logs/`.
- **View menu:** flows in % of full scale, panels, theme (follows Windows, or light/dark).
- **Log (bottom):** connections, setpoints, ramps, warnings and errors. No popup windows for
  communication errors.

## Safety
- **ALL TO 0** (red button, F12) cancels all ramps and sets every flow to 0. It is a software command,
  not a hardware interlock.
- **Closing the app or disconnecting sets every flow to 0.** If that cannot be confirmed (e.g. cable
  unplugged), the app asks before it closes.
- A max flow per channel can be set in **⚙**.

## Lab check (first run on the real instruments)
1. `git pull`, then `run.bat` (installs the new packages, creates the desktop shortcut).
2. Start screen → **Connect to the instruments**. Check the number of cards, gases and capacities.
3. **Instruments → Instrument report**, copy it and keep it.
4. **Identify** each MFC and name it in **⚙**.
5. With the gas supply in a safe state: a small setpoint on each MFC, then **ALL TO 0**, then close the app
   and check that the flows are 0.
6. A ramp on one MFC; unplug and replug the USB cable (status turns red, then recovers).

If the app does not open, run `run.bat --console` and send the text from the window.

## Tools (console)
- `run.bat --probe [--full]` or `python -m flowapp --probe [--full] [COM9] [--sim]`: list the instruments
  (read-only; `--full` saves the report in `logs/`).
- `python -m flowapp --monitor [COM9] [--sim]`: live values in the console.

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
| `run.bat` | The launcher: setup/update, then the app |
| `main.py` | Start from code (same as `python -m flowapp`) |
| `flowapp/core/` | Instrument layer: Bronkhorst driver, simulator, background worker, ramps, checks, report |
| `flowapp/ui/` | PySide6 + pyqtgraph user interface |
| `flowapp/assets/` | Logo (`logo.svg` is the source; `tools/make_icon.py` renders `logo.png` and `logo.ico`) |
| `flowapp/config.py`, `flowapp/desktop.py` | Settings; desktop shortcut and taskbar icon |
| `tests/` | pytest suite |
| `docs/` | Pressure-control integration brief and the UHV SEM card web page |

## Note
The Bronkhorst library on PyPI is `bronkhorst-propar`. The package named just `propar` is unrelated and
breaks `import propar`.

## Credits
Ideas were taken from these open-source projects:
[AutoFlow](https://github.com/EthanGYoung/AutoFlow),
[project-Anemoi](https://github.com/thithibaud/project-Anemoi),
[coldplasmas-unimib/flowcontroller](https://github.com/coldplasmas-unimib/flowcontroller).
