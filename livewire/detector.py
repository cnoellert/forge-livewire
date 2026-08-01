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
KEY_CHAINSEL = 8  # macOS vkey: C — replicate picks across the selection

CHAIN_DX_BATCH = 200   # batch chains march right
CHAIN_DY_ACTION = 200  # action chains build DOWN (children sit below
                       # parents; smaller y is lower in action space)

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
_chain_sel = False     # C tapped: parallel chains across the selection
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


_debug = []      # (timestamp, msg) ring buffer, kept even when quiet


def _log(msg):
    import time
    _debug.append((round(time.time() % 100000, 3), msg))
    del _debug[:-200]
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


def _nudge_flame(nsloc=None):
    """Wake Flame's redraw after a commit made while the popup holds
    focus. Flame repaints when processing its own input events (classic
    redraw-after-input), so: pump Qt's dispatcher (input excluded), then
    post a synthetic no-op mouse-move addressed to Flame's main window.
    Aim it at nsloc — the drop point in bottom-left screen coords, i.e.
    inside the schematic panel being used — since a center-of-window
    move wakes the Batch panel but can miss Action's. (A bare
    NSApplicationDefined post was not enough — tried and falsified.)"""
    try:
        from PySide6 import QtCore
        QtCore.QCoreApplication.sendPostedEvents()
        QtCore.QCoreApplication.processEvents(
            QtCore.QEventLoop.ExcludeUserInputEvents, 20)
    except Exception:
        pass
    try:
        import AppKit
        app = AppKit.NSApplication.sharedApplication()
        main = None
        for w in app.windows():
            try:
                f = w.frame()
                if w.isVisible() and (main is None
                                      or f.size.width > main.frame().size.width):
                    main = w
            except Exception:
                pass
        if main is not None:
            mtype = getattr(AppKit, "NSEventTypeMouseMoved",
                            getattr(AppKit, "NSMouseMoved", 5))
            f = main.frame()
            if nsloc is not None:
                loc = (nsloc[0] - float(f.origin.x),
                       nsloc[1] - float(f.origin.y))
            else:
                loc = (f.size.width / 2.0, f.size.height / 2.0)
            ev = (AppKit.NSEvent.
                  mouseEventWithType_location_modifierFlags_timestamp_windowNumber_context_eventNumber_clickCount_pressure_(
                      mtype, loc, 0, 0.0, main.windowNumber(), None,
                      0, 0, 0.0))
            app.postEvent_atStart_(ev, False)
    except Exception as e:
        _log("nudge failed: %r" % e)


def _pick(names, needle):
    """First name containing needle (case-insensitive), else None."""
    for n in names:
        if needle.lower() in n.lower():
            return n
    return None


def _pick_in(ins, image=True, back=False):
    """Pick an input socket by role: image vs matte, front-pair vs
    back-pair ('Front'/'Matte' vs 'Back'/'Back Matte')."""
    for s in ins:
        low = s.lower()
        if ("back" in low) != back:
            continue
        if image and "matte" not in low:
            return s
        if not image and "matte" in low:
            return s
    return None


