"""CHIRPS3-GEFS 5-day rainfall forecast per district, October-December issue days.

The v3 counterpart of build_chirps_gefs_adm2.py. CHIRPS-GEFS v2, on which every rain
threshold was calibrated, was discontinued on 1 Jul 2026; this builds the same table from
CHIRPS3-GEFS so the thresholds and backtests can be compared and recalibrated. Only the funding
window's issue days (1 Oct - 31 Dec) are read, which is all the trigger backtests use.

Writes {PROJECT_PREFIX}/processed/chirps_gefs/chirps3_gefs_5day_adm2.parquet
(issue_date, valid_end, pcode, mean, max). Resumable via yearly checkpoints.

Run:  uv run python pipeline/build_chirps3_gefs_adm2.py [start_year] [end_year]
"""

import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path

import ocha_stratus as stratus
import pandas as pd
import rasterio
from tqdm import tqdm

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.constants import PROJECT_PREFIX
from src.datasources.chirps_gefs import read_windowed_url, url_5day_v3
from src.zonal import zonal_stats
from src.zones import load_adm2

CKDIR = Path(__file__).resolve().parent / ".checkpoint_chirps3_gefs"
BLOB = f"{PROJECT_PREFIX}/processed/chirps_gefs/chirps3_gefs_5day_adm2.parquet"


def _one(args, attempts: int = 4):
    """One issue day, retried with backoff so a transient error is not recorded as missing."""
    issue, polys = args
    for i in range(attempts):
        try:
            arr, bounds, wkt = read_windowed_url(url_5day_v3(issue))
            break
        except rasterio.errors.RasterioIOError:
            if i == attempts - 1:
                return None  # genuinely missing (2020 has no hindcast), or the server is down
            time.sleep(2 ** (i + 1))
    df = zonal_stats(arr, bounds, wkt, polys)
    df.insert(0, "valid_end", pd.Timestamp(issue + timedelta(days=4)))
    df.insert(0, "issue_date", pd.Timestamp(issue))
    return df


def main(start_year: int = 2001, end_year: int = 2025) -> None:
    CKDIR.mkdir(exist_ok=True)
    polys = load_adm2()[["ADM2_PCODE", "geometry"]]
    with ThreadPoolExecutor(max_workers=4) as pool:
        for year in range(start_year, end_year + 1):
            out = CKDIR / f"{year}.parquet"
            if out.exists():
                continue
            d0, d1 = date(year, 10, 1), date(year, 12, 31)
            days = [d0 + timedelta(days=i) for i in range((d1 - d0).days + 1)]
            parts = list(
                tqdm(
                    pool.map(_one, [(d, polys) for d in days]),
                    total=len(days),
                    desc=f"chirps3-gefs {year}",
                    leave=False,
                )
            )
            got = [p for p in parts if p is not None]
            missing = len(parts) - len(got)
            if missing:
                tqdm.write(f"{year}: {missing} issue days missing")
            if got:
                pd.concat(got, ignore_index=True).to_parquet(out, index=False)

    df = pd.concat([pd.read_parquet(p) for p in sorted(CKDIR.glob("*.parquet"))], ignore_index=True)
    stratus.upload_parquet_to_blob(df, BLOB, stage="dev")
    tqdm.write(f"wrote {len(df):,} rows -> {BLOB}")


if __name__ == "__main__":
    main(*map(int, sys.argv[1:]))
