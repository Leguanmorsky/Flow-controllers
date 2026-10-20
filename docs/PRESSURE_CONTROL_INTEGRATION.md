# Integration brief: chamber pressure feedback for the gas-flow app

This brief is for the coding agent working in this repository. It explains how
to get live chamber pressure from the UHV SEM control card and how to use it
for closed-loop pressure control (a PID) in this gas-flow application.

Read the whole brief before changing code. **Section 3 (Safety) is mandatory.**

---

## 1. Goal

The gas-flow app currently sets gas flow (MFC setpoint) open-loop. Add:

1. **Live pressure readout.** Poll the control card in the background and show
   the chamber pressure in the app.
2. **Pressure-regulation mode.** The user enters a target pressure [Pa]. A PID
   adjusts the flow setpoint to hold it.
3. **Safety logic.** If the pressure trips or the data goes stale, the flow goes
   to zero (details in section 3).

Manual flow control must keep working exactly as before when regulation is off.

---

## 2. How the pressure data is obtained

### 2.1 The card

The lab PC contains a control card for the vacuum system. It runs an embedded
HTTP server that serves the lab web page (`indexsvg.html`) and a **JSON-RPC 2.0
endpoint**:

```
POST http://<card-ip>/jsonrpc
Content-Type: application/json-rpc
```

`<card-ip>` is whatever the browser address bar shows when the lab web page is
open. The endpoint is relative to the page, so `http://X/indexsvg.html` means
`http://X/jsonrpc`. Make the address configurable and don't hard-code it.

The web page is only a front end. **Do not scrape HTML.** Send the JSON-RPC
requests directly.

### 2.2 Read commands (the only ones this app may send)

| method | params | meaning |
|---|---|---|
| `chbr.prs?` | `{"value": 0}` | chamber FRG/AIB (full-range gauge) [Pa] |
| `chbr.prs?` | `{"value": 1}` | chamber IMG300 (inverted magnetron, UHV) [Pa] |
| `chbr.prs?` | `{"value": 2}` | chamber HFIG (hot-filament ion gauge) [Pa] |
| `chbr.prs?` | `{"value": 3}` | load-lock FRG [Pa] |
| `sem.prs?`  | `{"value": 0}` | FEG gun [Pa] |
| `sem.prs?`  | `{"value": 1}` | FEG column [Pa] |
| `chbr.stat?` / `sem.stat?` | none | subsystem status (optional) |
| `tsc.wrd`   | `["40", "", "4"]` | valve status register read (see 2.4) |

Naming: `chbr` = chamber subsystem, `sem` = electron-gun subsystem,
`prs` = pressure, a trailing `?` = query.

### 2.3 Request and reply format

Several calls can go into one POST as a JSON array (a batch). The web page does
this, and it's the fastest way to read everything:

```json
[
  {"jsonrpc":"2.0","method":"chbr.prs?","params":{"value":0},"id":1},
  {"jsonrpc":"2.0","method":"chbr.prs?","params":{"value":1},"id":2}
]
```

Each reply's `result` can take **either** of these forms, so handle both:

- a plain number: `"result": 2.1e-06`
- an object: `"result": {"value": 2.1e-06, ...}`

`"result": null` (or no value) means the gauge is off or outside its range.
IMG300 and HFIG return null at higher pressures, and that's normal.
An `"error"` key means the call failed.

Implementation notes:
- Match batch replies to requests **by `id`**, not by position.
- Keep one persistent HTTP connection and set `TCP_NODELAY`. Without it each
  request takes about 40 ms longer because of Nagle's algorithm and delayed ACKs.
- The embedded server may close keep-alive connections. On a connection error,
  reconnect once and retry.
- Use a short timeout (about 1 s). Never block the UI thread on this request.
- Poll at 5–20 Hz. The card is a small embedded server, and the web page itself
  polls at 2 Hz.

### 2.4 Valve register (optional interlock input)

`tsc.wrd ["40","","4"]` returns `{"status":"tscOK","rdata":"<hex>"}`.
Bit *n* set means the valve is open:

```
bit 0 FV1   bit 1 VV1   bit 4 V04   bit 5 V05   bit 6 V06   bit 7 V07
bit 8 V08   bit 9 V09   bit 10 V10  bit 11 V11  bit 12 V12  bit 13 V13
bit 14 V14  bit 15 V15  bit 16 V16  bit 17 V17  bit 18 V18  bit 19 V19
bit 31 = valve supply on 24 V (power-save off)
```

The web page labels some of these: V04 SVL, V05 airlock vent, V06 airlock pump,
V09 vvl tmp2, V10 fvl tmp2, V13 svl tmp2, V14 asv, V15 lsv, V16 ssv, V17 psv,
V18 bb, V19 isv. **Ask the user which valve is the gas inlet and which one
connects the chamber to its pump** before writing any interlock that depends
on them.

---

## 3. Safety (mandatory)

The same endpoint also **opens and closes valves, vents the chamber, starts
bake-out and switches the electron beam**. Examples: `tsc.wrd` with address 32
(open valve) or 36 (close valve), `chbr.vent`, `chbr.pump`, `sem.vent`,
`sem.pump`, `sem.beam`, `sem.ions`.

Rules:
1. **This app is read-only towards the card.** Enforce a whitelist in code:
   `chbr.prs?`, `sem.prs?`, `chbr.stat?`, `sem.stat?`, and `tsc.wrd` **only**
   with params exactly `["40","","4"]`. Any other request must raise an error
   before it is sent. Keep this guard even in test code.
