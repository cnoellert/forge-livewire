# Passoff — 2026-08-05 (the Shift bug is FIXED)

Read this first, then [FINDINGS.md](FINDINGS.md) — especially its
"isolation ladder (2026-08-05)" section, which is the authoritative
account of the bug that dominated the last week.

## State right now

- **The Media-panel shift-select bug is root-caused and fixed**
  (v1.3.0). Root cause: any Flame node-API access (`current_node`,
  `nodes` iteration, attr reads — each independently sufficient)
  performed synchronously while Flame processes a click breaks that
  click's shift-anchor handling in the Media panel. NOT the Quartz
  key/button polling, NOT the timer, NOT `cursor_position` reads,
  NOT popup focus churn. Proven by a 6-rung isolation ladder with
  repeat trials; see FINDINGS.
- **The fix:** `detector._tick` touches zero Flame node API at button
  press. The surface snapshot is deferred to the drag-live
  transition (two distinct `cursor_position` samples with the button
  down), which only genuine schematic drags produce. Media-panel
  clicks never touch the node API at all.
- **Verified live on portofino** (macOS, Flame 2026.2.2, real finish
  project): shift-select clean with the full detector running;
  noodle-drop verbs confirmed working. Action-schematic drag not yet
  explicitly re-tested post-fix (design says it works: both cursor
  feeds stream during Action drags; verify when convenient).
- **Livewire is RE-ENABLED on portofino** (hook symlink restored to
  `/opt/Autodesk/shared/python/livewire_hook.py`, detector running in
  the live session).
- **flame-01 (Linux) stays disabled** — not because of this bug
  (fixed), but because of the two unexplained hard crashes noted in
  `livewire/hid.py`. It needs a soak test on a disposable host before
  `LINUX_ENABLED` flips. Note: FINDINGS' "any X observation breaks
  Flame" conclusion is now suspect (all those trials carried the
  press-snapshot confound); the X backends could be retested with
  v1.3.0 if evdev ever becomes insufficient.

## Loose ends, in priority order

1. **Action-schematic regression pass** — one R/G gang and one
   converge inside an Action, confirming the deferred snapshot arms
   correctly there.
2. **flame-01 soak test** on a scratch box/session before re-enabling
   Linux (crashes, not the Shift bug, are the blocker).
3. **forge-flame-kb correction** — its entry on X polling breaking
   Flame keyboard handling inherits the confound; update it with the
   ladder result (edit docs/*.md, then rebuild chunks + index per
   that repo's README).
4. The `_bat_meta` staleness caveat is unchanged: `cursor_position`
   can be stale at the press instant (~100–150 ms catch-up), which is
   why drag-live requires two samples — do not "optimize" that away.

## Standing rules (unchanged, still earned the hard way)

- **Bridge-unreachable ≠ Flame-dead.** Confirm with the operator.
- **Never test on a working artist's box** without explicit consent
  for that session.
- **One variable per test; repeat before believing.** The ladder
  worked precisely because of this; v1.2.0 shipped off a confounded
  single trial and blamed the wrong call for a week.
- The bridge's `/exec` runs code on its HTTP thread by default — Qt
  objects (timers!) created there never fire. Pass
  `main_thread: true` or wrap in `flame.schedule_idle_event`, and
  remember idle events drain only on Flame UI activity (nudge the UI).

## Disable in an emergency

```bash
mv /opt/Autodesk/shared/python/livewire_hook.py /tmp/livewire_hook.py.disabled
```

Bridge one-liner to stop a running instance: `livewire.uninstall()`.
