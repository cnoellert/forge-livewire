# Passoff — 2026-08-04 (end of the "Shift" session)

Read this first, then [FINDINGS.md](FINDINGS.md). It is written for a
session starting cold.

## State right now

- **Livewire is DISABLED on both machines.** Hooks moved to
  `/tmp/livewire_hook.py.disabled` on portofino (macOS) and flame-01
  (Rocky). Running sessions had the detector stopped and modules
  unloaded. Nothing auto-loads on restart.
- Repo is clean and pushed; tip is v1.2.0 (`4cd92dd`). Tag `v1.0.0`
  marks the last release believed fully healthy in daily use.
- **Everything about livewire's *features* works** — the whole verb
  grammar (F/G/R/I), channel fan-out, socket inference, the index,
  Action support — on macOS and (validated) on Linux via evdev.
  Nothing below is about features.

## The one open bug

**With livewire's detector timer running, Shift-select stops working
in Flame's Media panel. Stop the timer and it works again instantly,
same session, no restart.** Reproduced on macOS (portofino) and Linux
(flame-01), i.e. across two completely different input backends.

### What is actually established (trust only this)

1. Timer running → Media-panel shift-select broken. Timer stopped →
   fixed immediately, no restart. Clean same-session bisect, both
   directions, macOS.
2. The symptom is **specific to the Media panel**; schematic work is
   unaffected (nobody holds a modifier there).
3. On flame-01 there was *also* a genuine PCoIP-stranded phantom Ctrl
   in the X server (server modifier mask showed `Ctrl` at rest). That
   is a **separate, real** issue — cure: tap both Ctrl keys. Do not
   let it contaminate this bug again.
4. A timer polling **only** `CGEventSourceButtonState` (no key-state
   calls) did **not** break Shift — **single trial, treat as weak.**
5. Gating key queries behind "the drag has moved in schematic space"
   (v1.2.0's `_drag_live`) did **NOT** fix it. So either the gate
   fails to suppress the queries in the shift-click path, or (4) was
   a false negative and something else in the tick is responsible.

### Theories already disproven (do not re-litigate)

- Popup focus churn / `makeKeyAndOrderFront` — the bug reproduces with
  the timer alone and **no popup ever opened**.
- X-specific mechanisms (`XSetInputFocus`, XTest, XI2 selection) —
  macOS reproduces the same symptom with no X anywhere.
- Flame-internal modifier latch needing a "resync" — a resync that
  posted true `NSFlagsChanged` did nothing; mechanism removed.
- PCoIP alone — macOS has no PCoIP and still shows it.

### The next step (do this, don't theorise)

Run a **three-rung isolation ladder** on portofino, each rung held
long enough for the operator to test Media-panel shift-select
properly, one variable at a time:

1. A `QTimer` at 30 ms whose callback does **nothing at all**.
2. Same timer + `CGEventSourceButtonState` only.
3. Same timer + button + `CGEventSourceKeyState` calls.

Whichever rung first breaks Shift names the culprit. If rung 1 breaks
it, the problem is the main-thread timer itself and the whole polling
design needs replacing (out-of-process helper feeding state over the
bridge is the fallback design). Do not ship a fix off a single trial —
that mistake was made twice in this session.

## Standing rules earned the hard way

- **Bridge-unreachable ≠ Flame-dead.** Confirm with the operator.
- **Never test on a working artist's box** without saying so and
  getting explicit consent for that session.
- **One variable per test**, and re-test before believing a result.
- Livewire's Linux backend (`evdev_reader.py`) is validated and safe
  from an input-capture standpoint; `LINUX_ENABLED` is False only
  because of this bug plus two unexplained crashes on flame-01 (no
  coredumps; that box also has broken third-party hooks and an
  installer daemon crash of its own).

## Re-enabling later

```bash
# macOS
mv /tmp/livewire_hook.py.disabled /opt/Autodesk/shared/python/livewire_hook.py
# flame-01 (also needs LINUX_ENABLED=True in livewire/hid.py)
ssh flame-01 'mv /tmp/livewire_hook.py.disabled /opt/Autodesk/shared/python/livewire_hook.py'
```

Bridge one-liner to stop a running instance at any time:
`livewire.uninstall()` (stops detector and any reader thread).
