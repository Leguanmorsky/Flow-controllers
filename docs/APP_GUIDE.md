# Flow controllers: guide for AI sessions (architecture, safety, integration)

This guide is for an AI coding session (e.g. Claude Code) that works on this app or **merges it with another
app, such as the one that measures energy spectra of materials in the UHV SEM**. It explains:
- what the app does and how it is built;
- what must never be touched or sent;
- how to extend it safely.

Read it completely before changing code. The user-facing manual is `README.md`. The hard rules are
repeated in `CLAUDE.md`.

---

## 1. What the app is

A PySide6 desktop app (Windows) for a **UHV scanning electron microscope** with a gas inlet:
- It controls **Bronkhorst EL-FLOW Prestige mass flow controllers (MFCs)** over propar (RS232/USB):
  - 3 instruments, propar addresses 4 / 5 / 6, gases C2H4 / CO / H2, 1 sccm full scale each;
  - serials M24207457D / B / A.
  - The gas goes into the **main chamber** through a manual valve.
- It reads (and, once enabled, controls) the microscope's **vacuum control card**. This is a JSON-RPC 2.0
  endpoint on the card's embedded web server, the same one its web page `docs/card_webpage/indexsvg.html`
  uses. It provides:
  - six pressure gauges;
  - the valve register and valves;
  - chamber, gun and beam commands.
- It links the two with **gas-safety rules**: flows go to 0 when the chamber pressure trips, the
  pressure data goes stale, the pumping path closes, before venting, and so on.
- It has a permanent **test mode** that simulates the MFCs *and* the vacuum system. It must keep working
  for every feature, on every PC.

**Users and places:**
- The user develops on a home PC, which now also has the MFCs (COM7) but **cannot reach the card**.
- The **lab PC** reaches the card; the MFCs used to be on COM9 there.
- The code is synced through GitHub (`main` branch).
- Real-hardware checks happen in the lab, done by the user.

**State (2026-10-28):** Blocks 1–3 are done:
- MFC core and UI, test mode, start screen, logo, desktop shortcut;
- vacuum card client, simulated card, Flows and Vacuum tabs, gas safety.

**Next planned:**
- closed-loop pressure regulation (log-space PID; spec in `docs/PRESSURE_CONTROL_INTEGRATION.md` §4);
- then programs / file logging / totalizer, presets.

**Not yet verified on the real card:** the reply formats, the latency, and `pump_path`.

---

## 2. Running

- **`run.bat`** is the only launcher. The desktop shortcut starts it too.
  - It creates and updates `.venv` from `requirements.txt` (ready-made wheels only, 64-bit Python 3.11–3.15;
    it rebuilds a `.venv` made from an unsupported Python).
  - It then starts `pythonw -m flowapp` without a console.
  - Options:
    - `--sim`: straight into test mode;
    - `COM9`: connect straight away;
    - `--console`: keep the console open with the log;
    - `--probe [--full]`: read-only instrument report;
    - `--card-probe [ADDRESS]`: read-only card probe;
    - `--monitor`.
- From code: `python main.py` or `python -m flowapp` (same options). VS Code launch entries exist.
- **Tests:** `.venv\Scripts\python -m pytest`.
  - 182 tests, about 30 s; the UI tests run offscreen (pytest-qt).
  - They use only simulators, a fake propar and a localhost HTTP mock of the card.
- `python -m flowapp.core.http_mock --port 8080` serves the simulated card over real HTTP. The app can
  then use `127.0.0.1:8080` as its card address.

---

## 3. Architecture

