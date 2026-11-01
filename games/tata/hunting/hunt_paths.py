"""Tata-only paths; no account data or game input at import time."""
from pathlib import Path
import sys

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
RUNTIME=ROOT/'runtime/tata/hunting'
ASSETS=HERE/'assets'
for folder in (ROOT/'games/tata/mainline',ROOT/'src'):
    if str(folder) not in sys.path:sys.path.insert(0,str(folder))
