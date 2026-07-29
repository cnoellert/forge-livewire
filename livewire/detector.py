"""Noodle-drag gesture detector.

Flow: user grabs an output socket and drags (native Flame noodle). While
holding the button they tap HOTKEY; that arms livewire and identifies the
source node from early-drag ``flame.batch.cursor_position`` samples. On
release the node browser pops at the drop point; committing creates the
chosen node there and wires it to the source.

All Qt work runs on Flame's main thread (the QTimer lives there); install()
and uninstall() are safe to call from bridge worker threads.
"""

import flame
import Quartz
from PySide6 import QtCore

try:
    import AppKit
except Exception:
    AppKit = None

from . import browser

# Arm keys, polled only while a drag is in flight. Tapping F routes the
# connection into the new node's Front input, M into its Matte; tapping
# both during one drag wires front+matte. (Tab and backtick are taken:
# Tab tabs the schematic, backtick is assigned in Action.)
KEY_FRONT = 3    # macOS vkey: F
KEY_MATTE = 46   # macOS vkey: M

VERBOSE = False  # arm/commit chatter in the shell; errors always print


def _log(msg):
    if VERBOSE:
        print("[livewire] %s" % msg)
TICK_MS = 30
GRAB_RADIUS = 150.0    # schematic units: max grab-point distance to a node anchor
EARLY_SAMPLES = 6      # drag samples considered part of the grab point
SETTLE_MS = 140        # let cursor_position settle after release before reading

_timer = None
_btn = 0
_armed = False
_to_front = False      # F tapped during the drag
_to_matte = False      # M tapped during the drag
_samples = []          # cursor_position samples during the current drag
_node_map = []         # [(name, x, y)] snapshotted at press
_source = None         # {"name":..., "sockets":[...]} once armed
_types_cache = None
err = None


def _cpos():
    try:
        cp = flame.batch.cursor_position
        if hasattr(cp, "get_value"):
            cp = cp.get_value()
        return (float(cp[0]), float(cp[1]))
    except Exception:
        return None


def _attr(v):
    return v.get_value() if hasattr(v, "get_value") else v


def _snapshot_nodes():
    out = []
    try:
        for n in _attr(flame.batch.nodes):
            try:
                out.append((str(_attr(n.name)),
                            float(_attr(n.pos_x)), float(_attr(n.pos_y))))
            except Exception:
                pass
    except Exception:
        pass
    return out


def _output_sockets(name):
    try:
        n = flame.batch.get_node(name)
        return [str(s) for s in _attr(n.output_sockets)]
    except Exception:
        return []


def _find_source():
    """Nearest node anchor to the early drag samples, within GRAB_RADIUS."""
    early = _samples[:EARLY_SAMPLES]
    if not early or not _node_map:
        return None
    best = None
    for (name, x, y) in _node_map:
        for (sx, sy) in early:
            d = ((sx - x) ** 2 + (sy - y) ** 2) ** 0.5
            if best is None or d < best[0]:
                best = (d, name)
    if best is None or best[0] > GRAB_RADIUS:
        return None
    return {"name": best[1], "sockets": _output_sockets(best[1]),
            "dist": round(best[0], 1)}


def _node_types():
    global _types_cache
    if not _types_cache:
        try:
            _types_cache = sorted(str(t) for t in _attr(flame.batch.node_types))
        except Exception:
            _types_cache = []
    return _types_cache


def _app_active():
    try:
        return bool(AppKit.NSApp.isActive()) if AppKit else True
    except Exception:
        return True


def _pick(names, needle):
    """First name containing needle (case-insensitive), else None."""
    for n in names:
        if needle.lower() in n.lower():
            return n
    return None


def _connect(src, out_sock, new, in_sock):
    try:
        if out_sock and in_sock:
            flame.batch.connect_nodes(src, out_sock, new, in_sock)
        else:
            flame.batch.connect_nodes(src, new)
    except TypeError:
        flame.batch.connect_nodes(src, new)


def _commit(node_type, out_socket, cp, source, mode):
    def do():
        try:
            new = flame.batch.create_node(node_type)
            try:
                new.pos_x = int(cp[0])
                new.pos_y = int(cp[1])
            except Exception:
                pass
            if source and source.get("name"):
                src = flame.batch.get_node(source["name"])
                outs = source.get("sockets") or []
                ins = []
                try:
                    ins = [str(s) for s in _attr(new.input_sockets)]
                except Exception:
                    pass
                if mode == "front_matte":
                    front_out = ("Result" if "Result" in outs
                                 else (outs[0] if outs else None))
                    matte_out = _pick(outs, "matte") or front_out
                    front_in = _pick(ins, "front") or (ins[0] if ins else None)
                    matte_in = _pick(ins, "matte")
                    _connect(src, front_out, new, front_in)
                    if matte_in:
                        _connect(src, matte_out, new, matte_in)
                else:
                    needle = "matte" if mode == "matte" else "front"
                    in_sock = (_pick(ins, needle)
                               or (ins[0] if ins else None))
                    _connect(src, out_socket, new, in_sock)
            _log("created %s at (%d, %d) [%s]"
                 % (node_type, cp[0], cp[1], mode))
        except Exception as e:
            print("[livewire] commit failed: %r" % e)
    flame.schedule_idle_event(do)


def _fire(release_guess, source, mode):
    def show():
        cp = _cpos() or release_guess
        if cp is None:
            return
        browser.show_browser(
            node_types=_node_types(),
            source=source,
            mode=mode,
            on_commit=lambda ntype, sock: _commit(ntype, sock, cp, source,
                                                  mode))
    QtCore.QTimer.singleShot(SETTLE_MS, show)


def _tick():
    global _btn, _armed, _to_front, _to_matte
    global _samples, _node_map, _source, err
    try:
        st = Quartz.kCGEventSourceStateCombinedSessionState
        btn = 1 if Quartz.CGEventSourceButtonState(st, 0) else 0
        if btn and not _btn:
            _samples = []
            _armed = False
            _to_front = False
            _to_matte = False
            _source = None
            _node_map = _snapshot_nodes() if _app_active() else []
            cp = _cpos()
            if cp:
                _samples.append(cp)
        elif btn:
            cp = _cpos()
            if cp and (not _samples or cp != _samples[-1]):
                _samples.append(cp)
            if _node_map:
                f_down = Quartz.CGEventSourceKeyState(st, KEY_FRONT)
                m_down = Quartz.CGEventSourceKeyState(st, KEY_MATTE)
                if f_down or m_down:
                    if not _armed:
                        _armed = True
                        _source = _find_source()
                        _log("armed, source=%s"
                             % (_source["name"] if _source else None))
                    _to_front = _to_front or bool(f_down)
                    _to_matte = _to_matte or bool(m_down)
        elif _btn and not btn:
            if _armed:
                if _to_front and _to_matte:
                    mode = "front_matte"
                elif _to_matte:
                    mode = "matte"
                else:
                    mode = "front"
                _fire(_samples[-1] if _samples else None, _source, mode)
            _armed = False
        _btn = btn
    except Exception as e:
        err = repr(e)


def _start():
    global _timer
    if _timer is not None:
        return
    _timer = QtCore.QTimer()
    _timer.timeout.connect(_tick)
    _timer.start(TICK_MS)
    _log("detector running")


def install():
    flame.schedule_idle_event(_start)


def uninstall():
    def _stop():
        global _timer
        if _timer is not None:
            _timer.stop()
            _timer = None
        browser.close_all()
        _log("detector stopped")
    flame.schedule_idle_event(_stop)
