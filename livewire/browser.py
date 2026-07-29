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

_QSS = """
#livewirePanel {
    background: #242424;
    border: 1px solid #4a4a4a;
    border-radius: 4px;
}
QLabel#header {
    color: #8f8f8f;
    font-size: 11px;
    padding: 2px 2px 0 2px;
}
QLineEdit {
    background: #171717;
    color: #e6e6e6;
    border: 1px solid #3d3d3d;
    border-radius: 3px;
    padding: 6px 8px;
    font-size: 13px;
    selection-background-color: #3d5a73;
}
QLineEdit:focus { border-color: #5a7d99; }
QComboBox {
    background: #171717;
    color: #cfcfcf;
    border: 1px solid #3d3d3d;
    border-radius: 3px;
    padding: 3px 8px;
    font-size: 12px;
}
QComboBox QAbstractItemView {
    background: #1e1e1e;
    color: #cfcfcf;
    selection-background-color: #3d5a73;
}
QListWidget {
    background: transparent;
    color: #c9c9c9;
    border: none;
    font-size: 13px;
    outline: none;
}
QListWidget::item { padding: 3px 8px; border-radius: 3px; }
QListWidget::item:selected { background: #3d5a73; color: #ffffff; }
"""


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

    def __init__(self, node_types, source, on_commit):
        super().__init__(None, QtCore.Qt.Popup | QtCore.Qt.FramelessWindowHint)
        self.setAttribute(QtCore.Qt.WA_DeleteOnClose)
        self.setObjectName("livewirePanel")
        self.setStyleSheet(_QSS)
        self.setFixedWidth(WIDTH)

        self._types = node_types
        self._on_commit = on_commit
        self._socket_combo = None

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)

        if source and source.get("name"):
            header = QtWidgets.QLabel(self)
            header.setObjectName("header")
            header.setText(u"⤷ from  %s" % source["name"])
            header.setTextFormat(QtCore.Qt.PlainText)
            lay.addWidget(header)
            sockets = source.get("sockets") or []
            if len(sockets) > 1:
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
        node_type = item.text()
        socket = self._current_socket()
        self.close()
        self._on_commit(node_type, socket)

    def closeEvent(self, ev):
        if self in _open:
            _open.remove(self)
        super().closeEvent(ev)


def show_browser(node_types, source, on_commit):
    close_all()
    w = NodeBrowser(node_types, source, on_commit)
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
    w.raise_()
    w.activateWindow()
    w._edit.setFocus()
    _open.append(w)
    return w


def close_all():
    for w in list(_open):
        try:
            w.close()
        except Exception:
            pass
    del _open[:]
