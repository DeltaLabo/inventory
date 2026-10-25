"""Local paths anchored to the checkout, independent of the working directory."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
ASSETS_DIR = ROOT / "assets"
