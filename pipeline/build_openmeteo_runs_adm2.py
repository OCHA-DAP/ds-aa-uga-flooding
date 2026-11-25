"""Archived GFS and ICON rainfall forecasts per district, from the Open-Meteo previous-runs API.

Open-Meteo keeps every model run since early 2024 and serves, for each valid hour, the value
predicted N days earlier (`precipitation_previous_dayN`). Summing previous_day0..2 over three
consecutive valid days gives the 72-hour accumulation as forecast on the first of them. Points on
a regular grid inside each district (ICON global is ~13 km, GFS ~25 km) are averaged to a
district value.

Only the Elgon zone districts (core and tier 2) are pulled. The archive starts in early 2024, so this covers October-December 2024
and 2025: enough to look at single seasons, not to estimate a return period.

Writes {PROJECT_PREFIX}/processed/openmeteo/runs_precip_adm2_daily.parquet
(date, pcode, model, lead_day, precip_mm): district-mean daily rainfall for valid `date`,
forecast `lead_day` days earlier.

Run:  uv run python pipeline/build_openmeteo_runs_adm2.py [start_date] [end_date]
"""

import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

import numpy as np
import ocha_stratus as stratus
import pandas as pd
from shapely.geometry import Point

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.constants import PROJECT_PREFIX, ZONES
from src.zones import load_adm2

API = "https://previous-runs-api.open-meteo.com/v1/forecast"
MODELS = ("gfs_seamless", "icon_global")
LEADS = (0, 1, 2)
STEP = 0.1  # grid spacing in degrees for points inside each district
BLOB = f"{PROJECT_PREFIX}/processed/openmeteo/runs_precip_adm2_daily.parquet"


def district_points(geom, step: float = STEP) -> list[tuple[float, float]]:
    x0, y0, x1, y1 = geom.bounds
    pts = [
        (round(y, 3), round(x, 3))
        for x in np.arange(x0 + step / 2, x1, step)
        for y in np.arange(y0 + step / 2, y1, step)
        if geom.contains(Point(x, y))
    ]
    if not pts:  # a district narrower than the grid: use its representative point
        p = geom.representative_point()
        pts = [(round(p.y, 3), round(p.x, 3))]
    return pts


def fetch(points, start: str, end: str, attempts: int = 4) -> list[dict]:
    hourly = ["precipitation"] + [f"precipitation_previous_day{k}" for k in LEADS if k]
    q = dict(
        latitude=",".join(str(p[0]) for p in points),
        longitude=",".join(str(p[1]) for p in points),
        hourly=",".join(hourly),
        models=",".join(MODELS),
        start_date=start,
        end_date=end,
        timezone="UTC",
    )
    url = f"{API}?{urllib.parse.urlencode(q)}"
    for i in range(attempts):
        try:
            with urllib.request.urlopen(url, timeout=120) as r:
                out = json.load(r)
            return out if isinstance(out, list) else [out]
        except Exception:
            if i == attempts - 1:
                raise
            time.sleep(5 * 2**i)
    raise RuntimeError("unreachable")


def daily_frame(resp: dict) -> pd.DataFrame:
    h = pd.DataFrame(resp["hourly"])
    h["date"] = pd.to_datetime(h.pop("time")).dt.floor("D")
    rows = []
    for m in MODELS:
        for k in LEADS:
            col = f"precipitation_{m}" if k == 0 else f"precipitation_previous_day{k}_{m}"
            # a day counts only when all 24 hours are present
            g = h.groupby("date")[col].agg(["sum", "count"])
            s = g["sum"].where(g["count"] == 24)
            rows.append(pd.DataFrame({"date": s.index, "model": m, "lead_day": k, "precip_mm": s}))
    return pd.concat(rows, ignore_index=True)


def main(start: str = "2024-03-01", end: str | None = None) -> None:
    end = end or (pd.Timestamp.utcnow().normalize() - pd.Timedelta(days=1)).date().isoformat()
    adm = load_adm2()
    adm = adm[adm.ADM2_EN.isin(ZONES["elgon"].core + ZONES["elgon"].tier2)]
    parts = []
    for _, r in adm.iterrows():
        pts = district_points(r.geometry)
        per_point = [daily_frame(x) for x in fetch(pts, start, end)]
        d = (
            pd.concat(per_point)
            .groupby(["date", "model", "lead_day"], as_index=False)
            .precip_mm.mean()
            .assign(pcode=r.ADM2_PCODE, n_points=len(pts))
        )
        parts.append(d)
        print(f"{r.ADM2_EN}: {len(pts)} points")
        time.sleep(2)
    df = pd.concat(parts, ignore_index=True)
    stratus.upload_parquet_to_blob(df, BLOB, stage="dev")
    print(f"wrote {len(df):,} rows -> {BLOB}")


if __name__ == "__main__":
    main(*sys.argv[1:])
