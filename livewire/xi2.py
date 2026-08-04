"""XInput2 raw-event reader — the event-driven Linux input backend.

Replaces X polling entirely. The old backend made two synchronous
round trips into the X server every 30 ms from Flame's main thread
(XQueryPointer/XQueryKeymap) and that alone broke Flame's keyboard
handling — Shift died in the Media panel and revived the instant the
poll timer stopped (see FINDINGS). This module:

- opens its OWN X connection,
- selects XI2 *raw* button/key events on the root window once
  (raw events are duplicated to every client that asked; delivery
  cannot affect any other client — this is how on-screen key display
  tools coexist with everything), and
- drains them on a DEDICATED thread that select()s on the connection's
  fd with a timeout — interruptible, and zero server round trips when
  idle.

Flame's main thread never touches X: the detector reads two plain
Python attributes (`button1`, `keys`).

Self-contained on purpose — runnable standalone, OUTSIDE Flame, to
validate the plumbing and (crucially) that a running reader does not
disturb the desktop's keyboard handling:

    DISPLAY=:1 python3 xi2.py [seconds]
"""

import ctypes
import ctypes.util
import select
import sys
import threading

# X11 / XInput2 constants
GenericEvent = 35
XIAllMasterDevices = 1
XI_RawKeyPress = 13
XI_RawKeyRelease = 14
XI_RawButtonPress = 15
XI_RawButtonRelease = 16
Button1 = 1


class XGenericEventCookie(ctypes.Structure):
    _fields_ = [("type", ctypes.c_int), ("serial", ctypes.c_ulong),
                ("send_event", ctypes.c_int), ("display", ctypes.c_void_p),
                ("extension", ctypes.c_int), ("evtype", ctypes.c_int),
                ("cookie", ctypes.c_uint), ("data", ctypes.c_void_p)]


class XIRawEvent(ctypes.Structure):
    _fields_ = [("type", ctypes.c_int), ("serial", ctypes.c_ulong),
                ("send_event", ctypes.c_int), ("display", ctypes.c_void_p),
                ("extension", ctypes.c_int), ("evtype", ctypes.c_int),
                ("time", ctypes.c_ulong), ("deviceid", ctypes.c_int),
                ("sourceid", ctypes.c_int), ("detail", ctypes.c_int),
                ("flags", ctypes.c_int)]  # valuator tail unused


class XIEventMask(ctypes.Structure):
    _fields_ = [("deviceid", ctypes.c_int), ("mask_len", ctypes.c_int),
                ("mask", ctypes.POINTER(ctypes.c_ubyte))]


