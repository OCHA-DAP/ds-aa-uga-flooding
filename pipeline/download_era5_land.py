"""Download ERA5-Land daily soil moisture (layers 1-2) for Uganda, 1998-2026.

Run:  uv run python pipeline/download_era5_land.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.datasources import era5_land

if __name__ == "__main__":
    era5_land.download()
