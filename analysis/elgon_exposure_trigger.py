"""Backtest a GloFAS flood-exposure trigger in Mt Elgon: households in the flood extent of the
GloFAS grid cells that exceed a return level.

Its parameters (districts, return period, household threshold) come from a partner's unpublished
plan, so they are read at run time from partner_triggers.local.json (dev blob,
ds-aa-uga-flooding/private/config/; a gitignored local config/ copy overrides), key "t2":
{"rp": <years>, "households": <count>}. No output is committed: tables go to site_private/.

Method, all on open data:

  * GloFAS v4 reanalysis (0.05 deg, 1999 onward) stands in for the forecast, as for the IFRC
    trigger: an exceedance is dated IFRC_LEAD days early. Each cell's return level comes from a
    Gumbel fit to its annual maxima.
  * Flood extent: the official GloFAS flood hazard map (JRC, 90 m, CC-BY 4.0). The smallest
    return period mapped is 10 years, so the 10-year extent is used for any lower return period:
    an approximation, stated wherever the result is shown.
  * Population: WorldPop 2026 constrained, 100 m (CC-BY 4.0). Households: population divided by
    the average household size of the district's sub-region, UBOS National Population and
    Housing Census 2024 final report, Table 2.6.
  * A day is met when, in any district, the households in the flood extent of the GloFAS cells
    that exceed the return level reach the threshold.

Run:  uv run python analysis/elgon_exposure_trigger.py
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
import xarray as xr
from rasterio.features import rasterize
from rasterio.warp import Resampling, reproject
from rasterio.windows import from_bounds

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import analysis.existing_triggers as et
from src.frameworks import read_private_config
from src.zones import load_adm2

HAZARD = (
    "https://jeodpp.jrc.ec.europa.eu/ftp/jrc-opendata/CEMS-GLOFAS/flood_hazard/"
    "RP{rp}/ID150_N10_E30_RP{rp}_depth.tif"
)
HAZARD_RPS = (10, 20, 50, 75, 100, 200, 500)
WORLDPOP = ROOT / "data" / "worldpop" / "uga_pop_2026_CN_100m_R2025A_v1.tif"
REANALYSIS = ROOT / "data" / "glofas" / "raw" / "reanalysis_uga_v4"
OUT = ROOT / "site_private"
CELL = 0.05  # GloFAS v4 grid

# UBOS NPHC 2024 final report, Table 2.6: average household size by sub-region
HH_SIZE_SUBREGION = {"Bugisu": 4.0, "Bukedi": 4.7, "Sebei": 4.7, "Teso": 4.9}
SUBREGION = {
    "Bududa": "Bugisu",
    "Bulambuli": "Bugisu",
    "Sironko": "Bugisu",
    "Manafwa": "Bugisu",
    "Mbale": "Bugisu",
    "Namisindwa": "Bugisu",
    "Butaleja": "Bukedi",
    "Budaka": "Bukedi",
    "Kibuku": "Bukedi",
    "Pallisa": "Bukedi",
    "Kapchorwa": "Sebei",
    "Kween": "Sebei",
    "Bukwo": "Sebei",
    "Bukedea": "Teso",
    "Kumi": "Teso",
}


def load_config() -> dict:
    cfg = read_private_config("partner_triggers.local.json")
    if cfg is None or "t2" not in cfg:
        print("No partner trigger config with a 't2' entry (private, not committed).")
        raise SystemExit(0)
    return cfg


def cell_households(adm, bounds, hazard_rp: int) -> pd.DataFrame:
    """Households living in the hazard extent, per (district, GloFAS cell)."""
    with rasterio.open(WORLDPOP) as wp:
        w = from_bounds(*bounds, wp.transform).round_offsets(op="floor").round_lengths(op="ceil")
        pop = wp.read(1, window=w).astype("float64")
        pop[(pop < 0) | ~np.isfinite(pop)] = 0
        if wp.nodata is not None:
            pop[pop == wp.nodata] = 0
        tr = wp.window_transform(w)
        crs = wp.crs
    flooded = np.zeros(pop.shape, dtype="float32")
    env = dict(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR", CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif")
    with rasterio.Env(**env), rasterio.open(f"/vsicurl/{HAZARD.format(rp=hazard_rp)}") as hz:
        hw = from_bounds(*bounds, hz.transform).round_offsets(op="floor").round_lengths(op="ceil")
        depth = hz.read(1, window=hw).astype("float32")
        depth[depth == hz.nodata] = 0
        reproject(
            depth,
            flooded,
            src_transform=hz.window_transform(hw),
            src_crs=hz.crs,
            dst_transform=tr,
            dst_crs=crs,
            resampling=Resampling.max,
        )
    exposed = np.where(flooded > 0, pop, 0)
    ids = rasterize(
        [(g, i + 1) for i, g in enumerate(adm.geometry)], out_shape=pop.shape, transform=tr
    )
    rows, cols = np.nonzero((ids > 0) & (exposed > 0))
    xs, ys = rasterio.transform.xy(tr, rows, cols)
    df = pd.DataFrame(
        {
            "district": adm.ADM2_EN.to_numpy()[ids[rows, cols] - 1],
            # GloFAS cell centres sit on odd multiples of 0.025 deg
            "lat": np.round((np.floor(np.asarray(ys) / CELL) + 0.5) * CELL, 3),
            "lon": np.round((np.floor(np.asarray(xs) / CELL) + 0.5) * CELL, 3),
            "people": exposed[rows, cols],
        }
    )
    out = df.groupby(["district", "lat", "lon"], as_index=False).people.sum()
    size = out.district.map(SUBREGION).map(HH_SIZE_SUBREGION)
    return out.assign(households=out.people / size)


def main() -> None:
    cfg = load_config()
    districts, rp, n_hh = cfg["districts"], float(cfg["t2"]["rp"]), float(cfg["t2"]["households"])
    hazard_rp = min(r for r in HAZARD_RPS if r >= rp)
    adm = load_adm2()
    adm = adm[adm.ADM2_EN.isin(districts)].reset_index(drop=True)
    x0, y0, x1, y1 = adm.total_bounds
    bounds = (x0 - 0.05, y0 - 0.05, x1 + 0.05, y1 + 0.05)

    cells = cell_households(adm, bounds, hazard_rp)
    print(f"flood extent used: GloFAS hazard map RP{hazard_rp}")
    print(
        cells.groupby("district")
        .agg(cells=("lat", "size"), people=("people", "sum"), households=("households", "sum"))
        .round(0)
        .to_string()
    )

    q = xr.open_mfdataset(sorted(REANALYSIS.glob("*.nc")), combine="by_coords")
    var = next(v for v in q.data_vars if "dis" in v)
    pts = cells[["lat", "lon"]].drop_duplicates().reset_index(drop=True)
    s = q[var].sel(
        latitude=xr.DataArray(pts.lat, dims="p"),
        longitude=xr.DataArray(pts.lon, dims="p"),
        method="nearest",
    ).to_pandas()  # time x point
    s.index = pd.to_datetime(s.index)
    am = s.groupby(s.index.year).max().loc[et.FIRST_SEASON : et.CAL_LAST]
    level = pd.Series(
        [et.gumbel_level(rp, *et.gumbel_fit(am[c])) for c in am.columns], index=am.columns
    )
    exceed = s.ge(level, axis=1)
    exceed.columns = pd.MultiIndex.from_frame(pts)

    hh = {}
    for d, g in cells.groupby("district"):
        cols = list(zip(g.lat, g.lon))
        hh[d] = exceed[cols].mul(g.households.to_numpy(), axis=1).sum(axis=1)
    hh = pd.DataFrame(hh)
    met = hh.ge(n_hh).any(axis=1)
    met.index = met.index - pd.Timedelta(days=et.IFRC_LEAD)  # reanalysis as a perfect forecast

    spec = dict(
        zone="elgon",
        key="partner_t2_exposure",
        short=cfg["t2"].get("short", "Partner T2"),
        # the description shown on the restricted page lives in the private config
        label=cfg["t2"].get("label", ""),
        type="glofas_rp",
    )
    events = {"elgon": et.zone_events("elgon")}
    df = et.seasonal(spec, et.in_season(met), events)
    OUT.mkdir(exist_ok=True)
    df.to_csv(OUT / "elgon_exposure_trigger.csv", index=False)
    hh.to_parquet(OUT / "elgon_exposure_households_daily.parquet")
    cal = df[df.season.between(et.FIRST_SEASON, et.CAL_LAST) & df.data]
    n = int(cal.activated.sum())
    print(
        f"\nseasons {len(cal)}, activations {n}, caught {int(cal.caught.sum())}, "
        f"return period {((len(cal) + 1) / n) if n else float('nan'):.1f}"
    )
    print(cal[cal.activated][["label_season", "first_date", "caught", "lead_days"]].to_string())


if __name__ == "__main__":
    main()
