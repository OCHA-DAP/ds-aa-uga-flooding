"""Daily per-district (ADM2) stats for FloodScan SFED and IMERG rainfall, all of Uganda.

The team rasterstats DB caps Uganda at ADM1, so district-level daily series
are computed here directly from the processed COGs on the prod raster blob:

  floodscan  raster/floodscan/daily/v5/processed/aer_area_300s_v{date}_v05r01.tif  (band 1 = SFED, 1998-)
  imerg      raster/imerg/daily/late/v7/processed/imerg-daily-late-{date}.tif       (mm/day, 1998-)

Per day and district: area-weighted mean and max pixel. Written as one parquet
per source (long format: date, pcode, mean, max) to the dev projects blob:

  {PROJECT_PREFIX}/processed/{source}/{source}_adm2_daily.parquet

Resumable: yearly checkpoints in pipeline/.checkpoint_{source}/ (gitignored).

Run:  uv run python pipeline/build_daily_adm2.py floodscan
      uv run python pipeline/build_daily_adm2.py imerg
"""

import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import ocha_stratus as stratus
import pandas as pd
from tqdm import tqdm

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.constants import PROJECT_PREFIX
from src.zonal import read_windowed, zonal_stats
from src.zones import load_adm2

SOURCES = {
    "floodscan": dict(
        prefix="floodscan/daily/v5/processed/aer_area_300s",
        date_re=re.compile(r"aer_area_300s_v(\d{4}-\d{2}-\d{2})_v05r01\.tif$"),
    ),
    "imerg": dict(
        prefix="imerg/daily/late/v7/processed/imerg-daily-late-",
        date_re=re.compile(r"imerg-daily-late-(\d{4}-\d{2}-\d{2})\.tif$"),
    ),
}
CKPT = Path(__file__).resolve().parent


def _one(args):
    blob, date, polys = args
    arr, bounds, wkt = read_windowed(blob)
    df = zonal_stats(arr, bounds, wkt, polys)
    df.insert(0, "date", pd.Timestamp(date))
    return df


def main(source: str) -> None:
    spec = SOURCES[source]
    ckdir = CKPT / f".checkpoint_{source}"
    ckdir.mkdir(exist_ok=True)
    polys = load_adm2()[["ADM2_PCODE", "geometry"]]
    names = stratus.list_container_blobs(
        name_starts_with=spec["prefix"], container_name="raster", stage="prod"
    )
    by_year: dict[int, list[tuple[str, str]]] = {}
    for n in names:
        m = spec["date_re"].search(n)
        if m:
            by_year.setdefault(int(m.group(1)[:4]), []).append((n, m.group(1)))
    tqdm.write(f"{source}: {sum(map(len, by_year.values())):,} daily rasters, {len(by_year)} years")

    with ThreadPoolExecutor(max_workers=12) as pool:
        for year in sorted(by_year):
            out = ckdir / f"{year}.parquet"
            # the current year is always recomputed so new days are picked up
            if out.exists() and year < pd.Timestamp.today().year:
                continue
            jobs = [(n, d, polys) for n, d in sorted(by_year[year], key=lambda t: t[1])]
            parts = list(
                tqdm(pool.map(_one, jobs), total=len(jobs), desc=f"{source} {year}", leave=False)
            )
            pd.concat(parts, ignore_index=True).to_parquet(out, index=False)

    df = pd.concat([pd.read_parquet(p) for p in sorted(ckdir.glob("*.parquet"))], ignore_index=True)
    df = df.sort_values(["date", "pcode"]).reset_index(drop=True)
    blob = f"{PROJECT_PREFIX}/processed/{source}/{source}_adm2_daily.parquet"
    stratus.upload_parquet_to_blob(df, blob, stage="dev")
    tqdm.write(f"wrote {len(df):,} rows -> {blob}")


if __name__ == "__main__":
    main(sys.argv[1])