class Reader(object):
    """Owns one X connection on one thread; publishes input state as
    plain Python attributes. Nothing else may touch the Display."""

    def __init__(self, chars=("f", "m", "g", "r", "i")):
        self.button1 = False
        self.keys = set()        # chars from `chars` currently held
        self.error = None
        self.events_seen = 0     # diagnostics
        self._chars = chars
        self._kc2ch = {}
        self._stop = threading.Event()
        self._thread = None

    # -- lifecycle (any thread) --

    def start(self):
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run,
                                        name="livewire-xi2", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        t = self._thread
        if t is not None:
            t.join(timeout=2.0)
        self._thread = None

    # -- everything below runs ONLY on the reader thread --

    def _run(self):
        try:
            self._loop()
        except Exception as e:
            self.error = repr(e)

    def _loop(self):
        x = ctypes.CDLL(ctypes.util.find_library("X11") or "libX11.so.6")
        xi = ctypes.CDLL(ctypes.util.find_library("Xi") or "libXi.so.6")
        x.XOpenDisplay.restype = ctypes.c_void_p
        x.XOpenDisplay.argtypes = [ctypes.c_char_p]
        dpy = x.XOpenDisplay(None)
        if not dpy:
            raise RuntimeError("XOpenDisplay failed (DISPLAY unset?)")
        dp = ctypes.c_void_p(dpy)
        try:
            # XI2 presence + opcode (needed to recognise our events)
            opcode = ctypes.c_int()
            ev_base = ctypes.c_int()
            err_base = ctypes.c_int()
            if not x.XQueryExtension(dp, b"XInputExtension",
                                     ctypes.byref(opcode),
                                     ctypes.byref(ev_base),
                                     ctypes.byref(err_base)):
                raise RuntimeError("XInputExtension not present")
            major = ctypes.c_int(2)
            minor = ctypes.c_int(0)
            xi.XIQueryVersion(dp, ctypes.byref(major), ctypes.byref(minor))

            x.XRootWindow.restype = ctypes.c_ulong
            x.XRootWindow.argtypes = [ctypes.c_void_p, ctypes.c_int]
            root = x.XRootWindow(dp, x.XDefaultScreen(dp))

            # arm-key keycode map (one-time lookups on our connection)
            for ch in self._chars:
                ks = x.XStringToKeysym(ch.encode())
                kc = x.XKeysymToKeycode(dp, ks)
                if kc:
                    self._kc2ch[int(kc)] = ch

            # select raw button/key events on the root window
            nbytes = (XI_RawButtonRelease >> 3) + 1
            buf = (ctypes.c_ubyte * nbytes)()
            for evt in (XI_RawKeyPress, XI_RawKeyRelease,
                        XI_RawButtonPress, XI_RawButtonRelease):
                buf[evt >> 3] |= (1 << (evt & 7))
            mask = XIEventMask(XIAllMasterDevices, nbytes, buf)
            xi.XISelectEvents(dp, ctypes.c_ulong(root),
                              ctypes.byref(mask), 1)
            x.XFlush(dp)

            # seed current button state (single round trip, at init only)
            r = ctypes.c_ulong(); c = ctypes.c_ulong()
            rx = ctypes.c_int(); ry = ctypes.c_int()
            wx = ctypes.c_int(); wy = ctypes.c_int()
            m = ctypes.c_uint()
            x.XQueryPointer(dp, ctypes.c_ulong(root), ctypes.byref(r),
                            ctypes.byref(c), ctypes.byref(rx),
                            ctypes.byref(ry), ctypes.byref(wx),
                            ctypes.byref(wy), ctypes.byref(m))
            self.button1 = bool(m.value & 0x100)

            fd = x.XConnectionNumber(dp)
            evbuf = (ctypes.c_char * 192)()
            while not self._stop.is_set():
                ready, _, _ = select.select([fd], [], [], 0.05)
                if not ready:
                    continue
                while x.XPending(dp):
                    x.XNextEvent(dp, evbuf)
                    cookie = ctypes.cast(
                        evbuf, ctypes.POINTER(XGenericEventCookie)).contents
                    if (cookie.type != GenericEvent
                            or cookie.extension != opcode.value):
                        continue
                    if not x.XGetEventData(dp, ctypes.byref(cookie)):
                        continue
                    try:
                        raw = ctypes.cast(
                            cookie.data,
                            ctypes.POINTER(XIRawEvent)).contents
                        self._dispatch(cookie.evtype, raw.detail)
                    finally:
                        x.XFreeEventData(dp, ctypes.byref(cookie))
        finally:
            try:
                x.XCloseDisplay(dp)
            except Exception:
                pass

    def _dispatch(self, evtype, detail):
        self.events_seen += 1
        if evtype == XI_RawButtonPress and detail == Button1:
            self.button1 = True
        elif evtype == XI_RawButtonRelease and detail == Button1:
            self.button1 = False
        elif evtype == XI_RawKeyPress:
            ch = self._kc2ch.get(detail)
            if ch:
                self.keys.add(ch)
        elif evtype == XI_RawKeyRelease:
            ch = self._kc2ch.get(detail)
            if ch:
                self.keys.discard(ch)


def _main():
    """Standalone validation, OUTSIDE Flame: report raw-event traffic
    and state transitions while the operator uses the desktop."""
    import time
    secs = float(sys.argv[1]) if len(sys.argv) > 1 else 15.0
    r = Reader()
    r.start()
    print("xi2 reader up for %.0fs — use the mouse, tap f/m/g/r/i ..."
          % secs, flush=True)
    last = (None, None)
    t0 = time.time()
    while time.time() - t0 < secs:
        cur = (r.button1, tuple(sorted(r.keys)))
        if cur != last:
            print("  t=%5.2f  button1=%-5s keys=%s"
                  % (time.time() - t0, cur[0], list(cur[1])), flush=True)
            last = cur
        if r.error:
            print("  READER ERROR:", r.error, flush=True)
            break
        time.sleep(0.02)
    r.stop()
    print("done: %d raw events seen, error=%s"
          % (r.events_seen, r.error), flush=True)


if __name__ == "__main__":
    _main()
