"""Action input capture: scan an Action's media inputs, guess each
pass's map type from its feeder's name, confirm in a table, and create
+ bind the map nodes inside the Action.

Scan side: `action.media_nodes` are the batch-side Action Media nodes;
each one's `.sockets` dict names the node feeding its Front input.
`action.media_layers` strings ("(1) (clipname)") add a clip-name hint.
Commit side: `action.create_node(<map type>)` +
`map.assign_media(<media name>)`, optionally parented under a surface
via `action.connect_nodes(surface, map)`.
"""

import re

import flame
from PySide6 import QtCore, QtWidgets

from . import browser

# Ordered, specific → generic. Matched (lowercased) against the feeder
# node name, then the media layer/clip string.
PASS_RULES = [
    (r'normal|nrml?\b|_n\b', "Normal Map"),
    (r'motion|vector|\bmv\b|vel|flow', "Motion Vectors Map"),
    (r'position|pworld|pref\b|\bpos\b', "Position Map"),
    (r'depth|zdepth|\bz\b', "Z-Depth Map"),
    (r'\buv\b|\bst\b|texcoord', "UV Map"),
    (r'spec', "Specular Map"),
    (r'emiss|emit|incand', "Emissive Map"),
    (r'displac|height|bump', "Displace Map"),
    (r'reflect', "Reflection Map"),
    (r'crypto|obj_?id|\bid\b', "Object ID Map"),
    (r'albedo|diffuse|beauty|\bbty\b|base_?colou?r', "Diffuse Map"),
]

SKIP = "(skip)"
MAP_TYPES = [SKIP, "Diffuse Map", "Normal Map", "Motion Vectors Map",
             "Position Map", "Z-Depth Map", "UV Map", "Specular Map",
             "Emissive Map", "Displace Map", "Reflection Map",
             "Parallax Map", "PBS Map", "Object ID Map"]

SURFACE_TYPES = ("Surface", "Extended Bicubic", "3D Shape", "3D Text",
                 "Deform Mesh")

MAP_ROW_DY = 250   # created maps sit in a row this far below the scene
MAP_STEP_X = 160

_open = []


def _attr(v):
    return v.get_value() if hasattr(v, "get_value") else v


def guess(feeder, layer_hint):
    text = " ".join(x for x in (feeder, layer_hint) if x).lower()
    for pat, map_type in PASS_RULES:
        if re.search(pat, text):
            return map_type
    return SKIP


def scan(action_name):
    """[{media, feeder, hint, guess}] for each media of the action."""
    a = flame.batch.get_node(action_name)
    layers = [str(x) for x in _attr(a.media_layers)]
    rows = []
    for i, mn in enumerate(_attr(a.media_nodes)):
        media = str(_attr(mn.name))
        feeder = None
        try:
            socks = _attr(mn.sockets)
            front = (socks.get("input") or {}).get("Front") or []
            feeder = front[0] if front else None
        except Exception:
            pass
        hint = None
        if i < len(layers):
            m = re.search(r'\(\d+\)\s*\((.+)\)', layers[i])
            if m and m.group(1) != "None":
                hint = m.group(1)
        rows.append({"media": media, "feeder": feeder, "hint": hint,
                     "guess": guess(feeder, hint)})
    return rows


def surfaces(action_name):
    a = flame.batch.get_node(action_name)
    out = []
    for n in _attr(a.nodes):
        try:
            if str(_attr(n.type)) in SURFACE_TYPES:
                out.append(str(_attr(n.name)))
        except Exception:
            pass
    return out


def ingest(action_name, choices, parent_name=None):
    """choices: [(media_name, map_type)] with SKIP rows removed."""
    a = flame.batch.get_node(action_name)
    xs, ys = [], []
    for n in _attr(a.nodes):
        try:
            xs.append(float(_attr(n.pos_x)))
            ys.append(float(_attr(n.pos_y)))
        except Exception:
            pass
    base_x = min(xs) if xs else 0
    base_y = (min(ys) if ys else 0) - MAP_ROW_DY
    parent = a.get_node(parent_name) if parent_name else None
    made = []
    for i, (media, map_type) in enumerate(choices):
        node = a.create_node(map_type)
        try:
            node.pos_x = int(base_x + i * MAP_STEP_X)
            node.pos_y = int(base_y)
        except Exception:
            pass
        node.assign_media(media)
        if parent is not None:
            try:
                a.connect_nodes(parent, node)
            except Exception as e:
                print("[livewire] map parent failed (%s): %r"
                      % (map_type, e))
        made.append(map_type)
    return made


