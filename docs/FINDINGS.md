# Probe findings — Flame 2026.2.2, macOS (2026-07-28)

Empirical results from a live in-Flame probe session (via forge-bridge
`flame_execute_python`). These are the load-bearing facts behind livewire's
design.

## Event routing

- Flame's main window **is** a Qt widget (`EventWidget 'CF Main Window'`),
  and the `QApplication` is real — synthetic `postEvent` reaches app- and
  widget-level event filters.
- But **no input events flow through Qt's event dispatch** — zero mouse,
  paint, or timer traffic seen by an application event filter over long
  windows. Flame handles schematic input natively, below Qt. Qt event
  filters are a dead end for input capture.
- `QAbstractNativeEventFilter` *does* receive NSEvents
  (`mac_generic_NSEvent`), so raw native interception is possible, but
  unnecessary given the polling approach below.
- Bridge code executes on a **worker thread**. Anything touching Qt objects
  must be marshalled to the main thread with `flame.schedule_idle_event()`.
  A QObject created on the worker thread has worker affinity and will never
  receive events.

## Input capture that works

- `Quartz.CGEventSourceButtonState(kCGEventSourceStateCombinedSessionState, 0)`
  polled on a 30 ms main-thread `QTimer` gives clean press/release edges.
  PyObjC (`objc`, `Quartz`, `AppKit`) ships inside Flame's Python.
  No permissions required. Captures clicks globally (including other
  monitors — bound checks needed).
- `QTimer` on the main thread runs fine (installed via
  `schedule_idle_event`).

## State fingerprints

- **Body press** on a node sets `flame.batch.current_node` *and*
  `selected_nodes` at press time (visible within one 30 ms tick).
- **Output-socket grab** leaves **zero** fingerprint in `current_node` /
  `selected_nodes`. Selection state cannot detect noodle pulls.
- `flame.batch.selected_nodes` is a `PyAttribute` in 2026 — call
  `.get_value()` before iterating.

## `flame.batch.cursor_position` — the key primitive

Live cursor position in **schematic space**, same coordinate system as
`node.pos_x/pos_y`.

- **Over a node body**: reads the node's own anchor within ~3 units
  (`timewarp2` @ (1288,−1513) read (1291,−1510); `comp1` @ (1484,−1248)
  read (1487,−1247)). Appears to snap to the node under the cursor —
  node identification is essentially exact.
- **On an output-socket grab**: a distinct small offset from the anchor,
  not snapped (`action3` @ (1065,−1390) read (1102,−1379), ≈ (+37,+11)).
  The offset may encode which output socket on multi-output nodes
  (unverified, one sample).
- **Over empty space / during a drag**: streams smooth continuous values —
  a full noodle drag was captured at ~30 ms resolution from grab to
  release.
- **Staleness caveat**: can be stale at the exact press instant; it caught
  up within ~100–150 ms. Use the first couple of drag samples, not the
  press-instant read.

## Gesture classification plan

- Socket grab: early-drag `cursor_position` near a node anchor with the
  socket-band offset, no selection change at press.
- Node move: looks similar until release — disambiguate by checking whether
  the candidate node's `pos_x/pos_y` changed.
- Marquee on empty: press point maps to no node anchor within tolerance.
- Fire condition: qualifying grab + release over empty space + no node
  moved + no connection made → pop browser at release `cursor_position`.

## Completion API (known-good)

`flame.batch.create_node()`, `flame.batch.connect_nodes(src, dst)` with
named sockets, `node.pos_x/pos_y` for placement at the drop point.
