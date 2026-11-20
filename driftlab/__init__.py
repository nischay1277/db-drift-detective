"""DB Drift Detective: bounded application-level differential database tests."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if (ROOT / '.vendor').is_dir():
    sys.path.insert(0, str(ROOT / '.vendor'))
