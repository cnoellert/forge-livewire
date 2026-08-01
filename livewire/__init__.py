"""forge-livewire — noodle-drop node browser for Autodesk Flame Batch."""

import os
import sys

__version__ = "0.6.0"

# Flame's embedded Python does not ship PyObjC; use the vendored copy
# (see README "Install" for the one-time bootstrap that creates it).
try:
    import Quartz  # noqa: F401
except ImportError:
    _vendor = os.path.join(os.path.dirname(os.path.dirname(
        os.path.realpath(__file__))), "vendor")
    if os.path.isdir(_vendor) and _vendor not in sys.path:
        sys.path.insert(0, _vendor)

from .detector import install, uninstall  # noqa: F401
from .indexer import refresh as reindex  # noqa: F401
