"""Download GloFAS v4 reanalysis (Uganda box) and, when a point is given, its reforecast.

Run:  uv run python pipeline/download_glofas.py reanalysis
      uv run python pipeline/download_glofas.py reforecast <station_key> <lat> <lon>
Needs a CDS/EWDS key in ~/.cdsapirc or CDSAPI_KEY.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.datasources import glofas

if __name__ == "__main__":
    what = sys.argv[1]
    if what == "reanalysis":
        glofas.download_reanalysis_box()
    elif what == "reforecast":
        key, lat, lon = sys.argv[2], float(sys.argv[3]), float(sys.argv[4])
        glofas.download_reforecast_point(key, lat, lon)
    else:
        raise SystemExit(__doc__)
