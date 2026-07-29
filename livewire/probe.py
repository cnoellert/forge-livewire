"""Diagnostic probe: log button edges + Flame batch state in schematic space.

This is the instrument that produced docs/FINDINGS.md. It is not part of the
runtime path, but stays here for re-validation on new Flame versions.

Usage (via forge-bridge flame_execute_python, or a Flame python console):

    from livewire import probe
    probe.install()      # marshals itself to the main thread
    ...pull noodles...
    probe.dump()         # print the captured log
    probe.uninstall()

All Qt objects live on the main thread; install()/uninstall() are safe to
call from bridge worker threads.
"""

import time

import flame
import Quartz
from PySide6 import QtCore

MAX_LOG = 1000

log = []
_timer = None
_last_btn = 0
_drag_last = None
err = None


def _nname(node):
    try:
        return str(node.name.get_value())
    except Exception:
        return repr(node)


def snap():
    """Snapshot the batch state relevant to gesture detection."""
    d = {}
    try:
        cur = getattr(flame.batch, "current_node", None)
        if cur is not None and hasattr(cur, "get_value"):
            cur = cur.get_value()
        d["cur"] = _nname(cur) if cur else None
    except Exception as e:
        d["cur"] = "ERR:" + repr(e)
    try:
        sel = flame.batch.selected_nodes
        if hasattr(sel, "get_value"):
            sel = sel.get_value()
        d["sel"] = [_nname(n) for n in sel]
    except Exception as e:
        d["sel"] = "ERR:" + repr(e)
    try:
        cp = flame.batch.cursor_position
        if hasattr(cp, "get_value"):
            cp = cp.get_value()
        d["cpos"] = tuple(cp)
    except Exception as e:
        d["cpos"] = "ERR:" + repr(e)
    return d


def _tick():
    global _last_btn, _drag_last, err
    try:
        from PySide6.QtGui import QCursor

        btn = 1 if Quartz.CGEventSourceButtonState(
            Quartz.kCGEventSourceStateCombinedSessionState, 0) else 0
        if btn != _last_btn:
            _last_btn = btn
            p = QCursor.pos()
            s = snap()
            log.append({"ev": "press" if btn else "release",
                        "t": round(time.time() % 100000, 3),
                        "pos": (p.x(), p.y()), "state": s})
            if btn:
                _drag_last = s
            else:
                _drag_last = None
                QtCore.QTimer.singleShot(150, lambda: log.append(
                    {"ev": "post-release+150", "state": snap()}))
        elif btn:
            s = snap()
            if s != _drag_last:
                log.append({"ev": "drag-change",
                            "t": round(time.time() % 100000, 3),
                            "state": s})
                _drag_last = s
        if len(log) > MAX_LOG:
            del log[:MAX_LOG // 2]
    except Exception as e:
        err = "tick:" + repr(e)


def _start():
    global _timer
    _timer = QtCore.QTimer()
    _timer.timeout.connect(_tick)
    _timer.start(30)


def install():
    """Start the poller (marshals to the Flame main thread)."""
    log.clear()
    flame.schedule_idle_event(_start)


def uninstall():
    def _stop():
        global _timer
        if _timer is not None:
            _timer.stop()
            _timer = None
    flame.schedule_idle_event(_stop)


def dump():
    import json
    print("err:", err)
    print("entries:", len(log))
    for r in log:
        print(json.dumps(r))
