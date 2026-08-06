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
  No permissions required. Captures clicks globally (including other
  monitors — bound checks needed).
- **Correction (2026-07-29):** PyObjC does *not* ship inside Flame's
  Python. It imported during the original probe session only because the
  launch environment happened to path it in; a clean Flame start has no
  `objc`/`Quartz`/`AppKit`. Livewire vendors PyObjC via
  `pip install --target vendor/` with Flame's own interpreter (see
  README), and the package inserts `vendor/` on import.
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

## Action schematic (probed 2026-07-29)

- `PyActionNode` mirrors the Batch surface: its own `cursor_position`,
  `create_node` (55 Action types), `connect_nodes(parent, child)`
  (2-arg), `get_node`, `nodes` + `media_nodes` (both with `pos_x/pos_y`),
  `node_types`, `organize`.
- **`action.cursor_position` is live, node-space, and snaps** to a
  node's anchor (±5) over its body — same behavior as Batch. Hover
  pauses matched `axis1`/`axis3`/`axis2` anchors exactly.
- **Context detection:** both cursor feeds track the pointer through
  their own pan/zoom simultaneously. When the Batch schematic is active,
  the Action feed mirrors the Batch feed *exactly* (identical tuples,
  sample after sample); when the Action schematic is active they
  diverge. Off-schematic both freeze. Before an Action's schematic has
  ever been opened its feed reads garbage (e.g. `(663659, 922559)`).
  Surface rule: diverged AND (feed moved during the drag OR grab
  resolves to an Action node) → Action; else Batch.
- **No selection signal inside Action:** internal clicks change neither
  `flame.batch.current_node` (stays the Action) nor any queryable
  selection — `PyActionNode` has no `selected_nodes`. Identification
  rides entirely on the cursor snap.
- `PyCoNode` has **no `.delete()`** — missing attributes resolve to
  `None`, so calling them raises `TypeError: 'NoneType' object is not
  callable` (a confusing signature worth remembering). Use the global
  `flame.delete(node)` instead.

## Indexing sources (probed 2026-07-29)

- **`~/Library/Preferences/Autodesk/flame/search/search_settings.json`**
  is the native search popup's database: per-entry `Name`, `Weight`
  (usage count — their ranking), `Tags` (search synonyms), `Favorite`,
  and `Type` (`Matchbox` / `OpenFX` / `User` / `Timeline FX` / …). It is
  a *usage* DB, not a catalog — only tools the artist has touched get
  typed entries. Gold for ranking parity and OFX label harvesting.
- **Stock Matchbox shaders**: `/opt/Autodesk/presets/<ver>/matchbox/
  shaders/*.mx` (compiled, no XML sidecars — name is the filename stem).
  `flame.batch.create_node("Matchbox", shader_path)` creates the node
  with the shader loaded, one call.
- **User bins**: `~/Library/Preferences/Autodesk/flame/batch/pref/
  _user.<Name>.batch` (+ companion resource dir). Instantiate with
  `flame.batch.append_setup(path)` — **which can raise "Could not load
  the Batch setup" AFTER successfully appending the nodes** (seen with
  2026.1-saved bins in 2026.2.2). Tolerate the exception and diff the
  node list for the truth.
- **OpenFX**: `create_node("OpenFX")` + `node.change_plugin(label)`.
  Labels only — the display label as shown in `node.plugin_name`
  ("ForgeFlow Apply", not the bundle name or the reverse-domain id);
  unknown labels silently no-op. No Flame-side OFX registry exists on
  disk; label sources: search_settings.json typed entries, Nuke's OFX
  plugin cache (`/var/tmp/nuke-*/ofxplugincache/*.xml`, carries
  `OfxPropLabel` for every installed plugin), and `plugin_name` of
  existing OpenFX nodes.

## Threading and API lessons (2026-07-29)

- **Batch `connect_nodes` is strictly 4-arg** (`src, out_socket, dst,
  in_socket`); the 2-arg parent/child shorthand exists only on Action.
  Boost's ArgumentError subclasses TypeError, so a naive try/except
  TypeError fallback retries the same broken call.
