"""Type-to-narrow node browser popup.

Appears at the cursor after an armed noodle drop. A search field on top, a
narrowing list below. Up/Down navigate without leaving the field, Enter
commits the highlighted node type, Esc (or clicking elsewhere) cancels.
"""

from PySide6 import QtCore, QtGui, QtWidgets

WIDTH = 300
MAX_ROWS = 14
ROW_H = 24

_open = []

# Flame-native body (neutral charcoal, Discreet font, dense rows) with a
# single forge signature: the E87E24 orange accent on selection and focus.
ACCENT = "#E87E24"
ACCENT_HI = "#f59035"

_QSS = """
#livewirePanel {
    background: #2b2b2b;
    border: 1px solid #464646;
    border-radius: 3px;
    font-family: "Discreet";
}
QLabel#header {
    color: %(accent)s;
    font-family: "Discreet";
    font-size: 12px;
    padding: 1px 2px 0 2px;
}
QLineEdit {
    background: #1c1c1c;
    color: #d9d9d9;
    border: 1px solid #3d3d3d;
    border-radius: 2px;
    padding: 5px 7px;
    font-family: "Discreet";
    font-size: 13px;
    selection-background-color: %(accent)s;
    selection-color: #141414;
}
QLineEdit:focus { border-color: %(accent)s; }
QComboBox {
    background: #1c1c1c;
    color: #c4c4c4;
    border: 1px solid #3d3d3d;
    border-radius: 2px;
    padding: 3px 7px;
    font-family: "Discreet";
    font-size: 12px;
}
QComboBox QAbstractItemView {
    background: #222222;
    color: #c4c4c4;
    selection-background-color: %(accent)s;
    selection-color: #141414;
}
QListWidget {
    background: transparent;
    color: #b8b8b8;
    border: none;
    font-family: "Discreet";
    font-size: 13px;
    outline: none;
}
QListWidget::item { padding: 3px 7px; border-radius: 2px; }
QListWidget::item:selected { background: %(accent)s; color: #141414; }
QListWidget::item:hover { background: #383838; }
""" % {"accent": ACCENT}


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
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)

        if source and source.get("name"):
            header = QtWidgets.QLabel(self)
            header.setObjectName("header")
            suffix = u"  ·  front+matte" if matte_mode else u""
            header.setText(u"⤷ from  %s%s" % (source["name"], suffix))
            header.setTextFormat(QtCore.Qt.PlainText)
            lay.addWidget(header)
            sockets = source.get("sockets") or []
            if len(sockets) > 1 and not matte_mode:
                self._socket_combo = QtWidgets.QComboBox(self)
                self._socket_combo.addItems(sockets)
                if "Result" in sockets:
                    self._socket_combo.setCurrentText("Result")
                lay.addWidget(self._socket_combo)
            self._sockets = sockets
        else:
            self._sockets = []

        self._edit = QtWidgets.QLineEdit(self)
        self._edit.setPlaceholderText("node type…")
        self._edit.textChanged.connect(self._refilter)
        self._edit.installEventFilter(self)
        lay.addWidget(self._edit)

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