def _selection_names():
    try:
        sel = flame.batch.selected_nodes
        if hasattr(sel, "get_value"):
            sel = sel.get_value()
        return [str(_attr(n.name)) for n in sel]
    except Exception:
        return []


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
            # only wire a matte when the source really has a matte
            # output — never route the image output into a Matte input
            matte_out = _pick(outs, "matte")
            front_in = _pick_in(ins, image=True) or (ins[0] if ins else None)
            matte_in = _pick_in(ins, image=False)
            _connect(src, front_out, new, front_in)
            if matte_in and matte_out:
                _connect(src, matte_out, new, matte_in)
        else:
            in_sock = (_pick_in(ins, image=(mode != "matte"))
                       or (ins[0] if ins else None))
            # Batch connect_nodes has no 2-arg form: always resolve an
            # output socket (chained gang picks arrive without one).
            use_out = out_socket or ("Result" if "Result" in outs
                                     else (outs[0] if outs else None))
            _connect(src, use_out, new, in_sock)
        extras = source.get("extra") or []
        if extras and hasattr(new, "add_media"):
            # Action: one media layer per additional selected node,
            # wired in selection order. add_media() returns the Action
            # Media batch node (ins Front/Matte); Flame auto-places it
            # attached to the Action.
            for ex in extras:
                try:
                    media = new.add_media()
                except Exception as e:
                    _log("add_media failed: %r" % e)
                    break
                exsrc = flame.batch.get_node(ex["name"])
                exouts = ex.get("sockets") or []
                img_out = ("Result" if "Result" in exouts
                           else (exouts[0] if exouts else None))
                m_ins = [str(s) for s in _attr(media.input_sockets)]
                front_in = (_pick_in(m_ins, image=True)
                            or (m_ins[0] if m_ins else None))
                _connect(exsrc, img_out, media, front_in)
                if mode == "front_matte":
                    matte_out = _pick(exouts, "matte")
                    matte_in = _pick_in(m_ins, image=False)
                    if matte_out and matte_in:
                        _connect(exsrc, matte_out, media, matte_in)
        else:
            # Non-Action nodes: extras fill the back pair where one
            # exists (Comp, Blend & Comp, ...). First extra only —
            # further pairs have no conventional socket names yet.
            for ex in extras[:1]:
                back_in = _pick_in(ins, image=True, back=True)
                if back_in is None:
                    _log("no back input on %s for extra source %s"
                         % (entry["display"], ex["name"]))
                    break
                exsrc = flame.batch.get_node(ex["name"])
                exouts = ex.get("sockets") or []
                img_out = ("Result" if "Result" in exouts
                           else (exouts[0] if exouts else None))
                _connect(exsrc, img_out, new, back_in)
                if mode == "front_matte":
                    back_matte_in = _pick_in(ins, image=False, back=True)
                    matte_out = _pick(exouts, "matte")
                    if back_matte_in and matte_out:
                        _connect(exsrc, matte_out, new, back_matte_in)
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


