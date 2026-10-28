"""Client for the UHV SEM control card (JSON-RPC 2.0 over HTTP, as used by the card's web page).

Every request is checked against a fixed catalog *before anything is sent*:
- read commands (pressures, status, valve register, UPS) are always allowed;
- control commands (valves, vent/pump, gun, beam, decontaminator, unlock, power save) need
  allow_control=True, which the app only sets for the simulated card or after the user enabled
  control on that PC;
- anything else raises CardCommandError: an unknown method, other tsc.wrd addresses or data,
  valves the web page does not operate.
Opening a valve also checks the web page's interlock rules on a freshly read register.
"""

import http.client
import json
import socket
import time
from dataclasses import dataclass
from urllib.parse import urlsplit

from .vacuum import GAUGES, VALVE_BY_NAME, VacuumState, interlock_reason, parse_register, valid_pressure

READ = "read"
CONTROL = "control"


class CardError(Exception):
    """The card could not be reached or gave an unusable reply."""


class CardCommandError(CardError):
    """The request is not in the catalog; nothing was sent."""


class CardLocked(CardCommandError):
    """A control command while control is locked on this PC; nothing was sent."""


class InterlockError(CardCommandError):
    """Opening this valve is blocked by an interlock rule; nothing was sent."""


class CardReplyError(CardError):
    """The card answered the request with an error."""


@dataclass(frozen=True)
class Request:
    method: str
    params: object = None
    text: str = ""      # what it does, for the log


def _tsc(addr, wdata, rlen, text):
    return Request("tsc.wrd", [addr, wdata, rlen], text)


def _valve_data(name):
    return f"{0x80000000 | 1 << VALVE_BY_NAME[name].bit:08x}"


# --- the catalog ------------------------------------------------------------------------------

def pressure(key):
    gauge = next(g for g in GAUGES if g.key == key)
    return Request(gauge.method, {"value": gauge.index}, f"read {gauge.label}")


def chamber_status():
    return Request("chbr.stat?", None, "read chamber status")


def gun_status():
    return Request("sem.stat?", None, "read gun status")


def valve_register():
    return _tsc("40", "", "4", "read valve register")


def ups_state():
    return _tsc("64", "", "2", "read UPS state")


def valve_open(name):
    return _tsc("32", _valve_data(name), "4", f"open {name}")


def valve_close(name):
    return _tsc("36", _valve_data(name), "4", f"close {name}")


def power_save():
    return _tsc("36", "80000000", "4", "valve supply back to 12 V (power save)")


UNLOCK_ADDR = {"FV1": "128", "VV1": "132"}


def valve_unlock(name):
    return _tsc(UNLOCK_ADDR[name], "00ffffff", "4", f"unlock {name}")


def decontaminator(on):
    return _tsc("48" if on else "50", "0200", "2", f"decontaminator {'on' if on else 'off'}")


CHAMBER_COMMANDS = {"vent": "vent the chamber", "pump": "pump the chamber", "off": "chamber off",
                    "clear": "clear the chamber error"}
GUN_COMMANDS = {"vent": "vent the gun", "off": "gun off", "clear": "clear the gun error",
                "ions": "ion pumps cold start"}
MAX_BAKE_HOURS = 24.0


def chamber(command):
    return Request(f"chbr.{command}", None, CHAMBER_COMMANDS[command])


def gun(command):
    return Request(f"sem.{command}", None, GUN_COMMANDS[command])


def gun_pump(hours=0.0):
    text = f"pump the gun with {hours:g} h bake-out" if hours else "pump the gun (getter activation)"
    return Request("sem.pump", {"value": 3600.0 * float(hours)}, text)


def beam(on):
    return Request("sem.beam", {"value": bool(on)}, f"beam {'on' if on else 'off'}")


_READ_TSC = {("40", "", "4"), ("64", "", "2")}
_CONTROL_TSC = ({tuple(valve_open(n).params) for n in VALVE_BY_NAME}
                | {tuple(valve_close(n).params) for n in VALVE_BY_NAME}
                | {tuple(power_save().params), tuple(decontaminator(True).params),
                   tuple(decontaminator(False).params)}
                | {tuple(valve_unlock(n).params) for n in UNLOCK_ADDR})
