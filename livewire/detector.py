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
from PySide6 import QtCore

from . import browser
from . import hid
from . import indexer

# Arm keys, polled only while a drag is in flight. In Batch, F routes the
# connection into the new node's Front input, M into its Matte, both =
# front+matte. G arms gang (chain) mode: the browser stays open and each
# pick chains from the previous one until Esc / click-away; G+M gangs
# with the matte flavors per link. In an Action schematic any arm key
# works; the new node(s) are linked as children (a gang = parent chain).
# (Tab and backtick are taken: Tab tabs the schematic, backtick is
# assigned in Action.)
# Keys by character; the hid shim maps them to platform codes.
# Rejected: Tab (tabs the schematic), backtick (assigned in Action),
# C (Batch compass), A (adds knots to node outputs mid-drag).
KEY_FRONT = "f"
KEY_MATTE = "m"
KEY_GANG = "g"
KEY_CHAINSEL = "r"   # replicate picks across the selection
KEY_INGEST = "i"     # grab an Action, tap I: map-ingest table

CHAIN_DX_BATCH = 200   # batch chains march right
CHAIN_DY_ACTION = 120  # action chains build DOWN (children sit below
                       # parents; smaller y is lower in action space);
                       # tightened from 200 (2026-08-05, operator call)
MEDIA_DX = 170         # media knots sit in line with their feeder,
                       # this far to its right
MEDIA_DY = 150         # channel fan-out stacks medias this far apart
CRYPTO_PAT = "crypto"  # channel names containing this (case-insens)
                       # are crypto layers: excluded from Action
                       # fan-out, exclusively used by CryptoMatte
EXPANDED_STEP = 40     # schematic units per socket row for the expanded
                       # -clip grab segment (calibrated 37.5; padded)
EXPANDED_XMAX = 320    # expanded-clip tabs are wide BOXES right of the
                       # anchor, not a line: live grabs observed at dx
                       # +109 and +214 (2026-08-05, the second one fell
                       # outside GRAB_RADIUS and killed the fan-out);
                       # treat dx in [0, this] as on-surface

# Socket-inference geometry, calibrated 2026-08-04 against a 30-tab
# expanded EXR and a Comp (see FINDINGS). Sockets stack down the right
# edge; body grabs snap to the anchor (dx~0) so dx gates confidence.
SOCK_STD_STEP = 21.0   # standard nodes: per-socket step, centered
SOCK_STD_XMIN = 15.0   # min dx to call it a socket grab (grabs ~+40)
SOCK_EXR_STEP = 37.5   # expanded clips: per-tab step
SOCK_EXR_PAD = 46.6    # top tab sits this far below the centered model
SOCK_EXR_XMIN = 60.0   # expanded-clip tab column is at dx ~+112

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
_drag_live = False     # the drag has actually MOVED in schematic
                       # space: only then may we query key state
_gang = False          # G tapped during the drag: chain mode
_chain_sel = False     # C tapped: parallel chains across the selection
_ingest = False        # A tapped: Action map-ingest table
_pairs = []            # [(batch_cpos, action_cpos|None), ...] this drag
_bat_map = []          # [(name, x, y)] batch nodes, snapshotted at press
_bat_types = {}        # name -> node type, same snapshot
_bat_meta = {}         # clip name -> (n_sockets, collapsed), same snapshot
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


def _snapshot(nodes, types=None):
    out = []
    for n in nodes:
        try:
            name = str(_attr(n.name))
            out.append((name,
                        float(_attr(n.pos_x)), float(_attr(n.pos_y))))
            if types is not None:
                types[name] = str(_attr(n.type))
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


def _find_source(samples, node_map, with_sockets, meta=None):
    """Nearest node to the early drag samples, within GRAB_RADIUS.

    Nodes with meta (expanded multichannel clips) match along a vertical
    segment sized by their socket count — their grab surface is a tall
    column, not a point."""
    early = samples[:EARLY_SAMPLES]
    if not early or not node_map:
        return None
    best = None
    for (name, x, y) in node_map:
        seg = 0.0
        m = (meta or {}).get(name)
        if m and not m[1]:  # expanded
            seg = (m[0] + 1) * EXPANDED_STEP
        for (sx, sy) in early:
            if seg:
                if (y - seg) <= sy <= (y + seg):
                    dy = 0.0
                else:
                    dy = min(abs(sy - (y - seg)), abs(sy - (y + seg)))
                # tabs are wide boxes to the RIGHT of the anchor — the
                # grab surface is a rectangle, not a vertical line
                dx = sx - x
                if 0.0 <= dx <= EXPANDED_XMAX:
                    dxd = 0.0
                else:
                    dxd = min(abs(dx), abs(dx - EXPANDED_XMAX))
                d = (dxd ** 2 + dy ** 2) ** 0.5
            else:
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


