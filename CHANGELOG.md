# Changelog

## 1.3.4 — 2026-10-05

**Fix: Flame crash on commit.** Pressing Enter in the browser crashed
Flame 2026.2.2 (SIGSEGV / SIGILL) right after `createNode` or
`connectNodes`. `_commit` closed the `WA_DeleteOnClose` popup *before*
running the commit, and `_nudge_flame`'s synchronous
`sendPostedEvents()` then ran the DeferredDelete while still on the
popup's own eventFilter stack — use-after-free on unwind. The popup now
hides, commits, then closes; and every repaint nudge, the first
included, goes through `QTimer.singleShot`, so the event loop is never
pumped re-entrantly from inside a Qt handler (gang mode too).

Operator-verified on portofino.

## 1.3.3 — 2026-08-05

**Expanded-EXR grab surface is a rectangle, not a line.** The tabs on
an expanded multichannel clip reach ~+320px right of the anchor (live
grabs landed at dx +109 and +214), so grabs past `GRAB_RADIUS` were
silently killing the fan-out with `source=None`. Matching now treats
any dx in `[0, EXPANDED_XMAX]` as on-surface, across the full
tab-column height.

**Fan-out geography.** The media column moves fully clear of the tab
rectangle (`anchor + EXPANDED_XMAX + MEDIA_DX`), and the picked
Action's root is pushed out of the column's lane when the drop lands
in line with it. Per-tab row alignment via the `SOCK_EXR` calibration
was tried and reverted — the on-screen layout doesn't map to it; a
warning comment marks the dead end.

**Linux is enabled by default again.** `LINUX_ENABLED = True`. A
full-day soak on flame-01 — Shift regression pass, the complete verb
suite, Action surface work, real production use — ran clean on the
evdev backend with v1.3.x. The two 2026-08-04 crashes that forced
1.1.2's opt-in never recurred and predate the restructuring. The
flame-01 hook symlink is restored.

Operator-verified on portofino: all verbs on expanded and collapsed
multichannel EXRs. Also recorded in FINDINGS: `clip.collapsed` can
read stale at rest (likely latched by undo) while reading correctly
mid-drag — advisory only.

## 1.3.2 — 2026-08-05

**Action surface rigs.** A commit that arrives with its own axis — as
surfaces do — occupies two rows, so the chain step doubles for it;
chained surfaces had been stacking into each other. When the drop
lands closer than two rows below the source, the rig is pushed down to
clearance so the auto-axis never crams into the source node.

**`Surface` is an alias for Extended Bicubic.** `create_node("Surface")`
raises despite `"Surface"` appearing in `node_types` — Extended Bicubic
is the only creatable surface, and its `.type` reads back as
`"Surface"`. Commits now route the source link into the auto-spawned
parent axis and place it midway, matching Flame's hand-made
source → axis → surface convention.

Probed live on 2026.2.1: surface flavor (Image / Bilinear /
Perspective / Ext Bicubic) is pure GUI state, invisible to Python in
both directions; `add_media()` spawns the full image rig, the only
scriptable "Image" path; and per-node `.selected` does work inside
Action, contrary to the earlier no-selection-signal claim.
Operator-verified on flame-01: clean axis → surface → axis → surface
stacks from both tight and roomy drops.

## 1.3.1 — 2026-08-05

**The surface decision moves from arm time to fire time.** With
1.3.0's deferred snapshot, a verb key held early armed with zero
Action samples and misclassified the surface as Batch — G-in-Action
offered Batch nodes, F-in-Action needed a late key, R+M and G+M missed
the multi-select context. Deciding at release sees the full history.

**Repaint is region-local, not just panel-local.** The post-commit
nudge burst now sweeps in ~55px steps from the drop point in the
chain-growth direction (right in Batch, down in Action). Fixed-point
bursts left 3rd-and-beyond chained nodes invisible until a real click.

**Browser polish.** Dropped the `::item:hover` rule — the sweep's
synthetic moves marched a phantom hover-selection down the list — and
pinned chain-mode selection to the committed entry by identity rather
than row index. `CHAIN_DY_ACTION` 200 → 120 (operator call).

Full operator regression pass clean on portofino (2026.2.2):
shift-select, F/G/G+M/R/R+M in Batch, F/G in Action.

## 1.3.0 — 2026-08-05

**The real fix: defer the node snapshot past click processing.** The
isolation ladder proved the Media-panel shift-select breakage was
never the Quartz polling. Any Flame node-API access — `current_node`,
iterating `nodes`, reading an attr, each independently sufficient —
made synchronously while Flame is processing a click breaks that
click's shift-anchor handling. The timer, button and key polling,
`cursor_position` reads, and `NSApp.isActive` all polled clean at
30 ms.

The press transition now touches zero Flame node API; the surface
snapshot defers to the drag-live transition (two distinct
`cursor_position` samples with the button down), which only genuine
schematic drags produce. Media-panel clicks never reach the node API.

Verified live: shift-select clean with the full detector running,
noodle drops working. FINDINGS gains the ladder record, and both the
08-04 latch-desync narrative and the Linux "any X observation breaks
Flame" conclusion are marked superseded/suspect — each carried the
press-snapshot confound.

## 1.1.2 — 2026-08-04

**Linux back to opt-in, pending a disposable-host soak.** The evdev
backend is complete and validated, but two evidence-free hard crashes
on the test box — one log ending at livewire's `_start` — made
"probably fine" insufficient for a production machine. Enabling Linux
is now explicit opt-in; the flame-01 hook was pulled.

## 1.1.0 — 2026-08-04

**Linux ships, on evdev.** `LINUX_ENABLED = True`, reading kernel
input events directly instead of asking X anything. The Shift saga
resolved: the input chain was clean end-to-end all along — server mask
probes showed perfect Shift+Btn1 chords while Flame ignored them. The
culprits were a PCoIP-stranded phantom Ctrl in the server, then
Flame's own internal modifier latch desyncing on focus churn, cured by
tapping the modifiers with Flame focused. All three transports are
exonerated and popups strand nothing (controlled test, clean mask).
`evdev` also rescans for new device nodes, since PCoIP recreates them
on reconnect.

## 1.0.3 — 2026-08-04

**Linux/X11 disabled.** With livewire running on Rocky, Shift stopped
working in Flame's Media panel; stopping the detector's 30 ms poll
timer restored it immediately, with no restart. A read-only X backend
(no XTest, no XSetInputFocus) did not help — the polling itself is the
cause. `LINUX_ENABLED = False` in `livewire/hid.py` until the backend
is redesigned around XInput2 raw events instead of polling. macOS is
unaffected and unchanged.

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

**Platforms.** macOS (Quartz). A Linux/X11 backend exists behind the
same `hid.py` shim but is **disabled in 1.0.3** — its poll loop
interferes with Flame's keyboard handling. Flame 2026.x and 2027
(per-interpreter vendored PyObjC on macOS).

Everything discovered along the way — how Flame routes input below Qt,
the `cursor_position` primitive, the repaint-nudge ladder, the
`hasattr` trap, socket geometry — is written up in
[docs/FINDINGS.md](docs/FINDINGS.md).

**Known open:** a pick that fans out into several nodes (two
CryptoMattes, an Action plus its medias) leaves the chain following
only one of them — see roadmap item 11. Interactive pin/tag controls
are deliberately absent: two attempts crashed Flame, so pins and tags
are file-edited.