```
flowapp/
  __main__.py        CLI + GUI entry (argparse; probe, monitor, card-probe, GUI)
  config.py          Settings, ChannelConfig, CardConfig; config/*.json loading; save_local()
  desktop.py         desktop shortcut + taskbar identity
  core/              NO Qt here. Hardware, simulators, threads, safety logic
    dde.py             Bronkhorst parameter numbers (DDE), control modes
    channel.py         ChannelInfo (static), ChannelState (one poll; t = time.time())
    ports.py           COM port listing / auto-detect (sends propar node scans!)
    bronkhorst.py      BronkhorstBus: open/read_states/set_setpoint/zero_all/set_control_mode/...
    simulator.py       SimBus: same interface, simulated MFCs + faults
    worker.py          InstrumentWorker thread: only thread that touches the MFC bus
    ramp.py            RampManager (runs on the instrument worker thread)
    watch.py           SetpointWatch (flow not reaching setpoint)
    report.py          instrument report (read-only)
    vacuum.py          vacuum model: GAUGES, VALVES (register bits), interlock_reason(), VacuumState
    card.py            CardClient + HttpTransport + the COMMAND CATALOG GUARD (classify())
    card_sim.py        SimCard: simulated card + vacuum physics (same post() interface as HttpTransport)
    http_mock.py       SimCard over HTTP on localhost (tests, trying the real path)
    card_worker.py     CardWorker thread: only thread that talks to the card
    safety.py          GasSupervisor: gas rules (pure logic, thread-safe)
  ui/                PySide6
    app.py             run_gui(): QApplication, theme, excepthook, log file, console-close -> zero flows
    main_window.py     MainWindow: start page / tabs (Flows | Vacuum), menus, wiring, confirmations
    bridge.py          InstrumentBridge (QObject): MFC worker <-> UI, gas_guard hook, safety_zero()
    card_bridge.py     CardBridge (QObject): card worker + GasSupervisor <-> UI, card commands
    start_page.py      "Connect to the instruments" / "Test mode"
    connection_bar.py  status + Disconnect + ALL TO 0 (in the tab row)
    channel_card.py    one MFC card (setpoint, slider, ramp, banners)
    graph.py           FlowGraph: flow panel + 2 switchable panels (pressure/mixture/valve), CSV/PNG
    history.py         SeriesBuffer (flows), PressureBuffer (pressures): numpy ring buffers
    vacuum_view.py     Vacuum tab: DiagramView (QGraphicsScene), side panel, Advanced window
    vacuum_widgets.py  PressureStrip (above the flow graph)
    dialogs.py         all questions to the user (tests monkeypatch these functions)
    theme.py, units.py
config/
  settings.json      shared defaults (port, poll_hz, history)
  local.json         THIS PC only, not in git: port, card_address, card_control_enabled
  channels.json      user names/colours/max flow per MFC serial (edited in the app; user data)
  simulator.json     instruments simulated in test mode (matches the real MFCs)
  card.json          vacuum card settings shared by all PCs (poll, p_max, stale_s, pump_path, ...)
docs/                integration brief, the card's web page (the protocol reference), this guide
tests/               pytest + pytest-qt
```

### Threading model (keep it)
- **The UI thread never does I/O.**
- `InstrumentWorker` is the only thread that uses the MFC bus. `CardWorker` is the only thread that uses
  the card. Commands go through `worker.submit(func, *args)`, which returns a `concurrent.futures.Future`.
- Worker callbacks run on the worker thread. The bridges turn them into Qt signals delivered to the UI
  thread.
- The safety reaction (`GasSupervisor.on_state`) runs on the card worker thread **directly**, without
  waiting for the UI. It calls `InstrumentBridge.safety_zero()`, which is thread-safe.
- Polling rates: MFCs `poll_hz` (4 Hz default), card 5 Hz plus status 1 Hz.
- All timestamps are `time.time()` (Unix seconds); use the same for anything you add.

### Data you can use
- **`InstrumentBridge.states_updated(list[ChannelState])`**: every MFC poll. `measure` / `setpoint` are in
  the capacity unit (sccm); `valve_pct`, `temperature`, `ok`, `error` are also there.
