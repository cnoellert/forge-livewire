"""Per-artist persistent state: usage counts and recency for ranking,
pinned entries, and (future) config. One JSON file, atomic writes.

Shape:
    {"usage":  {"Blur": {"n": 12, "t": 1791234567}, ...},
     "pinned": ["Lens_Blur - User", ...]}

Keys are entry *display* names, so "Blur" (node) and "Blur - Matchbox"
rank independently.
"""

import json
import os
import time

PATH = os.path.expanduser("~/.config/livewire.json")

_state = None


def _load():
    global _state
    if _state is None:
        try:
            with open(PATH) as f:
                _state = json.load(f)
        except Exception:
            _state = {}
        _state.setdefault("usage", {})
        _state.setdefault("pinned", [])
    return _state


def usage():
    return _load()["usage"]


def pinned():
    return _load()["pinned"]


def record(display):
    """Count a commit of this entry and persist."""
    st = _load()
    u = st["usage"].setdefault(display, {"n": 0, "t": 0})
    u["n"] += 1
    u["t"] = int(time.time())
    _save()


def _save():
    try:
        d = os.path.dirname(PATH)
        if d and not os.path.isdir(d):
            os.makedirs(d, exist_ok=True)
        tmp = PATH + ".tmp"
        with open(tmp, "w") as f:
            json.dump(_state, f, indent=1, sort_keys=True)
        os.replace(tmp, PATH)
    except Exception:
        pass
