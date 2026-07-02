"""
Azure App Service entry point.

Uvicorn loads this module from the project root, so we add the root to
sys.path before importing src.* (Azure does not set PYTHONPATH by default).
"""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.api.app import app  # noqa: F401