- **`flame.schedule_idle_event` drains only when Flame's own UI sees
  activity.** Work queued from a focused Qt popup sits until the user
  next touches Flame (e.g. clicks the schematic). Callbacks that already
  run on the main thread (dialog handlers) should call the flame API
  directly; reserve idle marshaling for bridge/worker-thread entry.
- **`hasattr()` is useless on Flame PyNodes** — missing attributes
  resolve to `None` instead of raising, so `hasattr(node, anything)` is
  always True and calling the result raises `TypeError: 'NoneType'
  object is not callable`. This bit twice (PyCoNode `.delete()`, and an
  `add_media` capability check that swallowed every multi-select commit
  for four days). Check `node.type` or catch the TypeError; never
  hasattr.
- `detector._debug` is a 200-entry timestamped ring buffer of livewire
  events — first stop when behavior looks timing-dependent.

## Making Flame repaint while a Qt popup holds focus (2026-07-29)

Flame repaints its schematics only while processing its own input
events (redraw-after-input). While a focused Qt popup starves it, API
commits land (<10 ms, per the ring buffer) but stay **invisible** until
the user clicks Flame. Escalation ladder, each step falsified live:

1. `NSApplicationDefined` posted to NSApp — processed, no repaint.
2. Qt dispatcher pump (`processEvents(ExcludeUserInputEvents)`) —
   insufficient alone.
3. Synthetic `NSEventTypeMouseMoved` posted to Flame's main window at
   the **window center** — wakes the Batch panel, misses Action's.
4. Same synthetic move aimed at the **drop point** (capture
   `NSEvent.mouseLocation()` when the browser opens — the cursor is in
   the working schematic right then; convert to window coords via the
   frame origin) — ✅ repaints both Batch and Action, per commit.

Corollary: panel repaint is hover-local — the move must land on the
panel you want redrawn.

- Action schematic layout is vertical: children sit *below* parents
  (smaller y). Chains/gangs in Action should build downward; Batch
  builds rightward.

## Linux port (validated 2026-08-03, flame-01: Rocky 9.5 / Flame 2026.2.1)

- The X11 backend (pure ctypes into `libX11`/`libXtst`, no python-xlib)
  worked on first load inside Flame's embedded Python: `XOpenDisplay`
  on Flame's `DISPLAY=:1`, `XQueryPointer` for the button mask,
  `XQueryKeymap` + keysym→keycode for arm keys, 30 ms QTimer polling
  identical to macOS.
- **The Qt popup takes keyboard focus with plain `activateWindow()`**
  on X11 — the macOS NSWindow `makeKeyAndOrderFront` dance is not
  needed there.
- All flame-API logic (`cursor_position`, surface detection, commits,
  media wiring) is platform-neutral and behaved identically.
- Deployment/iteration without sitting at the box: forge-bridge's HTTP
  `/exec` on the Linux host, driven over ssh
  (`curl -X POST 127.0.0.1:9999/exec -d '{"code": ...}'`) — same
  probe-reload loop as the local MCP tools.
- **No click-to-repaint quirk observed on Linux** — gang picks appear
  immediately (user-confirmed), so no nudge is needed there.
- **The X11 poll loop breaks Flame's keyboard handling — Linux is
  disabled (2026-08-04).** With livewire running, Shift stopped
  working in the Media panel. Bisected live: **stopping the detector's
  30 ms QTimer restored Shift immediately** — no restart, nothing else
  changed. First theory was `XSetInputFocus` stealing focus while a
  modifier was held; that was **refuted** — a strictly read-only
  backend (XQueryPointer/XQueryKeymap only, no XTest, no focus calls)
  still broke it. The polling itself is the problem, and note the key
  queries only run *during a drag* while the pointer query runs
  always, so `XQueryPointer` at 30 ms on Flame's main thread is the
  prime suspect.
- **The XI2 raw-event redesign (`livewire/xi2.py`) works standalone**
  (2026-08-04, Rocky 9.5): dedicated thread, own connection,
  `XISelectEvents` on root for raw button/key, drained via select() on
  the connection fd. Outside Flame it captured all arm keys
  (press+release), button-1 held, and arm-keys-during-drag — the full
  gesture vocabulary — with zero errors.