def _nudge_flame(nsloc=None):
    """Wake Flame's redraw after a commit made while the popup holds
    focus. Flame repaints when processing its own input events (classic
    redraw-after-input), so: pump Qt's dispatcher (input excluded), then
    have the hid shim deliver a synthetic no-op input event aimed at
    nsloc — the drop point — since panel repaint is hover-local (see
    FINDINGS: the repaint escalation ladder)."""
    try:
        QtCore.QCoreApplication.sendPostedEvents()
        QtCore.QCoreApplication.processEvents(
            QtCore.QEventLoop.ExcludeUserInputEvents, 20)
    except Exception:
        pass
    hid.nudge(nsloc)


def _pick(names, needle):
    """First name containing needle (case-insensitive), else None."""
    for n in names:
        if needle.lower() in n.lower():
            return n
    return None


def _matte_for(outs, img_out):
    """The matte output that belongs with img_out: its `_alpha` sibling
    on multichannel clips, else a real matte socket. Never a crypto
    layer — `Cryptomatte_MAT` contains "matte" but is not one."""
    if img_out:
        sib = img_out + "_alpha"
        if sib in outs:
            return sib
    for o in outs:
        low = o.lower()
        if "matte" in low and CRYPTO_PAT not in low:
            return o
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


def _channels(outs):
    """Split channel sockets from their _alpha siblings."""
    alpha = {o[:-len("_alpha")]: o for o in outs if o.endswith("_alpha")}
    chans = [o for o in outs if not o.endswith("_alpha")]
    return chans, alpha


def _wire_channels_to_action(new, src, outs):
    """Multichannel clip → Action: rgba to Back, one media per
    remaining non-crypto channel (its _alpha sibling to media Matte)."""
    chans, alpha = _channels(outs)
    non_crypto = [c for c in chans if CRYPTO_PAT not in c.lower()]
    if len(non_crypto) < 3:
        return False
    back = "rgba" if "rgba" in non_crypto else non_crypto[0]
    _connect(src, back, new, "Back")
    sx = float(_attr(src.pos_x))
    sy = float(_attr(src.pos_y))
    # keep the Action's root OUT of the media column's lane: if the
    # drop landed in line with the column, push it one media-step
    # right — the graph then reads clip -> medias -> action
    fan_x = int(sx + EXPANDED_XMAX + MEDIA_DX)
    try:
        if abs(float(_attr(new.pos_x)) - fan_x) < MEDIA_DX:
            new.pos_x = fan_x + MEDIA_DX
    except Exception:
        pass
    i = 0
    for c in non_crypto:
        if c == back:
            continue
        media = new.add_media()
        try:
            # clear of the expanded clip's tab RECTANGLE (tabs reach
            # EXPANDED_XMAX right of the anchor) — +170 alone put the
            # whole media column on top of the tabs (2026-08-05).
            # NB: do NOT try to align medias to per-tab rows via the
            # SOCK_EXR geometry — tried 2026-08-05, the on-screen tab
            # layout doesn't map to it and the result was worse.
            media.pos_x = fan_x
            media.pos_y = int(sy - i * MEDIA_DY)
        except Exception:
            pass
        _connect(src, c, media, "Front")
        if c in alpha:
            _connect(src, alpha[c], media, "Matte")
        i += 1
    _log("channel fan-out: %d medias (+%s to Back), crypto skipped: %d"
         % (i, back, len(chans) - len(non_crypto)))
    return True


