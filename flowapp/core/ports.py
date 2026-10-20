"""Finding the COM port the Bronkhorst instruments are connected to."""

import propar
import serial.tools.list_ports

DEFAULT_PORT = "COM9"


def is_bluetooth(port_info):
    """Bluetooth serial ports are skipped by auto-detect: opening them can hang or crash Python."""
    return ("BTHENUM" in (port_info.hwid or "").upper()
            or "bluetooth" in (port_info.description or "").lower())


def candidate_ports():
    """Returns (ports to try, all available ports). COM9 first if present, Bluetooth skipped."""
    ports = serial.tools.list_ports.comports()
    available = [p.device for p in ports]
    scanned = [p.device for p in ports if not is_bluetooth(p)]
    if DEFAULT_PORT in scanned:
        scanned.remove(DEFAULT_PORT)
        scanned.insert(0, DEFAULT_PORT)
    return scanned, available


def close_port(port):
    """Closes the serial port opened by propar and forgets the cached master."""
    master = propar._PROPAR_MASTERS.pop(port, None)
    if master:
        try:
            master.stop()
        except Exception:
            pass


def get_nodes(port):
    """Returns the propar node list on `port` (empty when nothing answers). Closes the port if empty."""
    try:
        nodes = propar.instrument(port).master.get_nodes()
    except Exception:
        nodes = []
    if not nodes:
        close_port(port)
    return nodes


def find_port():
    """Returns (port, nodes) of the first COM port with Bronkhorst nodes."""
    candidates, available = candidate_ports()
    for port in candidates:
        nodes = get_nodes(port)
        if nodes:
            return port, nodes
    raise ConnectionError(f"No Bronkhorst device found (tried: {', '.join(candidates) or 'none'}; "
                          f"available ports: {', '.join(available) or 'none'}). "
                          f"Check the USB cable/driver or name the port, e.g. COM9.")
