"""Type-to-narrow node browser popup.

Appears at the cursor after an armed noodle drop. A search field on top, a
narrowing list below. Up/Down navigate without leaving the field, Enter
commits the highlighted node type, Esc (or clicking elsewhere) cancels.
"""

from PySide6 import QtCore, QtGui, QtWidgets

WIDTH = 470
MAX_ROWS = 15
ROW_H = 25

_open = []

# Two skins over identical geometry (Discreet font, dense flat rows):
#   "flame" — faithful to Flame 2026's own node-search popup: neutral
#             charcoal, square corners, light-gray selection bar.
#   "forge" — same body, forge-orange E87E24 signature on selection/focus.
THEME = "flame"

THEMES = {
    "flame": {
        "font": '"Artifakt Element"',
        "panel_bg": "#252525", "panel_border": "#4e4e4e", "radius": "0px",
        "field_bg": "#0f0f0f", "field_border": "#6e6e6e",
        "field_focus": "#9a9a9a", "field_fg": "#d6d6d6",
        "row_fg": "#c8c8c8", "hover": "#313131",
        "sel_bg": "#56585a", "sel_fg": "#f2f2f2",
        "header_fg": "#909090",
    },
    "forge": {
        "font": '"Discreet"',
        "panel_bg": "#2b2b2b", "panel_border": "#464646", "radius": "2px",
        "field_bg": "#1c1c1c", "field_border": "#3d3d3d",
        "field_focus": "#E87E24", "field_fg": "#d9d9d9",
        "row_fg": "#b8b8b8", "hover": "#383838",
        "sel_bg": "#E87E24", "sel_fg": "#141414",
        "header_fg": "#E87E24",
    },
}

_QSS = """
#livewirePanel {
    background: %(panel_bg)s;
    border: 1px solid %(panel_border)s;
    border-radius: %(radius)s;
    font-family: %(font)s;
}
QLabel#header {
    color: %(header_fg)s;
    font-family: %(font)s;
    font-size: 12px;
    padding: 1px 2px 0 2px;
}
QLineEdit {
    background: %(field_bg)s;
    color: %(field_fg)s;
    border: 1px solid %(field_border)s;
    border-radius: %(radius)s;
    padding: 6px 8px;
    font-family: %(font)s;
    font-size: 14px;
    selection-background-color: %(sel_bg)s;
    selection-color: %(sel_fg)s;
}
QLineEdit:focus { border-color: %(field_focus)s; }
QComboBox {
    background: %(field_bg)s;
    color: %(row_fg)s;
    border: 1px solid %(field_border)s;
    border-radius: %(radius)s;
    padding: 3px 8px;
    font-family: %(font)s;
    font-size: 13px;
}
QComboBox QAbstractItemView {
    background: %(panel_bg)s;
    color: %(row_fg)s;
    selection-background-color: %(sel_bg)s;
    selection-color: %(sel_fg)s;
}
QListWidget {
    background: transparent;
    color: %(row_fg)s;
    border: none;
    font-family: %(font)s;
    font-size: 14px;
    outline: none;
}
QListWidget::item { padding: 4px 10px; }
QListWidget::item:selected { background: %(sel_bg)s; color: %(sel_fg)s; }
QListWidget::item:hover { background: %(hover)s; }
""" % THEMES[THEME]


def _rank(query, name):
    """Lower is better; None means no match."""
    q, n = query.lower(), name.lower()
    if not q:
        return (3, n)
    if n.startswith(q):
        return (0, n)
    if any(w.startswith(q) for w in n.split()):
        return (1, n)
    if q in n:
        return (2, n)
    it = iter(n)
    if all(c in it for c in q):
        return (3, n)
    return None


