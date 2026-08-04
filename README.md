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

**Artists: start with the [Artist Guide](docs/GUIDE.md)** — gestures,
the three verbs, workflow examples, and tips, with none of the
implementation detail below.

## Requirements

- Flame **2026.x**, on **macOS** (developed on 2026.2.2) or **Rocky
  Linux with X11** (validated on 2026.2.1 / Rocky 9.5). No external
  daemons, no special permissions on either platform.
- macOS additionally needs PyObjC vendored into the repo by a one-time
  bootstrap (below). Linux needs nothing beyond the system X libraries
  (`libX11`, `libXtst`) — the input backend is pure ctypes.

## Install

**macOS only**, one-time **per Flame generation**: vendor PyObjC into
the repo using **that Flame's own Python**, targeting a directory named
for its python version (compiled extensions don't cross versions —
Flame 2026 is py311, Flame 2027 is py313):

```bash
/opt/Autodesk/python/2026.2.2/bin/python3.11 -m pip install \
    --target /path/to/forge-livewire/vendor/py311 pyobjc-framework-Quartz
```

On either platform, symlink the hook into a Flame python hooks
directory and restart Flame (or re-scan hooks):

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
   | **G** | **gang (chain) mode** — the browser stays open; every Enter commits a node immediately, chained `Result` → `Front` off the previous one, marching right. Esc or click-away ends the gang |
   | **G then M** | gang with **front+matte** wiring on every link |
   | **R** | **replicate mode** — with several nodes selected (grab one of them), every pick is applied to *each* selected node: N parallel chains, one per source, each building in line with its own node. No fan-in. Esc ends all chains |
   | **R then M** | replicate with front+matte links (mattes only where a source really has a matte output) |
   | **I** | **ingest** — grab an *Action* node: scans its media inputs and opens a table (media, feeder, map-type guess from pass naming, parent-surface picker); Enter creates each map inside the Action, `assign_media`-bound |

3. **Release over empty schematic space.** The noodle cancels natively and
   the search popup appears at the drop point.
4. **Type to narrow** (matches favor prefix, then word-start, then
   substring, then fuzzy), **↑/↓** to choose, **Enter** or click to
   commit, **Esc** or click anywhere else to cancel.

The new node is created at the exact schematic position where you dropped
the noodle and connected per the table above.

The four verbs: **F converges** (many sources into one node),
**G chains** (one pipe off the grab), **R replicates** (one recipe onto
every selected node), **I ingests** (an Action's inputs into their
proper map nodes).

**Multi-select changes what F and G converge into.** With two or more
nodes selected and the grab on one of them:
- picking a node with a back pair (Comp, Blend & Comp) wires the second
  selected node to **Back** (and **Back Matte** in F+M mode);
- picking **Action** wires the grabbed node to `Back` and creates **one
  media layer per remaining selected node**, each wired
  `Result` → media `Front` (+ real matte → media `Matte` in F+M mode)
  in selection order — a full AOV ingest in one gesture.
In a gang the fan-in applies to the first link only; the chain then
continues single-source. Pulling from an *unselected* node ignores the
selection entirely.

**Multichannel sources fan out by target**: an EXR clip with many
channel sockets picked onto an Action wires rgba → Back plus one media
per non-crypto channel (`_alpha` siblings → media Matte); picked onto a
CryptoMatte it wires one node per crypto family (rank layers →
`uCryptoNNrgb/a`). Works collapsed or expanded.

**Inside an Action schematic** the same gesture works: drag a link, tap
**F or M** (equivalent there), release. The browser lists Action's node
types (Axis, Light, Surface, GMask, …), the header reads
`parent <node>`, and the pick is created at the drop point as a child of
the grabbed node — or unparented if you grabbed empty space. Livewire
detects per-drag which schematic is active; no mode switching. Media
nodes can be grab sources but are not creatable from the browser yet.

The header line shows what you're about to do — e.g.
`from cc1 (to matte)`, or the growing trail in a gang
(`gang cc1 > Blur > Colour Correct`). If the source node has more than
one output socket, a menu above the search field lets you override
which output feeds the connection (defaults to `Result`; in a gang it
applies to the first link only). Everything a gang commits is already
in the schematic — ending it changes nothing, and regret is Ctrl+Z.

Arm keys are only watched **while a connection drag is in flight** —
F, M, G, and R keep their normal Flame meanings the rest of the time.
(Tab, backtick, and C were rejected as arm keys: Tab tabs the
schematic, backtick is assigned in Action, C is the Batch compass.)

## The index

The browser lists far more than the built-in node types: stock Matchbox
shaders (`Blur - Matchbox`, created with the shader loaded), your user
bins (`Lens_Blur - User`, appended and wired at the drop point), and
OpenFX plugins (`Reduce Noise v6 - OpenFX`, created with the plugin
selected). Ranking comes from Flame's own search data — favorites
first, then your most-used tools — so an empty search box already
shows what you reach for daily. After installing new shaders or saving
new bins mid-session, run `livewire.reindex()` (or restart Flame).

## What it does *not* do (yet)

- **It can't tell which output socket you grabbed.** Pulling the matte
  noodle vs the result noodle looks the same to livewire today; the
  source socket is `Result`/first unless you change the menu (or use
  **M**, which guesses the matte output). Socket inference from the grab
  position is feasible (see docs/FINDINGS.md) and planned.
- **OFX coverage is harvested, not enumerated** — plugins you've used
  (or that appear in a Nuke OFX cache on the machine) are listed;
  a never-used plugin won't be until it's used once. Stale labels from
  renamed plugins can appear and silently create an empty OpenFX node.

## Configuration

Everything lives in two files, plain constants at the top:

- [`livewire/detector.py`](livewire/detector.py) —
  `KEY_FRONT` / `KEY_MATTE` (macOS virtual keycodes; F=3, M=46 —
  note ANSI layout: on ISO/Nordic boards some punctuation keys report
  different codes), `GRAB_RADIUS` (how close, in schematic units, the
  grab must be to a node's position to identify it; default 150),
  `TICK_MS` (poll rate, default 30 ms), `VERBOSE` (arm/commit messages
  in the shell; off by default, errors always print).
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
