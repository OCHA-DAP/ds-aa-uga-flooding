"""Evaluate the four zone triggers for one issue day.

Each function returns rows of one long table, one row per (zone, trigger, place):

  zone, trigger, place, value, threshold, unit, met, detail, source, source_date

`met` is True or False when the data was there, None when it was not; a zone is met when any of
its rows is. The rules are the backtested ones, read on the live products:

  teso_kyoga  IFRC/URCS EAP as the IBF portal runs it (analysis/ifrc_reproduction.py): each admin
              area at levels 2-4 of the six Teso districts is judged at its zonal maximum; it
              triggers when at least 60 % of the 51 GloFAS members exceed the zonal max of the
              official 5-year map at any step up to TESO_STEPS; a triggered area triggers its
              district. The portal triggers on lead days 0-5 (config trigger-on-lead-time 5; lead
              time = days between forecast and event), i.e. the steps ending 24 h to 144 h.
  elgon       The partner's two draft triggers, in the forms backtested by
              analysis/elgon_exposure_trigger.py and analysis/existing_triggers.py. Every
              parameter and label comes from the private config at run time. The rain is read
              on the GEFS control run, the series the backtest used.
  karamoja    CHIRPS3-GEFS 5-day forecast, district mean, against each district's v3 threshold;
              any of the nine core districts.
  adjumani    Lake leg: Lake Kyoga's 180-day rise (3-pass running median) at or above its
              threshold. Rain leg: CHIRPS3-GEFS 5-day district mean against each of the six
              districts' v3 thresholds. Either leg.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import xarray as xr

IFRC_SHARE = 0.6  # the IBF portal's ensemble probability
TESO_STEPS = 6  # 24 h .. 144 h: the IBF portal's lead days 0-5
T2_STEPS = 5  # 24 h .. 120 h: the Elgon exposure backtest dates an exceedance 5 days early
N_MEMBERS = 51
LAKE_RISE_DAYS = 180
# Passes are every 10 days (gaps of 18-19 days occur) and NASA publishes one to two weeks
# behind, so a pass older than this means the feed has stopped: the lake leg is then not evaluated rather than "not met".
LAKE_MAX_AGE_DAYS = 40

COLS = [
    "zone",
    "trigger",
    "place",
    "value",
    "threshold",
    "unit",
    "met",
    "detail",
    "source",
    "source_date",
]


def frame(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=COLS)


def members_present(q: xr.DataArray) -> int:
    """Members with data at every step (the EWDS trickle serves partial issues; a member
    missing at a later step would otherwise count as below the level there)."""
    return int(q.notnull().any(["lat", "lon"]).all("lead_day").sum())


# --- Teso --------------------------------------------------------------------------------------


def teso(q: xr.DataArray, units: pd.DataFrame, issue: pd.Timestamp) -> pd.DataFrame:
    """q: one issue, (member, lead_day, lat, lon) on the static grid. Per district: the highest
    member share over its areas and steps, and whether any area reached IFRC_SHARE."""
    if q.lead_day.max() < TESO_STEPS:
        raise ValueError(
            f"forecast has steps to {int(q.lead_day.max())} d; Teso reads {TESO_STEPS}"
        )
    v = q.sel(lead_day=slice(1, TESO_STEPS)).values  # member x step x lat x lon
    v = v.reshape(v.shape[0], v.shape[1], -1)
    rows_u = []
    for _, u in units.iterrows():
        x = v[:, :, np.asarray(u.cells)]
        x = np.where((x == 0) | np.isnan(x), -np.inf, x)
        zmax = x.max(axis=2)  # member x step: the area's largest flow, per member
        share = (zmax > u.threshold).mean(axis=0)  # per step
        med = np.median(zmax, axis=0) / u.threshold  # per step: member median over the level
        k, j = int(np.argmax(share)), int(np.argmax(med))
        rows_u.append(
            dict(
                district=u.district,
                level=u.level,
                name=u["name"],
                share=float(share[k]),
                step=k + 1,
                median_ratio=float(med[j]),
                median_step=j + 1,
            )
        )
    au = pd.DataFrame(rows_u)
    rows = []
    for d, g in au.groupby("district"):
        top = g.sort_values(["share", "median_ratio"], ascending=False).iloc[0]
        close = g.sort_values("median_ratio", ascending=False).iloc[0]
        rows.append(
            dict(
                _median=float(close.median_ratio),
                zone="teso_kyoga",
                trigger="IFRC/URCS EAP (GloFAS)",
                place=d,
                value=top.share,
                threshold=IFRC_SHARE,
                unit="share of members",
                met=bool((g.share >= IFRC_SHARE).any()),
                detail=(
                    f"highest share: {top['name']} (admin {top.level}), step {top.step} d; "
                    f"highest member median {close.median_ratio:.2f} x the 5-year level: "
                    f"{close['name']} (admin {close.level}), step {close.median_step} d"
                ),
                source="GloFAS operational forecast",
                source_date=issue.date().isoformat(),
            )
        )
    # closest first: by member share, then by the member median over the level (a tie at 0 %
    # is the usual case); notify.trigger_lines keeps this order among equal shares
    rows.sort(key=lambda r: (r["value"], r.pop("_median")), reverse=True)
    return frame(rows)


# --- Elgon: every parameter and label from the private config -----------------------------------


def elgon_t2(q: xr.DataArray, cells: pd.DataFrame, cfg: dict, issue: pd.Timestamp) -> pd.DataFrame:
    n_hh = float(cfg["t2"]["households"])
    min_share = float(cfg["t2"].get("share", IFRC_SHARE))
    v = q.sel(lead_day=slice(1, T2_STEPS))
    x = v.sel(
        lat=xr.DataArray(cells.lat.values, dims="c"),
        lon=xr.DataArray(cells.lon.values, dims="c"),
        method="nearest",
        tolerance=1e-3,
    ).values  # member x step x cell
    share = (x >= cells.level.values).mean(axis=0)  # step x cell
    hit = share >= min_share
    rows = []
    for d in cfg["districts"]:
        m = (cells.district == d).values
        hh_step = (hit[:, m] * cells.households.values[m]).sum(axis=1) if m.any() else np.zeros(1)
        k = int(np.argmax(hh_step))
        rows.append(
            dict(
                zone="elgon",
                trigger=cfg["t2"].get("short", "partner T2"),
                place=d,
                value=float(hh_step[k]),
                threshold=n_hh,
                unit="households",
                met=bool(hh_step[k] >= n_hh),
                detail=(
                    f"{int(hit[k, m].sum())} of {int(m.sum())} cells at step {k + 1} d"
                    if m.any()
                    else "no households in the mapped extent"
                ),
                source="GloFAS operational forecast x JRC hazard x WorldPop",
                source_date=issue.date().isoformat(),
            )
        )
    return frame(rows)


def ordinal(x: float) -> str:
    if not np.isfinite(x):
        return "n/a"
    n = round(x)
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def soil_percentile(value: float, history: pd.Series) -> float:
    """Percentile of `value` in a district's daily record (share of days at or below it)."""
    h = history.dropna().to_numpy()
    if not np.isfinite(value) or not len(h):
        return np.nan  # nodata must read as not evaluated, never as the 0th percentile
    return float((h <= value).mean() * 100)


