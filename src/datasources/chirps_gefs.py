"""CHIRPS-GEFS v12 rainfall forecasts (CHC, UCSB) — the rainfall-forecast archive.

Daily-issued forecasts on the CHIRPS 0.05 deg grid, 2000-01-01 onward, as
plain GeoTIFFs served over HTTPS (read with GDAL /vsicurl/ range requests,
windowed to Uganda). Two products are used:

  05day/precip_mean/data-mean_{issue}_{end}.tif   5-day accumulation from the issue day
  daily_16day/{Y}/{m}/{d}/data.{valid}.tif        one file per issue x valid day (16 leads)

The archive path holds data to 2026-07-04 as of 2026-09-02; the current
operational feed may have moved — check before using this for live monitoring.
Same product the team used for the Yemen flash-flood framework (CHIRPS-GEFS
3-day cumulative) and the hurricanes monitoring.
"""

from datetime import date, timedelta

import numpy as np
import rasterio
from rasterio.windows import bounds as window_bounds
from rasterio.windows import from_bounds

from src.constants import UGA_BOX

BASE = "https://data.chc.ucsb.edu/products/EWX/data/forecasts/CHIRPS-GEFS_precip_v12"


def url_5day(issue: date) -> str:
    end = issue + timedelta(days=4)
    return f"{BASE}/05day/precip_mean/data-mean_{issue:%Y%m%d}_{end:%Y%m%d}.tif"


def url_daily(issue: date, valid: date) -> str:
    return f"{BASE}/daily_16day/{issue:%Y/%m/%d}/data.{valid:%Y.%m%d}.tif"


def read_windowed_url(url: str, attempts: int = 3):
    """(array, bounds, crs_wkt) for one CHC GeoTIFF clipped to UGA_BOX via /vsicurl/."""
    env = dict(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR", CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif",
               GDAL_HTTP_MAX_RETRY="3", GDAL_HTTP_RETRY_DELAY="2")
    for i in range(attempts):
        try:
            with rasterio.Env(**env), rasterio.open(f"/vsicurl/{url}") as ds:
                w = from_bounds(*UGA_BOX, ds.transform).round_offsets(op="floor").round_lengths(op="ceil")
                arr = ds.read(1, window=w).astype("float32")
                if ds.nodata is not None:
                    arr[arr == ds.nodata] = np.nan
                arr[arr < 0] = np.nan
                return arr, window_bounds(w, ds.transform), ds.crs.to_wkt()
        except rasterio.errors.RasterioIOError:
            if i == attempts - 1:
                raise
    raise RuntimeError("unreachable")
