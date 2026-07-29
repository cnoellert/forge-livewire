# Roadmap / passoff

Where livewire could go next, in rough priority order. Each item notes the
approach and what's unknown, so any session (or anyone) can pick one up
cold. Background for all of it: [FINDINGS.md](FINDINGS.md) — and the probe
([`livewire/probe.py`](../livewire/probe.py)) is the tool for answering the
open questions below empirically, the same way v0.1 was derived.

## 1. Action schematic support

Batch isn't the only schematic — Action is the other place artists live,
and its node bin is a modal interruption in a way Batch's isn't. Same
gesture: pull from an Action node, tap a key, get a browser of Action
node types (Axis, Light, Surface, GMask, …), auto-parented at the drop
point.

Open questions (probe session required):
- Does `flame.batch.cursor_position` report while the Action schematic
  has the pointer, and in which coordinate space? If not, is there an
  equivalent on the Action object?
- Action python API: node positions exist on Action objects — confirm
  attribute names and coordinate space match what the cursor reports.
- Connections are parent/child (`node.parent` / assign), not sockets —
  the commit path differs: `action.create_node(type)` + parenting, and
  "front/matte" semantics don't apply. Mode keys would instead pick
  parent-under vs sibling.
- Detecting *which* schematic is under the cursor (Batch vs Action) so
  one detector serves both. `flame.batch.current_node` type +
  which view has the pointer may be enough.

## 2. Source-socket inference

Today the grabbed output socket isn't sensed — `Result`/first is assumed
(M-mode guesses the matte output). FINDINGS shows a socket grab reads as
a small, non-snapped offset from the node anchor (`action3`: ≈ (+37,+11))
while body hovers snap to the anchor (±3). The offset likely encodes the
socket's position along the node's bottom edge.

Approach: probe session grabbing every output of multi-output nodes
(Action, Master Keyer, Clamp) at a few zoom levels; if x-offset ranks
sockets left-to-right reliably, map offset rank → `output_sockets` index.
Fallback stays the combo. Watch zoom dependence — offsets may scale.

## 3. Matchbox / OFX / preset indexing

Flame's native search lists `Lens_Blur - User` and `ColourCorrect -
Matchbox`; livewire lists only the 99 `flame.batch.node_types`. Index:
- Matchbox shaders: scan the shader dirs (`/opt/Autodesk/presets/<ver>/
  matchbox/shaders`, project/user matchbox paths); names + shader path
  from the XML sidecars. Commit = create `Matchbox` node + load shader
  (`node.load_node_setup()` / matchbox path attribute — verify API).
- OFX: enumerate installed OFX plugins (verify what the python API
  exposes; worst case parse the OFX cache).
- User node setups/presets: user's node bin saves.
Entries get a suffix tag like the native browser. Index at install,
refresh lazily.

## 4. Favorites / recents

Persistent per-artist JSON (`~/.config/livewire.json` or similar): count
commits per node type, rank recents/frequents above the alphabetical
list, optional pinned favorites. Cheap, big daily-feel win. Also the
natural home for artist config (arm keys, theme) so shared installs
don't require editing source — see item 7.

## 5. Insert into an existing noodle

Drop the browser-created node *inline*: if the armed release lands near
an existing connection line (not near a node), create + rewire
upstream→new→downstream. We have node positions; connection topology is
readable from the batch (verify: `node.sockets` connections or batch
setup XML — forge-bridge already parses batch XML). Point-to-segment
distance in schematic space; threshold similar to GRAB_RADIUS.

## 6. Branch-from-input (pull upstream)

Grabbing an *input* socket (top edge — offset sign should distinguish it
from outputs, same probe as item 2) and dropping on empty = "create a
node feeding this input": browser commit wires new node's Result into
the grabbed input. Mirrors ComfyUI's reverse drag.

## 7. Config file + deployment story

Constants out of source: arm-key vkeys, theme, radius, verbosity into a
JSON config with per-user override. Then a proper deploy path for a
studio: one shared checkout + symlinked hook per workstation, version
tag, and eventually a Logik portal submission (which effectively
requires items 3 and 4 for feature parity with expectations).

## 8. Linux backend

All input capture is macOS Quartz today; Flame's big installed base is
Rocky Linux. The polling architecture ports cleanly: X11
`XQueryPointer` gives button state and `XQueryKeymap` key state — same
30 ms main-thread poll, no event taps, no extra permissions
(python-xlib, or ctypes straight into libX11 to avoid the dependency).
`cursor_position` and all flame-API logic is platform-neutral already;
isolate Quartz calls behind a small `hid.py` shim with mac/linux
implementations. Needs a Linux Flame box to validate Wayland/XWayland
behavior.

## Known rough edges (small, unordered)

- Armed release *onto* a node's input completes the native connection
  AND pops the browser — should detect release-over-node and stand down.
- `create_node` + `connect_nodes` are separate undo steps; investigate
  grouping so one Ctrl+Z removes the committed node cleanly.
- Grab radius is zoom-naive (150 schematic units regardless of view
  scale); if zoom is recoverable from socket-offset work (item 2), scale
  it.
- Browser list is capped at `MAX_ROWS * 4` entries with no scrollbar;
  fine at 99 types, revisit after item 3 grows the list.
- ISO keyboards: F/M are safe, but any future punctuation arm-key needs
  the vkey caveat from the README.
