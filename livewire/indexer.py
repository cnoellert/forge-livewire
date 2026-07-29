"""Build the browsable entry index: node types, Matchbox shaders,
OpenFX plugins, and user-bin setups, ranked by Flame's own usage data.

Entry shape:
    {"display": "Lens_Blur - User",   # what the list shows / matches on
     "label":   "Lens_Blur",
     "kind":    "node" | "matchbox" | "ofx" | "userbin",
     "payload": <type name | shader path | plugin label | setup path>,
     "fav":     bool,                  # Flame search favorite
     "weight":  int}                   # Flame search usage weight

Sources of truth:
- Matchbox: filesystem scan of the stock shader dir for the running
  Flame version plus EXTRA_MATCHBOX_DIRS (.mx / .glsl, top level only).
- User bins: ~/Library/Preferences/Autodesk/flame/batch/pref/_user.*.batch
- OpenFX: labels harvested from Flame's search_settings.json (entries
  typed "OpenFX" — i.e. plugins the artist has used), any Nuke OFX
  plugin cache on the machine (full OfxPropLabel inventory), and
  plugin_name of OpenFX nodes in the current batch. change_plugin()
  accepts display labels only and silently no-ops on unknown ones.
- Ranking: Weight / Favorite from search_settings.json, matched by name.
"""

import glob
import json
import os
import re

import flame

# Additional shader directories (e.g. a studio Logik collection).
EXTRA_MATCHBOX_DIRS = []

_SEARCH_SETTINGS = os.path.expanduser(
    "~/Library/Preferences/Autodesk/flame/search/search_settings.json")
_USER_BIN_DIR = os.path.expanduser(
    "~/Library/Preferences/Autodesk/flame/batch/pref")
_NUKE_CACHE_GLOB = "/var/tmp/nuke-*/ofxplugincache/*.xml"

_cache = None


def _attr(v):
    return v.get_value() if hasattr(v, "get_value") else v


def _flame_version():
    for fn in ("get_version", "get_version_major"):
        try:
            return str(getattr(flame, fn)())
        except Exception:
            continue
    return None


def _stock_matchbox_dirs():
    cands = sorted(glob.glob("/opt/Autodesk/presets/*/matchbox/shaders"))
    ver = _flame_version()
    if ver:
        hit = [c for c in cands if "/presets/%s/" % ver in c]
        if hit:
            return hit
    return cands[-1:]  # newest install as fallback


def _search_meta():
    """name -> (weight, favorite); plus the set of used OFX labels."""
    meta, ofx = {}, set()
    try:
        with open(_SEARCH_SETTINGS) as f:
            tools = json.load(f)["SearchSettings"]["Tools"]
        for t in tools:
            name = t.get("Name")
            if not name:
                continue
            old = meta.get(name, (0, False))
            meta[name] = (max(old[0], int(t.get("Weight", 0))),
                          old[1] or bool(t.get("Favorite")))
            if t.get("Type") == "OpenFX":
                ofx.add(name)
    except Exception:
        pass
    return meta, ofx


def _nuke_ofx_labels():
    labels = set()
    for path in glob.glob(_NUKE_CACHE_GLOB):
        try:
            with open(path, errors="replace") as f:
                s = f.read()
            labels.update(re.findall(
                r'OfxPropLabel" type="string" dimension="1" >\s*'
                r'<value index="0" value="([^"]+)"', s))
        except Exception:
            pass
    return labels


def _batch_ofx_labels():
    labels = set()
    try:
        for n in _attr(flame.batch.nodes):
            try:
                if str(_attr(n.type)) == "OpenFX":
                    p = str(_attr(n.plugin_name))
                    if p:
                        labels.add(p)
            except Exception:
                pass
    except Exception:
        pass
    return labels


def _entry(display, label, kind, payload, meta):
    w, fav = meta.get(label, meta.get(display, (0, False)))
    return {"display": display, "label": label, "kind": kind,
            "payload": payload, "fav": fav, "weight": w}


def build(node_types):
    """Assemble the full entry list. node_types: list of batch type names."""
    meta, used_ofx = _search_meta()
    entries = []
    seen = set()

    for t in node_types:
        entries.append(_entry(t, t, "node", t, meta))
        seen.add(t)

    for d in _stock_matchbox_dirs() + list(EXTRA_MATCHBOX_DIRS):
        for path in sorted(glob.glob(os.path.join(d, "*.mx"))
                           + glob.glob(os.path.join(d, "*.glsl"))):
            stem = os.path.splitext(os.path.basename(path))[0]
            key = ("matchbox", stem)
            if key in seen:
                continue
            seen.add(key)
            entries.append(_entry("%s - Matchbox" % stem, stem,
                                  "matchbox", path, meta))

    for path in sorted(glob.glob(os.path.join(_USER_BIN_DIR,
                                              "_user.*.batch"))):
        stem = os.path.basename(path)[len("_user."):-len(".batch")]
        entries.append(_entry("%s - User" % stem, stem,
                              "userbin", path, meta))

    for label in sorted(used_ofx | _nuke_ofx_labels() | _batch_ofx_labels()):
        entries.append(_entry("%s - OpenFX" % label, label,
                              "ofx", label, meta))

    return entries


def entries(node_types):
    global _cache
    if _cache is None:
        _cache = build(node_types)
    return _cache


def refresh():
    global _cache
    _cache = None
