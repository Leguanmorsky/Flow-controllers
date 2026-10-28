# Flow controllers: instructions for AI sessions

This app controls Bronkhorst MFCs (gas into a UHV SEM chamber) and the microscope's vacuum control card
(pressures, valves, vent, gun, beam).
- **Read `docs/APP_GUIDE.md` first:** architecture, threading, data, safety, and how to merge other apps
  (e.g. the energy-spectrum app) into this one.
- `README.md` is the user manual.

## Hard rules (from the user; do not break them)
- **Never send anything to the real vacuum card to test something.** Use `SimCard` / `flowapp.core.http_mock`.
- **Card requests:**
  - Every card request goes through `CardClient`; its catalog guard (`card.classify()`) checks it before
    sending.
  - Do not bypass or widen the guard. New card commands need the user's explicit approval and tests.
- **Card control:**
  - Control of a real card stays locked until the user enables it on that PC (`card_control_enabled` in
    `config/local.json`).
  - Never enable it in code; never commit `config/local.json`.
- **Valve interlocks** (`vacuum.interlock_reason`) are always on, with no bypass.
- **Serious commands are the user's decision, each time:** vent, bake-out, beam on/off, ion pump cold
  start, valves. Keep the confirmation dialogs; never automate these.
- **Gas:**
  - Flows only change through `InstrumentBridge.set_setpoint` / `start_ramp`, so the gas checks run.
  - Every exit path sets every flow to 0. ALL TO 0 (F12) must always work.
  - Never change MFC fluid, capacity or calibration. Control modes only within `{0, 18}`.
- **Test mode:**
  - Test mode (`--sim` / start page) never touches real hardware or the real card, and its data is always
    marked as TEST.
  - Every feature must also work in test mode, with a simulator.
- **Tests:** tests use only simulators, the fake propar and the localhost mock (offscreen Qt). Keep
  `.venv\Scripts\python -m pytest` green.
- **Git:** work on `main`, no new branches. Commit and push at the end of a block or when asked. Don't
  commit the user's `config/channels.json` edits unless asked.
- **Dependencies:** exact pins with Windows wheels for Python 3.11–3.15 (`run.bat` installs wheels only).
  `.bat` files are CRLF.
- **Workflow:** plan bigger changes with the user first; ask about hardware facts you cannot find in the
  code.