MODEL_NAME = {"gfs_seamless": "GFS", "icon_global": "ICON", "gefs_c00": "GEFS control"}


def elgon_t3(
    rain: pd.DataFrame,
    soil: pd.DataFrame | None,
    soil_hist: pd.DataFrame,
    cfg: dict,
    issue: pd.Timestamp,
) -> pd.DataFrame:
    """rain: (pcode, district, model, mm_72h); soil: (pcode, mean, date) or None;
    soil_hist: (date, pcode, mean) 2000-2025."""
    mm, pmin = float(cfg["rain_mm"]), float(cfg["antecedent_pctl"])
    label = cfg.get("t3", {}).get("short", "partner T3")
    pct = {}
    if soil is not None:
        for _, r in soil.iterrows():
            pct[r.pcode] = soil_percentile(r["mean"], soil_hist[soil_hist.pcode == r.pcode]["mean"])
    soil_day = soil.date.iloc[0].date().isoformat() if soil is not None else "unavailable"
    rows = []
    several = rain.model.nunique() > 1
    for _, r in rain[rain.district.isin(cfg["districts"])].iterrows():
        p = pct.get(r.pcode, np.nan)
        model = MODEL_NAME.get(r.model, r.model)
        rows.append(
            dict(
                zone="elgon",
                trigger=f"{label} ({model})" if several else label,
                place=r.district,
                value=r.mm_72h,
                threshold=mm,
                unit="mm in 72 h",
                met=(
                    bool(r.mm_72h >= mm and p >= pmin)
                    if np.isfinite(r.mm_72h) and np.isfinite(p)
                    else None
                ),
                detail=(
                    f"soil moisture {ordinal(p)} percentile (threshold {ordinal(pmin)}), "
                    f"CPC {soil_day}"
                ),
                source=(
                    "GEFS control run (NOAA); NOAA CPC soil moisture"
                    if r.model == "gefs_c00"
                    else f"{model} via Open-Meteo; NOAA CPC soil moisture"
                ),
                source_date=issue.date().isoformat(),
            )
        )
    return frame(rows)


