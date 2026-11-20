"""NOAA CPC daily soil moisture (Leaky Bucket model, 0.5 deg) per district, 2000-2025.

CPC publishes one archive per year of daily GeoTIFFs of total-column soil moisture `w`
(https://ftp.cpc.ncep.noaa.gov/wd51yf/global_daily/clim/w.YYYY.tif.tar.gz, ~86 MB each).
Each day is read windowed to Uganda and reduced to an area-weighted district mean and max.
A 0.5 deg cell (~3,000 km2) is larger than most districts, so neighbouring districts often
share one or two cells: read this as a regional soil state, not a district-scale one.

Writes {PROJECT_PREFIX}/processed/cpc_soil/cpc_soil_adm2_daily.parquet
(date, pcode, mean, max), in the file's units. Resumable via yearly checkpoints.

Run:  uv run python pipeline/build_cpc_soil_adm2.py [start_year] [end_year]
"""

import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

import numpy as np
import ocha_stratus as stratus
import pandas as pd
import rasterio
from rasterio.io import MemoryFile
from rasterio.windows import bounds as window_bounds
from rasterio.windows import from_bounds
from tqdm import tqdm

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.constants import PROJECT_PREFIX, UGA_BOX
from src.zonal import zonal_stats
from src.zones import load_adm2

URL = "https://ftp.cpc.ncep.noaa.gov/wd51yf/global_daily/clim/w.{year}.tif.tar.gz"
CKDIR = Path(__file__).resolve().parent / ".checkpoint_cpc_soil"
BLOB = f"{PROJECT_PREFIX}/processed/cpc_soil/cpc_soil_adm2_daily.parquet"


def read_member(data: bytes):
    """(array, bounds, crs_wkt) for one daily GeoTIFF held in memory, clipped to UGA_BOX."""
    with MemoryFile(data) as mf, mf.open() as ds:
        w = from_bounds(*UGA_BOX, ds.transform).round_offsets(op="floor").round_lengths(op="ceil")
        arr = ds.read(1, window=w).astype("float32")
        if ds.nodata is not None:
            arr[arr == ds.nodata] = np.nan
        arr[arr < 0] = np.nan
        crs = ds.crs.to_wkt() if ds.crs else rasterio.crs.CRS.from_epsg(4326).to_wkt()
        return arr, window_bounds(w, ds.transform), crs


def one_year(year: int, polys) -> pd.DataFrame:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / f"w.{year}.tif.tar.gz"
        urllib.request.urlretrieve(URL.format(year=year), path)
        parts = []
        with tarfile.open(path) as tar:
            members = [m for m in tar.getmembers() if m.isfile() and m.name.endswith(".tif")]
            for m in tqdm(members, desc=f"cpc soil {year}", leave=False):
                day = pd.to_datetime(Path(m.name).name.split(".")[1], format="%Y%m%d")
                df = zonal_stats(*read_member(tar.extractfile(m).read()), polys)
                df.insert(0, "date", day)
                parts.append(df)
    return pd.concat(parts, ignore_index=True)


def main(start_year: int = 2000, end_year: int = 2025) -> None:
    CKDIR.mkdir(exist_ok=True)
    polys = load_adm2()[["ADM2_PCODE", "geometry"]]
    for year in range(start_year, end_year + 1):
        out = CKDIR / f"{year}.parquet"
        if not out.exists():
            one_year(year, polys).to_parquet(out, index=False)
            tqdm.write(f"{year} done")
    df = pd.concat([pd.read_parquet(p) for p in sorted(CKDIR.glob("*.parquet"))], ignore_index=True)
    stratus.upload_parquet_to_blob(df, BLOB, stage="dev")
    tqdm.write(f"wrote {len(df):,} rows -> {BLOB}")


if __name__ == "__main__":
    main(*map(int, sys.argv[1:]))