2. Never send a request to the real card to test something "quickly". Use the
   mock (section 6).
3. In regulation mode, set the flow to **0** when any of these happens:
   - pressure > the trip limit (`p_max`, user-configurable, default 1 Pa).
     Then leave regulation mode and require the user to re-arm it.
   - no valid reading for longer than `stale_s` (default 1 s): card unreachable,
     timeout, null value, or a value ≤ 0 or NaN. Resume automatically once
     valid data returns, without resetting the integrator.
   - the app closes, regulation is switched off, or an exception occurs in the
     control loop.
4. Clamp the flow output to `[q_min, q_max]`. Default `q_max` should be modest,
   and the user sets it.
5. Optional, once the user confirms which valves matter: refuse to regulate if
   the chamber's pumping valve is closed.

---

## 4. Control algorithm

Pressure spans decades, and at steady state `p ≈ p_base + Q / S_pump`.
Pressure is roughly **proportional to flow**, so control in log space:

```
y = log10(p_measured)       r = log10(p_setpoint)
e = clip(r - y, -0.5, +0.5)        # max ±0.5 decade, prevents slamming the MFC
                                   # to max when starting from base vacuum
u = I + Kp*e + Kd*D                # u = log10(flow)
flow = 10**clip(u, log10(q_min), log10(q_max))
```

- Integrator: `I += Ki*e*dt`, **only if** the output is not saturated in the
  direction of the error (anti-windup).
- Initialise `I = log10(q_start)` for a bumpless start. A good `q_start` is the
  current manual flow when the user switches to regulation.
- D term: compute on the measurement, not the error, with a low-pass filter
  (τ about 0.3 s). Default Kd = 0.
- Defaults: `Kp = 0.6`, `Ki = 1.5 /s`, `Kd = 0`, control rate 10 Hz.
  These were tuned on a simulated chamber with a time constant of 0.5 s.
  A slower real chamber needs a lower Ki (roughly Ki ∝ 1/τ). Expose all gains
  in the config or UI.
- Pick the gauge from config. The default is `chamber_FRG` because it covers the
  whole range. IMG300 and HFIG are more accurate in UHV but return null at
  higher pressures.
- If the MFC has a deadband or minimum controllable flow, set `q_min` to it.

On the simulator this goes from 2e-6 Pa to 5e-3 Pa in about 1.5 s with no
overshoot. The real system has not been tested yet.

---

## 5. Reference implementation (provided, tested on the simulator)

Ask the user for the folder `uhv_pressure/` (from `uhv_pressure.zip`). It contains:

- `uhv_pressure.py`
  - `CardClient` handles the persistent connection, the batch calls and the
    whitelist guard.
  - `PressureMonitor` is a background thread with `.latest(name)` that returns
    `(value_Pa, age_s)`.
  - It also has a CLI with `--probe`.
- `pid_pressure.py`: `LogPID` (the algorithm above) plus a reference control
  loop with all the safety handling in section 3. Its `GasFlow.set_flow()` is
  the stub that this app should replace.
- `mock_card.py`: a simulator of the card and chamber (`python mock_card.py
  --port 8080`). It adds one method that doesn't exist on the real card,
  `mock.flow {"value": sccm}`, which lets the simulated chamber "see" the flow.

Prefer importing or vendoring these modules over rewriting them. If the app's
architecture needs changes (Qt signals, asyncio, etc.), adapt the wrapper but
keep the protocol handling, whitelist and PID logic the same.

---

## 6. Implementation steps

1. **Explore this repository first.** Find:
   - how the MFC setpoint is set (driver, serial or Modbus call, units, range)
   - the UI framework and its threading model
   - where configuration lives
   - whether there is an existing poll loop or timer

   Summarise this to the user before writing code.
2. **Ask the user** about anything you can't find: card IP, working pressure
   range, which gauge to use, MFC full scale and units, gas-inlet and
   pump-valve names.
3. Add the pressure reader as a **background worker** that never runs on the
   UI thread, and display the selected gauge (plus optionally all six) in the UI.
4. Add a regulation mode with:
   - setpoint [Pa], gauge selection, p_max, q_min/q_max and gains
   - Start/Stop controls
   - a clear status indicator: off / running / stale / tripped
5. Route the PID output through the **existing** MFC setpoint function, so the
   existing limits and handling still apply.
6. Log time, setpoint, pressure, flow and state to CSV.
7. **Test against `mock_card.py`**:
   - step the setpoint up and down a decade
   - kill the mock mid-run: flow must go to 0, show "stale" and resume when
     the mock comes back
   - force p > p_max: the loop must trip and stop
   - check that the whitelist blocks a write such as `chbr.vent`
8. For the first run on the real card, tell the user to run
   `python uhv_pressure.py <card-address> --probe`. It prints the raw replies
   (confirming the reply format) and the latency. Only then enable regulation,
   with a low `q_max` and `p_max`.

---

## 7. Known unknowns

- The exact reply format from the real card hasn't been observed. It was inferred
  from the web page's JavaScript, which accepts a number or `{value}`.
- The card may handle simultaneous clients (the web page plus this app) slowly.
  If latency gets worse while the web page's plot is running, poll less often
  or close the plot.
- The real chamber's response time is unknown, so the gains will need tuning in the lab.
- Which valve is the gas inlet or pump path isn't known yet. Ask the user.
