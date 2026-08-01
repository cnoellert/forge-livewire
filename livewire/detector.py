"""Noodle-drag gesture detector for Batch and Action schematics.

Flow: user grabs a noodle/link and drags. While holding the button they
tap an arm key; livewire identifies the active schematic (Batch, or an
open Action's) and the source node from early-drag cursor samples. On
release the node browser pops at the drop point; committing creates the
chosen node there and wires it to the source.

Surface detection: both `flame.batch.cursor_position` and an open
Action's `cursor_position` track the pointer, each through its own
pan/zoom. When the Batch schematic is active the two feeds are exactly
identical; when the Action schematic is active they diverge. A grab is
attributed to the Action surface only if the feeds diverged AND the grab
point resolves to an Action node — stale feed values fail that test.

All Qt work runs on Flame's main thread (the QTimer lives there);
install() and uninstall() are safe to call from bridge worker threads.
"""

import flame
import Quartz
from PySide6 import QtCore

try:
    import AppKit
except Exception:
    AppKit = None

from . import browser
from . import indexer

# Arm keys, polled only while a drag is in flight. In Batch, F routes the
# connection into the new node's Front input, M into its Matte, both =
# front+matte. G arms gang (chain) mode: the browser stays open and each
# pick chains from the previous one until Esc / click-away; G+M gangs
# with the matte flavors per link. In an Action schematic any arm key
# works; the new node(s) are linked as children (a gang = parent chain).
# (Tab and backtick are taken: Tab tabs the schematic, backtick is
# assigned in Action.)
KEY_FRONT = 3    # macOS vkey: F
KEY_MATTE = 46   # macOS vkey: M
KEY_GANG = 5     # macOS vkey: G

CHAIN_DX_BATCH = 200   # schematic-units step between chained nodes
CHAIN_DX_ACTION = 130

VERBOSE = False  # arm/commit chatter in the shell; errors always print

TICK_MS = 30
GRAB_RADIUS = 150.0    # schematic units: max grab-point distance to a node
EARLY_SAMPLES = 6      # drag samples considered part of the grab point
SETTLE_MS = 140        # let cursor_position settle after release

_timer = None
_btn = 0
_armed = False
_to_front = False
_to_matte = False
_gang = False          # G tapped during the drag: chain mode
_pairs = []            # [(batch_cpos, action_cpos|None), ...] this drag
_bat_map = []          # [(name, x, y)] batch nodes, snapshotted at press
_act_map = []          # [(name, x, y)] open action's nodes
_act_name = None       # name of the current Action node, if any
_act_obj = None        # its PyActionNode, held for the drag only
_surface = None        # {"kind": "batch"} | {"kind": "action", "action": name}
_source = None         # {"name":..., "sockets":[...]} once armed
_types_cache = None
_act_types_cache = None
err = None


def _log(msg):
    if VERBOSE:
        print("[livewire] %s" % msg)


def _attr(v):
    return v.get_value() if hasattr(v, "get_value") else v


def _cpos_of(obj):
    try:
        cp = _attr(obj.cursor_position)
        return (float(cp[0]), float(cp[1]))
    except Exception:
        return None


def _snapshot(nodes):
    out = []
    for n in nodes:
        try:
            out.append((str(_attr(n.name)),
                        float(_attr(n.pos_x)), float(_attr(n.pos_y))))
        except Exception:
            pass
    return out


def _current_action():
    try:
        cur = _attr(flame.batch.current_node)
        if cur is not None and str(_attr(cur.type)) == "Action":
            return cur
    except Exception:
        pass
    return None


def _output_sockets(name):
    try:
        n = flame.batch.get_node(name)
        return [str(s) for s in _attr(n.output_sockets)]
    except Exception:
        return []


def _find_source(samples, node_map, with_sockets):
    """Nearest node anchor to the early drag samples, within GRAB_RADIUS."""
    early = samples[:EARLY_SAMPLES]
    if not early or not node_map:
        return None
    best = None
    for (name, x, y) in node_map:
        for (sx, sy) in early:
            d = ((sx - x) ** 2 + (sy - y) ** 2) ** 0.5
            if best is None or d < best[0]:
                best = (d, name)
    if best is None or best[0] > GRAB_RADIUS:
        return None
    return {"name": best[1],
            "sockets": _output_sockets(best[1]) if with_sockets else [],
            "dist": round(best[0], 1)}