- **`InstrumentBridge.channels`** (`ChannelInfo`: address, serial, fluid, capacity, unit) and `name(address)`
  (the user's alias).
- **`CardBridge.vacuum_updated(VacuumState | None)`**: every card poll.
  - `pressures` is a dict of gauge key → Pa, or None. The keys are `chamber_frg`, `chamber_img`,
    `chamber_hfig`, `loadlock_frg`, `gun`, `column`.
  - `valves` is a dict of name → open; also `supply_24v`, `chamber_status`, `gun_status` (raw reply,
    format undocumented), `ok`, `stale`, `age_s`.
- **`CardBridge.latest`**: the newest VacuumState. **`CardBridge.gas_status()`** returns
  `GasStatus(allowed, reason, rule, level)`.
- **Events** for the log: `InstrumentBridge.event` and `CardBridge.event`, each `(level, message)`.
  `MainWindow.log_event(level, message)` writes to the log panel, stdout and `logs/last_run.log`
  (under pythonw).
- **Session:**
  - `InstrumentBridge.simulated` is True in test mode;
  - `CardBridge.mode` is `"sim"`, `"real"` or `"none"`; `CardBridge.control_allowed` tells whether
    control is enabled.

---

## 4. Safety: what must never be done

This app can put gas into a UHV chamber and can switch valves, vent, start bake-outs and switch the
electron beam on a real microscope. **These rules come from the user and are not negotiable**:

1. **Never send anything to the real vacuum card to "test" something**, from tests, scripts or the CLI.
   Use `SimCard` or `http_mock`. The only real-card tool is the read-only `--card-probe`, run by the user.
2. **Every card request goes through `CardClient`**, and every request is checked by `card.classify()`
   against a fixed catalog **before anything is sent**:
   - Do not bypass it: no raw `requests`/`http.client` calls to the card, no second client.
   - Do not widen it, and do not add raw `tsc.wrd` or `adc.get`.
   - A new card command (even a read-only one such as an emission-current or ADC read) needs **the user's
     explicit approval**, an exact entry in the catalog, and tests for the guard.
   - Valves V07, V08, V11, V12 and V18 are not in use and are refused.
3. **Card control is locked on a real card** until the user enables it on that PC (Vacuum → Advanced,
   typed ENABLE, stored as `card_control_enabled` in `config/local.json`):
   - Never enable it in code, never default it to true, never commit a `local.json`.
   - While it is locked, only read commands are sent (pressures, status, valve register, UPS).
4. **The web page's valve interlocks are always on**, with no override, in `vacuum.interlock_reason()`:
   - They are checked in the UI, and again in `CardClient.open_valve()` on a freshly read register,
     right before sending.
   - Do not remove them or add a bypass.
5. **Serious commands need the user's confirmation in the UI:**
   - vent, gun bake-out, beam on and ion pump cold start need a typed word (`dialogs.confirm_typed`);
   - valves and the other commands need a confirm;
   - switching a valve while gas flows needs an extra confirm.
   - Never automate them, and never fire them from a timer, a script or another app's workflow without
     the user deciding each time.
   - In particular **`sem.beam`** (beam on/off) belongs to the user. A spectrum app must not switch the
     beam by itself.
6. **Gas safety must keep working.** The rules are in `GasSupervisor` and are wired through
   `InstrumentBridge.gas_guard` and `safety_zero`.
   - Always on, once a card is read:
     - chamber pressure above `p_max_pa` (1 Pa) sets every flow to 0 and latches until the user
       acknowledges;
     - no pressure data for `stale_s` (2 s) while gas flows sets every flow to 0.
   - Overridable rules, one confirmation each, reset on disconnect: `vent_zero`, `path_zero`,
     `block_unpumped`, `confirm_valves`.
   - Every new way of raising a flow must go through `InstrumentBridge.set_setpoint` / `start_ramp`,
     which run `check_gas`. **Lowering a flow is always allowed.**
   - Never write setpoints to the bus directly from new code.
7. **Closing the app, disconnecting, or closing the console window sets every flow to 0**
   (`release_instruments`, `emergency_zero`). Keep that on every exit path you add.
   `ALL TO 0` (F12) must keep working from anywhere.
8. **MFC writes:**
   - Only setpoints, the control mode within `BUS_SETPOINT_MODES {0, 18}` (enforced in the bus), and
     wink (identify).
   - Never change the fluid (DDE 24), the capacity, the calibration or other instrument settings.
9. **Test mode is sacred.**
   - A `--sim` session can never open real ports.
   - Test mode always uses `SimCard`, never the real card.
   - Simulated data is always marked: the orange TEST MODE strip, `[TEST MODE]` in the title, and
     `TEST_` export prefixes.
   - Every new feature must work in test mode, with a simulator for any new device.
10. **Tests never touch hardware**, real COM ports or the real card. UI tests use the fixtures in
    `tests/test_ui.py`:
    - the card config is replaced by an empty `CardConfig()`;
    - `local.json` writes go to `tmp_path`;
    - the dialogs are monkeypatched so that an unexpected dialog raises.

---

## 5. Conventions

- **Git:**
  - Work on `main` (the user said: no new branches).
  - Commit and push at the end of a block of work or when the user asks.
  - End commit messages with the `Co-Authored-By:` trailer the session is given.
  - Never commit `config/local.json`. Don't commit the user's edits of `config/channels.json` unless
    asked.
- **Workflow:** plan a block with the user before coding it. The user answers architecture questions;
  ask about what you can't find in the code (device addresses, which valve matters, ranges).
- **Code style:** match the surrounding code.
  - Short module docstrings that say *why*; few comments; 120-column lines; f-strings.
  - Dataclasses for data; no Qt in `core/`.
  - User-visible text in plain English sentences.
  - Errors go to the log panel; there are no popups for communication errors.
- **Dependencies:** pin exact versions, and only versions with **Windows wheels for Python 3.11–3.15**
  (run.bat installs with `--only-binary=:all:`; the lab PC has no compiler). Use an environment marker
  when one pin can't cover all of them (see numpy in `requirements.txt`).
- **Files:** `.bat` files must have CRLF line endings (`.gitattributes` enforces it). `README.md` is the
  user manual: keep it current.
- **The home PC's shell (for an agent working there):**
  - Run batch files with `env -u NoDefaultCurrentDirectoryInExePath cmd //c run.bat ...`.
  - Bash heredocs collapse `\\`, so write code with an editor tool instead.
  - Offscreen Qt screenshots need `QT_QPA_FONTDIR=C:/Windows/Fonts`.

---

## 6. Merging with the energy-spectrum app: recommended approach

**Goal:** one desktop app for the UHV SEM, in which spectra are measured while the gas flows and the vacuum
are visible, controlled and recorded.

1. **One process, one window.**
   - Add the spectrum app as a new tab ("Spectra") in `MainWindow.tabs`, next to Flows and Vacuum.
     Don't run two apps side by side against the same hardware.
   - Put its device code in its own package, e.g. `flowapp/spectra/core/` (no Qt) and
     `flowapp/spectra/ui/`, or keep it as a separate package imported here.
   - Follow the same split: a device class, a **simulated device** with the same interface, and a worker
     thread that is the only one touching the spectrometer.
   - Add a bridge QObject that turns worker callbacks into signals.
2. **Test mode covers the spectrometer too.**
   - When `InstrumentBridge.simulated` is true (start page "Test mode" or `--sim`), use the simulated
     spectrometer.
   - Its output can depend on the simulated gas and pressure, for example peaks scaling with the flows.
3. **Don't open the spectrometer on a port the MFC auto-detect scans.**
   - `core/ports.find_port()` sends propar node scans to every non-Bluetooth COM port (COM9 first).
   - If the spectrometer uses a serial port, either give the MFCs a fixed port (`config/local.json`
     `{"port": "COM9"}`) or add an exclusion list to `candidate_ports()` (ask the user).
   - Never let both apps open the same port.
4. **Use the existing data; don't open new connections.**
   - For spectrum metadata (gas flows and pressures during a spectrum), subscribe to `states_updated` and
     `vacuum_updated`, or read `InstrumentBridge.worker.latest` / `CardBridge.latest`.
   - Store, with each spectrum:
     - the time range (`time.time()`);
     - flows per gas (name, sccm);
     - chamber pressures (all gauges);
     - the valve states;
     - the gas status;
     - whether it was test mode.
   - The card is a small embedded server. Do not start a second card client or poll it from the spectrum
     code.
5. **Anything that changes hardware goes through the existing bridges, with the existing confirmations.**
   - Gas: `InstrumentBridge.set_setpoint` / `start_ramp` (wrapped by `MainWindow._request_setpoint` /
     `_request_ramp`, which handle a refused setpoint).
   - Valves and commands: `MainWindow._valve_requested` / `_card_command`. These confirm, then call
     `CardBridge`.
   - Automated sequences (e.g. "measure a spectrum at each of these flows") belong to the planned program
     engine:
     - they step setpoints through `set_setpoint`;
     - they must stop and zero on ALL TO 0, a trip, stale data or close;
     - they must never switch valves, vent or switch the beam without a per-step user decision.
6. **Shared infrastructure:**
   - `MainWindow.log_event` for logging;
   - `theme.py` for colours (light/dark; `Theme.series` for data, `Theme.gauges` for pressures);
   - pyqtgraph for plots (with the same `DateAxisItem` time axis if you plot against time);
   - `exports/` for exported files (the `TEST_` prefix in test mode);
   - QSettings ("FlowControllers", "FlowApp") for per-PC view state.
7. **Closing:**
   - The spectrometer worker must stop cleanly in `MainWindow.closeEvent` / `_on_disconnected`.
   - It must not block zeroing the flows: zero first, then stop the other devices.
8. **Tests:**
   - Add tests for the spectrum core (on its simulator) and pytest-qt tests for the new tab, reusing the
     `window` fixture pattern.
   - Keep the whole suite green and offscreen.

**Ask the user before deciding:**
- the spectrometer's interface (port or protocol, vendor SDK, 32/64-bit, Python wheel availability for
  3.11–3.15);
- whether it needs the beam, or anything from the card that isn't in the catalog;
- which metadata to store and in what file format;
- where the Spectra tab goes and what it shows next to the gas and vacuum data.

---

## 7. Open items

- **Lab checks not done yet:**
  - `run.bat --card-probe <address>` output (real reply formats and latency);
  - comparing the read-only Vacuum tab with the web page;
  - only then enabling control.
- **`pump_path` in `config/card.json` is `V16, V17, V04, FV1`**, as the user chose. The web page drawing
  suggests V17 joins the main and prep chambers directly, so V16 may not belong in the path. Confirm with
  the user at the lab.
- **Chamber and gun status reply formats are unknown.** They are shown raw.
- **Next block:** pressure regulation (LogPID through `set_setpoint`, its own trip/stale handling, CSV log),
  as described in `docs/PRESSURE_CONTROL_INTEGRATION.md`.
