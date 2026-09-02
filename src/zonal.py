"""Windowed COG reads from the team raster blob + exactextract zonal stats.

Shared by the FloodScan and IMERG daily pipelines: read one global/continental
daily COG windowed to Uganda, then compute per-district mean and max with
exactextract (area-weighted; reproduces the rasterstats DB within ~1% where
the DB has the country — it does not have Uganda ADM2).
"""

import io

import geopandas as gpd
import numpy as np
import ocha_stratus as stratus
import pandas as pd
import rasterio
from exactextract import exact_extract
from exactextract.raster import NumPyRasterSource
from rasterio.windows import bounds as window_bounds
from rasterio.windows import from_bounds

from src.constants import UGA_BOX


def read_windowed(blob_name: str, band: int = 1, attempts: int = 3):
    """Return (array, bounds, crs_wkt) for one blob COG clipped to UGA_BOX."""
    for i in range(attempts):
        try:
            data = stratus.load_blob_data(blob_name, container_name="raster", stage="prod")
            with rasterio.open(io.BytesIO(data)) as ds:
                w = (
                    from_bounds(*UGA_BOX, ds.transform)
                    .round_offsets(op="floor")
                    .round_lengths(op="ceil")
                )
                arr = ds.read(band, window=w).astype("float32")
                nodata = ds.nodata
                if nodata is not None:
                    arr[arr == nodata] = np.nan
                return arr, window_bounds(w, ds.transform), ds.crs.to_wkt()
        except Exception:  # noqa: BLE001 — transient blob/network errors; re-raised on the last try
            if i == attempts - 1:
                raise
    raise RuntimeError("unreachable")


def zonal_stats(
    arr: np.ndarray, bounds, wkt: str, polys: gpd.GeoDataFrame, id_col: str = "ADM2_PCODE"
) -> pd.DataFrame:
    """Area-weighted mean and max of `arr` per polygon."""
    xmin, ymin, xmax, ymax = bounds
    src = NumPyRasterSource(arr, xmin=xmin, ymin=ymin, xmax=xmax, ymax=ymax, srs_wkt=wkt, nodata=np.nan)
    df = exact_extract(src, polys, ["mean", "max"], include_cols=[id_col], output="pandas")
    return df.rename(columns={id_col: "pcode"})