def _node_types():
    global _types_cache
    if not _types_cache:
        try:
            _types_cache = sorted(str(t) for t in _attr(flame.batch.node_types))
        except Exception:
            _types_cache = []
    return _types_cache


def _action_types(action):
    global _act_types_cache
    if not _act_types_cache:
        try:
            _act_types_cache = sorted(str(t) for t in _attr(action.node_types))
        except Exception:
            _act_types_cache = []
    return _act_types_cache


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


def _instantiate_batch(entry, cp):
    """Create the picked entry in Batch at cp.

    Returns (in_node, out_node): the node to connect the source into and
    the node a chain continues from. Identical except for multi-node
    user bins (leftmost in, rightmost out).
    """
    kind = entry.get("kind", "node")
    if kind == "matchbox":
        new = flame.batch.create_node("Matchbox", entry["payload"])
    elif kind == "ofx":
        new = flame.batch.create_node("OpenFX")
        new.change_plugin(entry["payload"])
    elif kind == "userbin":
        before = set()
        for n in _attr(flame.batch.nodes):
            try:
                before.add(str(_attr(n.name)))
            except Exception:
                pass
        try:
            flame.batch.append_setup(entry["payload"])
        except Exception as e:
            # append_setup can raise (e.g. setup saved by an older Flame)
            # AFTER having appended the nodes — the diff below is the real
            # success test, so treat the exception as advisory only.
            _log("append_setup complained (tolerated): %r" % e)
        added = [n for n in _attr(flame.batch.nodes)
                 if str(_attr(n.name)) not in before]
        if not added:
            raise RuntimeError("append_setup added no nodes")
        # move the whole group so its left edge lands at the drop point
        xs = [float(_attr(n.pos_x)) for n in added]
        ys = [float(_attr(n.pos_y)) for n in added]
        dx, dy = int(cp[0] - min(xs)), int(cp[1] - (sum(ys) / len(ys)))
        for n in added:
            n.pos_x = int(float(_attr(n.pos_x)) + dx)
            n.pos_y = int(float(_attr(n.pos_y)) + dy)
        return (min(added, key=lambda n: float(_attr(n.pos_x))),
                max(added, key=lambda n: float(_attr(n.pos_x))))
    else:
        new = flame.batch.create_node(entry["payload"])
    try:
        new.pos_x = int(cp[0])
        new.pos_y = int(cp[1])
    except Exception:
        pass
    return new, new


def _commit_batch(entry, out_socket, cp, source, mode):
    """Create + wire one pick; returns the chain-out node."""
    new, out_node = _instantiate_batch(entry, cp)
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
            in_sock = _pick(ins, needle) or (ins[0] if ins else None)
            # Batch connect_nodes has no 2-arg form: always resolve an
            # output socket (chained gang picks arrive without one).
            use_out = out_socket or ("Result" if "Result" in outs
                                     else (outs[0] if outs else None))
            _connect(src, use_out, new, in_sock)
    return out_node


def _commit_action(entry, cp, source, action_name):
    """Create + link one pick inside the Action; returns the new node."""
    a = flame.batch.get_node(action_name)
    new = a.create_node(entry["payload"])
    try:
        new.pos_x = int(cp[0])
        new.pos_y = int(cp[1])
    except Exception:
        pass
    if source and source.get("name"):
        src = a.get_node(source["name"])
        if src is not None:
            a.connect_nodes(src, new)
    return new


def _fire(release_guess, source, mode, surface, act_obj, gang):
    def show():
        is_action = bool(surface and surface.get("kind") == "action")
        if is_action:
            cp = _cpos_of(act_obj) if act_obj is not None else None
            entries = [{"display": t, "label": t, "kind": "action_node",
                        "payload": t, "fav": False, "weight": 0}
                       for t in (_action_types(act_obj)
                                 if act_obj is not None else [])]
        else:
            cp = _cpos_of(flame.batch)
            entries = indexer.entries(_node_types())
        cp = cp or release_guess
        if cp is None:
            return

        # Mutable across a gang: each pick chains from the previous one.
        state = {"source": source, "cp": cp, "first": True}

        def on_commit(entry, sock):
            def do():
                try:
                    use_sock = sock if state["first"] else None
                    if is_action:
                        new = _commit_action(entry, state["cp"],
                                             state["source"],
                                             surface["action"])
                        outs = []
                    else:
                        new = _commit_batch(entry, use_sock, state["cp"],
                                            state["source"], mode)
                        try:
                            outs = [str(s) for s in _attr(new.output_sockets)]
                        except Exception:
                            outs = []
                    name = str(_attr(new.name))
                    dx = CHAIN_DX_ACTION if is_action else CHAIN_DX_BATCH
                    state["source"] = {"name": name, "sockets": outs}
                    state["cp"] = (float(_attr(new.pos_x)) + dx,
                                   float(_attr(new.pos_y)))
                    state["first"] = False
                    _log("created %s [%s/%s]"
                         % (entry["display"],
                            "action" if is_action else "batch", mode))
                except Exception as e:
                    print("[livewire] commit failed: %r" % e)
            flame.schedule_idle_event(do)

        browser.show_browser(
            entries=entries,
            source=source,
            mode=mode,
            kind=(surface or {}).get("kind", "batch"),
            chain=gang,
            on_commit=on_commit)
    QtCore.QTimer.singleShot(SETTLE_MS, show)


