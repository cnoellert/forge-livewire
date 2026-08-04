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

## 2. Matchbox / OFX / user-bin indexing — ✅ shipped 2026-07-29

262 entries on the dev box: node types + stock Matchbox scan + user
bins (`append_setup`, tolerating its throw-after-append quirk) + OFX
labels harvested from search_settings.json / Nuke's plugin cache / live
batch nodes. Ranking uses Flame's own Weight/Favorite, so an empty
query surfaces the artist's most-used tools. See FINDINGS "Indexing
sources". Follow-ups: stale harvested OFX labels silently no-op
(`change_plugin` gives no error — validate against plugin_name after
commit and warn); `EXTRA_MATCHBOX_DIRS` config for Logik collections
(belongs in the item-8 config file); auto-reindex on a timer or hook
instead of manual `livewire.reindex()`.

## 3. Action input capture → auto-wire into maps — ✅ shipped 2026-07-30

Shipped as the **I (ingest) verb**: grab an Action in Batch, tap I,
release → confirm table (media | feeder | map-type guess, parent-surface
picker) → creates each map inside the Action, `assign_media`-bound,
rowed below the scene. Scan rides `media_nodes` + per-node `.sockets`
(full connection topology as a dict); guesses from feeder/clip naming
conventions. Follow-ups: richer inference (channel metadata), matte/
selective destinations, re-running ingest on an already-mapped Action
(dedup). Original spec follows for reference.

The original flagship brief: Capture everything feeding an Action's
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

## 4. Source-socket inference — ✅ shipped 2026-08-04

Calibrated live from seven labeled pulls: standard nodes stack output
sockets down the right edge at ~21 units/socket centered on the anchor
(grabs at dx≈+40); expanded multichannel clips at 37.5 units/tab in a
column at dx≈+112, top tab ~47 units below the centered model, alphas
sharing their channel's tab. Median of the first three drag samples
defeats press staleness; dx≈0 (body grabs snap to anchor) gates
confidence; half-step residual guard rejects ambiguity. The inferred
socket pre-selects the browser's socket menu. Follow-up: per-type
geometry table if any node class deviates from the centered model.
Original brief:

Today the grabbed output socket isn't sensed — `Result`/first is assumed
(M-mode guesses the matte output). FINDINGS shows a socket grab reads as
a small, non-snapped offset from the node anchor (`action3`: ≈ (+37,+11))
while body hovers snap to the anchor (±3). The offset likely encodes the
socket's position along the node's bottom edge.

Approach: probe session grabbing every output of multi-output nodes
(Action, Master Keyer, Clamp) at a few zoom levels; if x-offset ranks
sockets left-to-right reliably, map offset rank → `output_sockets` index.
Fallback stays the combo. Watch zoom dependence — offsets may scale.

## 5. Favorites / recents — ✅ shipped 2026-08-04