- **XI 2.0 suppresses raw events during pointer grabs** — and Flame
  grabs the pointer for every noodle drag, so button releases vanished
  mid-gesture (stuck-down state, browser never opened). Negotiating
  **XI 2.2** fixes delivery-during-grabs; with it, the full gesture
  engine worked in-Flame on Linux (a 3-chain replicate gang committed
  9 wired nodes flawlessly).
- **REFUTED (the hard way, 2026-08-04): even passive XI2 raw-event
  selection breaks Flame's Shift handling.** Second independent
  mechanism, same symptom, same instant recovery when the reader
  stops. Combined with the polling result, the conclusion is: **any
  X-protocol input observation from inside Flame's process disturbs
  this stack** (Rocky 9.5 / Flame 2026.2.1). Mechanism unknown; both
  bisects were clean. The X road is closed.
- **evdev is the shipping Linux backend** (`livewire/evdev_reader.py`):
  reads `/dev/input/event*` on the dedicated reader thread — kernel
  level, no X protocol. Requires read access (input group membership +
  relogin, or an immediate `setfacl -m u:<user>:r /dev/input/event*`).
  Kernel keycodes are physical/layout-free (F=33 M=50 G=34 R=19 I=23,
  BTN_LEFT=272). Validated in-Flame over **PCoIP/HP Anyware** — whose
  virtual input devices inject at the *kernel* level, so evdev sees
  remote users (an XTEST-injecting remote stack would be invisible).

## The Shift saga, resolved (2026-08-04) — SUPERSEDED, see the
## 2026-08-05 isolation ladder below for the actual root cause

A week of "livewire breaks Shift" ended with every transport
exonerated and the truth two layers away:

1. Mask probes (XQueryPointer from an ssh-side client) first caught a
   **phantom latched Ctrl in the X server** — every click was secretly
   Ctrl+click, presenting as "Shift broken". Cured by tapping both
   Ctrl keys. Classic PCoIP stranded-modifier failure: a modifier
   keyup lost across a focus change.
2. After the server was clean, shift-select STILL failed — with the
   server provably seeing perfect Shift+Btn1 chords. **Flame's own
   internal modifier latch was desynced**: old-school X apps track
   modifiers from events delivered to them, and presses/releases that
   land while another window (a popup, a PCoIP focus blink) holds
   focus never reach Flame. Cure: focus Flame and tap each modifier
   (both Shifts, both Ctrls, Alt) once — clean pairs resync it. A
   Flame restart also cures it, which is why every restart all week
   "fixed Shift".
3. A controlled session of heavy livewire popup use left the server
   mask **clean** — the popups strand nothing. The earlier "stopping
   livewire fixed Shift instantly" bisections were confounded by the
   focus churn and modifier taps that came with each test cycle.

Diagnostic kit for next time: watch the server modifier mask from an
ssh X client while the operator (a) rests hands, (b) holds Shift and
clicks. Stuck bit at rest → tap that modifier. Clean chords ignored →
Flame-internal desync → tap all modifiers with Flame focused. (macOS
equivalent: `CGEventSourceFlagsState(kCGEventSourceStateCombinedSessionState)`.)

**Epilogue (same day): the symptom appeared on macOS too — no PCoIP.**
System modifier state clean, Flame ignoring Shift: the identical
second-layer failure. Unified conclusion: **Flame's internal modifier
latch desyncs when modifier transitions land during focus churn, on
any platform** — and livewire's popup, which forcibly takes and
returns key-window focus on every open/close, is a potent churn
trigger (PCoIP merely adds a second, server-level stranding failure on
top). Livewire is disabled on both machines pending a fix. Candidate
fix (macOS, untested): on popup close, read the true
CGEventSource flags and post a synthetic `NSFlagsChanged` event to
Flame's main window — the same in-process posting mechanism as the
repaint nudge — so Flame's latch resyncs to reality. No
injection-safe Linux equivalent is known; the Linux answer may be
Qt-side (avoid taking key-window at all?) or acceptance.
## The Shift bug, actually resolved: the isolation ladder (2026-08-05)

The Media-panel shift-select breakage was root-caused on portofino
(macOS, Flame 2026.2.2) with a live isolation ladder — one variable
per rung, each rung a 30 ms main-thread QTimer, operator testing
Media-panel shift-select at every rung, recovery confirmed after
every break, breaking rungs repeated before being believed.

**Exonerated (all clean under sustained, ungated 30 ms polling):**

