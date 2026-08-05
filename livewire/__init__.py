"""forge-livewire — noodle-drop node browser for Autodesk Flame Batch."""

import os
import sys

__version__ = "1.2.0-dev"

# Flame's embedded Python does not ship PyObjC; use the vendored copy
# matching THIS interpreter (vendor/py311 for Flame 2026, vendor/py313
# for 2027, ... — compiled extensions are not cross-version). See
# README "Install" for the one-time bootstrap per Flame generation.
try:
    import Quartz  # noqa: F401
except ImportError:
    _vendor = os.path.join(
        os.path.dirname(os.path.dirname(os.path.realpath(__file__))),
        "vendor", "py%d%d" % sys.version_info[:2])
    if os.path.isdir(_vendor) and _vendor not in sys.path:
        sys.path.insert(0, _vendor)

from .detector import install, uninstall  # noqa: F401
from .indexer import refresh as reindex  # noqa: F401
