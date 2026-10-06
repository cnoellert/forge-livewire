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

# Two skins over identical geometry (dense flat rows), switchable live
# from the pill switch in the popup's header; the choice persists in
# ~/.config/livewire.json ("theme"). THEME is only the first-run default.
#   "forge" — the FORGE family look (forge-hud / forge-takes): translucent
#             slate panel, rounded, #3a3f4f border, the host's system UI
#             font (the family never names one), small bold uppercase
#             #8a93a4 labels, menu-blue #2d4f7a selection, ember focus.
#   "flame" — faithful to Flame 2026's own node-search popup: Discreet,
#             neutral charcoal, square corners, light-gray selection bar.
THEME = "forge"
EMBER = "#E87E24"

THEMES = {
    "flame": {
        "panel_rgba": (38, 38, 38, 255), "panel_border": "#4e4e4e",
        "panel_radius": 0, "radius": "0px",
        "font": 'font-family: "Discreet";',
        "field_bg": "#131313", "field_border": "#5a5a5a",
        "field_focus": "#8a8a8a", "field_fg": "#d6d6d6",
        "row_fg": "#c0c0c0", "alt_bg": "#2e3033",
        "sel_bg": "#57595b", "sel_fg": "#f2f2f2",
        "view_bg": "#262626", "view_border": "#4e4e4e",
        "scroll": "#5a5a5a", "scroll_radius": "0px",
        # header: verb words / names / dim suffixes
        "hdr_verb": "#909090", "hdr_name": "#909090", "hdr_dim": "#909090",
        "hdr_upper": False,
        "hdr_verb_css": "",
    },
    "forge": {
        "panel_rgba": (20, 22, 28, 235), "panel_border": "#3a3f4f",
        "panel_radius": 9, "radius": "3px",
        "font": "",
        "field_bg": "#0f1116", "field_border": "#3a3f4f",
        "field_focus": EMBER, "field_fg": "#dddddd",
        "row_fg": "#cccccc", "alt_bg": "#1a1d24",
        "sel_bg": "#2d4f7a", "sel_fg": "#ffffff",
        "view_bg": "#23262f", "view_border": "#3a3f4f",
        "scroll": "#3a3f4f", "scroll_radius": "3px",
        "hdr_verb": "#8a93a4", "hdr_name": "#dddddd", "hdr_dim": "#666666",
        "hdr_upper": True,
        "hdr_verb_css": "font-size: 10px; font-weight: bold; ",
    },
}

# The panel body itself is painted (paint_panel: rounded + translucent
# needs WA_TranslucentBackground, which can't be flipped after show), so
# the sheet only styles the children.
_QSS = """
#livewirePanel { %(font)s }
QLabel#header { %(font)s font-size: 11px; padding: 1px 2px 0 2px; }
QLineEdit {
    background: %(field_bg)s;
    color: %(field_fg)s;
    border: 1px solid %(field_border)s;
    border-radius: %(radius)s;
    padding: 5px 7px;
    %(font)s
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
    %(font)s
    font-size: 12px;
}
QComboBox QAbstractItemView {
    background: %(view_bg)s;
    color: %(row_fg)s;
    border: 1px solid %(view_border)s;
    outline: none;
    padding: 2px;
    selection-background-color: %(sel_bg)s;
    selection-color: %(sel_fg)s;
}
QListWidget {
    background: transparent;
    alternate-background-color: %(alt_bg)s;
    color: %(row_fg)s;
    border: none;
    %(font)s
    font-size: 13px;
    outline: none;
}
QListWidget::item { padding: 3px 7px; border-radius: %(radius)s; }
QListWidget::item:selected { background: %(sel_bg)s; color: %(sel_fg)s; }
QScrollBar:vertical {
    background: transparent; width: 6px; margin: 2px 0 2px 0;
}
QScrollBar::handle:vertical {
    background: %(scroll)s; border-radius: %(scroll_radius)s;
    min-height: 24px;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0; border: none; background: none;
}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
    background: none;
}
"""


