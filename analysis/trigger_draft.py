"""Draft trigger mechanisms, one per zone, balanced to an overall 3-year return period.

One all-in trigger per zone (any activation releases the zone's whole envelope):

  teso_kyoga  GloFAS G5196 (Akokoro) daily discharge. REANALYSIS as a stand-in for the
              forecast until the reforecast is complete, so the backtest has no lead time
              and no forecast error in it — it is an upper bound on what the forecast
              trigger could do.
  elgon       CHIRPS-GEFS 5-day forecast accumulation, mean over the zone's 15 districts
              (slopes and lowlands: every lowland flood year is also a slope flood year).
  karamoja    CHIRPS-GEFS 5-day forecast per district, each district against its own
              threshold at a common rarity; the zone activates when any district does.
              Karamoja is the size of a small country and flash floods are local, so a
              zone mean would dilute exactly the storms that matter.
  adjumani    Two legs, either activates. (1) The Nile high-stand: Lake Kyoga's rise over
              180 days (NASA GWM altimetry since 1992; Kyoga tracks Lake Albert at r = 0.96
              month to month, and Albert's own record only starts in 2016). Months of lead.
              (2) Flash floods on the tributaries: CHIRPS-GEFS 5-day forecast per district,
              as in Karamoja. The record shows both regimes; neither leg alone covers it.

Balancing. Every zone gets the same number of activation years over the calibration period,
so the same individual return period; that number is the one whose OVERALL return period —
the years in which at least one zone activates — is closest to 3. Thresholds are then the
values that give exactly that many activation years per zone (per leg or per district where
a zone has several, at a common rarity chosen so the zone's own count comes out right).
Weibull throughout: RP = (n + 1) / activations.

Outputs (outputs/triggers/): one CSV per zone, a year per row, plus summary.csv and
thresholds.csv. The page is built by pipeline/build_pages.py.

Run:  uv run python analysis/trigger_draft.py
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
from impact_maps import CERF_YEARS, district_year_table

from src.constants import GLOFAS_PIXEL_LONLAT, PROJECT_PREFIX, ZONES
from src.zones import load_adm2

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "outputs" / "triggers"
GLOFAS_DIR = ROOT / "data" / "glofas" / "raw" / "reanalysis_uga_v4"
TARGET_OVERALL_RP = 3.0
# How the overall budget is shared across zones (see allocate): in proportion to recorded
# people affected, with the years in MUST_CATCH required of the mechanism (see must_catch).
MUST_CATCH = [2007]  # the largest flood year on record and a CERF year
ALLOCATION = "people affected, 2007 required"
FIRST_YEAR = 2000  # CHIRPS-GEFS hindcast starts 2000-01-01
LAKE_RISE_DAYS = 180
MAJOR_DEATHS, MAJOR_AFFECTED = 5, 5000  # the repo's "major event" bar, applied to a zone-year


# --- indicators -------------------------------------------------------------------------


def load(path: str) -> pd.DataFrame:
    return stratus.load_parquet_from_blob(f"{PROJECT_PREFIX}/{path}", stage="dev")


def glofas_g5196() -> pd.Series:
    files = sorted(GLOFAS_DIR.glob("*.nc"))
    ds = xr.open_mfdataset(files, combine="by_coords")
    var = next(v for v in ds.data_vars if "dis" in v)
    s = (
        ds[var]
        .sel(latitude=GLOFAS_PIXEL_LONLAT[1], longitude=GLOFAS_PIXEL_LONLAT[0], method="nearest")
        .to_series()
    )
    s.index = pd.to_datetime(s.index)
    return s.dropna().rename("discharge")


def chirps_gefs_wide(pcodes: list[str]) -> pd.DataFrame:
    cg = load("processed/chirps_gefs/chirps_gefs_5day_adm2.parquet")
    return cg[cg.pcode.isin(pcodes)].pivot_table(index="issue_date", columns="pcode", values="mean")


def kyoga_rise() -> pd.Series:
    ll = load("processed/gwm/lake_levels.parquet")
    ky = ll[ll.lake == "kyoga"].set_index("date").height_m.sort_index()
    kyd = ky.resample("D").mean().interpolate(limit=40)
    return (kyd - kyd.shift(LAKE_RISE_DAYS)).dropna().rename("kyoga_rise_m")


def complete_years(s: pd.Series, min_share: float = 0.9) -> pd.Series:
    """Drop days in years the series covers less than `min_share` of.

    CHIRPS-GEFS has no issues from 1 Jan to 4 Oct 2020 (the gap between the GEFS v12
    reforecast and the operational feed); an annual maximum over the remaining weeks would
    read as a quiet year. Such years are left out of calibration and shown as "no data".
    Lake levels come every ~10 days, so they are judged on the daily-interpolated series.
    """
    s = s.dropna()
    days = s.groupby(s.index.year).size()
    expected = pd.Series(
        {y: 366 if pd.Timestamp(y, 12, 31).dayofyear == 366 else 365 for y in days.index}
    )
    ok = days.index[(days / expected) >= min_share]
    return s[s.index.year.isin(ok)]


def annual_max(s: pd.Series) -> pd.Series:
    return s.groupby(s.index.year).max()


def first_day_at_or_above(s: pd.Series, thr: float, year: int) -> pd.Timestamp | None:
    x = s[(s.index.year == year) & (s >= thr)]
    return x.index[0] if len(x) else None


# --- calibration ------------------------------------------------------------------------


def gumbel_fit(am: pd.Series) -> tuple[float, float]:
    """Method-of-moments Gumbel fit to annual maxima: (location, scale)."""
    beta = float(np.sqrt(6) * am.std() / np.pi)
    return float(am.mean() - 0.5772 * beta), beta


def gumbel_rp(x, mu: float, beta: float):
    """Return period of value x under the fitted Gumbel."""
    # survival 1 - exp(-exp(-z)) via expm1, so extreme values keep distinct return periods
    # instead of all underflowing to the same cap (which created ties in the ranking)
    z = (np.asarray(x, dtype=float) - mu) / beta
    return 1.0 / -np.expm1(-np.exp(-z))


def gumbel_level(rp: float, mu: float, beta: float) -> float:
    """Value with return period rp under the fitted Gumbel."""
    return float(mu - beta * np.log(-np.log(1.0 - 1.0 / rp)))


def zone_statistic(cal_ams: dict[str, pd.Series]) -> tuple[pd.Series, dict]:
    """Per calibration year, the rarest value any of the zone's series reached, as a return
    period on that series' own Gumbel fit. Putting every series on its own RP scale holds a
    wet district and a dry one to the same rarity; for a single series it is a monotone
    transform of the annual maximum, so rankings are unchanged."""
    fits = {key: gumbel_fit(a.dropna()) for key, a in cal_ams.items()}
    rp_year = pd.concat(
        {key: pd.Series(gumbel_rp(a, *fits[key]), index=a.index) for key, a in cal_ams.items()},
        axis=1,
    ).max(axis=1)
    return rp_year.dropna(), fits


def calibrate_zone(
    cal_ams: dict[str, pd.Series], k: float
) -> tuple[dict[str, float], set[int], float]:
    """Thresholds so the zone activates in about k calibration years (k may be fractional).

    The zone statistics, sorted, give the threshold for exactly 1, 2, 3 ... activation years.
    For a fractional target the threshold is interpolated (log scale) at rank k + 0.5, between
    the order statistics, so the backtest shows round(k) activations while the threshold itself
    sits where the target rate puts it rather than jumping in whole-year steps. Below one
    expected activation the threshold is extrapolated above the record's largest value.
    Per-series thresholds are each series' Gumbel return level at the resulting RP.
    """
    rp_year, fits = zone_statistic(cal_ams)
    v = np.log(rp_year.sort_values(ascending=False).to_numpy())
    pos = k + 0.5  # 1-based rank position
    if pos <= 1:
        slope = v[0] - v[1] if len(v) > 1 else 0.5
        log_star = v[0] + (1 - pos) * slope
    elif pos >= len(v):
        log_star = v[-1]
    else:
        i = int(np.floor(pos)) - 1
        log_star = v[i] + (pos - np.floor(pos)) * (v[i + 1] - v[i])
    rp_star = float(np.exp(log_star))
    years = {int(y) for y in rp_year[rp_year >= rp_star].index}
    thr = {key: gumbel_level(rp_star, *fits[key]) for key in cal_ams}
    return thr, years, rp_star


# Zones whose trigger has separate legs for separate flood regimes. Each leg gets an equal
# part of the zone's share and is calibrated on its own, so a leg with one series (the lake)
# is not outvoted by a leg with six (the district rain forecasts). Without this, Adjumani's
# lake leg lost 2020 — its largest flood year — to rain extremes in years with nothing recorded.
LEGS = {"adjumani": {"lake": ["Kyoga rise"], "rain": None}}  # None = every other series


def calibrate_zone_legs(z: str, cal_ams: dict[str, pd.Series], k: float):
    if z not in LEGS:
        return calibrate_zone(cal_ams, k)
    named = {x for v in LEGS[z].values() if v for x in v}
    thr, years, rps = {}, set(), {}
    for leg, keys in LEGS[z].items():
        keys = keys or [x for x in cal_ams if x not in named]
        t, y, rp = calibrate_zone({x: cal_ams[x] for x in keys}, k / len(LEGS[z]))
        thr |= t
        years |= y
        rps[leg] = rp
    return thr, years, rps


def impact_weights(impact: dict[str, pd.DataFrame], cal: list[int]) -> pd.DataFrame:
    """Each zone's share of recorded impact over the calibration years."""
    w = pd.DataFrame(
        {
            z: {"affected": g.loc[cal].affected.sum(), "deaths": g.loc[cal].deaths.sum()}
            for z, g in impact.items()
        }
    ).T
    return w / w.sum()