def _wire_channels_to_crypto(new, src, outs):
    """Multichannel clip → CryptoMatte: one CryptoMatte node per crypto
    family (MAT, NODE, ...), each with rgba to Front and its family's
    numbered rank layers to uCryptoNNrgb/a. The picked node takes the
    first family; extra families get their own node stacked below."""
    import re
    fams = sorted({m.group(1) for o in outs
                   for m in [re.match(r"(.*%s.*?)(\d{2})$" % CRYPTO_PAT,
                                      o, re.I)] if m})
    if not fams:
        return False
    fams.sort(key=lambda f: (0 if "mat" in f.lower() else 1, f))
    base_x = float(_attr(new.pos_x))
    base_y = float(_attr(new.pos_y))
    node = new
    for i, fam in enumerate(fams):
        if i > 0:
            node = flame.batch.create_node("CryptoMatte")
            try:
                node.pos_x = int(base_x)
                node.pos_y = int(base_y - 220 * i)
            except Exception:
                pass
        if "rgba" in outs:
            _connect(src, "rgba", node, "Front")
        for r in range(3):
            cname = "%s%02d" % (fam, r)
            if cname not in outs:
                continue
            _connect(src, cname, node, "uCrypto%02drgb" % r)
            aname = cname + "_alpha"
            if aname in outs:
                _connect(src, aname, node, "uCrypto%02da" % r)
        _log("cryptomatte wired: %s" % fam)
    return True


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
        # Channel fan-out: a multichannel CLIP picked onto an Action or
        # CryptoMatte dispatches on the target, like every other
        # converge. Gated on the source actually being a multichannel
        # clip — a plain "has 3+ outputs" test caught chained picks off
        # a CryptoMatte (Result + OutMatte1-4) and fanned those out.
        if source.get("multichannel") and not (source.get("extra") or []):
            try:
                new_type = str(_attr(new.type))
            except Exception:
                new_type = ""
            if (new_type == "Action"
                    and _wire_channels_to_action(new, src, outs)):
                return out_node
            if (new_type == "CryptoMatte"
                    and _wire_channels_to_crypto(new, src, outs)):
                return out_node
        if mode == "front_matte":
            front_out = out_socket or ("Result" if "Result" in outs
                                       else (outs[0] if outs else None))
            # only wire a matte when the source really has a matte
            # output — never route the image output into a Matte input
            matte_out = _matte_for(outs, front_out)
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
            img_out = ("Result" if "Result" in outs
                       else (outs[0] if outs else None))
            use_out = out_socket or (_matte_for(outs, img_out)
                                     if mode == "matte" else img_out)
            _connect(src, use_out, new, in_sock)
        extras = source.get("extra") or []
        # NB: hasattr() is useless on Flame PyNodes — missing attributes
        # resolve to None instead of raising, so hasattr(new,
        # "add_media") is True for EVERY node. Check the node type.
        try:
            is_action_node = str(_attr(new.type)) == "Action"
        except Exception:
            is_action_node = False
        if extras and is_action_node:
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
                try:
                    # park the knot in line with its feeder, not where
                    # Flame's auto-placement scatters it
                    media.pos_x = int(float(_attr(exsrc.pos_x)) + MEDIA_DX)
                    media.pos_y = int(float(_attr(exsrc.pos_y)))
                except Exception:
                    pass
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
                    matte_out = _matte_for(exouts, img_out)
                    if back_matte_in and matte_out:
                        _connect(exsrc, matte_out, new, back_matte_in)
    return out_node


# PyActionNode.node_types lists entries create_node() cannot take:
# "Surface" is an abstract label that RAISES RuntimeError, while the
# concrete "Extended Bicubic" creates a node whose .type reads
# "Surface" (live-probed 2026-08-05, 2026.2.1; the surface also
# auto-spawns its parent axis, which is Flame's normal behavior).
ACTION_CREATE_ALIASES = {"Surface": "Extended Bicubic"}


def _commit_action(entry, cp, source, action_name):
    """Create + link one pick inside the Action.

    Returns (new_node, via_axis): via_axis is True when the create
    auto-spawned a parent axis (surfaces do) — the caller budgets the
    chain step for the extra row."""
    a = flame.batch.get_node(action_name)
    payload = ACTION_CREATE_ALIASES.get(entry["payload"], entry["payload"])
    new = a.create_node(payload)
    # Some creates auto-spawn a parent (a surface arrives with its own
    # axis). Flame's hand-made convention is source -> auto-axis ->
    # surface in a vertical stack, so route the source link into the
    # auto-parent and place it between source and new node. NB
    # PyCoNode.parents is a METHOD (parents()), and a fresh node's
    # parents are exactly its auto-spawned ones.
    link_target = new
    try:
        autos = list(new.parents())
        if len(autos) == 1:
            link_target = autos[0]
    except Exception:
        pass
    src = (a.get_node(source["name"])
           if source and source.get("name") else None)
    nx, ny = int(cp[0]), int(cp[1])
    if src is not None and link_target is not new:
        try:
            # the rig needs two rows below its source — a drop closer
            # than that crams the auto-axis into the source node
            ny = min(ny, int(float(_attr(src.pos_y))
                             - 2 * CHAIN_DY_ACTION))
        except Exception:
            pass
    try:
        new.pos_x = nx
        new.pos_y = ny
    except Exception:
        pass
    placed = False
    if src is not None:
        a.connect_nodes(src, link_target)
        if link_target is not new:
            try:
                sx = float(_attr(src.pos_x))
                sy = float(_attr(src.pos_y))
                link_target.pos_x = int((sx + nx) / 2)
                link_target.pos_y = int((sy + ny) / 2)
                placed = True
            except Exception:
                pass
    if link_target is not new and not placed:
        try:
            link_target.pos_x = nx
            link_target.pos_y = ny + CHAIN_DY_ACTION // 2
        except Exception:
            pass
    return new, link_target is not new


