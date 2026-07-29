# forge-livewire

**Noodle-drop node browser for Autodesk Flame Batch.**

Pull a noodle from a node's output socket, tap **F** or **M** while you're
still holding it, and let go over empty schematic space. A search popup
appears at the drop point — type a few letters, hit Enter, and the node is
created right there, already wired to the output you pulled from. The same
interaction you know from ComfyUI or Nuke's Tab-search, but socket-aware
and native to Batch.

Flame's own node search (the Tools/Learn popup) can't be invoked from a
noodle. This closes that gap.

## Requirements

- Flame **2026.x on macOS** (developed and validated on 2026.2.2).
  Everything livewire needs ships inside Flame's own Python: PySide6 and
  PyObjC. No pip installs, no external daemons, no Accessibility or
  Screen Recording permissions.
- **Linux is not supported yet.** Input capture currently uses macOS Quartz
  APIs; a Linux backend (XRecord/evdev) is possible but not written.

## Install

Symlink the hook into a Flame python hooks directory and restart Flame
(or re-scan hooks):

```bash
ln -s /path/to/forge-livewire/hooks/livewire_hook.py \
      /opt/Autodesk/shared/python/livewire_hook.py
```

The hook resolves the repo location through the symlink, so nothing else
needs configuring. To load it into a *running* Flame session instead, run
this in the Flame python console:

```python
import sys
sys.path.insert(0, "/path/to/forge-livewire")
import livewire
livewire.install()
```

`livewire.uninstall()` stops it cleanly at any time.

## Using it

1. In the Batch schematic, **drag a noodle out of any output socket** —
   a normal connection drag, nothing special.
2. **While still holding the pen/button, tap an arm key:**

   | Key while dragging | What gets connected on commit |
   |---|---|
   | **F** | source output → new node's **Front** (or its first input) |
   | **M** | source output → new node's **Matte** input; the source-socket menu pre-selects the source's matte output (e.g. `OutMatte`) if it has one |
   | **F then M** (both, same drag) | source's image output (`Result`, or first) → **Front** *and* source's matte output → **Matte** |

3. **Release over empty schematic space.** The noodle cancels natively and
   the search popup appears at the drop point.
4. **Type to narrow** (matches favor prefix, then word-start, then
   substring, then fuzzy), **↑/↓** to choose, **Enter** or click to
   commit, **Esc** or click anywhere else to cancel.

The new node is created at the exact schematic position where you dropped
the noodle and connected per the table above.

The header line shows what you're about to do — e.g.
`from cc1 (to matte)`. If the source node has more than one output
socket, a menu above the search field lets you override which output
feeds the connection (defaults to `Result`).

F and M are only watched **while a connection drag is in flight** — they
keep their normal Flame meanings the rest of the time.

## What it does *not* do (yet)

- **It can't tell which output socket you grabbed.** Pulling the matte
  noodle vs the result noodle looks the same to livewire today; the
  source socket is `Result`/first unless you change the menu (or use
  **M**, which guesses the matte output). Socket inference from the grab
  position is feasible (see docs/FINDINGS.md) and planned.
- **The list is Flame's built-in node types only** (the 99 entries of
  `flame.batch.node_types`). User Matchbox setups, OFX plugins, and
  saved presets are not indexed yet — you get a bare `Matchbox`/`OpenFX`
  node, not `Lens_Blur - User`. Planned.
- No favorites/recents ordering yet.

## Configuration

Everything lives in two files, plain constants at the top:

- [`livewire/detector.py`](livewire/detector.py) —
  `KEY_FRONT` / `KEY_MATTE` (macOS virtual keycodes; F=3, M=46 —
  note ANSI layout: on ISO/Nordic boards some punctuation keys report
  different codes), `GRAB_RADIUS` (how close, in schematic units, the
  grab must be to a node's position to identify it; default 150),
  `TICK_MS` (poll rate, default 30 ms).
- [`livewire/browser.py`](livewire/browser.py) — `THEME`: `"flame"`
  (neutral greys matching the native node search, alternating rows in a
  cool Autodesk grey) or `"forge"` (forge-orange selection/focus
  accent). Fonts, colors, and sizes are all in the `THEMES` table.

## How it works

Flame handles schematic input natively, *below* Qt's event dispatch — Qt
event filters inside Flame see no mouse events at all. Livewire instead:

1. polls the raw HID button state (`Quartz.CGEventSourceButtonState`) on
   a 30 ms `QTimer` on Flame's main thread — press/release edges;
2. reads `flame.batch.cursor_position` — live **schematic-space**
   coordinates that snap to a node's `pos_x/pos_y` when the cursor is
   over it — to identify the grabbed node and the drop point;
3. polls `CGEventSourceKeyState` for F/M only while the button is down;
4. on an armed release, pops the PySide6 browser and commits with
   `flame.batch.create_node()` + `connect_nodes()`.

The full empirical background (what Flame exposes, what it doesn't, and
the probe that measured it) is in [docs/FINDINGS.md](docs/FINDINGS.md).
The measurement instrument itself is kept in
[`livewire/probe.py`](livewire/probe.py) for re-validation on new Flame
versions.

## Troubleshooting

- **Popup appears but typing goes to Flame** — the popup forces itself to
  be the macOS key window (`makeKeyAndOrderFront` via PyObjC); if you
  ever see focus fail, check the shell for `[livewire] makeKey failed`.
- **Wrong source node in the header** — the grab point resolved to the
  nearest node within `GRAB_RADIUS`; zoomed far out, anchors crowd
  together. Zoom in a touch or lower `GRAB_RADIUS`.
- **Nothing pops** — confirm the detector is alive: in the Flame python
  console, `from livewire import detector; print(detector._timer,
  detector.err)`.
- **Arm keys clash with your setup** — hotkey assignments differ per
  artist; pick unassigned keys and set their vkeys in `detector.py`.
  (Tab and backtick are both taken in stock Flame — Tab tabs the
  schematic, backtick is assigned in Action.)