class ThemeSwitch(QtWidgets.QAbstractButton):
    """Tiny painted pill switch: ember = FORGE, grey = Flame. Painted,
    not a glyph (same reasoning as forge-hud's grip), and NoFocus so
    the search field keeps every key. Its handler must only restyle —
    see the controls NOTE on NodeBrowser."""

    W, H = 22, 12

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setFocusPolicy(QtCore.Qt.NoFocus)
        self.setFixedSize(self.W, self.H)
        self.setToolTip("FORGE theme")

    def paintEvent(self, _ev):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        on = self.isChecked()
        r = self.H / 2.0
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(QtGui.QColor(EMBER if on else "#3a3f4f"))
        p.drawRoundedRect(QtCore.QRectF(0, 0, self.W, self.H), r, r)
        d = self.H - 4
        x = self.W - d - 2 if on else 2
        p.setBrush(QtGui.QColor("#f2f2f2" if on else "#8a93a4"))
        p.drawEllipse(QtCore.QRectF(x, 2, d, d))


def _theme_name():
    from . import store
    name = store.theme(THEME)
    return name if name in THEMES else THEME


def _qss(name):
    return _QSS % THEMES[name]


def _header_html(segs, name):
    """Header segments as rich text in theme *name*: forge-hud's row
    titles (small bold uppercase grey) for verbs, bright names."""
    import html
    t = THEMES[name]
    out = []
    for kind, text in segs:
        text = html.escape(text)
        if kind == "verb":
            if t["hdr_upper"]:
                text = text.upper()
            out.append(u'<span style="%scolor: %s;">%s</span>'
                       % (t["hdr_verb_css"], t["hdr_verb"], text))
        else:
            out.append(u'<span style="color: %s;">%s</span>'
                       % (t["hdr_%s" % kind], text))
    # plain spaces kept by white-space: pre, NOT &nbsp; — Discreet maps
    # U+00A0 to a stray glyph ("fromÊÊSET_prerender", 2026-10-05)
    return u'<span style="white-space: pre;">%s</span>' % u"  ".join(out)


def paint_panel(w, name):
    """Paint the panel body for theme *name* on a translucent widget."""
    t = THEMES[name]
    p = QtGui.QPainter(w)
    p.setRenderHint(QtGui.QPainter.Antialiasing)
    p.setBrush(QtGui.QColor(*t["panel_rgba"]))
    p.setPen(QtGui.QPen(QtGui.QColor(t["panel_border"]), 1))
    r = t["panel_radius"]
    p.drawRoundedRect(QtCore.QRectF(w.rect()).adjusted(0.5, 0.5, -0.5, -0.5),
                      r, r)
# No ::item:hover rule, deliberately: the post-commit repaint nudge
# sweeps synthetic mouse moves from the drop point (where this popup
# sits) toward the freshly placed nodes, and a hover highlight turns
# that sweep into a phantom "selection" marching down the list
# (2026-08-05, Action gangs — the sweep direction there is straight
# down the rows). The list is keyboard-driven; hover feedback isn't
# worth the artifact.


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


# NOTE: interactive pin/tag controls crashed Flame twice (2026-08-04:
# QStyledItemDelegate row icons, then Ctrl+P / Ctrl+T via the event
# filter). Best explanation since 1.3.4: the commit nudge's synchronous
# sendPostedEvents() deleted this WA_DeleteOnClose widget mid-handler.
# Other suspects still worth respecting: Qt6 dropped QMouseEvent.pos(),
# and exceptions inside a delegate unwind through Qt's C++ dispatch.
# Pins and tags remain file-edited in ~/.config/livewire.json.