def _fire(release_guess, source, mode, surface, act_obj, gang,
          parallel_req=False):
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

        # Chains, mutable across a gang. Normally one chain from the
        # drop point. C (chain-selection) = PARALLEL chains: the same
        # picks replicate onto every selected node, each chain building
        # in line with its own source (no fan-in — that's F's job; and
        # G keeps its first-link fan-in behavior).
        parallel = bool(parallel_req and not is_action and source
                        and source.get("extra"))
        if parallel:
            posmap = {n: (x, y) for (n, x, y) in _bat_map}
            chains = []
            for nm in ([source["name"]]
                       + [e["name"] for e in source["extra"]]):
                p = posmap.get(nm)
                start = (p[0] + CHAIN_DX_BATCH, p[1]) if p else cp
                chains.append({"source": {"name": nm,
                                          "sockets": _output_sockets(nm)},
                               "cp": start, "first": True})
            source = {"name": u"%d selected" % len(chains), "sockets": []}
        else:
            chains = [{"source": source, "cp": cp, "first": True}]

        state = {"nsloc": None}
        try:
            import AppKit
            p = AppKit.NSEvent.mouseLocation()  # cursor is at the drop
            state["nsloc"] = (float(p.x), float(p.y))  # point right now
        except Exception:
            pass

        def on_commit(entry, sock):
            _log("on_commit called: %s (mode=%s, chains=%d)"
                 % (entry["display"], mode, len(chains)))

            def do_chain(ch):
                use_sock = sock if ch["first"] else None
                src_ctx = ch["source"]
                # Multi-select fan-in (Action media / back pairs)
                # applies to the FIRST pick only; chained picks must
                # never see the original selection.
                if not ch["first"] and src_ctx and "extra" in src_ctx:
                    src_ctx = {k: v for k, v in src_ctx.items()
                               if k != "extra"}
                    ch["source"] = src_ctx
                if parallel and use_sock:
                    # per-chain sanity: only honor the socket menu where
                    # that source actually has the socket
                    if use_sock not in (src_ctx.get("sockets") or []):
                        use_sock = None
                if is_action:
                    new = _commit_action(entry, ch["cp"], src_ctx,
                                         surface["action"])
                    outs = []
                else:
                    new = _commit_batch(entry, use_sock, ch["cp"],
                                        src_ctx, mode)
                    try:
                        outs = [str(s) for s in _attr(new.output_sockets)]
                    except Exception:
                        outs = []
                name = str(_attr(new.name))
                _log("do() created+wired: %s" % name)
                # fresh dict deliberately drops "extra": the chain
                # continues single-source from the new node
                ch["source"] = {"name": name, "sockets": outs}
                if is_action:
                    ch["cp"] = (float(_attr(new.pos_x)),
                                float(_attr(new.pos_y)) - CHAIN_DY_ACTION)
                else:
                    ch["cp"] = (float(_attr(new.pos_x)) + CHAIN_DX_BATCH,
                                float(_attr(new.pos_y)))
                ch["first"] = False

            # Browser callbacks run on Flame's main thread, so commit
            # directly — schedule_idle_event would sit in Flame's idle
            # queue until the user next touches Flame's own UI.
            for ch in chains:
                try:
                    do_chain(ch)
                except Exception as e:
                    print("[livewire] commit failed (%s): %r"
                          % (ch["source"].get("name"), e))
            # Burst: Flame dirties some layout (e.g. Action media
            # attachment) in its own deferred pass AFTER the first
            # repaint, so nudge again shortly; jitter each synthetic
            # move a pixel so same-position moves aren't coalesced away.
            base = state.get("nsloc")
            _nudge_flame(base)
            for delay, (jx, jy) in ((120, (1, 0)), (350, (0, 1))):
                loc = (base[0] + jx, base[1] + jy) if base else None
                QtCore.QTimer.singleShot(
                    delay, lambda loc=loc: _nudge_flame(loc))

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
    # When Batch is active, an open Action's feed MIRRORS the batch feed
    # — but the two are read sequentially per tick, so fast drags show
    # tiny skews between them. Exact equality on ANY pair is therefore
    # the batch tell (mirroring hits it constantly at pauses); a truly
    # open Action schematic has its own origin/zoom and never matches.
    mirrored = any(p[0] is not None and p[1] is not None and p[0] == p[1]
                   for p in _pairs)
    if _act_name is not None and not mirrored:
        src = _find_source(act_samples, _act_map, with_sockets=False)
        act_moving = len(set(act_samples)) >= 2
        if src is not None or act_moving:
            return {"kind": "action", "action": _act_name}, src
    src = _find_source(bat_samples, _bat_map, with_sockets=True)
    # Deliberate multi-select including the grabbed node: the other
    # selected nodes become additional sources (back pair, and beyond
    # once nodes with more input pairs are supported).
    if src is not None:
        sel = _selection_names()
        if len(sel) >= 2 and src["name"] in sel:
            src["extra"] = [{"name": n, "sockets": _output_sockets(n)}
                            for n in sel if n != src["name"]]
    return {"kind": "batch"}, src


def _tick():
    global _btn, _armed, _to_front, _to_matte, _gang, _chain_sel, _pairs
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
            _chain_sel = False
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
                c_down = Quartz.CGEventSourceKeyState(st, KEY_CHAINSEL)
                if f_down or m_down or g_down or c_down:
                    if not _armed:
                        _armed = True
                        _surface, _source = _decide_surface()
                        _log("armed [%s], source=%s"
                             % (_surface["kind"],
                                _source["name"] if _source else None))
                    _to_front = _to_front or bool(f_down)
                    _to_matte = _to_matte or bool(m_down)
                    _gang = _gang or bool(g_down)
                    _chain_sel = _chain_sel or bool(c_down)
        elif _btn and not btn:
            if _armed:
                gang_like = _gang or _chain_sel
                if _surface and _surface.get("kind") == "action":
                    mode = "child"
                    samples = [p[1] for p in _pairs if p[1] is not None]
                else:
                    if _to_front and _to_matte:
                        mode = "front_matte"
                    elif _to_matte:
                        # gm/cm mirror fm: a gang's M means front+matte
                        # links (matte-only chains aren't a thing)
                        mode = "front_matte" if gang_like else "matte"
                    else:
                        mode = "front"
                    samples = [p[0] for p in _pairs if p[0] is not None]
                _fire(samples[-1] if samples else None, _source, mode,
                      _surface, _act_obj, gang_like,
                      parallel_req=_chain_sel)
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