def _nudge_burst(base, step=(1, 0)):
    """Burst of repaint nudges SWEEPING outward from the drop point in
    the chain-growth direction (screen px, AppKit bottom-left origin;
    Batch builds right (1,0), Action builds down (0,-1)).

    Flame's redraw-after-input repaint is region-local around the
    synthetic move (2026-08-05: a fixed-point burst repainted only the
    first couple of chained nodes; 3rd+ stayed invisible until a real
    click — sweeping fixed it, operator-verified per-Enter on 6-node
    chains). The alternating ±1 px keeps same-position moves from
    being coalesced away, and the long tail covers layout Flame
    dirties in deferred passes AFTER the first repaint (e.g. Action
    media attachment)."""
    _nudge_flame(base)
    if base is None:
        for delay in (100, 250, 600):
            QtCore.QTimer.singleShot(delay, lambda: _nudge_flame(None))
        return
    sx, sy = step
    for i, delay in enumerate((80, 180, 300, 450, 650, 900), start=1):
        off = i * 55
        loc = (base[0] + sx * off + (i % 2),
               base[1] + sy * off + ((i + 1) % 2))
        QtCore.QTimer.singleShot(delay, lambda loc=loc: _nudge_flame(loc))


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
        # NB: never assign to `source` in this scope — it would shadow
        # the closure variable and UnboundLocalError the whole function.
        disp_source = source
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
            disp_source = {"name": u"%d selected" % len(chains),
                           "sockets": []}
        else:
            chains = [{"source": source, "cp": cp, "first": True}]

        # cursor is at the drop point right now
        state = {"nsloc": hid.cursor_loc()}

        def on_commit(entry, sock):
            _log("on_commit called: %s (mode=%s, chains=%d)"
                 % (entry["display"], mode, len(chains)))

            def do_chain(ch):
                use_sock = sock if ch["first"] else None
                src_ctx = ch["source"]
                # Multi-select fan-in (Action media / back pairs)
                # applies to the FIRST pick only; chained picks must
                # never see the original selection.
                if not ch["first"] and src_ctx and (
                        "extra" in src_ctx or "multichannel" in src_ctx):
                    src_ctx = {k: v for k, v in src_ctx.items()
                               if k not in ("extra", "multichannel")}
                    ch["source"] = src_ctx
                if parallel and use_sock:
                    # per-chain sanity: only honor the socket menu where
                    # that source actually has the socket
                    if use_sock not in (src_ctx.get("sockets") or []):
                        use_sock = None
                if is_action:
                    new, via_axis = _commit_action(entry, ch["cp"],
                                                   src_ctx,
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
                    # a commit that arrived with its own axis occupies
                    # two rows (axis + node) — budget the next drop
                    # accordingly or chained surfaces stack into each
                    # other (2026-08-05 screenshot)
                    dy = CHAIN_DY_ACTION * (2 if via_axis else 1)
                    ch["cp"] = (float(_attr(new.pos_x)),
                                float(_attr(new.pos_y)) - dy)
                else:
                    ch["cp"] = (float(_attr(new.pos_x)) + CHAIN_DX_BATCH,
                                float(_attr(new.pos_y)))
                ch["first"] = False

            # Browser callbacks run on Flame's main thread, so commit
            # directly — schedule_idle_event would sit in Flame's idle
            # queue until the user next touches Flame's own UI.
            committed = 0
            for ch in chains:
                try:
                    do_chain(ch)
                    committed += 1
                except Exception as e:
                    print("[livewire] commit failed (%s): %r"
                          % (ch["source"].get("name"), e))
            if committed:
                try:
                    from . import store
                    store.record(entry["display"])
                except Exception:
                    pass
            _nudge_burst(state.get("nsloc"),
                         (0, -1) if is_action else (1, 0))

        browser.show_browser(
            entries=entries,
            source=disp_source,
            mode=mode,
            kind=(surface or {}).get("kind", "batch"),
            chain=gang,
            on_commit=on_commit)
    QtCore.QTimer.singleShot(SETTLE_MS, show)


def _infer_socket(outs, anchor, samples, meta):
    """Which output socket was grabbed, from the grab point's offset to
    the node anchor. Returns a socket name or None (not confident)."""
    if len(outs) < 2 or not samples:
        return None
    pts = samples[:3]
    sx = sorted(p[0] for p in pts)[len(pts) // 2]
    sy = sorted(p[1] for p in pts)[len(pts) // 2]
    dx = sx - anchor[0]
    dy = sy - anchor[1]
    if meta and meta[1]:
        # Collapsed multichannel clip: it draws ONE stacked output, so
        # there is no per-socket geometry to read — inferring would map
        # the grab to an arbitrary middle channel (crypto, in practice).
        return None
    if meta:  # expanded multichannel clip
        visible = [o for o in outs if not o.endswith("_alpha")]
        step = SOCK_EXR_STEP
        top = (len(visible) - 1) / 2.0 * step - SOCK_EXR_PAD
        if dx < SOCK_EXR_XMIN:
            return None
    else:
        visible = outs
        step = SOCK_STD_STEP
        top = (len(visible) - 1) / 2.0 * step
        if dx < SOCK_STD_XMIN:
            return None
    idx = int(round((top - dy) / step))
    if not (0 <= idx < len(visible)):
        return None
    if abs((top - dy) - idx * step) > step * 0.5 + 1:
        return None
    return visible[idx]


def _decide_surface():
    """Called once, at fire time (release). Returns (surface, source).

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
    src = _find_source(bat_samples, _bat_map, with_sockets=True,
                       meta=_bat_meta)
    # Deliberate multi-select including the grabbed node: the other
    # selected nodes become additional sources (back pair, and beyond
    # once nodes with more input pairs are supported).
    if src is not None:
        try:
            ax, ay = next((x, y) for (n, x, y) in _bat_map
                          if n == src["name"])
            offs = [(round(sx - ax), round(sy - ay))
                    for (sx, sy) in bat_samples[:3]]
            if src["name"] in _bat_meta:
                src["multichannel"] = True
            gs = _infer_socket(src.get("sockets") or [], (ax, ay),
                               bat_samples, _bat_meta.get(src["name"]))
            if gs:
                src["grab_socket"] = gs
            _log("grab offsets vs %s anchor: %s -> socket %s"
                 % (src["name"], offs, gs))
        except Exception:
            pass
        sel = _selection_names()
        _log("selection at arm: %s (grab=%s)" % (sel, src["name"]))
        if len(sel) >= 2 and src["name"] in sel:
            src["extra"] = [{"name": n, "sockets": _output_sockets(n)}
                            for n in sel if n != src["name"]]
    return {"kind": "batch"}, src


def _snapshot_surfaces():
    """The press-time burst, deferred to the drag-live transition.

    Runs only once the pointer has produced two distinct
    cursor_position samples with the button down — i.e. a genuine
    schematic drag (Batch or Action: both cursor feeds stream during
    either; off-schematic both freeze). Never runs for Media-panel
    clicks, whose cursor_position stays frozen. See the CRITICAL note
    in _tick.
    """
    global _bat_types, _bat_map, _bat_meta, _act_obj, _act_name, _act_map
    if not hid.app_active():
        return
    _bat_types = {}
    _bat_map = _snapshot(_attr(flame.batch.nodes), _bat_types)
    _bat_meta = {}
    for n in _attr(flame.batch.nodes):
        try:
            if str(_attr(n.type)) != "Clip":
                continue
            nsock = len(_attr(n.output_sockets))
            if nsock <= 2:
                continue
            col = True
            try:
                col = bool(_attr(n.collapsed))
            except Exception:
                pass
            _bat_meta[str(_attr(n.name))] = (nsock, col)
        except Exception:
            pass
    _act_obj = _current_action()
    if _act_obj is not None:
        _act_name = str(_attr(_act_obj.name))
        _act_map = (_snapshot(_attr(_act_obj.nodes))
                    + _snapshot(_attr(_act_obj.media_nodes)))
    else:
        _act_name, _act_map = None, []


def _tick():
    global _btn, _armed, _to_front, _to_matte, _gang, _chain_sel, _pairs
    global _ingest, _bat_types, _bat_meta, _drag_live
    global _bat_map, _act_map, _act_name, _act_obj, _surface, _source, err
    try:
        btn = 1 if hid.button_down() else 0
        if btn and not _btn:
            # CRITICAL: touch NOTHING in the Flame node API at press.
            # The 2026-08-05 isolation ladder proved that any
            # PyBatch/PyNode access made while Flame is processing a
            # click (current_node, nodes iteration, attr reads — each
            # independently sufficient) breaks shift-select in the
            # Media panel. Quartz key/button polling and
            # flame.batch.cursor_position reads are proven safe under
            # sustained 30 ms polling. The snapshot is deferred to the
            # drag-live transition below; a Media-panel click leaves
            # cursor_position frozen, so it never triggers there.
            _pairs = []
            _armed = False
            _to_front = False
            _to_matte = False
            _gang = False
            _chain_sel = False
            _ingest = False
            _source = None
            _surface = None
            _bat_types = {}
            _bat_meta = {}
            _bat_map, _act_map = [], []
            _act_name, _act_obj = None, None
            _drag_live = False
            _pairs.append((_cpos_of(flame.batch), None))
        elif btn:
            pair = (_cpos_of(flame.batch),
                    _cpos_of(_act_obj) if _act_obj else None)
            if not _pairs or pair != _pairs[-1]:
                _pairs.append(pair)
                if len(_pairs) >= 2 and not _drag_live:
                    _drag_live = True
                    _snapshot_surfaces()
            # Key-state queries proved harmless in the ladder (rung 3),
            # but there is no reason to poll them outside a live drag.
            if (_bat_map or _act_map) and _drag_live:
                f_down = hid.key_down(KEY_FRONT)
                m_down = hid.key_down(KEY_MATTE)
                g_down = hid.key_down(KEY_GANG)
                c_down = hid.key_down(KEY_CHAINSEL)
                a_down = hid.key_down(KEY_INGEST)
                if f_down or m_down or g_down or c_down or a_down:
                    if not _armed:
                        _armed = True
                        _log("armed")
                    _to_front = _to_front or bool(f_down)
                    _to_matte = _to_matte or bool(m_down)
                    _gang = _gang or bool(g_down)
                    _chain_sel = _chain_sel or bool(c_down)
                    _ingest = _ingest or bool(a_down)
        elif _btn and not btn:
            if _armed:
                # Decide the surface at FIRE time, not arm time. With
                # the v1.3.0 deferred snapshot, Action cursor samples
                # only begin flowing on the tick AFTER drag-live; a
                # verb key already held when the drag starts arms on
                # the drag-live tick itself, where zero Action samples
                # exist and the decision would fall through to Batch
                # (2026-08-05: G-in-Action showed Batch nodes,
                # F-in-Action failed unless the key came late). By
                # release every sample exists.
                _surface, _source = _decide_surface()
                _log("fire [%s], source=%s"
                     % (_surface["kind"],
                        _source["name"] if _source else None))
                if (_ingest and _source is not None
                        and (_surface or {}).get("kind") != "action"
                        and _bat_types.get(_source["name"]) == "Action"):
                    # A on an Action in Batch: open the map-ingest table
                    src_name = _source["name"]

                    def open_mapper(src_name=src_name):
                        nsloc = hid.cursor_loc()
                        from . import actionmaps
                        actionmaps.show_mapper(
                            src_name,
                            on_done=lambda: _nudge_burst(nsloc))
                    QtCore.QTimer.singleShot(SETTLE_MS, open_mapper)
                else:
                    gang_like = _gang or _chain_sel
                    if _surface and _surface.get("kind") == "action":
                        mode = "child"
                        samples = [p[1] for p in _pairs if p[1] is not None]
                    else:
                        if _to_front and _to_matte:
                            mode = "front_matte"
                        elif _to_matte:
                            # gm/cm mirror fm: a gang's M means
                            # front+matte links
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
    if not hid.DARWIN and not getattr(hid, "LINUX_ENABLED", False):
        print("[livewire] Linux/X11 support is disabled pending "
              "validation of the event-driven XI2 backend. See "
              "livewire/hid.py and livewire/xi2.py.")
        return
    hid.start()
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
        hid.stop()
        _log("detector stopped")
    flame.schedule_idle_event(_stop)