`livewire/store.py`: per-artist `~/.config/livewire.json` (atomic
writes), every browser commit records count + timestamp per display
name. Ranking = match quality → pinned (Flame favorites + the JSON's
hand-editable `pinned` list) → usage score (livewire count ×4 +
Flame's search weight) → recency → name. The same file is item 8's
future config home. Tag search also matches Flame's own Tags plus a
per-entry `tags` map in the same file.

**Do not add in-browser pin/tag controls.** Tried twice, crashed Flame
both times (delegate row icons; then Ctrl+P/Ctrl+T) — see the note in
browser.py. Any retry needs a scratch project and a soak test.
Follow-up worth having: usage decay if ancient habits crowd the list.

## 6. Insert into an existing noodle

Drop the browser-created node *inline*: if the armed release lands near
an existing connection line (not near a node), create + rewire
upstream→new→downstream. We have node positions; connection topology is
readable from the batch (verify: `node.sockets` connections or batch
setup XML — forge-bridge already parses batch XML). Point-to-segment
distance in schematic space; threshold similar to GRAB_RADIUS.

## 7. Branch-from-input (pull upstream)

Grabbing an *input* socket (top edge — offset sign should distinguish it
from outputs, same probe as item 4) and dropping on empty = "create a
node feeding this input": browser commit wires new node's Result into
the grabbed input. Mirrors ComfyUI's reverse drag.

## 8. Config file + deployment story

Constants out of source: arm-key vkeys, theme, radius, verbosity into a
JSON config with per-user override. Then a proper deploy path for a
studio: one shared checkout + symlinked hook per workstation, version
tag, and eventually a Logik portal submission (which effectively
requires items 2 and 5 for feature parity with expectations).

## 9. Linux backend — ✅ shipped 2026-08-03

`livewire/hid.py` shim: macOS Quartz vs pure-ctypes X11
(`XQueryPointer` button mask, `XQueryKeymap` via keysym→keycode,
XTest 1px jiggle as the repaint nudge). Validated in production use on
flame-01 (Rocky 9.5, Flame 2026.2.1, X11 `:1`) — popup takes focus
with plain `activateWindow`, no NSWindow-style trick needed. Remaining
Linux follow-ups: repaint confirmed immediate (jiggle kept as
insurance); `app_active()` is a stub (always True); flame-01's user bins/favorites came up empty —
find where 2026.2.1 keeps user prefs on that box; Wayland untested
(Flame ships X11).

## 10. Channel fan-out: multichannel EXR → Action & CryptoMatte — ✅ shipped 2026-08-04

Shipped and verified against production V-Ray multipart EXRs (33–39
sockets): Action pick = rgba→Back + one media per non-crypto channel
(`_alpha` sibling → media Matte), medias stacked beside the clip;
CryptoMatte pick = one CryptoMatte node per crypto family (MAT first,
extras stacked), rgba→Front + rank layers → uCryptoNNrgb/a. Works on
collapsed AND expanded clips — expanded ones match grabs along a
vertical segment (EXPANDED_STEP≈55 units/socket; `collapsed` is a
readable node attribute). Follow-ups: family picker UI; multitrack
clips and *groups* still unprobed; socket-tab-specific grabs await
item 4. Original brief:

The missing half of the fan-out grammar: converge maps N selected
nodes → N inputs; this maps the M output sockets of ONE node → M
inputs. No new arm key — F + target dispatch, as ever:

- **Multi-output clip + pick Action**: one media per channel output,
  wired in socket order, crypto channels EXCLUDED by pattern
  (`Crypto*` families + numbered sub-layers). Header announces e.g.
  "fan 12 channels (3 crypto skipped)".
- **Multi-output clip + pick Cryptomatte**: the inverse filter — only
  the crypto MAT/LAYER channels wire in. One CRYPTO_PATTERNS table
  serves both directions (edit point for studio naming schemes).
- Single-input picks keep today's behavior (socket combo etc.).

Probe list (blocked on a free Flame + a real multichannel EXR):
1. How a multichannel EXR clip presents in Batch — output socket per
   channel? naming? colour/matte pairs per layer?
2. The Cryptomatte node: exact type name, input sockets, how many
   crypto layers it expects, whether the manifest path needs setting.
3. Multitrack clips and *groups* ("group to Action") — same socket
   mechanism or a different exposure?
4. Whether media wiring from a named channel socket
   (`connect_nodes(clip, "N", media, "Front")`) behaves like Result.

Follow-up variant: connect-to-EXISTING Cryptomatte node (select EXR +
existing node, wire without the browser) — a new gesture class,
kin to item 6's drop-on-target; design after the create-and-wire
version proves the filtering.

## 11. Fan-out products become parallel chain heads

When a single pick produces SEVERAL nodes — a CryptoMatte fan-out
creating one node per crypto family, an Action fan-out creating N
media layers, a multi-node user bin — the gang currently continues
from one of them. It should be able to continue from *all* of them,
turning the fan-out into the heads of parallel chains (exactly what
R does across a selection, but seeded by the fan-out instead).

Shape: have the commit helpers return every node they created, not
just the chain-out node; if a gang/replicate is active and more than
one came back, split `chains` into one entry per product. Natural
demo: MC clip → CryptoMatte (2 families) → next pick lands on both
crypto nodes. Question to settle first: should plain G do this
automatically, or should it require R? (Leaning: G follows the
primary product, R adopts all of them — keeps "replicate" the verb
that means many.)

## Known rough edges (small, unordered)

- Armed release *onto* a node's input completes the native connection
  AND pops the browser — should detect release-over-node and stand down.
- `create_node` + `connect_nodes` are separate undo steps; investigate
  grouping so one Ctrl+Z removes the committed node cleanly.
- Grab radius is zoom-naive (150 schematic units regardless of view
  scale); if zoom is recoverable from socket-offset work (item 4), scale
  it.
- Browser list is capped at `MAX_ROWS * 4` entries with no scrollbar;
  fine at 99 types, revisit after item 2 grows the list.
- ISO keyboards: F/M are safe, but any future punctuation arm-key needs
  the vkey caveat from the README.
