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

# Two skins over identical geometry (Discreet font, dense flat rows):
#   "flame" — faithful to Flame 2026's own node-search popup: neutral
#             charcoal, square corners, light-gray selection bar.
#   "forge" — same body, forge-orange E87E24 signature on selection/focus.
THEME = "flame"

THEMES = {
    "flame": {
        "panel_bg": "#262626", "panel_border": "#4e4e4e", "radius": "0px",
        "field_bg": "#131313", "field_border": "#5a5a5a",
        "field_focus": "#8a8a8a", "field_fg": "#d6d6d6",
        "row_fg": "#c0c0c0", "hover": "#3a3d42",
        "alt_bg": "#2e3033",
        "sel_bg": "#57595b", "sel_fg": "#f2f2f2",
        "header_fg": "#909090",
    },
    "forge": {
        "panel_bg": "#2b2b2b", "panel_border": "#464646", "radius": "2px",
        "field_bg": "#1c1c1c", "field_border": "#3d3d3d",
        "field_focus": "#E87E24", "field_fg": "#d9d9d9",
        "row_fg": "#b8b8b8", "hover": "#383838",
        "alt_bg": "#313131",
        "sel_bg": "#E87E24", "sel_fg": "#141414",
        "header_fg": "#E87E24",
    },
}

_QSS = """
#livewirePanel {
    background: %(panel_bg)s;
    border: 1px solid %(panel_border)s;
    border-radius: %(radius)s;
    font-family: "Discreet";
}
QLabel#header {
    color: %(header_fg)s;
    font-family: "Discreet";
    font-size: 12px;
    padding: 1px 2px 0 2px;
}
QLineEdit {
    background: %(field_bg)s;
    color: %(field_fg)s;
    border: 1px solid %(field_border)s;
    border-radius: %(radius)s;
    padding: 5px 7px;
    font-family: "Discreet";
    font-size: 13px;
    selection-background-color: %(sel_bg)s;
    selection-color: %(sel_fg)s;
}
QLineEdit:focus { border-color: %(field_focus)s; }
QComboBox {
    background: %(field_bg)s;
    color: %(row_fg)s;
    border: 1px solid %(field_border)s;
    border-radius: %(radius)s;
    padding: 3px 7px;
    font-family: "Discreet";
    font-size: 12px;
}
QComboBox QAbstractItemView {
    background: %(panel_bg)s;
    color: %(row_fg)s;
    selection-background-color: %(sel_bg)s;
    selection-color: %(sel_fg)s;
}
QListWidget {
    background: transparent;
    alternate-background-color: %(alt_bg)s;
    color: %(row_fg)s;
    border: none;
    font-family: "Discreet";
    font-size: 13px;
    outline: none;
}
QListWidget::item { padding: 3px 7px; border-radius: %(radius)s; }
QListWidget::item:selected { background: %(sel_bg)s; color: %(sel_fg)s; }
QListWidget::item:hover { background: %(hover)s; }
""" % THEMES[THEME]


def _match(query, text):
    """Lower is better; None means no match."""
    q, n = query.lower(), text.lower()
    if not q:
        return 3
    if n.startswith(q):
        return 0
    if any(w.startswith(q) for w in n.split()):
        return 1
    if q in n:
        return 2
    it = iter(n)
    if all(c in it for c in q):
        return 3
    return None


def _rank(query, entry):
    """Sort key: match quality, then pinned/favorite, then a usage score
    (livewire's own commit counts weighted over Flame's search weights),
    then recency, then name. Tags (Flame's search synonyms + the
    artist's own) match at substring quality."""
    from . import store
    disp = entry["display"]
    m = _match(query, disp)
    if m is None and query:
        hay = " ".join((entry.get("tags") or [])
                       + (store.tags().get(disp) or []))
        if hay and query.lower() in hay.lower():
            m = 2
    if m is None:
        return None
    u = store.usage().get(disp) or {}
    pin = entry.get("fav") or disp in store.pinned()
    score = u.get("n", 0) * 4 + entry.get("weight", 0)
    return (m, 0 if pin else 1, -score, -u.get("t", 0), disp.lower())