_PRESSURE_INDEX = {"chbr.prs?": range(4), "sem.prs?": range(2)}


def classify(method, params):
    """READ or CONTROL for a request in the catalog; raises CardCommandError for anything else."""
    if method in _PRESSURE_INDEX:
        if (isinstance(params, dict) and set(params) == {"value"} and type(params["value"]) is int
                and params["value"] in _PRESSURE_INDEX[method]):
            return READ
    elif method in ("chbr.stat?", "sem.stat?"):
        if params is None:
            return READ
    elif method == "tsc.wrd":
        if isinstance(params, list) and len(params) == 3 and all(type(p) is str for p in params):
            if tuple(params) in _READ_TSC:
                return READ
            if tuple(params) in _CONTROL_TSC:
                return CONTROL
    elif method.startswith("chbr.") and method[5:] in CHAMBER_COMMANDS:
        if params is None:
            return CONTROL
    elif method.startswith("sem.") and method[4:] in GUN_COMMANDS:
        if params is None:
            return CONTROL
    elif method == "sem.pump":
        if (isinstance(params, dict) and set(params) == {"value"} and isinstance(params["value"], (int, float))
                and not isinstance(params["value"], bool) and 0 <= params["value"] <= MAX_BAKE_HOURS * 3600):
            return CONTROL
    elif method == "sem.beam":
        if isinstance(params, dict) and set(params) == {"value"} and isinstance(params["value"], bool):
            return CONTROL
    raise CardCommandError(f"Not allowed: {method} {json.dumps(params)} is not a known card command.")


# --- transport --------------------------------------------------------------------------------

def parse_address(address):
    """'10.0.0.5', '10.0.0.5:8080' or 'http://10.0.0.5/indexsvg.html' -> (host, port, '/jsonrpc')."""
    text = (address or "").strip()
    if not text:
        raise CardError("No card address set.")
    parts = urlsplit(text if "://" in text else f"http://{text}")
    if parts.scheme != "http" or not parts.hostname:
        raise CardError(f"Invalid card address: {address}")
    path = parts.path.rsplit("/", 1)[0] if parts.path and not parts.path.endswith("/") else parts.path.rstrip("/")
    return parts.hostname, parts.port or 80, f"{path}/jsonrpc"


class HttpTransport:
    """One persistent HTTP connection (TCP_NODELAY), reconnected once when the card dropped it."""

    def __init__(self, address, timeout=1.0):
        self.host, self.port, self.path = parse_address(address)
        self.timeout = timeout
        self._conn = None
        self.latency = None     # seconds of the last request

    @property
    def address(self):
        return f"{self.host}:{self.port}"

    def _connect(self):
        conn = http.client.HTTPConnection(self.host, self.port, timeout=self.timeout)
        conn.connect()
        conn.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self._conn = conn

    def post(self, payload):
        body = json.dumps(payload).encode()
        for attempt in (1, 2):
            started = time.perf_counter()
            try:
                if self._conn is None:
                    self._connect()
                self._conn.request("POST", self.path, body, {"Content-Type": "application/json-rpc"})
                response = self._conn.getresponse()
                data = response.read()
                if response.will_close:
                    self.close()
            except (socket.timeout, TimeoutError) as e:
                self.close()
                raise CardError(f"No answer from the card within {self.timeout:g} s.") from e
            except (ConnectionError, http.client.HTTPException, OSError) as e:
                self.close()
                if attempt == 2:
                    raise CardError(f"Card not reachable: {e}") from e
                continue
            self.latency = time.perf_counter() - started
            if response.status != 200:
                raise CardError(f"The card answered HTTP {response.status}.")
            try:
                return json.loads(data)
            except ValueError as e:
                raise CardError("The card sent a reply that is not JSON.") from e

    def close(self):
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None


# --- client -----------------------------------------------------------------------------------

def _register_from(result):
    if isinstance(result, dict) and result.get("status") == "tscOK" and "rdata" in result:
        return int(result["rdata"], 16)
    raise CardError(f"Unexpected valve register reply: {json.dumps(result)}")


