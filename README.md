# Flow controllers

<img src="flowapp/assets/logo.png" width="72" align="right" alt="logo">

Control software for Bronkhorst mass flow controllers (EL-FLOW Prestige, propar over RS232/USB) on the
UHV SEM: chamber pressures and valves from the microscope's vacuum control card, gas-safety rules that link
the two, and a **test mode** that simulates the instruments and the vacuum system, so everything can be tried
without gas flowing.

## Setup (once per computer)
1. Install 64-bit Python 3.11 to 3.15 from python.org (3.13 recommended; keep the "py launcher" option
   checked). `run.bat` installs only ready-made packages, so no C compiler is needed; if the `.venv` was made
   with an unsupported Python, `run.bat` builds it again with a supported one.
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
- Test mode always uses a **simulated vacuum card and chamber** (never the real card): the simulated pressure
  follows the simulated flows (0.01 sccm into the main chamber ≈ 1e-3 Pa) and the valves you switch.
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
- **Graph (right):** the gas flow panel (solid = measured, dashed = setpoint, thick grey = total) and two
  lower panels you choose: **chamber pressure** (log scale, one line per gauge, red dashed p max line),
  **mixture** (% of the total flow) or **valve drive** (% of the MFC valve signal). Each panel has a header
  with its title and unit. Pick the time window, zoom with the mouse wheel (Live returns to following),
  hover to read values, export PNG or CSV (flows and pressures, saved in `exports/` by default).
- **Pressure strip** (above the graph): vacuum card status, the main gauges and whether gas is allowed now
  (and why not).
- **Instruments → Instrument report:** a read-only report of the connected instruments (identity,
  capacity, control mode, firmware, fluid slot, setpoint slope, extra sensors), saved in `logs/`.
- **View menu:** flows in % of full scale, panels, theme (follows Windows, or light/dark).
- **Log (bottom):** connections, setpoints, ramps, warnings and errors. No popup windows for
  communication errors.

## Vacuum tab (control card)
The app reads the microscope's vacuum control card (the same JSON-RPC interface its web page uses) about
5 times a second.
- **Diagram:** the layout of the card's web page, with chambers tinted by pressure (blue = UHV … red =
  atmosphere), every gauge with its live value, the MFC gas inlet with the live flows, the pumping path of
  the main chamber highlighted in green.
- **Valves:** green = open, red = closed, hatched = blocked by an interlock (the tooltip says why). Click a
  valve (or Open / Close in the list) to switch it; the app asks first and checks the valve register 2 s
  later. The web page's **interlocks are always on** and are checked again right before a valve is sent.
- **Pressures** of all six gauges (chamber FRG / IMG300 / HFIG, load-lock FRG, FEG gun / column), a 5-minute
  pressure graph, the card, chamber and gun status.
- **Advanced:** the card address and enabling control (per PC), the gas protections, and the web page's other
  commands: chamber vent / pump / off / clear, gun vent / pump + bake-out hours / off / clear / ion pumps
  cold start / beam on-off, UPS check, decontaminator, unlock FV1 / VV1, power save. Venting, bake-out,
  beam on and the ion pump cold start ask you to type a word to confirm.
- **Read-only until enabled:** on a real card, valves and commands stay locked until "Allow this app to
  control the card" is ticked in Advanced on that PC (after the lab check). Pressures, valve states and the
  UPS check work while locked.
- Without a card address on this PC there are no pressures and the vacuum protections are off (the strip says
  so).

## Safety
- **ALL TO 0** (red button, F12) cancels all ramps and sets every flow to 0. It is a software command,
  not a hardware interlock.
- **Closing the app or disconnecting sets every flow to 0.** If that cannot be confirmed (e.g. cable
  unplugged), the app asks before it closes.
- A max flow per channel can be set in **⚙**.
- **Gas protections** (need the vacuum card):
  - always on: chamber pressure above `p_max` (1 Pa) sets every flow to 0 and blocks gas until you
    acknowledge the trip; no pressure data for 2 s while gas flows sets every flow to 0;
  - on by default, each can be switched off with an extra confirmation until you disconnect (Advanced, or
    the question that appears when gas is refused): every flow to 0 before venting; every flow to 0 when
    the pumping path of the main chamber closes; more gas is refused while the main chamber is not pumped
    (pumping path closed, or above 1e-2 Pa before gas starts); an extra question before switching a valve
    while gas flows.
  - Lowering a flow is always allowed.

