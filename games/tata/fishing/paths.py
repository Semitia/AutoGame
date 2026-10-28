"""Repository and runtime paths shared by Tata's fishing entry points."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
RUNTIME = ROOT / 'runtime' / 'tata' / 'fishing'
