"""Reproduce the IFRC/URCS flood EAP trigger the way the IBF portal actually computes it.

The approved EAP (EAP2021UG01, May 2021) and the Nov 2023 activation state the trigger in words;
the 510 IBF river-flood pipeline (github.com/rodekruis/IBF-river-flood-pipeline, config UGA) is
what turns those words into an activation. What the pipeline does, per admin area at levels 2, 3
and 4 (district, county, sub-county):

  1. threshold = zonal MAX (all_touched) of the official GloFAS v4 5-year return-level map
  2. forecast  = zonal MAX (all_touched) of each ensemble member's discharge, per lead day 0-7
  3. likelihood = share of members whose zonal max exceeds the zonal-max threshold
  4. triggered  = likelihood >= 0.6 at any lead <= 5 days
  5. a triggered sub-county or county also triggers the district that contains it

So the trigger is not read at a reporting point: each area is judged at its largest river cell,
and the district inherits the trigger of any of its sub-areas. Our earlier stand-in (reforecast at
G5196, own Gumbel fit on annual maxima) is checked against this here.

Stand-in, stated once: the reforecast only exists for a 5 x 5 box around G5196, so the per-area
check runs on the REANALYSIS (deterministic — "the forecast came true") against the official
RL5 map. A day counts when the zonal max of the reanalysis exceeds the zonal max of the RL5 map.
The official map is the operational threshold, so no calibration of ours enters.

Validation: the portal's own Nov 2023 trigger (notification 15 Nov 2023) listed 16 potentially
exposed districts — Ntoroko, Buyende, Namayingo, Kikuube, Pallisa, Kagadi, Butaleja, Kyenjojo,
Kaliro, Bugiri, Kibuku, Namutumba, Busia, Tororo, Budaka, Butebo — and none in Teso.

Outputs (outputs/triggers/):
  ifrc_units.csv            per admin area: zonal-max threshold, the cell it sits on, the cell
                            carrying the area's largest flow, and the river that is
  ifrc_district_days.csv    per district and day (1999-2025): exceedance at adm2 only / up to
                            adm3 / up to adm4 (the portal's rule)
  ifrc_ratio_adm{2,4}.parquet  per district and day: zonal-max flow / zonal-max RL5, the largest
                            over the district's areas (> 1 = triggered); read by trigger_draft
                            (Teso) and existing_triggers (the IFRC rows)
  ifrc_2023_check.csv       districts exceeding around the Nov 2023 notification
  ifrc_seasonal.csv         per zone and OND season, activation and event match, for the EAP
                            high-risk districts in the zone and for every zone district

The official map is the one the IBF pipeline downloads: flood_threshold_glofas_v4_rl_5.0.nc
(173 MB) from the CEMS "Auxiliary Data" page, https://confluence.ecmwf.int/display/CEMS/Auxiliary+Data.
Put it in data/glofas/thresholds/, or pull the mirror from the dev blob
(ds-aa-uga-flooding/raw/glofas/thresholds/).

Run:  uv run python analysis/ifrc_reproduction.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr
from ocha_stratus import codab
from rasterio.features import geometry_mask
from rasterio.transform import from_origin

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from trigger_draft import (
    CAL_LAST_SEASON,
    FIRST_SEASON,
    GLOFAS_DIR,
    match,
    season_bounds,
    season_label,
    zone_events,
)

from src.constants import GLOFAS_PIXEL_LONLAT, ZONES

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "outputs" / "triggers"
RL5 = ROOT / "data" / "glofas" / "thresholds" / "flood_threshold_glofas_v4_rl_5.0.nc"
ISO3 = "uga"

# EAP2021UG01 "high risk" districts (approved EAP summary, May 2021)
EAP_DISTRICTS = (
    "Kasese",
    "Katakwi",
    "Amuria",
    "Kampala",
    "Butaleja",
    "Sironko",
    "Bududa",
    "Manafwa",
    "Kumi",
    "Ntoroko",
    "Bulambuli",
    "Moyo",
    "Nabilatuk",
    "Ngora",
)
# IBF portal, trigger notification 15 Nov 2023 (EAP activation document)
PORTAL_2023 = (
    "Ntoroko",
    "Buyende",
    "Namayingo",
    "Kikuube",
    "Pallisa",
    "Kagadi",
    "Butaleja",
    "Kyenjojo",
    "Kaliro",
    "Bugiri",
    "Kibuku",
    "Namutumba",
    "Busia",
    "Tororo",
    "Budaka",
    "Butebo",
)
NOTIFIED = pd.Timestamp("2023-11-15")
LEAD = 5  # the protocol's lead: an exceedance on day d is in view of forecasts issued d-5 .. d


def grid() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """The official RL5 map on the reanalysis grid (same 0.05 deg cells)."""
    first = xr.open_dataset(min(GLOFAS_DIR.glob("*.nc")))
    lat, lon = first.latitude.values, first.longitude.values
    rl = xr.open_dataset(RL5)["rl_5.0"]
    rl = rl.sel(lat=lat, lon=lon, method="nearest", tolerance=1e-3)
    return rl.values.astype("float64"), lat, lon


def units(lat: np.ndarray, lon: np.ndarray) -> pd.DataFrame:
    """Every CODAB admin area at levels 2-4 with its all_touched cell indices."""
    tr = from_origin(lon[0] - 0.025, lat[0] + 0.025, 0.05, 0.05)
    shape = (len(lat), len(lon))
    rows = []
    for level in (2, 3, 4):
        g = codab.load_codab_from_blob(ISO3, admin_level=level)
        for _, r in g.iterrows():
            m = geometry_mask([r.geometry], shape, tr, all_touched=True, invert=True)
            rows.append(
                dict(
                    level=level,
                    pcode=r[f"ADM{level}_PCODE"],
                    name=r[f"ADM{level}_EN"],
                    district=r.ADM2_EN,
                    cells=np.flatnonzero(m),
                )
            )
    return pd.DataFrame(rows)


def zonal_max(values: np.ndarray, cells: np.ndarray) -> tuple[float, int]:
    """rasterstats max with nodata=0: zeros and NaN are ignored. Returns (max, flat cell)."""
    v = values.reshape(values.shape[0], -1)[:, cells] if values.ndim == 3 else values.ravel()[cells]
    v = np.where((v == 0) | np.isnan(v), -np.inf, v)
    i = np.argmax(v, axis=-1)
    return np.take_along_axis(v, np.expand_dims(i, -1), -1).squeeze(-1), cells[i]


def main() -> None:
    rl, lat, lon = grid()
    u = units(lat, lon)
    thr, thr_cell = zip(*(zonal_max(rl, c) for c in u.cells), strict=True)
    u["threshold"], u["thr_cell"] = np.array(thr), np.array(thr_cell)
    u = u[np.isfinite(u.threshold)].reset_index(drop=True)
    print(
        f"{len(u)} admin areas with a threshold ({u.level.value_counts().sort_index().to_dict()})"
    )

    # daily zonal max of the reanalysis, year by year (one year of the box is ~20 MB)
    ratio, mean_flow = [], np.zeros(len(lat) * len(lon))
    n_days = 0
    for f in sorted(GLOFAS_DIR.glob("*.nc")):
        ds = xr.open_dataset(f)
        var = next(v for v in ds.data_vars if "dis" in v)
        q = ds[var].values.astype("float64")
        t = pd.to_datetime(ds.valid_time.values)
        mean_flow += np.nansum(q, axis=0).ravel()
        n_days += len(t)
        zm = np.stack([zonal_max(q, c)[0] for c in u.cells], axis=1)  # days x units
        ratio.append(pd.DataFrame(zm / u.threshold.values, index=t))
    ratio = pd.concat(ratio).sort_index()
    ratio = ratio[~ratio.index.duplicated()]
    exceed = ratio > 1
    mean_flow /= n_days

    # which river each area is judged on: the threshold cell vs the cell carrying the most water
    u["flow_cell"] = [c[np.argmax(mean_flow[c])] for c in u.cells]
    for k in ("thr", "flow"):
        iy, ix = np.unravel_index(u[f"{k}_cell"].values, (len(lat), len(lon)))
        u[f"{k}_lat"], u[f"{k}_lon"] = lat[iy].round(3), lon[ix].round(3)
    u["same_cell"] = u.thr_cell == u.flow_cell
    u["mean_flow_thr_cell"] = mean_flow[u.thr_cell].round(1)
    g_iy = int(np.argmin(abs(lat - GLOFAS_PIXEL_LONLAT[1])))
    g_ix = int(np.argmin(abs(lon - GLOFAS_PIXEL_LONLAT[0])))
    u["is_g5196"] = u.thr_cell == g_iy * len(lon) + g_ix
    print(f"official RL5 at G5196: {rl[g_iy, g_ix]:.1f} m3/s")

    # district-day flags: the portal's upward rule, and adm2-only for comparison
    cols = {}
    for upto in (2, 3, 4):
        sel = u.level <= upto
        cols[f"adm{upto}"] = exceed.loc[:, sel.values].T.groupby(u.district[sel].values).any().T
    dd = pd.concat(cols, axis=1)
    OUT.mkdir(parents=True, exist_ok=True)
    # the same as a continuous margin — zonal-max flow over zonal-max RL5, the largest over a
    # district's areas — so a trigger can be backtested on it with a fixed threshold of 1
    for upto in (2, 4):
        sel = (u.level <= upto).values
        r = ratio.loc[:, sel].T.groupby(u.district[sel].values).max().T
        r.columns = r.columns.astype(str)
        r.astype("float32").to_parquet(OUT / f"ifrc_ratio_adm{upto}.parquet")
    u.drop(columns="cells").to_csv(OUT / "ifrc_units.csv", index=False)
    long = dd.stack(level=1, future_stack=True).rename_axis(["date", "district"]).reset_index()
    long[long[["adm2", "adm3", "adm4"]].any(axis=1)].to_csv(
        OUT / "ifrc_district_days.csv", index=False
    )

    # --- Nov 2023: does the reproduction see what the portal saw? ---
    win = dd["adm4"].loc[NOTIFIED : NOTIFIED + pd.Timedelta(days=LEAD + 10)]
    hit = win.any()
    check = pd.DataFrame(
        {
            "district": hit.index,
            "exceeds_15_30_nov": hit.values,
            "first_day": [win.index[win[c]].min() if hit[c] else pd.NaT for c in hit.index],
            "portal_2023": hit.index.isin(PORTAL_2023),
        }
    )
    check = check[check.exceeds_15_30_nov | check.portal_2023].sort_values(
        ["portal_2023", "exceeds_15_30_nov"], ascending=False
    )
    check.to_csv(OUT / "ifrc_2023_check.csv", index=False)
    agree = int((check.exceeds_15_30_nov & check.portal_2023).sum())
    print(
        f"\nNov 2023: portal listed {len(PORTAL_2023)} districts; reproduction exceeds in "
        f"{int(check.exceeds_15_30_nov.sum())}, of which {agree} are on the portal list"
    )
    print(check.to_string(index=False))

    # --- per zone, OND seasons ---
    rows = []
    for z, zone in ZONES.items():
        ev = zone_events(z)
        members = list(zone.all_districts)
        for scope, dists in (
            ("eap", [d for d in members if d in EAP_DISTRICTS]),
            ("zone", members),
        ):
            if not dists:
                continue
            for how in ("adm2", "adm4"):
                day = dd[how].reindex(columns=dists, fill_value=False).any(axis=1)
                for y in range(FIRST_SEASON, 2026):
                    lo, hi = season_bounds(y)
                    x = day[(day.index >= lo) & (day.index <= hi) & day]
                    # the forecast would show the exceedance up to LEAD days ahead
                    a0 = x.index[0] - pd.Timedelta(days=LEAD) if len(x) else None
                    a0 = max(a0, lo) if a0 is not None else None
                    m = match(a0, "glofas", ev) if a0 is not None else ev.iloc[0:0]
                    who = (
                        dd[how]
                        .loc[x.index, [d for d in dists if d in dd[how].columns]]
                        .any()
                        .pipe(lambda s: ";".join(s.index[s]))
                        if len(x)
                        else ""
                    )
                    rows.append(
                        dict(
                            zone=z,
                            scope=scope,
                            districts=";".join(dists),
                            levels=how,
                            season=y,
                            label_season=season_label(y),
                            activated=a0 is not None,
                            first_date=a0.date().isoformat() if a0 is not None else "",
                            which=who,
                            caught=bool(len(m)),
                        )
                    )
    s = pd.DataFrame(rows)
    s.to_csv(OUT / "ifrc_seasonal.csv", index=False)
    cal = s[s.season.between(FIRST_SEASON, CAL_LAST_SEASON)]
    summ = (
        cal.groupby(["zone", "scope", "levels"])
        .agg(activations=("activated", "sum"), caught=("caught", "sum"), seasons=("season", "size"))
        .assign(rp=lambda x: ((x.seasons + 1) / x.activations.replace(0, np.nan)).round(1))
    )
    print("\nOND activations, reanalysis vs official RL5, 2000-2024:")
    print(summ.to_string())
    print("\nthreshold cells, EAP districts at adm2:")
    print(
        u[(u.level == 2) & u.district.isin(EAP_DISTRICTS)][
            [
                "district",
                "threshold",
                "thr_lat",
                "thr_lon",
                "flow_lat",
                "flow_lon",
                "same_cell",
                "is_g5196",
            ]
        ].to_string(index=False)
    )


if __name__ == "__main__":
    main()