# --- CHIRPS3-GEFS zones ------------------------------------------------------------------------


def rain_zone(
    zone: str, cg: pd.DataFrame, thr: pd.DataFrame, name_of: dict, issue: pd.Timestamp
) -> pd.DataFrame:
    t = thr[(thr.zone == zone) & (thr.leg == "rain")].set_index("series").threshold
    vals = cg.set_index("pcode")["mean"].rename(index=name_of)
    rows = []
    for d, level in t.items():
        val = float(vals.get(d, np.nan))
        rows.append(
            dict(
                zone=zone,
                trigger="CHIRPS3-GEFS 5-day rain",
                place=d,
                value=val,
                threshold=float(level),
                unit="mm in 5 days (district mean)",
                met=bool(val >= level) if np.isfinite(val) else None,
                detail=f"{val / level:.0%} of the threshold" if np.isfinite(val) else "no data",
                source="CHIRPS3-GEFS (CHC)",
                source_date=issue.date().isoformat(),
            )
        )
    return frame(rows)


def kyoga_rise(passes: pd.DataFrame, upto: pd.Timestamp) -> pd.Series:
    """Daily 180-day rise of Lake Kyoga from passes on or before `upto`, as in
    analysis/trigger_draft.kyoga_rise (3-pass running median, daily interpolation)."""
    ky = passes[passes.date <= upto].set_index("date").height_m.sort_index()
    ky = ky.rolling(3, center=True, min_periods=1).median()
    kyd = ky.resample("D").mean().interpolate(limit=40)
    return (kyd - kyd.shift(LAKE_RISE_DAYS)).dropna()


def adjumani_lake(passes: pd.DataFrame, thr: pd.DataFrame, issue: pd.Timestamp) -> pd.DataFrame:
    level = float(thr[(thr.zone == "adjumani") & (thr.leg == "lake")].threshold.iloc[0])
    rise = kyoga_rise(passes, issue)
    last = rise.index[-1]
    val = float(rise.iloc[-1])
    age = (issue - last).days
    if age > LAKE_MAX_AGE_DAYS:
        return frame(
            [
                dict(
                    zone="adjumani",
                    trigger="Lake Kyoga 180-day rise",
                    place="Lake Kyoga",
                    value=np.nan,
                    threshold=level,
                    unit="m",
                    met=None,
                    detail=(
                        f"last satellite pass {last.date().isoformat()}, {age} days before the "
                        f"issue day (more than {LAKE_MAX_AGE_DAYS}): the feed looks stopped"
                    ),
                    source="NASA Global Water Monitor (altimetry)",
                    source_date=last.date().isoformat(),
                )
            ]
        )
    return frame(
        [
            dict(
                zone="adjumani",
                trigger="Lake Kyoga 180-day rise",
                place="Lake Kyoga",
                value=val,
                threshold=level,
                unit="m",
                met=bool(val >= level),
                detail=(
                    f"last satellite pass {last.date().isoformat()}, "
                    f"{(issue - last).days} days before the issue day; the newest pass is "
                    "smoothed with the one before only, until the next pass arrives"
                ),
                source="NASA Global Water Monitor (altimetry)",
                source_date=last.date().isoformat(),
            )
        ]
    )