class _RowIcons(QtWidgets.QStyledItemDelegate):
    """Star (pin) and tag controls on the current row, Flame-style.
    Drawn as vector paths — Discreet's glyph coverage is not trusted."""

    ICON_W = 20

    def __init__(self, browser):
        super().__init__(browser)
        self._browser = browser

    def _rects(self, opt):
        r = opt.rect
        tag = QtCore.QRect(r.right() - self.ICON_W - 4,
                           r.top(), self.ICON_W, r.height())
        star = QtCore.QRect(tag.left() - self.ICON_W,
                            r.top(), self.ICON_W, r.height())
        return star, tag

    @staticmethod
    def _star_path(rect):
        import math
        cx, cy = rect.center().x(), rect.center().y() + 0.5
        R, r = rect.height() * 0.28, rect.height() * 0.115
        path = QtGui.QPainterPath()
        for i in range(10):
            ang = -math.pi / 2 + i * math.pi / 5
            rad = R if i % 2 == 0 else r
            pt = QtCore.QPointF(cx + rad * math.cos(ang),
                                cy + rad * math.sin(ang))
            if i == 0:
                path.moveTo(pt)
            else:
                path.lineTo(pt)
        path.closeSubpath()
        return path

    def paint(self, p, opt, index):
        super().paint(p, opt, index)
        if not (opt.state & QtWidgets.QStyle.State_Selected):
            return
        entry = index.data(QtCore.Qt.UserRole)
        if not entry:
            return
        from . import store
        star, tag = self._rects(opt)
        p.save()
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        pinned = (entry.get("fav")
                  or entry["display"] in store.pinned())
        col = QtGui.QColor(opt.palette.highlightedText().color())
        p.setPen(QtGui.QPen(col, 1.1))
        p.setBrush(col if pinned else QtCore.Qt.NoBrush)
        p.drawPath(self._star_path(star))
        # tag: a little label shape with a hole
        t = tag.adjusted(4, tag.height() // 2 - 5, -4, 0)
        t.setHeight(10)
        p.setBrush(QtCore.Qt.NoBrush)
        body = QtGui.QPainterPath()
        body.moveTo(t.left() + 3, t.top())
        body.lineTo(t.right() - 4, t.top())
        body.lineTo(t.right(), t.center().y())
        body.lineTo(t.right() - 4, t.bottom())
        body.lineTo(t.left() + 3, t.bottom())
        body.closeSubpath()
        p.drawPath(body)
        p.drawEllipse(QtCore.QPointF(t.left() + 6, t.center().y()), 1.2, 1.2)
        p.restore()

    def editorEvent(self, ev, model, opt, index):
        # swallow BOTH press and release over the icons — the release
        # would otherwise reach itemClicked and commit the row
        if ev.type() in (QtCore.QEvent.MouseButtonPress,
                         QtCore.QEvent.MouseButtonRelease) \
                and (opt.state & QtWidgets.QStyle.State_Selected):
            star, tag = self._rects(opt)
            entry = index.data(QtCore.Qt.UserRole)
            if entry and (star.contains(ev.pos())
                          or tag.contains(ev.pos())):
                if ev.type() == QtCore.QEvent.MouseButtonPress:
                    from . import store
                    if star.contains(ev.pos()):
                        store.toggle_pin(entry["display"])
                        self._browser._list.viewport().update()
                    else:
                        self._browser._edit_tags(entry)
                return True
        return False


class NodeBrowser(QtWidgets.QWidget):

    def __init__(self, entries, source, on_commit, mode="front",
                 kind="batch", chain=False):
        super().__init__(None, QtCore.Qt.Tool
                         | QtCore.Qt.FramelessWindowHint
                         | QtCore.Qt.WindowStaysOnTopHint)
        self.setAttribute(QtCore.Qt.WA_DeleteOnClose)
        self.setObjectName("livewirePanel")
        self.setStyleSheet(_QSS)
        self.setFixedWidth(WIDTH)

        self._entries = entries
        self._on_commit = on_commit
        self._socket_combo = None
        self._committed = False
        self._chain = chain
        self._source = source
        self._trail = [source["name"]] if (source and source.get("name")) \
            else []
        self._header = None

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)

        self._kind = kind
        self._mode = mode
        if chain or (source and source.get("name")):
            self._header = QtWidgets.QLabel(self)
            self._header.setObjectName("header")
            self._header.setTextFormat(QtCore.Qt.PlainText)
            self._update_header()
            lay.addWidget(self._header)
        if source and source.get("name"):
            sockets = source.get("sockets") or []
            if len(sockets) > 1 and kind != "action" and mode != "front_matte":
                self._socket_combo = QtWidgets.QComboBox(self)
                self._socket_combo.addItems(sockets)
                # the socket the artist actually grabbed wins; then the
                # mode heuristics; then Result
                default = source.get("grab_socket")
                if default not in sockets:
                    default = None
                if default is None and mode == "matte":
                    default = next((s for s in sockets
                                    if "matte" in s.lower()), None)
                if default is None and "Result" in sockets:
                    default = "Result"
                if default:
                    self._socket_combo.setCurrentText(default)
                lay.addWidget(self._socket_combo)
            self._sockets = sockets
        else:
            self._sockets = []

        self._edit = QtWidgets.QLineEdit(self)
        self._edit.setPlaceholderText("Search for...")
        self._edit.textChanged.connect(self._refilter)
        self._edit.installEventFilter(self)
        lay.addWidget(self._edit)

        self._list = QtWidgets.QListWidget(self)
        self._list.setAlternatingRowColors(True)
        self._list.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        self._list.setItemDelegate(_RowIcons(self))
        self._list.itemActivated.connect(lambda _i: self._commit())
        self._list.itemClicked.connect(lambda _i: self._commit())
        lay.addWidget(self._list)

        self._refilter("")

    # -- header ------------------------------------------------------------

    def _update_header(self):
        if self._header is None:
            return
        extras = (self._source or {}).get("extra") or []
        back = (u"   back  %s" % ", ".join(e["name"] for e in extras)
                if extras else u"")
        if self._chain:
            trail = "  >  ".join(self._trail) if self._trail else "(new)"
            self._header.setText(u"gang  %s%s" % (trail, back))
        elif self._kind == "action":
            self._header.setText(u"parent  %s" % self._trail[0])
        else:
            suffix = {"matte": u"  (to matte)",
                      "front_matte": u"  (front+matte)"}.get(self._mode, u"")
            self._header.setText(u"from  %s%s%s"
                                 % (self._trail[0], suffix, back))

    # -- filtering ---------------------------------------------------------

    def _refilter(self, text):
        ranked = []
        for e in self._entries:
            r = _rank(text, e)
            if r is not None:
                ranked.append((r, e))
        ranked.sort(key=lambda re_: re_[0])
        self._list.clear()
        for _r, e in ranked[:MAX_ROWS * 8]:
            item = QtWidgets.QListWidgetItem(e["display"])
            item.setData(QtCore.Qt.UserRole, e)
            self._list.addItem(item)
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

    # -- tags --------------------------------------------------------------

    def _edit_tags(self, entry):
        """Tiny popover editing the entry's custom tags, comma-separated."""
        from . import store
        disp = entry["display"]
        pop = QtWidgets.QWidget(None, QtCore.Qt.Tool
                                | QtCore.Qt.FramelessWindowHint
                                | QtCore.Qt.WindowStaysOnTopHint)
        pop.setAttribute(QtCore.Qt.WA_DeleteOnClose)
        pop.setObjectName("livewirePanel")
        pop.setStyleSheet(_QSS)
        lay = QtWidgets.QVBoxLayout(pop)
        lay.setContentsMargins(8, 8, 8, 8)
        head = QtWidgets.QLabel(u"tags  %s" % disp, pop)
        head.setObjectName("header")
        lay.addWidget(head)
        edit = QtWidgets.QLineEdit(pop)
        edit.setText(", ".join(store.tags().get(disp) or []))
        lay.addWidget(edit)

        def done():
            store.set_tags(disp, edit.text().split(","))
            pop.close()
        edit.returnPressed.connect(done)

        # the popover takes key focus: suspend the browser's
        # close-on-deactivate until it's gone, then take focus back
        self._suspend_close = True

        def restore(_=None):
            self._suspend_close = False
            if self.isVisible():
                _force_key(self)
        pop.destroyed.connect(restore)

        pop.setFixedWidth(280)
        pos = QtGui.QCursor.pos()
        pop.move(pos.x() - 20, pos.y() + 12)
        pop.show()
        _force_key(pop)
        edit.setFocus(QtCore.Qt.OtherFocusReason)
        self._tag_pop = pop  # keep a ref

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
        entry = item.data(QtCore.Qt.UserRole)
        socket = self._current_socket()
        if self._chain:
            # gang mode: commit and stay open for the next pick
            self._on_commit(entry, socket)
            self._trail.append(entry["label"])
            self._update_header()
            self._edit.clear()
            self._edit.setFocus(QtCore.Qt.OtherFocusReason)
            self.adjustSize()
            return
        self._committed = True
        self.close()
        self._on_commit(entry, socket)

    # Close when the user clicks away (Tool windows don't auto-dismiss
    # like Popup, but Popup can never become the macOS key window inside
    # Flame's natively-focused fullscreen app).
    def changeEvent(self, ev):
        if (ev.type() == QtCore.QEvent.ActivationChange
                and not self.isActiveWindow() and not self._committed
                and not getattr(self, "_suspend_close", False)):
            self.close()
        super().changeEvent(ev)

    def closeEvent(self, ev):
        if self in _open:
            _open.remove(self)
        super().closeEvent(ev)


def _force_key(w):
    """Make the popup the key window; Flame's native fullscreen window
    otherwise keeps keyboard focus and typing never reaches Qt. The
    NSWindow dance is macOS-only; on X11 activateWindow suffices."""
    import sys
    if sys.platform == "darwin":
        try:
            import objc
            nsview = objc.objc_object(c_void_p=int(w.winId()))
            nswin = nsview.window()
            if nswin is not None:
                nswin.makeKeyAndOrderFront_(None)
        except Exception as e:
            print("[livewire] makeKey failed: %r" % e)
    else:
        from . import hid
        hid.force_focus(int(w.winId()))
    w.raise_()
    w.activateWindow()
    edit = getattr(w, "_edit", None)
    if edit is not None:
        edit.setFocus(QtCore.Qt.OtherFocusReason)


def show_browser(entries, source, on_commit, mode="front", kind="batch",
                 chain=False):
    close_all()
    w = NodeBrowser(entries, source, on_commit, mode=mode, kind=kind,
                    chain=chain)
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
