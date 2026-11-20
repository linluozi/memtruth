"""memtruth: triangulate Python memory claims against real resident memory."""

from .measure import MeasureError, run_once
from .verdict import classify

__version__ = "0.1.0"
__all__ = ["run_once", "MeasureError", "classify", "__version__"]