def allocate(
    weights: pd.Series, n_years: dict[str, int], cal_ams, n: int, floors: dict | None = None
):
    """Scale annual probabilities proportional to `weights` until the backtest's OVERALL return
    period — years with at least one zone activating — is as close to TARGET_OVERALL_RP as the
    whole-year counts allow (ties go to the rarer option). Returns (per-zone results, overall
    activation years, overall RP, per-zone design annual probability)."""
    best = None
    for scale in np.linspace(0.02, 1.2, 600):
        p = (weights * scale).clip(upper=0.9)
        for z, f in (floors or {}).items():
            p[z] = max(p[z], f)
        res = {z: calibrate_zone_legs(z, cal_ams[z], p[z] * n_years[z]) for z in cal_ams}
        union = set().union(*(y for _, y, _ in res.values()))
        rp = (n + 1) / max(1, len(union))
        key = (abs(rp - TARGET_OVERALL_RP), -rp)
        if best is None or key < best[0]:
            best = (key, res, len(union), rp, p)
    _, res, n_union, rp, p = best
    return res, n_union, rp, p


def must_catch(year: int, weights: pd.Series, n_years, cal_ams, n: int, worst: dict[str, set[int]]):
    """Meet a must-catch year at the least cost to the rest of the mechanism.

    For each zone, find the smallest annual probability at which that zone's trigger would
    activate in `year`, give the zone at least that, and re-scale the others (still in
    proportion to `weights`) so the overall return period stays on target. Of the zones that
    can catch the year, keep the option that catches the most of the zones' five worst years
    in total. Returns (floors, options table)."""
    rows, best = [], None
    for z in cal_ams:
        need = next(
            (
                p
                for p in np.linspace(0.005, 0.6, 1200)
                if year in calibrate_zone_legs(z, cal_ams[z], p * n_years[z])[1]
            ),
            None,
        )
        if need is None:
            rows.append(dict(zone=z, can_catch=False))
            continue
        res, nu, rp, _p = allocate(weights, n_years, cal_ams, n, floors={z: need})
        caught = sum(len(worst[zz] & res[zz][1]) for zz in cal_ams)
        rows.append(
            dict(
                zone=z,
                can_catch=True,
                needed_rp=1 / need,
                overall_years=nu,
                overall_rp=rp,
                worst5_caught=caught,
            )
        )
        if best is None or caught > best[0]:
            best = (caught, {z: need})
    return (best[1] if best else {}), pd.DataFrame(rows)


