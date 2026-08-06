# Passoff — 2026-08-05 (Shift bug fixed; full regression pass clean)

Read this first, then [FINDINGS.md](FINDINGS.md) — its "isolation
ladder (2026-08-05)" section is the authoritative account of the
Shift bug; the repaint-refinement and fire-time-decision notes cover
the same-day follow-on fixes.

## State right now

- **v1.3.1 is live and verified on portofino** (macOS, Flame
  2026.2.2, real finish project). Full operator regression pass
  clean: Media-panel shift-select, F / G / G+M / R / R+M in Batch,
  F and G chains in Action schematics, browser selection stable,
  Action chain spacing tightened (CHAIN_DY_ACTION 200 → 120).
- **The Shift bug** (a week of pain): any Flame node-API access
  during click processing breaks that click's shift-anchor in the
  Media panel. Fixed by deferring the surface snapshot to drag-live
  (v1.3.0) and the surface *decision* to fire time (v1.3.1). The
  Quartz polling was never guilty. See FINDINGS.
- **Repaint** is region-local, not just panel-local: the post-commit
  nudge burst now SWEEPS from the drop point toward the chain growth
  direction. The browser list deliberately has no hover style — the
  sweep's synthetic moves drove a phantom hover-selection march
  (see FINDINGS refinement note).
- **Livewire is ENABLED on portofino** (hook symlink at
  `/opt/Autodesk/shared/python/livewire_hook.py`).
- **flame-01: ENABLED (2026-08-05)** — `LINUX_ENABLED = True` in the
  repo, hook symlink restored. Graduated after a full-day soak
  (Shift regression pass, complete verb suite, Action surface work,
  real use) ran clean. The two 2026-08-04 crashes never recurred and
  predate the v1.3.x restructuring; if a crash pattern reappears,
  park the hook (command below) and re-open FINDINGS.

## Loose ends

1. FINDINGS' old Linux conclusion "any X observation breaks Flame"
   is marked suspect (all trials carried the press-snapshot
   confound). Only relevant if evdev ever becomes insufficient.
2. Action surface flavors (Image/Bilinear/Perspective) are GUI-only —
   invisible to the Python API in both directions (FINDINGS + KB).
   Candidate Autodesk feature request.

## Standing rules (unchanged, still earned the hard way)

- **Bridge-unreachable ≠ Flame-dead.** Confirm with the operator.
- **Never test on a working artist's box** without explicit consent
  for that session.
- **One variable per test; repeat before believing.** The ladder
  worked because of this; v1.2.0 shipped off a confounded single
  trial and blamed the wrong call for a week.
- The bridge's `/exec` runs code on its HTTP thread by default — Qt
  timers/events created there never fire. Use `main_thread: true` or
  `flame.schedule_idle_event`, and remember idle events drain only on
  Flame UI activity (nudge the UI).

## Disable in an emergency

```bash
mv /opt/Autodesk/shared/python/livewire_hook.py /tmp/livewire_hook.py.disabled
```

Bridge one-liner to stop a running instance: `livewire.uninstall()`.