## Lab check (first run on the real instruments)
1. `git pull`, then `run.bat` (installs the new packages, creates the desktop shortcut).
2. Start screen → **Connect to the instruments**. Check the number of cards, gases and capacities.
3. **Instruments → Instrument report**, copy it and keep it.
4. **Identify** each MFC and name it in **⚙**.
5. With the gas supply in a safe state: a small setpoint on each MFC, then **ALL TO 0**, then close the app
   and check that the flows are 0.
6. A ramp on one MFC; unplug and replug the USB cable (status turns red, then recovers).

If the app does not open, run `run.bat --console` and send the text from the window.

### Vacuum card check (lab PC)
1. `run.bat --card-probe 192.168.x.x` (the address of the card's web page) and send me the output. It sends
   read-only requests only and shows the raw replies and the latency.
2. Vacuum → Advanced: enter the card address, Save. Connect the instruments; the Vacuum tab is read-only.
   Compare the pressures and the valve states with the card's web page.
3. Check `pump_path` in `config/card.json` (the valves that must be open to pump the main chamber while gas
   flows; now V16, V17, V04, FV1).
4. Only then tick "Allow this app to control the card" (type ENABLE) and switch one harmless valve of your
   choice; watch it on the web page too.

## Tools (console)
- `run.bat --probe [--full]` or `python -m flowapp --probe [--full] [COM9] [--sim]`: list the instruments
  (read-only; `--full` saves the report in `logs/`).
- `python -m flowapp --monitor [COM9] [--sim]`: live values in the console.
- `run.bat --card-probe [ADDRESS]` or `python -m flowapp --card-probe [ADDRESS] [--sim]`: read the vacuum card
  once (read-only): decoded values, raw reply, latency.
- `python -m flowapp.core.http_mock --port 8080`: the simulated card over HTTP on this PC (use
  `127.0.0.1:8080` as the card address to try the real connection path).

## Configuration
- `config/settings.json`: shared defaults (port `auto`, poll rate, graph history). Synced through git.
- `config/local.json`: settings for this computer only, e.g. `{"port": "COM9"}`. Not synced.
- `config/channels.json`: name, gas, colour, max flow and step per instrument serial number.
- `config/simulator.json`: the instruments simulated in test mode.
- `config/card.json`: the vacuum card settings shared by all PCs (poll rate, `p_max_pa`, `stale_s`,
  `pumped_below_pa`, `pump_path`, graph gauges). The card address and enabling control are per PC, in
  `config/local.json` as `card_address` / `card_control_enabled` (set them in Vacuum → Advanced).
- Window layout, theme and view options are remembered per computer (Windows registry).

## Tests
`.venv\Scripts\python -m pytest` runs on the simulator, a fake propar and the simulated card (also over HTTP on
localhost), never on hardware or the real card (the UI tests run offscreen).

## Project layout
| Path | Content |
|---|---|
| `run.bat` | The launcher: setup/update, then the app |
| `main.py` | Start from code (same as `python -m flowapp`) |
| `flowapp/core/` | Instrument layer: Bronkhorst driver, simulator, background worker, ramps, checks, report |
| `flowapp/core/vacuum.py`, `card*.py`, `safety.py` | Vacuum card: model and interlocks, client with the command guard, simulated card, worker, gas safety |
| `flowapp/ui/` | PySide6 + pyqtgraph user interface |
| `flowapp/assets/` | Logo (`logo.svg` is the source; `tools/make_icon.py` renders `logo.png` and `logo.ico`) |
| `flowapp/config.py`, `flowapp/desktop.py` | Settings; desktop shortcut and taskbar icon |
| `tests/` | pytest suite |
| `docs/` | Pressure-control integration brief and the UHV SEM card web page (the protocol reference) |

## Note
The Bronkhorst library on PyPI is `bronkhorst-propar`. The package named just `propar` is unrelated and
breaks `import propar`.

## Credits
Ideas were taken from these open-source projects:
[AutoFlow](https://github.com/EthanGYoung/AutoFlow),
[project-Anemoi](https://github.com/thithibaud/project-Anemoi),
[coldplasmas-unimib/flowcontroller](https://github.com/coldplasmas-unimib/flowcontroller).
