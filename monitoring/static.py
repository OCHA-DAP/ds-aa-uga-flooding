"""Build the monitor's fixed inputs once, from the same sources the backtests used, and put them
on the dev blob so the daily job reads small files only.

  teso_units.parquet      every admin area (levels 2-4) of the six Teso districts: its all_touched
                          cells on the GloFAS forecast grid and its threshold, the zonal max of the
                          official GloFAS v4 5-year return-level map (the IBF portal's rule, as in
                          analysis/ifrc_reproduction.py). Checked against outputs/triggers/ifrc_units.csv.
  elgon_t2_cells.parquet  the GloFAS cells, households and cell levels of the Elgon exposure
                          trigger, built by analysis/elgon_exposure_trigger.py's own functions
                          from the private config (so stored under private/monitoring/).
  thresholds.csv          the zone thresholds the monitor reads (monitoring/config/ on the dev blob):
                          Karamoja and Adjumani from the CHIRPS3-GEFS (v3) calibration,
                          outputs/triggers_v3/thresholds.csv. Kept off the public repo with the
                          rest of the draft-trigger numbers.

Run:  uv run python monitoring/static.py
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

import numpy as np
import ocha_stratus as stratus
import pandas as pd
import xarray as xr
from ocha_stratus import codab
from rasterio.features import geometry_mask
from rasterio.transform import from_origin

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from monitoring.feeds import GLOFAS_AREA
from src.constants import PROJECT_PREFIX, ZONES
from src.frameworks import read_private_config

STATIC = f"{PROJECT_PREFIX}/monitoring/static"
PRIVATE_STATIC = f"{PROJECT_PREFIX}/private/monitoring"
CONFIG = f"{PROJECT_PREFIX}/monitoring/config"
RL5 = ROOT / "data" / "glofas" / "thresholds" / "flood_threshold_glofas_v4_rl_5.0.nc"
CELL = 0.05


def forecast_grid() -> tuple[np.ndarray, np.ndarray]:
    """Cell centres of the GloFAS 0.05 deg grid inside GLOFAS_AREA (lat descending)."""
    n, w, s, e = GLOFAS_AREA
    lat = np.round(np.arange(n - CELL / 2, s, -CELL), 3)
    lon = np.round(np.arange(w + CELL / 2, e, CELL), 3)
    return lat, lon


def teso_units(lat: np.ndarray, lon: np.ndarray) -> pd.DataFrame:
    tr = from_origin(lon[0] - CELL / 2, lat[0] + CELL / 2, CELL, CELL)
    shape = (len(lat), len(lon))
    teso = set(ZONES["teso_kyoga"].all_districts)
    rl = xr.open_dataset(RL5)["rl_5.0"].sel(lat=lat, lon=lon, method="nearest", tolerance=1e-3)
    rl = rl.values.astype("float64")
    rows = []
    for level in (2, 3, 4):
        g = codab.load_codab_from_blob("uga", admin_level=level)
        g = g[g.ADM2_EN.isin(teso)]
        for _, r in g.iterrows():
            x0, y0, x1, y1 = r.geometry.bounds
            assert lon[0] - CELL / 2 < x0 and x1 < lon[-1] + CELL / 2, r[f"ADM{level}_EN"]
            assert lat[-1] - CELL / 2 < y0 and y1 < lat[0] + CELL / 2, r[f"ADM{level}_EN"]
            cells = np.flatnonzero(
                geometry_mask([r.geometry], shape, tr, all_touched=True, invert=True)
            )
            v = rl.ravel()[cells]
            v = np.where((v == 0) | np.isnan(v), -np.inf, v)
            rows.append(
                dict(
                    level=level,
                    pcode=r[f"ADM{level}_PCODE"],
                    name=r[f"ADM{level}_EN"],
                    district=r.ADM2_EN,
                    threshold=float(v.max()),
                    cells=cells.astype("int32").tolist(),
                )
            )
    u = pd.DataFrame(rows)
    return u[np.isfinite(u.threshold)].reset_index(drop=True)


def elgon_t2_cells() -> pd.DataFrame:
    import analysis.elgon_exposure_trigger as ex
    import analysis.existing_triggers as et
    from src.zones import load_adm2

    cfg = read_private_config("partner_triggers.local.json")
    districts, rp = cfg["districts"], float(cfg["t2"]["rp"])
    hazard_rp = min(r for r in ex.HAZARD_RPS if r >= rp)
    adm = load_adm2()
    adm = adm[adm.ADM2_EN.isin(districts)].reset_index(drop=True)
    x0, y0, x1, y1 = adm.total_bounds
    cells = ex.cell_households(adm, (x0 - 0.05, y0 - 0.05, x1 + 0.05, y1 + 0.05), hazard_rp)
    q = xr.open_mfdataset(sorted(ex.REANALYSIS.glob("*.nc")), combine="by_coords")
    var = next(v for v in q.data_vars if "dis" in v)
    pts = cells[["lat", "lon"]].drop_duplicates().reset_index(drop=True)
    s = (
        q[var]
        .sel(
            latitude=xr.DataArray(pts.lat, dims="p"),
            longitude=xr.DataArray(pts.lon, dims="p"),
            method="nearest",
        )
        .to_pandas()
    )
    s.index = pd.to_datetime(s.index)
    am = s.groupby(s.index.year).max().loc[et.FIRST_SEASON : et.CAL_LAST]
    pts["level"] = [et.gumbel_level(rp, *et.gumbel_fit(am[c])) for c in am.columns]
    return cells.merge(pts, on=["lat", "lon"])


def upload(df: pd.DataFrame, blob: str) -> None:
    stratus.upload_parquet_to_blob(df, blob, stage="dev")
    print(f"wrote {len(df):,} rows -> {blob}")


def main() -> None:
    lat, lon = forecast_grid()
    u = teso_units(lat, lon)
    ref = pd.read_csv(ROOT / "outputs" / "triggers" / "ifrc_units.csv").set_index("pcode")
    diff = (u.set_index("pcode").threshold - ref.threshold.reindex(u.pcode)).abs()
    print(
        f"Teso: {len(u)} admin areas; largest difference from ifrc_units.csv {diff.max():.3g} m3/s"
    )
    upload(u, f"{STATIC}/teso_units.parquet")

    cells = elgon_t2_cells()
    inside = cells.lat.between(lat.min(), lat.max()) & cells.lon.between(lon.min(), lon.max())
    assert inside.all(), f"{(~inside).sum()} Elgon cells outside GLOFAS_AREA"
    print(f"Elgon: {len(cells)} (district, cell) rows, all inside the forecast area")
    upload(cells, f"{PRIVATE_STATIC}/elgon_t2_cells.parquet")

    thr = pd.read_csv(ROOT / "outputs" / "triggers_v3" / "thresholds.csv")
    thr = thr[thr.zone.isin(["karamoja", "adjumani"])]
    buf = io.BytesIO()
    thr.to_csv(buf, index=False)
    stratus.upload_blob_data(buf.getvalue(), f"{CONFIG}/thresholds.csv", stage="dev")
    print(f"wrote {len(thr)} thresholds -> {CONFIG}/thresholds.csv")


if __name__ == "__main__":
    main()
