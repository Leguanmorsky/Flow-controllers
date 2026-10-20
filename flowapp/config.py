"""Settings and per-instrument configuration.

Settings are merged in this order (later wins):
  defaults < config/settings.json < config/local.json < FLOW_COM_PORT env var < command line
config/local.json is per computer and not synced through git (e.g. {"port": "COM9"} on the lab PC).
"""

import json
import os
from dataclasses import asdict, dataclass, fields
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"


@dataclass
class Settings:
    port: str = "auto"              # "auto" or a COM port name
    poll_hz: float = 4.0
    history_minutes: float = 60.0   # how much data the live graph can show
    simulate: bool = False


@dataclass
class ChannelConfig:
    """What the user assigned to an instrument, saved by serial number."""
    alias: str = ""
    gas: str = ""
    color: str = ""
    max_flow: float | None = None


def _read_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def load_settings(overrides=None, config_dir=CONFIG_DIR, env=os.environ):
    data = {}
    data.update(_read_json(config_dir / "settings.json"))
    data.update(_read_json(config_dir / "local.json"))
    if env.get("FLOW_COM_PORT"):
        data["port"] = env["FLOW_COM_PORT"]
    data.update({k: v for k, v in (overrides or {}).items() if v is not None})
    known = {f.name for f in fields(Settings)}
    return Settings(**{k: v for k, v in data.items() if k in known})


def load_channels(path=CONFIG_DIR / "channels.json"):
    known = {f.name for f in fields(ChannelConfig)}
    return {serial: ChannelConfig(**{k: v for k, v in cfg.items() if k in known})
            for serial, cfg in _read_json(path).items()}


def save_channels(channels, path=CONFIG_DIR / "channels.json"):
    with open(path, "w", encoding="utf-8") as f:
        json.dump({serial: asdict(cfg) for serial, cfg in channels.items()}, f, indent=2)
        f.write("\n")