class NodeBrowser(QtWidgets.QWidget):

    def __init__(self, node_types, source, on_commit, matte_mode=False):
        super().__init__(None, QtCore.Qt.Tool
                         | QtCore.Qt.FramelessWindowHint
                         | QtCore.Qt.WindowStaysOnTopHint)
        self.setAttribute(QtCore.Qt.WA_DeleteOnClose)
        self.setObjectName("livewirePanel")
        self.setStyleSheet(_QSS)
        self.setFixedWidth(WIDTH)

        self._types = node_types
        self._on_commit = on_commit
        self._socket_combo = None
        self._committed = False

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(1, 1, 1, 1)
        lay.setSpacing(0)

        top = QtWidgets.QWidget(self)
        tlay = QtWidgets.QVBoxLayout(top)
        tlay.setContentsMargins(8, 8, 8, 7)
        tlay.setSpacing(6)
        lay.addWidget(top)

        def _add(widget):
            tlay.addWidget(widget)

        if source and source.get("name"):
            header = QtWidgets.QLabel(self)
            header.setObjectName("header")
            suffix = u"  ·  front+matte" if matte_mode else u""
            header.setText(u"⤷ from  %s%s" % (source["name"], suffix))
            header.setTextFormat(QtCore.Qt.PlainText)
            _add(header)
            sockets = source.get("sockets") or []
            if len(sockets) > 1 and not matte_mode:
                self._socket_combo = QtWidgets.QComboBox(self)
                self._socket_combo.addItems(sockets)
                if "Result" in sockets:
                    self._socket_combo.setCurrentText("Result")
                _add(self._socket_combo)
            self._sockets = sockets
        else:
            self._sockets = []

        self._edit = QtWidgets.QLineEdit(self)
        self._edit.setPlaceholderText("Search for...")
        self._edit.textChanged.connect(self._refilter)
        self._edit.installEventFilter(self)
        _add(self._edit)

        self._list = QtWidgets.QListWidget(self)
        self._list.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self._list.itemActivated.connect(lambda _i: self._commit())
        self._list.itemClicked.connect(lambda _i: self._commit())
        lay.addWidget(self._list)

        self._refilter("")

    # -- filtering ---------------------------------------------------------

    def _refilter(self, text):
        ranked = []
        for t in self._types:
            r = _rank(text, t)
            if r is not None:
                ranked.append((r, t))
        ranked.sort()
        self._list.clear()
        for _r, t in ranked[:MAX_ROWS * 4]:
            self._list.addItem(t)
        if self._list.count():
            self._list.setCurrentRow(0)
        rows = min(self._list.count(), MAX_ROWS)
        self._list.setFixedHeight(max(rows, 1) * ROW_H + 4)
        self.adjustSize()

    # -- keys --------------------------------------------------------------

    def eventFilter(self, obj, ev):
        if obj is self._edit and ev.type() == QtCore.QEvent.KeyPress:
            key = ev.key()
            if key in (QtCore.Qt.Key_Down, QtCore.Qt.Key_Up):
                row = self._list.currentRow()
                row += 1 if key == QtCore.Qt.Key_Down else -1
                row = max(0, min(row, self._list.count() - 1))
                self._list.setCurrentRow(row)
                return True
            if key in (QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter):
                self._commit()
                return True
            if key == QtCore.Qt.Key_Escape:
                self.close()
                return True
        return False

    # -- commit ------------------------------------------------------------

    def _current_socket(self):
        if self._socket_combo is not None:
            return self._socket_combo.currentText()
        if self._sockets:
            return "Result" if "Result" in self._sockets else self._sockets[0]
        return None

    def _commit(self):
        item = self._list.currentItem()
        if item is None:
            return
        self._committed = True
        node_type = item.text()
        socket = self._current_socket()
        self.close()
        self._on_commit(node_type, socket)

    # Close when the user clicks away (Tool windows don't auto-dismiss
    # like Popup, but Popup can never become the macOS key window inside
    # Flame's natively-focused fullscreen app).
    def changeEvent(self, ev):
        if (ev.type() == QtCore.QEvent.ActivationChange
                and not self.isActiveWindow() and not self._committed):
            self.close()
        super().changeEvent(ev)

    def closeEvent(self, ev):
        if self in _open:
            _open.remove(self)
        super().closeEvent(ev)


def _force_key(w):
    """Make the popup the macOS key window; Flame's native fullscreen
    window otherwise keeps keyboard focus and typing never reaches Qt."""
    try:
        import objc
        nsview = objc.objc_object(c_void_p=int(w.winId()))
        nswin = nsview.window()
        if nswin is not None:
            nswin.makeKeyAndOrderFront_(None)
    except Exception as e:
        print("[livewire] makeKey failed: %r" % e)
    w.raise_()
    w.activateWindow()
    w._edit.setFocus(QtCore.Qt.OtherFocusReason)


def show_browser(node_types, source, on_commit, matte_mode=False):
    close_all()
    w = NodeBrowser(node_types, source, on_commit, matte_mode=matte_mode)
    pos = QtGui.QCursor.pos()
    screen = QtGui.QGuiApplication.screenAt(pos)
    w.adjustSize()
    x, y = pos.x() - 24, pos.y() - 16
    if screen is not None:
        geo = screen.availableGeometry()
        x = max(geo.left(), min(x, geo.right() - w.width()))
        y = max(geo.top(), min(y, geo.bottom() - w.height()))
    w.move(x, y)
    w.show()
    _force_key(w)
    QtCore.QTimer.singleShot(80, lambda: w.isVisible() and _force_key(w))
    _open.append(w)
    return w


def close_all():
    for w in list(_open):
        try:
            w.close()
        except Exception:
            pass
    del _open[:]