# --- impact -----------------------------------------------------------------------------


def zone_year_impact(years: list[int]) -> dict[str, pd.DataFrame]:
    t = district_year_table()
    out = {}
    for key, z in ZONES.items():
        ds = list(z.core) + list(z.tier2)
        x = t[t.district.isin(ds)]
        g = (
            x.groupby("year")
            .agg(
                affected=("affected_any", "sum"),
                deaths=("deaths_any", "sum"),
                districts=("any_record", "sum"),
                sources=(
                    "sources",
                    lambda s: "|".join(sorted({v for x in s.dropna() for v in x.split("|")})),
                ),
                cards=("n_cards", "sum"),
            )
            .reindex(years)
        )
        g[["affected", "deaths", "districts", "cards"]] = g[
            ["affected", "deaths", "districts", "cards"]
        ].fillna(0)
        g["sources"] = g.sources.fillna("")
        g.loc[g.cards > 0, "sources"] = g.loc[g.cards > 0, "sources"].map(
            lambda s: "|".join(filter(None, [s, "DesInventar"]))
        )
        g["major"] = (g.deaths >= MAJOR_DEATHS) | (g.affected >= MAJOR_AFFECTED)
        out[key] = g
    return out


def weibull_rp(am: pd.Series, cal: list[int]) -> pd.Series:
    """Return period of each year's peak, ranked within the calibration years."""
    ref = am.reindex(cal).dropna().sort_values(ascending=False).to_numpy()
    n = len(ref)
    return am.map(lambda v: (n + 1) / max(1, int((ref >= v).sum())) if pd.notna(v) else np.nan)


