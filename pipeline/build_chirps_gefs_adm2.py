"""Daily-issued CHIRPS-GEFS 5-day rainfall forecast per district, 2000-2026.

For every issue date in the CHC archive, reads the 5-day accumulation forecast
(05day/precip_mean) windowed to Uganda and computes per-district mean and max.
This is the forecast leg of the flash-flood skill chain (forecast -> observed
rainfall -> observed flooding/impact); the observed leg is IMERG from
build_daily_adm2.py, accumulated over the same 5-day windows at analysis time.

Writes {PROJECT_PREFIX}/processed/chirps_gefs/chirps_gefs_5day_adm2.parquet
(issue_date, valid_end, pcode, mean, max). Resumable via yearly checkpoints.

Run:  uv run python pipeline/build_chirps_gefs_adm2.py [start_year] [end_year]
"""

import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path

import ocha_stratus as stratus
import pandas as pd
import rasterio
from tqdm import tqdm

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.constants import PROJECT_PREFIX
from src.datasources.chirps_gefs import read_windowed_url, url_5day
from src.zonal import zonal_stats
from src.zones import load_adm2

CKDIR = Path(__file__).resolve().parent / ".checkpoint_chirps_gefs"
ARCHIVE_END = date(2026, 7, 4)


def _one(args):
    issue, polys = args
    try:
        arr, bounds, wkt = read_windowed_url(url_5day(issue))
    except rasterio.errors.RasterioIOError:
        return None  # missing issue day in the archive; logged by the caller
    df = zonal_stats(arr, bounds, wkt, polys)
    df.insert(0, "valid_end", pd.Timestamp(issue + timedelta(days=4)))
    df.insert(0, "issue_date", pd.Timestamp(issue))
    return df


def main(start_year: int = 2000, end_year: int = ARCHIVE_END.year) -> None:
    CKDIR.mkdir(exist_ok=True)
    polys = load_adm2()[["ADM2_PCODE", "geometry"]]
    with ThreadPoolExecutor(max_workers=8) as pool:
        for year in range(start_year, end_year + 1):
            out = CKDIR / f"{year}.parquet"
            if out.exists() and year < ARCHIVE_END.year:
                continue
            d0, d1 = date(year, 1, 1), min(date(year, 12, 31), ARCHIVE_END)
            days = [d0 + timedelta(days=i) for i in range((d1 - d0).days + 1)]
            parts = list(
                tqdm(
                    pool.map(_one, [(d, polys) for d in days]),
                    total=len(days),
                    desc=f"chirps-gefs {year}",
                    leave=False,
                )
            )
            missing = sum(p is None for p in parts)
            if missing:
                tqdm.write(f"{year}: {missing} issue days missing from the archive")
            pd.concat([p for p in parts if p is not None], ignore_index=True).to_parquet(
                out, index=False
            )

    df = pd.concat([pd.read_parquet(p) for p in sorted(CKDIR.glob("*.parquet"))], ignore_index=True)
    blob = f"{PROJECT_PREFIX}/processed/chirps_gefs/chirps_gefs_5day_adm2.parquet"
    stratus.upload_parquet_to_blob(df, blob, stage="dev")
    tqdm.write(f"wrote {len(df):,} rows -> {blob}")


if __name__ == "__main__":
    main(*map(int, sys.argv[1:]))
