"""Backtest other organisations' existing flood triggers year by year, alongside our drafts.

Each existing trigger is reproduced as closely as the public data allows, over the same years
and against the same impact record as analysis/trigger_draft.py, so the tables on the trigger
pages can put them side by side.

Two sources of trigger specifications:

  PUBLIC_SPECS   below — triggers from published documents (the IFRC/URCS EAP). Results go to
                 outputs/triggers/existing_public.csv and onto the public /triggers/ page.
  private specs  config/private_frameworks.local.json, key "trigger_specs" (gitignored) —
                 triggers from partner documents that are not published (FAO's draft Elgon
                 AAP, and plans shared through the country team). Results go to the gitignored
                 site_private/existing_private.csv and only into the encrypted /partner/ page.

Stand-ins, stated once:
  * GloFAS ensemble probabilities (IFRC ">=70 % probability of a 5-yr flood", CRS ">=70 %")
    are replaced by the REANALYSIS reaching the 5-year return level at the point — the same
    stand-in our own Teso draft uses until the reforecast is in. The return level is a Gumbel
    fit to the reanalysis annual maxima over the calibration years.
  * Soil-moisture conditions use the IMERG antecedent precipitation index (k = 0.9) as a
    proxy, at a percentile of its own record, as in analysis/flash_flood_antecedent.py.
  * Impact-based conditions (">1,000 households") and community indicators cannot be
    backtested and are left out; each label says so where it matters.

Run:  uv run python analysis/existing_triggers.py      (after analysis/trigger_draft.py)
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import ocha_stratus as stratus
from flash_flood_antecedent import api_index, pctl
from trigger_draft import (
    FIRST_SEASON,
    GLOFAS_DIR,
    gumbel_fit,
    gumbel_level,
    in_season,
    match,
    season_bounds,
    season_label,
    season_max,
    season_of,
    zone_events,
)

from src.constants import GLOFAS_PIXEL_LONLAT, PROJECT_PREFIX
from src.frameworks import load_private
from src.skill_chain import rolling_sum
from src.zones import load_adm2

ROOT = Path(__file__).resolve().parent.parent
OUT_PUBLIC = ROOT / "outputs" / "triggers" / "existing_public.csv"
OUT_PRIVATE = ROOT / "site_private" / "existing_private.csv"
CAL_LAST = 2024  # last calibration SEASON (2024/25), matching trigger_draft

PUBLIC_SPECS = [
    dict(
        zone="teso_kyoga",
        key="ifrc_teso",
        short="IFRC EAP",
        label=(
            "GloFAS 5-year flood at a reporting point, 5-day lead (IFRC/URCS EAP2021UG01). Stand-in: the reanalysis at "
            "G5196, the point in their Teso districts, reaching its 5-year level (the >1,000-household condition "
            "cannot be backtested)"
        ),
        type="glofas_rp",
        lat=GLOFAS_PIXEL_LONLAT[1],
        lon=GLOFAS_PIXEL_LONLAT[0],
        rp=5,
    ),
    dict(
        zone="elgon",
        key="ifrc_elgon",
        short="IFRC EAP",
        label=(
            "GloFAS 5-year flood at a reporting point, 5-day lead (IFRC/URCS EAP2021UG01). Stand-in: the reanalysis at "
            "G5220, Manafwa at Butaleja — the only reporting point in the sub-region — reaching its "
            "5-year level"
        ),
        type="glofas_rp",
        lat=0.925,
        lon=34.075,
        rp=5,
    ),
]


def load(path: str) -> pd.DataFrame:
    return stratus.load_parquet_from_blob(f"{PROJECT_PREFIX}/{path}", stage="dev")


class Data:
    """Lazily loaded inputs shared across specs."""

    def __init__(self):
        self.adm = load_adm2().set_index("ADM2_EN").ADM2_PCODE
        self._glofas = None
        self._imerg = None
        self._cg = {}

    def glofas(self, lat: float, lon: float) -> pd.Series:
        if self._glofas is None:
            self._glofas = xr.open_mfdataset(sorted(GLOFAS_DIR.glob("*.nc")), combine="by_coords")
        var = next(v for v in self._glofas.data_vars if "dis" in v)
        s = self._glofas[var].sel(latitude=lat, longitude=lon, method="nearest").to_series()
        s.index = pd.to_datetime(s.index)
        return s.dropna()

    def imerg(self, stat: str) -> pd.DataFrame:
        if self._imerg is None:
            self._imerg = load("processed/imerg/imerg_adm2_daily.parquet")
        return self._imerg.pivot_table(index="date", columns="pcode", values=stat)

    def chirps_gefs(self, stat: str = "mean") -> pd.DataFrame:
        if stat not in self._cg:
            cg = load("processed/chirps_gefs/chirps_gefs_5day_adm2.parquet")
            self._cg[stat] = cg.pivot_table(index="issue_date", columns="pcode", values=stat)
        return self._cg[stat]


def activation_days(spec: dict, d: Data) -> pd.Series:
    """Boolean daily series: the trigger condition holds that day (any district, where several)."""
    t = spec["type"]
    if t == "glofas_rp":
        q = d.glofas(spec["lat"], spec["lon"])
        am = season_max(q)
        level = gumbel_level(spec["rp"], *gumbel_fit(am.loc[FIRST_SEASON:CAL_LAST]))
        return in_season(q) >= level
    pcs = [d.adm[x] for x in spec["districts"]]
    if t == "rain_forecast":  # CHIRPS-GEFS 5-day accumulation, district mean or wettest pixel
        w = d.chirps_gefs(spec.get("stat", "mean"))[pcs]
        return (w >= spec["mm"]).any(axis=1)[w.notna().any(axis=1)].pipe(in_season)
    if (
        t == "rain_observed"
    ):  # IMERG n-day sum (district mean, or the wettest pixel), optional wet soils
        mean = d.imerg("mean")[pcs]
        src = d.imerg(spec.get("stat", "mean"))[pcs]
        rain = pd.DataFrame({c: rolling_sum(src[c], spec["window"]) for c in pcs})
        cond = rain >= spec["mm"]
        if spec.get("antecedent_pctl") is not None:
            ante = pd.DataFrame({c: pctl(api_index(mean[c]).shift(spec["window"])) for c in pcs})
            cond &= ante >= spec["antecedent_pctl"]
        return cond.any(axis=1).pipe(in_season)
    raise ValueError(f"unknown trigger type {t}")


def seasonal(spec: dict, days: pd.Series, events: dict) -> pd.DataFrame:
    """One row per season: did this trigger activate inside the funding window, and did that
    activation catch a major event, judged exactly as our own drafts are (same events, same
    lead windows — GloFAS-style triggers get the GloFAS window, rain triggers the rain one)."""
    leg = "glofas" if spec["type"] == "glofas_rp" else "rain"
    ev = events[spec["zone"]]
    have = {season_of(t) for t in days.index}
    rows = []
    for y in range(FIRST_SEASON, 2026):
        lo, hi = season_bounds(y)
        x = days[(days.index >= lo) & (days.index <= hi) & days]
        a0 = x.index[0] if len(x) else None
        m = match(a0, leg, ev) if a0 is not None else ev.iloc[0:0]
        rows.append(
            dict(
                zone=spec["zone"],
                key=spec["key"],
                short=spec["short"],
                label=spec["label"],
                season=y,
                label_season=season_label(y),
                data=y in have,
                activated=a0 is not None,
                first_date=a0.date().isoformat() if a0 is not None else "",
                caught=bool(len(m)),
                lead_days=int(m.lead_days.max()) if len(m) else float("nan"),
            )
        )
    return pd.DataFrame(rows)


def run(specs: list[dict], d: Data, out: Path) -> pd.DataFrame | None:
    if not specs:
        return None
    events = {z: zone_events(z) for z in {sp["zone"] for sp in specs}}
    df = pd.concat(
        [seasonal(sp, activation_days(sp, d), events) for sp in specs], ignore_index=True
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False)
    cal = df[df.season.between(FIRST_SEASON, CAL_LAST) & df.data]
    print(f"\n{out.relative_to(ROOT)}")
    print(
        cal.groupby(["zone", "short"])
        .agg(activations=("activated", "sum"), caught=("caught", "sum"), seasons=("data", "size"))
        .assign(rp=lambda x: ((x.seasons + 1) / x.activations.replace(0, np.nan)).round(1))
        .to_string()
    )
    return df


def main() -> None:
    d = Data()
    run(PUBLIC_SPECS, d, OUT_PUBLIC)
    priv = load_private().get("trigger_specs", [])
    if priv:
        run(priv, d, OUT_PRIVATE)
    else:
        print(
            "\nno private trigger specs (config/private_frameworks.local.json) — public ones only"
        )


if __name__ == "__main__":
    main()