def _decide_surface():
    """Called once, at arm time. Returns (surface, source).

    The Action surface is chosen when its cursor feed diverged from the
    Batch feed AND is live — either it moved during the drag, or the grab
    point resolves to an Action node. A stale feed (Action selected in
    Batch but its schematic never opened) is frozen and far from any
    node, so it fails both tests and falls through to Batch.
    """
    bat_samples = [p[0] for p in _pairs if p[0] is not None]
    act_samples = [p[1] for p in _pairs if p[1] is not None]
    diverged = any(p[0] is not None and p[1] is not None and p[0] != p[1]
                   for p in _pairs)
    if _act_name is not None and diverged:
        src = _find_source(act_samples, _act_map, with_sockets=False)
        act_moving = len(set(act_samples)) >= 2
        if src is not None or act_moving:
            return {"kind": "action", "action": _act_name}, src
    return ({"kind": "batch"},
            _find_source(bat_samples, _bat_map, with_sockets=True))


def _tick():
    global _btn, _armed, _to_front, _to_matte, _gang, _pairs
    global _bat_map, _act_map, _act_name, _act_obj, _surface, _source, err
    try:
        st = Quartz.kCGEventSourceStateCombinedSessionState
        btn = 1 if Quartz.CGEventSourceButtonState(st, 0) else 0
        if btn and not _btn:
            _pairs = []
            _armed = False
            _to_front = False
            _to_matte = False
            _gang = False
            _source = None
            _surface = None
            if _app_active():
                _bat_map = _snapshot(_attr(flame.batch.nodes))
                _act_obj = _current_action()
                if _act_obj is not None:
                    _act_name = str(_attr(_act_obj.name))
                    _act_map = (_snapshot(_attr(_act_obj.nodes))
                                + _snapshot(_attr(_act_obj.media_nodes)))
                else:
                    _act_name, _act_map = None, []
            else:
                _bat_map, _act_map = [], []
                _act_name, _act_obj = None, None
            _pairs.append((_cpos_of(flame.batch),
                           _cpos_of(_act_obj) if _act_obj else None))
        elif btn:
            pair = (_cpos_of(flame.batch),
                    _cpos_of(_act_obj) if _act_obj else None)
            if not _pairs or pair != _pairs[-1]:
                _pairs.append(pair)
            if _bat_map or _act_map:
                f_down = Quartz.CGEventSourceKeyState(st, KEY_FRONT)
                m_down = Quartz.CGEventSourceKeyState(st, KEY_MATTE)
                g_down = Quartz.CGEventSourceKeyState(st, KEY_GANG)
                if f_down or m_down or g_down:
                    if not _armed:
                        _armed = True
                        _surface, _source = _decide_surface()
                        _log("armed [%s], source=%s"
                             % (_surface["kind"],
                                _source["name"] if _source else None))
                    _to_front = _to_front or bool(f_down)
                    _to_matte = _to_matte or bool(m_down)
                    _gang = _gang or bool(g_down)
        elif _btn and not btn:
            if _armed:
                if _surface and _surface.get("kind") == "action":
                    mode = "child"
                    samples = [p[1] for p in _pairs if p[1] is not None]
                else:
                    if _to_front and _to_matte:
                        mode = "front_matte"
                    elif _to_matte:
                        mode = "matte"
                    else:
                        mode = "front"
                    samples = [p[0] for p in _pairs if p[0] is not None]
                _fire(samples[-1] if samples else None, _source, mode,
                      _surface, _act_obj, _gang)
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
