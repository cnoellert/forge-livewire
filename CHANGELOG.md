# Changelog

## 1.0.0 — 2026-08-04

First stable release. Livewire went from "could a daemon watch the
screen?" to a cross-platform production tool in a week of probe-driven
sessions, every behaviour validated in a running Flame.

**The gesture.** Pull a noodle, tap an arm key while dragging, release
over empty schematic space: a searchable browser opens at the drop
point and the pick is created there, already wired.

**The verbs.**

- **F — converge.** One node wired from the grab. With several nodes
  selected: Comps get the second source on Back/Back Matte; Actions get
  one media layer per selected node, in selection order.
- **G — chain.** The browser stays open; each Enter commits instantly
  and chains off the last pick. Rightward in Batch, downward in Action.
- **R — replicate.** With several nodes selected, every pick lands on
  each of them — N parallel chains until Esc.
- **I — ingest.** Grab an Action: scan its media inputs, guess each
  pass's map type from the feeder names, confirm in a table, and create
  + bind the map nodes inside the Action.
- **+M** on any verb wires mattes, but only from real matte outputs.

**Channel fan-out.** A multichannel EXR picked onto an Action wires
`rgba` to Back and every non-crypto channel to its own media (with its
`_alpha` on the media's Matte); picked onto a CryptoMatte it wires one
node per crypto family.

**The browser.** Node types, stock Matchbox shaders (created with the
shader loaded), user bins (appended and wired), and OpenFX plugins —
ranked by pins, then usage (livewire learns from every commit, blended
over Flame's own search weights), then recency. Tag search reads
Flame's tags plus your own. Pins/tags/usage persist in
`~/.config/livewire.json`.

**Socket inference.** The output you grabbed is read from the grab
point's offset and pre-selects the socket menu — calibrated for
standard nodes and expanded multichannel clips; declines rather than
guesses when the geometry is ambiguous.

**Platforms.** macOS (Quartz) and Rocky Linux/X11 (pure-ctypes
libX11/libXtst) behind one `hid.py` shim. Flame 2026.x and 2027
(per-interpreter vendored PyObjC on macOS).

Everything discovered along the way — how Flame routes input below Qt,
the `cursor_position` primitive, the repaint-nudge ladder, the
`hasattr` trap, socket geometry — is written up in
[docs/FINDINGS.md](docs/FINDINGS.md).

**Known open:** R (replicate) needs its multi-selection to survive the
grab; if Flame clears selection on press in some cases the selection
should be captured in the press snapshot instead of at arm time.
Interactive pin/tag controls are deliberately absent — two attempts
crashed Flame; pins and tags are file-edited.