class CardClient:
    def __init__(self, transport, allow_control=False):
        self.transport = transport
        self.allow_control = allow_control
        self.register = None    # the latest valve register read
        self.last_raw = None    # the card's last raw reply (for the probe)
        self._next_id = 1

    @property
    def simulated(self):
        return getattr(self.transport, "simulated", False)

    def call(self, requests):
        """Sends the requests as one batch. Returns (result, error) per request, in request order."""
        payload = []
        for request in requests:
            if classify(request.method, request.params) == CONTROL and not self.allow_control:
                raise CardLocked(f"Card control is locked on this PC: “{request.text or request.method}” "
                                 f"was not sent.")
            item = {"jsonrpc": "2.0", "method": request.method, "id": self._next_id}
            self._next_id += 1
            if request.params is not None:
                item["params"] = request.params
            payload.append(item)
        replies = self.last_raw = self.transport.post(payload)
        if isinstance(replies, dict):
            replies = [replies]
        if not isinstance(replies, list):
            raise CardError("The card sent an unexpected reply.")
        by_id = {r.get("id"): r for r in replies if isinstance(r, dict)}
        out = []
        for item in payload:
            reply = by_id.get(item["id"])
            if reply is None:
                out.append((None, "no reply"))
            elif "error" in reply and reply["error"] is not None:
                error = reply["error"]
                out.append((None, error.get("message", str(error)) if isinstance(error, dict) else str(error)))
            else:
                out.append((reply.get("result"), None))
        return out

    def send(self, request):
        (result, error), = self.call([request])
        if error is not None:
            raise CardReplyError(f"{request.text or request.method}: {error}")
        return result

    def read_all(self, with_status=False):
        """Pressures + valve register (+ chamber and gun status). Raises CardError when unreachable."""
        requests = [pressure(g.key) for g in GAUGES] + [valve_register()]
        if with_status:
            requests += [chamber_status(), gun_status()]
        replies = self.call(requests)
        state = VacuumState(t=time.time())
        for gauge, (result, _) in zip(GAUGES, replies):
            state.pressures[gauge.key] = valid_pressure(result)
        result, error = replies[len(GAUGES)]
        if error is None:
            state.register = _register_from(result)
            self.register = state.register
        if with_status:
            state.chamber_status = replies[-2][0] if replies[-2][1] is None else f"error: {replies[-2][1]}"
            state.gun_status = replies[-1][0] if replies[-1][1] is None else f"error: {replies[-1][1]}"
        return state

    def read_register(self):
        self.register = _register_from(self.send(valve_register()))
        return self.register

    def open_valve(self, name):
        """Opens a valve after checking the interlocks on a fresh register read. Returns the new register."""
        request = valve_open(name)
        classify(request.method, request.params)
        if not self.allow_control:
            raise CardLocked(f"Card control is locked on this PC: “open {name}” was not sent.")
        reason = interlock_reason(parse_register(self.read_register()), name)
        if reason:
            raise InterlockError(f"{name} not opened: {reason}")
        self.register = _register_from(self.send(request))
        return self.register

    def close_valve(self, name):
        self.register = _register_from(self.send(valve_close(name)))
        return self.register

    def power_save(self):
        self.register = _register_from(self.send(power_save()))
        return self.register

    def unlock(self, name):
        return self.send(valve_unlock(name))

    def chamber(self, command):
        return self.send(chamber(command))

    def gun(self, command):
        return self.send(gun(command))

    def gun_pump(self, hours=0.0):
        return self.send(gun_pump(hours))

    def beam(self, on):
        return self.send(beam(on))

    def ups(self):
        """(AC ok, battery ok) from the UPS inputs, as decoded by the web page."""
        result = self.send(ups_state())
        bits = int(result["rdata"], 16)
        return bool(bits & 0x4000), bool(bits & 0x8000)     # web page: 0x4000 alone = "AC OK, Batt LOW"

    def decontaminator(self, on):
        """Switches the decontaminator; returns whether it is on afterwards."""
        result = self.send(decontaminator(on))
        return bool(int(result["rdata"], 16) & 0x0200)

    def close(self):
        try:
            self.transport.close()
        except Exception:
            pass