1. The bare main-thread QTimer itself.
2. `CGEventSourceButtonState` every tick.
3. `CGEventSourceKeyState` — all five arm vkeys, every tick,
   unconditionally. (The v1.2.0 "CRITICAL" comment blamed exactly
   this. It was wrong.)
4. `flame.batch.cursor_position` reads every tick, with live
   schematic values latched.
5. `AppKit.NSApp.isActive()` every tick.

**Guilty — Flame node-API access during click processing.** Each of
these, alone, performed synchronously on the press transition, breaks
Media-panel shift-select (and stopping the timer restores it
instantly, same session):

- a single `flame.batch.current_node` read (confirmed twice), or
- iterating `flame.batch.nodes` with name/pos/type attr reads
  (confirmed independently).

Batch size does not matter — the breaking batch had **2 nodes**. The
mechanism is not load; **any PyBatch/PyNode access made while Flame
is processing a click corrupts that click's shift-anchor handling in
the Media panel.** `flame.batch.cursor_position` is notably NOT in
the guilty class — it polls clean (rung 4), which is what makes the
fix possible.

**Why v1.2.0 failed:** its `_drag_live` gate silenced the (innocent)
Quartz key queries but still ran the (guilty) node snapshot on every
button press.

**The fix (v1.3.0):** the press transition touches zero Flame node
API. The full surface snapshot (`_snapshot_surfaces`) is deferred to
the drag-live transition — two distinct `cursor_position` samples
with the button down, which only a genuine schematic drag produces
(both cursor feeds stream during Batch *and* Action drags;
off-schematic both freeze — see the context-detection finding above).
Media-panel clicks never trigger any node-API call at all. Verified
live 2026-08-05: shift-select clean with the full detector running,
noodle-drop verbs working.

**Fallout for earlier conclusions:**

- The 2026-08-04 "internal modifier latch desync" narrative and the
  popup-focus-churn theory are superseded for THIS bug (the ladder
  reproduced it with no popup ever opening). The PCoIP
  server-level stranded-modifier failure remains real and separate.
- The Linux conclusion "any X-protocol input observation from inside
  Flame's process disturbs this stack" is now **suspect**: every
  Linux trial behind it ran the full detector, i.e. the press-time
  Flame-API snapshot was present in all of them — the same confound
  that misled macOS for a week. The X backends deserve a retest with
  the v1.3.0 deferred snapshot before the X road is declared closed.
  (evdev remains the shipping Linux backend regardless; it needs no
  X and is validated.)

- **Bridge-unreachable ≠ Flame-dead.** The forge-bridge HTTP server
  can die inside a healthy, running Flame (observed after a python
  hook rescan: port 9999 unbound, Flame fine, operator-confirmed).
  From outside, that is indistinguishable from a host crash — several
  of this project's "Flame restarted?" moments were probably bridge
  outages. Confirm with the operator or the process table before
  writing a crash narrative; a false one nearly halted the Linux
  backend for good.
- macOS is unaffected: the Quartz backend
  (`CGEventSourceButtonState`/`KeyState`) has run for a week with no
  input side effects. User prefs on the test box exposed no `_user.*.batch`
  bins under `/opt/Autodesk/user/*` — location TBD.

## Socket geometry (calibrated 2026-08-04, Flame 2027)

Grab offsets vs the matched node's anchor, from labeled pulls:

- **Standard nodes** (Comp): output sockets stack down the right edge,
  ~**21 units/socket**, vertically **centered on the anchor**; grabs
  read dx ≈ +37..45. (Retro-explains the day-one action3 sample of
  (+37,+11) — a top-socket grab.)
- **Expanded multichannel clips**: tab column at dx ≈ **+112**,
  **37.5 units/tab** (least-squares over 5 tabs across a 30-tab clip,
  max residual 0.2 tab), top tab ~47 units below where a centered
  model predicts. `_alpha` channels do NOT get their own tabs — the
  visible tab list is the non-alpha outputs.
- **Body grabs snap to the anchor** (dx≈0) — a free confidence gate:
  no x-offset, no socket inference.
- Offsets are in schematic units and therefore **zoom-invariant**.
- The press-instant sample can be stale (documented earlier); the
  median of the first three drag samples is robust to it.

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
