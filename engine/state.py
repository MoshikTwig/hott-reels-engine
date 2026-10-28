"""Small JSON files that remember what the engine already used."""

import json
from pathlib import Path

STATE_DIR = Path(__file__).resolve().parent.parent / "state"


def load(name, default):
    path = STATE_DIR / f"{name}.json"
    if not path.exists():
        return default
    return json.loads(path.read_text())


def save(name, value):
    STATE_DIR.mkdir(exist_ok=True)
    (STATE_DIR / f"{name}.json").write_text(json.dumps(value, indent=2) + "\n")