class NodeBrowser(QtWidgets.QWidget):

    def __init__(self, entries, source, on_commit, mode="front",
                 kind="batch", chain=False):
        super().__init__(None, QtCore.Qt.Tool
                         | QtCore.Qt.FramelessWindowHint
                         | QtCore.Qt.WindowStaysOnTopHint)
        self.setAttribute(QtCore.Qt.WA_DeleteOnClose)
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground)
        self.setObjectName("livewirePanel")
        self._theme = _theme_name()
        self.setStyleSheet(_qss(self._theme))
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
        # header row: context label left, FORGE theme tick right. The
        # tick is the popup's only non-keyboard control — NoFocus so the
        # search field keeps the keys, and its handler only restyles
        # (no timers, no close, no Flame API). See the NOTE below.
        hrow = QtWidgets.QHBoxLayout()
        hrow.setContentsMargins(0, 0, 0, 0)
        hrow.setSpacing(6)
        if chain or (source and source.get("name")):
            self._header = QtWidgets.QLabel(self)
            self._header.setObjectName("header")
            self._header.setTextFormat(QtCore.Qt.RichText)
            self._update_header()
            hrow.addWidget(self._header, 1)
        else:
            hrow.addStretch(1)
        self._tick = ThemeSwitch(self)
        self._tick.setChecked(self._theme == "forge")
        self._tick.toggled.connect(self._set_theme)
        hrow.addWidget(self._tick, 0, QtCore.Qt.AlignVCenter)
        lay.addLayout(hrow)
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
                    # the image output's _alpha sibling is the matte on
                    # multichannel clips; never a Cryptomatte_* layer
                    img = ("Result" if "Result" in sockets
                           else (sockets[0] if sockets else None))
                    sib = (img + "_alpha") if img else None
                    if sib in sockets:
                        default = sib
                    else:
                        default = next(
                            (s for s in sockets if "matte" in s.lower()
                             and "crypto" not in s.lower()), None)
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
        self._list.itemActivated.connect(lambda _i: self._commit())
        self._list.itemClicked.connect(lambda _i: self._commit())
        lay.addWidget(self._list)

        self._refilter("")

    # -- theme -------------------------------------------------------------

    def _set_theme(self, forge):
        self._theme = "forge" if forge else "flame"
        self.setStyleSheet(_qss(self._theme))
        self._update_header()
        self._refilter(self._edit.text())
        self.update()
        try:
            from . import store
            store.set_theme(self._theme)
        except Exception:
            pass
        self._edit.setFocus(QtCore.Qt.OtherFocusReason)

    def paintEvent(self, _ev):
        paint_panel(self, self._theme)

    # -- header ------------------------------------------------------------

    def _update_header(self):
        if self._header is None:
            return
        if not self._trail and not self._chain:
            self._header.setText(u"")
            return
        segs = []
        if self._chain:
            segs += [("verb", u"gang"),
                     ("name", u"  >  ".join(self._trail) if self._trail
                      else u"(new)")]
        elif self._kind == "action":
            segs += [("verb", u"parent"), ("name", self._trail[0])]
        else:
            segs += [("verb", u"from"), ("name", self._trail[0])]
            suffix = {"matte": u"to matte",
                      "front_matte": u"front+matte"}.get(self._mode)
            if suffix:
                segs.append(("dim", u"(%s)" % suffix))
        extras = (self._source or {}).get("extra") or []
        if extras:
            segs += [("verb", u"back"),
                     ("name", u", ".join(e["name"] for e in extras))]
        self._header.setText(_header_html(segs, self._theme))

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
        # the real row height (it follows the theme's font): a fixed
        # ROW_H that disagreed left a half row peeking at the bottom
        row_h = self._list.sizeHintForRow(0)
        if row_h <= 0:
            row_h = ROW_H
        self._list.setFixedHeight(max(rows, 1) * row_h + 4)
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

    # NOTE: interactive pin/tag controls crashed Flame twice
    # (2026-08-04), most likely via the since-fixed 1.3.4
    # use-after-free (the commit nudge flushed this widget's
    # DeferredDelete mid-handler), not controls as such — see ROADMAP.
    # Keep any control NoFocus, and never close, commit, or pump
    # events from its handler.

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
            # Keep the just-committed entry selected by IDENTITY, not
            # row index: clearing the filter rebuilds the list, and
            # index-based selection made the highlight creep down the
            # list on every chained commit (2026-08-05, Action gangs).
            # Repeated Enters now re-commit the same pick.
            for i in range(self._list.count()):
                if self._list.item(i).data(QtCore.Qt.UserRole) is entry:
                    self._list.setCurrentRow(i)
                    self._list.scrollToItem(self._list.item(i))
                    break
            self._edit.setFocus(QtCore.Qt.OtherFocusReason)
            self.adjustSize()
            return
        # hide, commit, THEN close: close() posts this WA_DeleteOnClose
        # widget's DeferredDelete, and anything in the commit that
        # flushes posted events would destroy us while we are still on
        # our own eventFilter stack (2026-10-05: SIGSEGV/SIGILL right
        # after createNode/connectNodes).
        self._committed = True
        self.hide()
        try:
            self._on_commit(entry, socket)
        finally:
            self.close()

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
        import sys
        if sys.platform != "darwin":
            # hand keyboard focus back — on X11 a closed popup can
            # otherwise leave X input focus on a destroyed window
            try:
                from . import hid
                hid.release_focus()
            except Exception:
                pass
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
