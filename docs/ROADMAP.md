# Roadmap / passoff

Where livewire could go next, in rough priority order. Each item notes the
approach and what's unknown, so any session (or anyone) can pick one up
cold. Background for all of it: [FINDINGS.md](FINDINGS.md) — and the probe
([`livewire/probe.py`](../livewire/probe.py)) is the tool for answering the
open questions below empirically, the same way v0.1 was derived.

## 1. Action schematic support — ✅ shipped 2026-07-29

Same gesture inside an open Action: link-drag + F/M → browser of the 55
Action node types → child of the grabbed node at the drop point (or
unparented from an empty-space grab). Per-drag surface detection via
cursor-feed divergence + liveness (see FINDINGS "Action schematic").
Remaining Action follow-ups: creatable media nodes (`add_media`), other
schematic-bearing nodes (GMask Tracer), and a parent-vs-sibling choice
on the mode keys if artists want it.

## 2. Action input capture → auto-wire into maps (BIG)

The flagship follow-up. Capture everything feeding an Action's
Batch-side inputs — beauty, normals, motion vectors, position, ID,
mattes, whatever passes are noodled in — bring them into the Action as
media, and plug each one into its proper destination: Diffuse Map,
Normal Map, Motion Vectors Map, Position Map, Z-Depth Map, UV Map,
matte/selective inputs, etc. Today this is minutes of manual add-media
and map wiring per setup; it should be one gesture and a confirmation.

Building blocks and open questions (probe sessions required):
- **Batch side:** enumerate the Action node's input sockets and what
  feeds each (connection topology — forge-bridge already parses batch
  setup XML if the python API doesn't expose it directly).
- **Media side:** `PyActionNode.add_media()` / `media_layers` /
  `media_nodes`, and `PyCoNode.assign_media()` — probe how a media
  entry maps to a Batch input socket and to Media nodes in the
  schematic.
- **Map side:** `create_node("Normal Map")` etc. + `assign_media` to
  bind the right media, parented under the target surface/material —
  verify the parenting/binding rules per map type.
- **Inference:** deciding which input is which — input socket names,
  upstream node/clip/pass naming conventions (N, MV, P, Z, crypto…),
  with a mapping-table UI to confirm/override guesses before commit.
- **UX sketch:** select the Action (or invoke on it via livewire),
  scan inputs, show input → map-type table with guesses pre-filled,
  Enter wires the lot.

## 3. Source-socket inference

Today the grabbed output socket isn't sensed — `Result`/first is assumed
(M-mode guesses the matte output). FINDINGS shows a socket grab reads as
a small, non-snapped offset from the node anchor (`action3`: ≈ (+37,+11))
while body hovers snap to the anchor (±3). The offset likely encodes the
socket's position along the node's bottom edge.

Approach: probe session grabbing every output of multi-output nodes
(Action, Master Keyer, Clamp) at a few zoom levels; if x-offset ranks
sockets left-to-right reliably, map offset rank → `output_sockets` index.
Fallback stays the combo. Watch zoom dependence — offsets may scale.

## 4. Matchbox / OFX / preset indexing

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

## 5. Favorites / recents

Persistent per-artist JSON (`~/.config/livewire.json` or similar): count
commits per node type, rank recents/frequents above the alphabetical
list, optional pinned favorites. Cheap, big daily-feel win. Also the
natural home for artist config (arm keys, theme) so shared installs
don't require editing source — see item 8.

## 6. Insert into an existing noodle

Drop the browser-created node *inline*: if the armed release lands near
an existing connection line (not near a node), create + rewire
upstream→new→downstream. We have node positions; connection topology is
readable from the batch (verify: `node.sockets` connections or batch
setup XML — forge-bridge already parses batch XML). Point-to-segment
distance in schematic space; threshold similar to GRAB_RADIUS.

## 7. Branch-from-input (pull upstream)

Grabbing an *input* socket (top edge — offset sign should distinguish it
from outputs, same probe as item 2) and dropping on empty = "create a
node feeding this input": browser commit wires new node's Result into
the grabbed input. Mirrors ComfyUI's reverse drag.

## 8. Config file + deployment story

Constants out of source: arm-key vkeys, theme, radius, verbosity into a
JSON config with per-user override. Then a proper deploy path for a
studio: one shared checkout + symlinked hook per workstation, version
tag, and eventually a Logik portal submission (which effectively
requires items 4 and 5 for feature parity with expectations).

## 9. Linux backend

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
  scale); if zoom is recoverable from socket-offset work (item 3), scale
  it.
- Browser list is capped at `MAX_ROWS * 4` entries with no scrollbar;
  fine at 99 types, revisit after item 4 grows the list.
- ISO keyboards: F/M are safe, but any future punctuation arm-key needs
  the vkey caveat from the README.
