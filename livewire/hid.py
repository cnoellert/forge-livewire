"""Platform shim: raw input polling and repaint nudging.

Everything OS-specific lives here. The detector talks only to:
    button_down() -> bool        left mouse button, raw HID/X state
    key_down(ch)  -> bool        letter key by character, e.g. "f"
    app_active()  -> bool        is Flame the foreground app
    cursor_loc()  -> (x, y)|None screen coords in the platform's native
                                 space (only ever fed back to nudge())
    nudge(loc)                   synthetic no-op input event to make
                                 Flame repaint (see FINDINGS)

macOS: Quartz event-source state polling + an NSMouseMoved posted to
Flame's main window (in-process, no permissions).
Linux/X11: XQueryPointer / XQueryKeymap via ctypes into libX11 — READ
ONLY. The X11 side never injects input and never touches focus; both
were tried and both caused problems (see the note in the linux
branch). No dependencies beyond libX11.
"""

import sys

DARWIN = sys.platform == "darwin"

# Linux/X11 is DISABLED pending a redesign (2026-08-04). The 30 ms
# XQueryPointer/XQueryKeymap poll loop breaks Flame's keyboard
# handling: with livewire running, Shift stopped working in the Media
# panel; stopping the detector's timer restored it immediately, with no
# restart and no other change. Read-only X access was not enough — the
# polling itself is the problem. The likely fix is to stop polling and
# instead select XInput2 raw events once and drain them (no per-tick
# round trips), but that needs a test host, not a working artist's box.
# Set LINUX_ENABLED = True only on a machine you can afford to disturb.
LINUX_ENABLED = False

if DARWIN:
    import Quartz

    _VKEYS = {"f": 3, "m": 46, "g": 5, "r": 15, "i": 34}
    _ST = Quartz.kCGEventSourceStateCombinedSessionState

    def button_down():
        return bool(Quartz.CGEventSourceButtonState(_ST, 0))

    def key_down(ch):
        return bool(Quartz.CGEventSourceKeyState(_ST, _VKEYS[ch]))

    def app_active():
        try:
            import AppKit
            return bool(AppKit.NSApp.isActive())
        except Exception:
            return True

    def cursor_loc():
        try:
            import AppKit
            p = AppKit.NSEvent.mouseLocation()  # bottom-left origin
            return (float(p.x), float(p.y))
        except Exception:
            return None

    def force_focus(window_id):
        pass  # macOS focus is the NSWindow makeKey dance in browser.py

    def release_focus():
        pass  # macOS returns focus to Flame on its own

    def nudge(loc=None):
        """Post a synthetic mouse-move to Flame's main window, aimed at
        loc (native screen coords) so the right panel repaints."""
        try:
            import AppKit
            app = AppKit.NSApplication.sharedApplication()
            main = None
            for w in app.windows():
                try:
                    f = w.frame()
                    if w.isVisible() and (
                            main is None
                            or f.size.width > main.frame().size.width):
                        main = w
                except Exception:
                    pass
            if main is None:
                return
            mtype = getattr(AppKit, "NSEventTypeMouseMoved",
                            getattr(AppKit, "NSMouseMoved", 5))
            f = main.frame()
            if loc is not None:
                p = (loc[0] - float(f.origin.x),
                     loc[1] - float(f.origin.y))
            else:
                p = (f.size.width / 2.0, f.size.height / 2.0)
            ev = (AppKit.NSEvent.
                  mouseEventWithType_location_modifierFlags_timestamp_windowNumber_context_eventNumber_clickCount_pressure_(
                      mtype, p, 0, 0.0, main.windowNumber(), None,
                      0, 0, 0.0))
            app.postEvent_atStart_(ev, False)
        except Exception:
            pass

else:
    import ctypes
    import ctypes.util

    _x11 = None
    _xtst = None
    _dpy = None
    _root = None
    _keycodes = {}

    def _init():
        global _x11, _xtst, _dpy, _root
        if _dpy is not None:
            return True
        try:
            _x11 = ctypes.CDLL(ctypes.util.find_library("X11")
                               or "libX11.so.6")
            _x11.XOpenDisplay.restype = ctypes.c_void_p
            _x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
            _dpy = _x11.XOpenDisplay(None)
            if not _dpy:
                return False
            _x11.XRootWindow.restype = ctypes.c_ulong
            _x11.XRootWindow.argtypes = [ctypes.c_void_p, ctypes.c_int]
            screen = _x11.XDefaultScreen(ctypes.c_void_p(_dpy))
            _root = _x11.XRootWindow(ctypes.c_void_p(_dpy), screen)
            try:
                _xtst = ctypes.CDLL(ctypes.util.find_library("Xtst")
                                    or "libXtst.so.6")
            except Exception:
                _xtst = None
            return True
        except Exception:
            _dpy = None
            return False

    def _keycode(ch):
        kc = _keycodes.get(ch)
        if kc is None and _init():
            ks = _x11.XStringToKeysym(ch.encode())
            kc = _x11.XKeysymToKeycode(ctypes.c_void_p(_dpy), ks)
            _keycodes[ch] = kc
        return kc or 0

    def button_down():
        if not _init():
            return False
        root_ret = ctypes.c_ulong()
        child_ret = ctypes.c_ulong()
        rx = ctypes.c_int(); ry = ctypes.c_int()
        wx = ctypes.c_int(); wy = ctypes.c_int()
        mask = ctypes.c_uint()
        _x11.XQueryPointer(ctypes.c_void_p(_dpy), _root,
                           ctypes.byref(root_ret), ctypes.byref(child_ret),
                           ctypes.byref(rx), ctypes.byref(ry),
                           ctypes.byref(wx), ctypes.byref(wy),
                           ctypes.byref(mask))
        return bool(mask.value & 0x100)  # Button1Mask

    def key_down(ch):
        if not _init():
            return False
        keys = (ctypes.c_char * 32)()
        _x11.XQueryKeymap(ctypes.c_void_p(_dpy), keys)
        kc = _keycode(ch)
        if not kc:
            return False
        return bool(ord(keys[kc // 8]) & (1 << (kc % 8)))

    def app_active():
        # v1: assume yes; the grab-point candidate guard already keeps
        # stray non-Flame drags from arming anything meaningful.
        return True

    def cursor_loc():
        if not _init():
            return None
        root_ret = ctypes.c_ulong()
        child_ret = ctypes.c_ulong()
        rx = ctypes.c_int(); ry = ctypes.c_int()
        wx = ctypes.c_int(); wy = ctypes.c_int()
        mask = ctypes.c_uint()
        _x11.XQueryPointer(ctypes.c_void_p(_dpy), _root,
                           ctypes.byref(root_ret), ctypes.byref(child_ret),
                           ctypes.byref(rx), ctypes.byref(ry),
                           ctypes.byref(wx), ctypes.byref(wy),
                           ctypes.byref(mask))
        return (float(rx.value), float(ry.value))

    # X11 backend is deliberately READ-ONLY: it queries pointer and key
    # state and never mutates X. Two mutations were tried and removed —
    # XTest pointer jiggle (unnecessary: Linux Flame repaints commits
    # immediately) and XSetInputFocus for the popup (it broke Flame's
    # modifier tracking — Shift stopped working in the Media panel,
    # because stealing X focus while a modifier is held robs Flame of
    # the KeyRelease). Qt's activateWindow alone gives the popup focus
    # on X11, as originally validated. Do not reintroduce either.

    def nudge(loc=None):
        pass

    def force_focus(window_id):
        pass

    def release_focus():
        pass
