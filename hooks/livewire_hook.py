"""Flame startup hook for forge-livewire.

Symlink (or copy) this file into a Flame python hooks directory, e.g.:

    ln -s /path/to/forge-livewire/hooks/livewire_hook.py \
          /opt/Autodesk/shared/python/livewire_hook.py

It resolves the repo root from its own real location, so a symlink is enough.
"""

import os
import sys


def app_initialized(project_name):
    repo = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
    if repo not in sys.path:
        sys.path.insert(0, repo)
    import livewire
    livewire.install()