# --- main -------------------------------------------------------------------------------


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    adm = load_adm2().set_index("ADM2_EN").ADM2_PCODE
    name_of = {v: k for k, v in adm.items()}

    q = glofas_g5196()
    # calibrate on years every indicator covers in full
    last = min(q.index.max().year if q.index.max().month == 12 else q.index.max().year - 1, 2025)
    cal = list(range(FIRST_YEAR, last + 1))
    show = list(range(FIRST_YEAR, 2026))
    n = len(cal)

    series: dict[str, dict[str, pd.Series]] = {}
    series["teso_kyoga"] = {"GloFAS G5196": q}
    elgon_pc = [adm[d] for d in list(ZONES["elgon"].core) + list(ZONES["elgon"].tier2)]
    series["elgon"] = {"zone-mean 5-day forecast": chirps_gefs_wide(elgon_pc).mean(axis=1)}
    kar = chirps_gefs_wide([adm[d] for d in ZONES["karamoja"].core])
    series["karamoja"] = {name_of[c]: kar[c].dropna() for c in kar.columns}
    adj = chirps_gefs_wide(
        [adm[d] for d in list(ZONES["adjumani"].core) + list(ZONES["adjumani"].tier2)]
    )
    series["adjumani"] = {"Kyoga rise": kyoga_rise()} | {
        name_of[c]: adj[c].dropna() for c in adj.columns
    }

    series = {z: {k: complete_years(s) for k, s in d.items()} for z, d in series.items()}
    ams = {z: {k: annual_max(s) for k, s in d.items()} for z, d in series.items()}
    cal_ams = {z: {k: a.reindex(cal) for k, a in d.items()} for z, d in ams.items()}

    impact = zone_year_impact(show)
    n_years = {z: int(max(a.notna().sum() for a in d.values())) for z, d in cal_ams.items()}
    w = impact_weights(impact, cal)
    allocations = {
        "equal shares": pd.Series(0.25, index=w.index),
        "people affected": w.affected,
        "deaths": w.deaths,
        "half equal, half people affected": 0.5 * 0.25 + 0.5 * w.affected,
    }
    worst = {z: set(impact[z].loc[cal].affected.nlargest(5).index) for z in cal_ams}
    floors_by = {name: {} for name in allocations}
    for yr in MUST_CATCH:
        fl, opts = must_catch(yr, w.affected, n_years, cal_ams, n, worst)
        opts.to_csv(OUT / f"must_catch_{yr}.csv", index=False)
        name = f"people affected, {yr} required"
        allocations[name] = w.affected
        floors_by[name] = fl
        print(f"must-catch {yr}: " + ", ".join(f"{z} 1-in-{1 / f:.1f}" for z, f in fl.items()))
    alt_rows = []
    for name, wt in allocations.items():
        r, nu, rp, p = allocate(wt, n_years, cal_ams, n, floors_by[name])
        for z in cal_ams:
            alt_rows.append(
                dict(
                    allocation=name,
                    zone=z,
                    weight=wt[z],
                    design_rp=1 / p[z],
                    activation_years=len(r[z][1]),
                    overall_years=nu,
                    overall_rp=rp,
                )
            )
    pd.DataFrame(alt_rows).to_csv(OUT / "allocations.csv", index=False)
    res, n_union, overall, p = allocate(
        allocations[ALLOCATION], n_years, cal_ams, n, floors_by[ALLOCATION]
    )
    print(
        f"calibration {cal[0]}-{cal[-1]} (n={n}); allocation by {ALLOCATION}; overall {n_union} years -> RP {overall:.2f}"
    )
    for z in cal_ams:
        print(
            f"   {z:11s} weight {allocations[ALLOCATION][z]:.2f}  design RP {1 / p[z]:5.1f}  activation years {len(res[z][1])}"
        )

    summary, thr_rows = [], []
    for z, (thr, _, rp_star) in res.items():
        rows = []
        for y in show:
            fired, first, via = False, None, []
            for key, s in series[z].items():
                t = thr.get(key, np.inf)
                d0 = first_day_at_or_above(s, t, y)
                if d0 is not None:
                    fired = True
                    via.append(key)
                    first = d0 if first is None or d0 < first else first
            peak_rp = {
                key: float(
                    gumbel_rp(ams[z][key].get(y, np.nan), *gumbel_fit(cal_ams[z][key].dropna()))
                )
                for key in series[z]
            }
            best_key = max(peak_rp, key=lambda kk: peak_rp[kk] if pd.notna(peak_rp[kk]) else -1)
            have = [kk for kk in series[z] if y in ams[z][kk].index and pd.notna(ams[z][kk].get(y))]
            rows.append(
                dict(
                    year=y,
                    in_calibration=y in cal,
                    data=bool(have),
                    activated=fired,
                    first_date=first.date().isoformat() if first is not None else "",
                    via=", ".join(via),
                    peak_rp=peak_rp[best_key],
                    peak_where=best_key,
                )
            )
        tab = pd.DataFrame(rows).set_index("year").join(impact[z])
        tab["cerf"] = tab.index.map(lambda y: CERF_YEARS.get(y, ""))
        tab.sort_index(ascending=False).to_csv(OUT / f"{z}.csv")
        c = tab[tab.in_calibration]
        act = c[c.activated]
        worst = set(c.affected.nlargest(5).index)
        summary.append(
            dict(
                zone=z,
                activation_years=int(c.activated.sum()),
                years_with_data=int(c.data.sum()),
                individual_rp=round((int(c.data.sum()) + 1) / max(1, int(c.activated.sum())), 1),
                activations_in_major_years=int(act.major.sum()),
                major_years=int(c.major.sum()),
                base_rate_major=round(c.major.mean(), 2),
                worst5_caught=len(worst & set(act.index)),
                worst5=", ".join(str(y) for y in sorted(worst, reverse=True)),
                activated_years=", ".join(str(y) for y in sorted(act.index, reverse=True)),
            )
        )
        for key, t in thr.items():
            if isinstance(rp_star, dict):  # zone with legs: each leg has its own rarity
                leg = next((lg for lg, ks in LEGS[z].items() if ks and key in ks), "rain")
                thr_rows.append(
                    dict(zone=z, series=key, threshold=t, series_rp=rp_star[leg], leg=leg)
                )
            else:
                thr_rows.append(dict(zone=z, series=key, threshold=t, series_rp=rp_star, leg=""))
    s = pd.DataFrame(summary)
    s["calibration"] = f"{cal[0]}-{cal[-1]}"
    s["allocation"] = ALLOCATION
    s["weight"] = s.zone.map(allocations[ALLOCATION])
    s["design_rp"] = s.zone.map(lambda z: round(1 / p[z], 1))
    s["overall_years"] = n_union
    s["overall_rp"] = round(overall, 2)
    s.to_csv(OUT / "summary.csv", index=False)
    pd.DataFrame(thr_rows).to_csv(OUT / "thresholds.csv", index=False)
    pd.set_option("display.width", 220)
    print(s.to_string(index=False))
    print(pd.DataFrame(thr_rows).round(2).to_string(index=False))


if __name__ == "__main__":
    main()
