# forge-livewire

ComfyUI-style noodle-drop node browser for Autodesk Flame Batch.

Pull a noodle from a node's output socket, release it over empty schematic
space, and a searchable node browser pops at the drop point. Pick a node and
it is created there and wired to the output you pulled from.

Runs entirely inside Flame's embedded Python (PySide6 + PyObjC) — no external
daemon, no screen capture, no OS accessibility permissions.

## How it works

Flame handles schematic input natively, below Qt's event dispatch, so Qt
event filters never see it. Livewire instead:

1. Polls the raw HID left-button state via `Quartz.CGEventSourceButtonState`
   on a 30 ms `QTimer` (main thread) to get press/release edges.
2. Reads `flame.batch.cursor_position` — live *schematic-space* coordinates —
   to map the grab point and drag path onto node rectangles
   (`node.pos_x/pos_y`).
3. Classifies the gesture (socket grab vs body click vs node move vs
   marquee), and on a qualifying release pops a PySide6 browser dialog.
4. Commits with `flame.batch.create_node()` + `connect_nodes()` at the
   release position.

See [docs/FINDINGS.md](docs/FINDINGS.md) for the empirical probe results
(Flame 2026.2.2 / macOS) that this design rests on.

## Status

Prototype. Gesture-detection findings validated live in Flame 2026.2.2;
detector + browser dialog in progress.
