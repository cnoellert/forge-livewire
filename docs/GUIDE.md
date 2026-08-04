# forge-livewire — Artist Guide

Livewire gives Flame the node browser the schematic always deserved:
pull a noodle, tap a key, type a few letters, and the node you wanted is
created at the drop point — already wired. It works in Batch and inside
Action, and it knows your Matchboxes, your user bins, and your OFX.

Everything livewire creates is a normal Flame node made through Flame's
own API. There is nothing special to render, save, or clean up, and
Ctrl+Z works exactly as if you had built it by hand.

## Setup (once)

macOS (once per Flame generation — 2026 is py311, 2027 is py313):

```bash
/opt/Autodesk/python/2026.2.2/bin/python3.11 -m pip install \
    --target /path/to/forge-livewire/vendor/py311 pyobjc-framework-Quartz
```

Both platforms (Linux needs nothing else):

```bash
ln -s /path/to/forge-livewire/hooks/livewire_hook.py \
      /opt/Autodesk/shared/python/livewire_hook.py
```

Restart Flame (or rescan python hooks). That's it — livewire is now
armed in every session, macOS and Rocky Linux (X11) alike.

## The gesture

1. **Pull a noodle** out of any node's output socket — a completely
   normal connection drag.
2. **While still holding**, tap an arm key: **F**, **G**, or **R**
   (add **M** for matte wiring — see below).
3. **Let go over empty schematic space.** The noodle cancels, and the
   search popup appears right where you dropped it.
4. **Type to narrow, Enter to commit.** ↑/↓ choose, Esc or clicking
   anywhere else cancels.

The arm keys are only watched mid-drag. F, G, R, and M all keep their
normal Flame meanings the rest of the time.

## The three verbs

Think of it as: **F converges, G chains, R replicates, I ingests.**

### F — insert one node

Pull from `plate`, tap **F**, drop, type `bl`, Enter → a Blur wired
`plate → Blur`, sitting exactly where you dropped it.

- **F then M** (same drag): wires front *and* matte — the source's
  image output to the new node's Front and its matte output (e.g. a
  keyer's `OutMatte`) to the Matte input. Livewire only wires a matte
  when the source really has a matte output — it never routes an image
  output into a Matte input.
- **M alone**: the connection goes to the new node's Matte input, and
  the socket menu pre-selects the source's matte output.
- If the source has several outputs, a menu above the search field
  picks which one feeds the connection — pre-set to the socket you
  grabbed (pull the matte tab, get the matte), else `Result`.

### F with several nodes selected — converge

Select two or more nodes, then pull from **one of the selected ones**:

- Pick a **Comp** (or Blend & Comp): the grabbed node feeds Front, the
  *other* selected node feeds **Back** — with F+M, mattes land on Matte
  and Back Matte too. A four-wire comp from one pull.
- Pick an **Action**: the grabbed node feeds `Back`, and every other
  selected node gets **its own media layer**, wired in selection order.
  Select beauty + normals + motion vectors + Z, pull, F, `action`,
  Enter — a fully loaded Action, every pass ingested.

Pulling from a node that *isn't* selected ignores the selection — no
surprises from a leftover selection somewhere in the schematic.

**Multichannel EXRs fan out on their own.** Pull from a multipart EXR
clip (collapsed or expanded — grab any tab), F, and:

- pick **Action**: `rgba` feeds Back and every other non-crypto channel
  gets its own media — Z, AO, light selects, the lot — each channel's
  `_alpha` landing on its media's Matte. A full AOV hookup in one pull.
- pick **CryptoMatte**: the inverse — one CryptoMatte node per crypto
  family (MAT, NODE…), each wired `rgba` → Front and its three rank
  layers + alphas into the crypto inputs, ready to pick mattes.

### G — gang (build a pipe)

Pull, tap **G**, drop. The browser stays open: every Enter commits a
node *immediately* and the next pick chains off it, marching right —
`blur↵ cc↵ regrain↵ Esc` builds `plate → Blur → CC → Regrain` in four
keystrokes. The header shows the growing trail. **Esc ends the gang** —
everything is already committed; regret is Ctrl+Z.

**G then M**: every link wires front+matte (where the upstream node
really has a matte output). In Action, gangs build *downward* as a
parent chain, matching Action's layout.

### R — replicate (one recipe, many nodes)

Select several nodes, pull from one of them, tap **R**, drop. Now every
pick applies to **each selected node**: pick Blur → every selected node
grows its own Blur, each in line with its own source. Keep picking and
all the chains extend in parallel; Esc ends them all.

