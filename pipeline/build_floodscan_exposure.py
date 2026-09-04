"""Daily flood-exposed population per district, 1998-present, from FloodScan x WorldPop.

exposure(district, day) = sum over FloodScan cells of SFED_fraction * population of that
district inside that cell — the population weight matrix from build_exposure_weights.py
applied to each daily SFED raster. Same definition as the team's
ds-floodexposure-monitoring pipeline (WorldPop 2020 1 km UN-adjusted x SFED), computed
here because Uganda is not among the countries that pipeline covers.

Two variants are written: `exposure` on raw SFED, and `exposure_floor` on SFED with the
team's 0.05 noise floor applied (values below it zeroed), which is what the operational
pipeline uses for its thresholds.

Writes {PROJECT_PREFIX}/processed/exposure/floodscan_exposure_adm2_daily.parquet
(date, pcode, exposure, exposure_floor). Resumable: yearly checkpoints in
pipeline/.checkpoint_exposure/ (gitignored).

Run:  uv run python pipeline/build_floodscan_exposure.py
"""

import io
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import ocha_stratus as stratus
import pandas as pd
from tqdm import tqdm

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.constants import PROJECT_PREFIX, SFED_NOISE_FLOOR
from src.zonal import read_windowed

PREFIX = "floodscan/daily/v5/processed/aer_area_300s"
DATE_RE = re.compile(r"aer_area_300s_v(\d{4}-\d{2}-\d{2})_v05r01\.tif$")
WEIGHTS = f"{PROJECT_PREFIX}/processed/exposure/pop_weights.npz"
OUT = f"{PROJECT_PREFIX}/processed/exposure/floodscan_exposure_adm2_daily.parquet"
CKDIR = Path(__file__).resolve().parent / ".checkpoint_exposure"


def load_weights():
    raw = stratus.load_blob_data(WEIGHTS, stage="dev")
    z = np.load(io.BytesIO(raw))
    return z["W"].astype("float64"), z["pcodes"], tuple(z["shape"])


def main() -> None:
    W, pcodes, shape = load_weights()
    CKDIR.mkdir(exist_ok=True)
    names = stratus.list_container_blobs(
        name_starts_with=PREFIX, container_name="raster", stage="prod"
    )
    by_year: dict[int, list[tuple[str, str]]] = {}
    for n in names:
        if m := DATE_RE.search(n):
            by_year.setdefault(int(m.group(1)[:4]), []).append((n, m.group(1)))
    tqdm.write(f"{sum(map(len, by_year.values())):,} daily rasters, {len(by_year)} years")

    def one(job):
        blob, date = job
        arr, _, _ = read_windowed(blob)
        if arr.shape != shape:
            raise ValueError(f"{blob}: grid {arr.shape} != weight-matrix grid {shape}")
        v = np.nan_to_num(arr.ravel().astype("float64"), nan=0.0)
        vf = np.where(v >= SFED_NOISE_FLOOR, v, 0.0)
        return date, W @ v, W @ vf

    with ThreadPoolExecutor(max_workers=12) as pool:
        for year in sorted(by_year):
            out = CKDIR / f"{year}.parquet"
            if out.exists() and year < pd.Timestamp.today().year:
                continue
            jobs = sorted(by_year[year], key=lambda t: t[1])
            recs = list(
                tqdm(pool.map(one, jobs), total=len(jobs), desc=f"exposure {year}", leave=False)
            )
            frames = [
                pd.DataFrame(
                    {"date": pd.Timestamp(d), "pcode": pcodes, "exposure": e, "exposure_floor": ef}
                )
                for d, e, ef in recs
            ]
            pd.concat(frames, ignore_index=True).to_parquet(out, index=False)

    df = pd.concat([pd.read_parquet(p) for p in sorted(CKDIR.glob("*.parquet"))], ignore_index=True)
    df = df.sort_values(["date", "pcode"]).reset_index(drop=True)
    stratus.upload_parquet_to_blob(df, OUT, stage="dev")
    tqdm.write(f"wrote {len(df):,} rows -> {OUT}")


if __name__ == "__main__":
    main()
