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
Linux/X11: event-driven — an XInput2 raw-event reader thread (xi2.py)
owning its own connection; Flame's threads make zero X calls. Strictly
hands-off otherwise: no synthetic input, no focus calls. start()/stop()
manage the reader; both are no-ops on macOS.
"""

import sys

DARWIN = sys.platform == "darwin"

# Linux/X11 backend, take two: EVENT-DRIVEN via XInput2 raw events
# (see xi2.py). The original 30 ms XQueryPointer/XQueryKeymap poll
# loop broke Flame's keyboard handling — Shift died in the Media panel
# and revived the instant the timer stopped; read-only access did not
# help, the synchronous per-tick round trips were the cause. The xi2
# reader makes ZERO X calls from Flame's threads: a dedicated thread
# owns its own connection and drains raw events via select().
# Linux status (2026-08-05): ENABLED. The evdev backend is complete —
# gesture engine validated in-Flame over PCoIP, device rescan handles
# PCoIP reconnects. The Shift saga's true root cause (Flame node-API
# access during click processing — see FINDINGS' isolation ladder) is
# fixed as of v1.3.x, and a full-day soak on flame-01 (2026-08-05,
# heavy regression + surface probing + real use) ran clean. The two
# 2026-08-04 hard crashes never recurred and predate the v1.3.x
# restructuring; if a crash pattern reappears, park the hook and
# re-open FINDINGS.
LINUX_ENABLED = True

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

    def start():
        pass  # Quartz state queries need no reader thread

    def stop():
        pass

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
    # evdev, not X: both X approaches broke Flame's Shift handling
    # (see FINDINGS). xi2.py stays in-tree as the record of why.
    from . import evdev_reader

    _reader = None

    def start():
        """Start the evdev reader thread (idempotent)."""
        global _reader
        if _reader is None:
            _reader = evdev_reader.Reader()
            _reader.start()

    def stop():
        global _reader
        if _reader is not None:
            _reader.stop()
            _reader = None

    def button_down():
        return _reader.button1 if _reader is not None else False

    def key_down(ch):
        return (ch in _reader.keys) if _reader is not None else False

    def app_active():
        return True

    def cursor_loc():
        # only ever consumed by nudge(), which is a no-op on Linux
        return None

    # X11 is strictly hands-off: no synthetic input, no focus calls,
    # and (now) no polling. See FINDINGS for the history.
    def nudge(loc=None):
        pass

    def force_focus(window_id):
        pass

    def release_focus():
        pass

