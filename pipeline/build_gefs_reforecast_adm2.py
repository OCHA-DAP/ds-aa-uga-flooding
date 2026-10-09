"""GEFS v12 reforecast: 24-, 48- and 72-hour rainfall forecasts per district, Oct-Dec 2000-2019.

NOAA's GEFS v12 reforecast (s3://noaa-gefs-retrospective, open, no credentials) reruns the
current GFS-based ensemble daily from 00 UTC for 2000-2019. Only the control member (c00), the
unperturbed run and the closest analogue of the deterministic GFS, is used. Each file holds
APCP for days 1-10 as alternating 3-hour and 6-hour accumulations; the first 72 hours sit in
the first messages, so only that byte range is downloaded (read from the .idx), and the 6-hour
accumulations ending at 6, 12, ..., 72 h are summed.

Writes {PROJECT_PREFIX}/processed/gefs_reforecast/gefs_c00_apcp_adm2.parquet
(issue_date, pcode, hours, mean, max): district accumulation over the first `hours` hours.
Resumable via yearly checkpoints.

Run:  uv run python pipeline/build_gefs_reforecast_adm2.py [start_year] [end_year]
"""

import sys
import tempfile
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import ocha_stratus as stratus
import pandas as pd
import rasterio
from rasterio.windows import bounds as window_bounds
from rasterio.windows import from_bounds
from tqdm import tqdm

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.constants import PROJECT_PREFIX, UGA_BOX
from src.zonal import zonal_stats
from src.zones import load_adm2

BASE = "https://noaa-gefs-retrospective.s3.amazonaws.com/GEFSv12/reforecast"
MEMBER = "c00"
HOURS = (24, 48, 72)
CKDIR = Path(__file__).resolve().parent / ".checkpoint_gefs_reforecast"
BLOB = f"{PROJECT_PREFIX}/processed/gefs_reforecast/gefs_{MEMBER}_apcp_adm2.parquet"


def url(issue: date) -> str:
    run = f"{issue:%Y%m%d}00"
    return f"{BASE}/{issue:%Y}/{run}/{MEMBER}/Days:1-10/apcp_sfc_{run}_{MEMBER}.grib2"


def _get(u: str, headers: dict | None = None, attempts: int = 4) -> bytes:
    for i in range(attempts):
        try:
            req = urllib.request.Request(u, headers=headers or {})
            with urllib.request.urlopen(req, timeout=120) as r:
                return r.read()
        except Exception:
            if i == attempts - 1:
                raise
            time.sleep(2 ** (i + 1))
    raise RuntimeError("unreachable")


def six_hour_messages(idx: str) -> tuple[list[int], int]:
    """1-based message numbers of the 6-hour accumulations ending at 6..72 h, and the byte
    offset where the first message past 72 h starts (the end of the range to download)."""
    lines = [ln.split(":") for ln in idx.strip().splitlines()]
    want, end = [], None
    for ln in lines:
        n, offset, span = int(ln[0]), int(ln[1]), ln[5]  # e.g. "66-72 hour acc fcst"
        a, b = (int(x) for x in span.split()[0].split("-"))
        if b > 72:
            end = offset
            break
        if b - a == 6:
            want.append(n)
    return want, end


def _one(args):
    issue, polys = args
    try:
        u = url(issue)
        msgs, end = six_hour_messages(_get(u + ".idx").decode())
        data = _get(u, {"Range": f"bytes=0-{end - 1}"})
    except Exception:
        return None
    with tempfile.NamedTemporaryFile(suffix=".grib2", delete=False) as f:
        f.write(data)
        path = f.name
    try:
        with rasterio.open(path) as ds:
            w = from_bounds(*UGA_BOX, ds.transform).round_offsets(op="floor").round_lengths(
                op="ceil"
            )
            six = np.stack([ds.read(m, window=w).astype("float32") for m in msgs])
            bounds, wkt = window_bounds(w, ds.transform), ds.crs.to_wkt()
    finally:
        Path(path).unlink(missing_ok=True)
    parts = []
    for h in HOURS:
        arr = six[: h // 6].sum(axis=0)
        df = zonal_stats(arr, bounds, wkt, polys)
        df.insert(0, "hours", h)
        df.insert(0, "issue_date", pd.Timestamp(issue))
        parts.append(df)
    return pd.concat(parts, ignore_index=True)


def main(start_year: int = 2000, end_year: int = 2019) -> None:
    CKDIR.mkdir(exist_ok=True)
    polys = load_adm2()[["ADM2_PCODE", "geometry"]]
    with ThreadPoolExecutor(max_workers=8) as pool:
        for year in range(start_year, end_year + 1):
            out = CKDIR / f"{year}.parquet"
            if out.exists():
                continue
            d0 = date(year, 10, 1)
            days = [d0 + timedelta(days=i) for i in range(92)]
            parts = list(
                tqdm(
                    pool.map(_one, [(d, polys) for d in days]),
                    total=len(days),
                    desc=f"gefs {year}",
                    leave=False,
                )
            )
            got = [p for p in parts if p is not None]
            if len(got) < len(parts):
                tqdm.write(f"{year}: {len(parts) - len(got)} issue days missing")
            pd.concat(got, ignore_index=True).to_parquet(out, index=False)
            tqdm.write(f"{year} done")
    df = pd.concat([pd.read_parquet(p) for p in sorted(CKDIR.glob("*.parquet"))], ignore_index=True)
    stratus.upload_parquet_to_blob(df, BLOB, stage="dev")
    tqdm.write(f"wrote {len(df):,} rows -> {BLOB}")


if __name__ == "__main__":
    main(*map(int, sys.argv[1:]))