Five shots that all need `Resize → Burn-in`? Select the five, pull, R,
`resize↵ burn↵ Esc`. Ten nodes, wired and placed, in three seconds.

### I — ingest (an Action's passes into maps)

Got an Action with a stack of AOVs noodled into its media inputs —
normals, motion vectors, position, Z, crypto? Pull from the **Action
node**, tap **I**, release. Instead of the node browser you get a
table: one row per media showing what feeds it and a map-type guess
read from the pass names (`_N` → Normal Map, `MV`/`vectors` → Motion
Vectors Map, `P` → Position, `Z` → Z-Depth, `crypto`/`ID` → Object ID,
`albedo`/`bty` → Diffuse, and so on). Correct any guesses, pick which
surface the maps should parent under, hit **Ingest** — every map is
created inside the Action, bound to its media, and rowed neatly below
the scene. Rows set to `(skip)` are left alone.

The minutes of add-media-and-wire ritual at the start of every 3D comp,
compressed into one pull.

## What's in the browser

Everything Flame can make, tagged by origin:

- **Node types** — the standard Batch tools (or Action's node types
  when you're inside an Action).
- **`Blur - Matchbox`** — stock Matchbox shaders, created with the
  shader already loaded.
- **`Lens_Blur - User`** — your saved user-bin setups, appended at the
  drop point and wired in (multi-node bins come in as a group).
- **`Reduce Noise v6 - OpenFX`** — OFX plugins, created with the plugin
  selected.

With an empty search box, the list is ordered by **your** habits:
pinned and favorite tools first, then by use — and livewire learns
from every commit, so the nodes you actually pick climb the list and
your most recent picks break ties. (It also seeds from Flame's own
search history, so day one already looks like you.) Search matches
prefer prefixes, then word starts, then anything-inside, then fuzzy.

The highlighted row shows a **star** and a **tag**, just like Flame's
own search: click the star to pin the entry to the top of every list
(click again to unpin); click the tag to give it your own search
synonyms ("shake, steady" on 2D Transform means typing `shake` finds
it). Flame's built-in tags already work — livewire reads them from your
Flame search settings. Pins, tags, and usage history all live in
`~/.config/livewire.json` and travel with your home directory.

Installed new shaders or saved new bins mid-session? Run
`livewire.reindex()` in the Flame python console, or just restart.

## Inside Action

Same gesture on Action's schematic: drag a link, tap any arm key, drop.
The browser lists Action's nodes (Axis, Light, Surface, GMask, …), the
header reads `parent <node>`, and the pick becomes a child of the
grabbed node — or unparented if you grabbed empty space. Livewire
figures out which schematic you're in per-drag; there is no mode to
switch.

## Quick reference

| Keys (while dragging) | Result |
|---|---|
| **F** | one node, source → Front |
| **M** | one node, source matte output → Matte |
| **F + M** | one node, front *and* matte wired |
| **F**, multi-select | converge: Back pair on Comps, media layers on Action |
| **G** | gang: chain picks off the grab until Esc |
| **G + M** | gang with front+matte links |
| **R**, multi-select | replicate picks onto every selected node until Esc |
| **R + M** | replicate with front+matte links |
| **I** on an Action | ingest: media → map-type table, Enter wires the lot |
| **Enter** | commit the highlighted entry |
| **↑ / ↓** | move the highlight |
| **Esc / click away** | close (ends a gang/replicate — already committed) |

## Tips and honest limits

- **Arm while the button is down.** Tapping F before you grab or after
  you release does nothing (and bare F is Flame's own Timeline hotkey).
- **Which output did I grab?** Livewire infers it from the grab point
  — pull `OutMatte` and the socket menu arrives pre-set to `OutMatte`;
  pull a channel tab on an expanded EXR and that channel is pre-set.
  Body grabs and ambiguous pulls default to `Result`. The menu is
  always there to correct a guess, and **M** still forces matte intent.
- **OFX list is learned, not exhaustive** — plugins you've used appear;
  a brand-new plugin shows up after its first manual use.
- **Wrong node in the header?** Zoomed way out, node anchors crowd
  together and the grab can resolve to a neighbor. Zoom in a touch.
- A gang pick occasionally paints a beat late — the node is already
  committed; it's Flame's redraw catching up.
- Keyboard layouts: the arm keys are US-layout virtual keycodes; on
  ISO/Nordic boards letters are fine, but if a key ever seems dead,
  see the constants at the top of `livewire/detector.py`.