class MapperDialog(QtWidgets.QWidget):

    def __init__(self, action_name, rows, surface_names, on_done):
        super().__init__(None, QtCore.Qt.Tool
                         | QtCore.Qt.FramelessWindowHint
                         | QtCore.Qt.WindowStaysOnTopHint)
        self.setAttribute(QtCore.Qt.WA_DeleteOnClose)
        self.setObjectName("livewirePanel")
        self.setStyleSheet(browser._QSS)
        self._action = action_name
        self._rows = rows
        self._on_done = on_done
        self._combos = []
        self._done = False

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(10, 9, 10, 9)
        lay.setSpacing(6)

        header = QtWidgets.QLabel(u"ingest  %s  (%d inputs)"
                                  % (action_name, len(rows)), self)
        header.setObjectName("header")
        lay.addWidget(header)

        grid = QtWidgets.QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(4)
        for r, row in enumerate(rows):
            feeder = row["feeder"] or row["hint"] or "(unconnected)"
            grid.addWidget(QtWidgets.QLabel(row["media"], self), r, 0)
            grid.addWidget(QtWidgets.QLabel(feeder, self), r, 1)
            combo = QtWidgets.QComboBox(self)
            combo.addItems(MAP_TYPES)
            combo.setCurrentText(row["guess"])
            grid.addWidget(combo, r, 2)
            self._combos.append(combo)
        lay.addLayout(grid)

        prow = QtWidgets.QHBoxLayout()
        prow.addWidget(QtWidgets.QLabel("parent under", self))
        self._parent = QtWidgets.QComboBox(self)
        self._parent.addItem("(no parent)")
        self._parent.addItems(surface_names)
        if surface_names:
            self._parent.setCurrentIndex(1)
        prow.addWidget(self._parent, 1)
        lay.addLayout(prow)

        btns = QtWidgets.QHBoxLayout()
        btns.addStretch(1)
        ok = QtWidgets.QPushButton("Ingest", self)
        ok.setDefault(True)
        ok.clicked.connect(self._commit)
        btns.addWidget(ok)
        lay.addLayout(btns)

    def keyPressEvent(self, ev):
        if ev.key() in (QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter):
            self._commit()
        elif ev.key() == QtCore.Qt.Key_Escape:
            self.close()
        else:
            super().keyPressEvent(ev)

    def _commit(self):
        if self._done:
            return
        self._done = True
        choices = []
        for row, combo in zip(self._rows, self._combos):
            map_type = combo.currentText()
            if map_type != SKIP:
                choices.append((row["media"], map_type))
        parent = self._parent.currentText()
        if parent == "(no parent)":
            parent = None
        self.close()
        try:
            made = ingest(self._action, choices, parent)
            print("[livewire] ingested %d maps into %s"
                  % (len(made), self._action))
        except Exception as e:
            print("[livewire] ingest failed: %r" % e)
        if self._on_done:
            self._on_done()

    def changeEvent(self, ev):
        if (ev.type() == QtCore.QEvent.ActivationChange
                and not self.isActiveWindow() and not self._done):
            self.close()
        super().changeEvent(ev)

    def closeEvent(self, ev):
        if self in _open:
            _open.remove(self)
        try:
            from . import hid
            QtCore.QTimer.singleShot(80, hid.resync_modifiers)
        except Exception:
            pass
        super().closeEvent(ev)


def show_mapper(action_name, on_done=None):
    rows = scan(action_name)
    if not rows:
        print("[livewire] %s has no media inputs to ingest" % action_name)
        return None
    for w in list(_open):
        try:
            w.close()
        except Exception:
            pass
    d = MapperDialog(action_name, rows, surfaces(action_name), on_done)
    from PySide6 import QtGui
    pos = QtGui.QCursor.pos()
    d.adjustSize()
    d.move(pos.x() - 30, pos.y() - 20)
    d.show()
    browser._force_key(d)
    QtCore.QTimer.singleShot(
        80, lambda: d.isVisible() and browser._force_key(d))
    _open.append(d)
    return d
