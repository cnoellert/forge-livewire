"""evdev input reader — the Linux backend that owes X nothing.

Both X-based approaches (30 ms polling, then passive XI2 raw-event
selection) broke Flame's keyboard handling on Rocky — two unrelated
mechanisms, identical Shift symptom, identical instant recovery on
stop (see FINDINGS). This reader bypasses the X protocol entirely: it
reads `/dev/input/event*` — the kernel interface underneath X — on a
dedicated thread. It cannot interact with any X client because it
never speaks X.

Requires read access to /dev/input/event* (input group membership, or
an ACL). Kernel keycodes are physical-layout codes, independent of X
keymaps. Reading evdev does not consume events (no EVIOCGRAB — every
other consumer still sees everything).

Standalone validation, outside Flame:

    python3 evdev_reader.py [seconds]
"""

import glob
import os
import select
import struct
import sys
import threading

# struct input_event on 64-bit: struct timeval (2x long) + u16 type
# + u16 code + s32 value = 24 bytes
_EV_FMT = "<qqHHi"
_EV_SIZE = struct.calcsize(_EV_FMT)

EV_KEY = 0x01
BTN_LEFT = 0x110

# kernel keycodes (linux/input-event-codes.h) — physical, layout-free
_KEYCODES = {"f": 33, "m": 50, "g": 34, "r": 19, "i": 23}


class Reader(object):
    """Owns the event-device fds on one thread; publishes input state
    as plain Python attributes (same surface as the xi2 Reader)."""

    def __init__(self, chars=("f", "m", "g", "r", "i")):
        self.button1 = False
        self.keys = set()        # chars currently held
        self.error = None
        self.events_seen = 0
        self._code2ch = {c: ch for ch, c in _KEYCODES.items()
                         if ch in chars}
        self._stop = threading.Event()
        self._thread = None

    # -- lifecycle (any thread) --

    def start(self):
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run,
                                        name="livewire-evdev",
                                        daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        t = self._thread
        if t is not None:
            t.join(timeout=2.0)
        self._thread = None

    # -- reader thread only --

    def _run(self):
        try:
            self._loop()
        except Exception as e:
            self.error = repr(e)

    def _open_all(self):
        fds = {}
        for path in sorted(glob.glob("/dev/input/event*")):
            try:
                fds[os.open(path, os.O_RDONLY | os.O_NONBLOCK)] = path
            except OSError:
                pass
        return fds

    def _loop(self):
        fds = self._open_all()
        if not fds:
            raise RuntimeError("no readable /dev/input/event* devices "
                               "(input group / ACL missing?)")
        try:
            while not self._stop.is_set():
                ready, _, _ = select.select(list(fds), [], [], 0.05)
                for fd in ready:
                    try:
                        buf = os.read(fd, _EV_SIZE * 64)
                    except OSError:
                        # device unplugged; drop it, keep going
                        os.close(fd)
                        fds.pop(fd, None)
                        if not fds:
                            raise RuntimeError("all input devices lost")
                        continue
                    for off in range(0, len(buf) - _EV_SIZE + 1,
                                     _EV_SIZE):
                        _, _, etype, code, value = struct.unpack_from(
                            _EV_FMT, buf, off)
                        if etype == EV_KEY:
                            self._dispatch(code, value)
        finally:
            for fd in list(fds):
                try:
                    os.close(fd)
                except OSError:
                    pass

    def _dispatch(self, code, value):
        self.events_seen += 1
        if code == BTN_LEFT:
            if value == 1:
                self.button1 = True
            elif value == 0:
                self.button1 = False
            return
        ch = self._code2ch.get(code)
        if ch is None:
            return
        if value == 1:            # press (2 = autorepeat: keep held)
            self.keys.add(ch)
        elif value == 0:          # release
            self.keys.discard(ch)


def _main():
    import time
    secs = float(sys.argv[1]) if len(sys.argv) > 1 else 15.0
    r = Reader()
    r.start()
    print("evdev reader up for %.0fs — use the mouse, tap f/m/g/r/i ..."
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
    print("done: %d key/button events seen, error=%s"
          % (r.events_seen, r.error), flush=True)


if __name__ == "__main__":
    _main()
