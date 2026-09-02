"""The two-link skill chain for the rainfall-based (flash-flood) zones.

Link 1 — forecast → observed rainfall: CHIRPS-GEFS 5-day accumulation issued on
day d (valid d..d+4) against IMERG summed over the same five days, per district
or per zone. Reported as correlation, and as hit/miss/false-alarm contingency at
return-period thresholds derived separately for each series (so a forecast bias
does not masquerade as a miss — same logic as setting GloFAS thresholds in model
space).

Link 2 — observed rainfall → observed flooding/impact: for every impact event in
the zone, the observed 1-, 3-, 5-day rainfall percentile / return period in the
days before the event; and, in the other direction, how often heavy-rain days
were followed by a recorded event (the false-alarm side).

All functions take the long parquet tables built by pipeline/ (date, pcode,
mean, max) and return tidy frames; notebooks in analysis/ do the plotting.
"""

import numpy as np
import pandas as pd

from src.constants import ZONES


def zone_series(
    df: pd.DataFrame,
    zone_key: str,
    pcode_of: dict[str, str],
    value: str = "mean",
    include_candidates: bool = False,
    date_col: str = "date",
) -> pd.Series:
    """Area-unweighted mean over the zone's districts of a per-district daily table."""
    zone = ZONES[zone_key]
    names = zone.all_districts if include_candidates else zone.core
    pcodes = [pcode_of[n] for n in names]
    sub = df[df.pcode.isin(pcodes)]
    return sub.groupby(date_col)[value].mean().rename(zone_key)


def rolling_sum(s: pd.Series, days: int) -> pd.Series:
    """Backward-looking rolling sum ending on each day (a full daily index is enforced)."""
    s = s.asfreq("D")
    return s.rolling(days, min_periods=days).sum()


def forward_sum(s: pd.Series, days: int) -> pd.Series:
    """Sum over d..d+days-1, indexed on d — matches a forecast issued on d."""
    return rolling_sum(s, days).shift(-(days - 1))


def weibull_threshold(annual_max: pd.Series, rp_years: float) -> float:
    """Empirical (Weibull plotting position) return-level for a series of annual maxima."""
    x = np.sort(annual_max.dropna().to_numpy())
    n = len(x)
    ranks = np.arange(1, n + 1)
    rp = (n + 1) / (n + 1 - ranks)  # exceedance RP of the i-th smallest value
    return float(np.interp(rp_years, rp, x))


def annual_max(s: pd.Series, months: tuple[int, ...] | None = None) -> pd.Series:
    if months:
        s = s[s.index.month.isin(months)]
    return s.groupby(s.index.year).max()


def contingency(
    fc: pd.Series, ob: pd.Series, fc_thresh: float, ob_thresh: float, window_days: int = 0
) -> dict:
    """Hit / miss / false alarm counts of forecast exceedance vs observed exceedance.

    window_days > 0 credits a forecast exceedance as a hit if the observation
    exceeds within +/- that many days (event-based tolerance).
    """
    idx = fc.dropna().index.intersection(ob.dropna().index)
    f = fc.loc[idx] >= fc_thresh
    o = ob.loc[idx] >= ob_thresh
    if window_days:
        o_any = (
            o.astype(int)
            .rolling(2 * window_days + 1, center=True, min_periods=1)
            .max()
            .astype(bool)
        )
        f_any = (
            f.astype(int)
            .rolling(2 * window_days + 1, center=True, min_periods=1)
            .max()
            .astype(bool)
        )
    else:
        o_any, f_any = o, f
    hits = int((f & o_any).sum())
    false_alarms = int((f & ~o_any).sum())
    misses = int((o & ~f_any).sum())
    pod = hits / (hits + misses) if hits + misses else np.nan
    far = false_alarms / (hits + false_alarms) if hits + false_alarms else np.nan
    return dict(
        hits=hits, misses=misses, false_alarms=false_alarms, pod=pod, far=far, n_days=len(idx)
    )


def link1_forecast_vs_observed(
    fc_5day: pd.Series,
    obs_daily: pd.Series,
    rp_years=(2, 3, 5),
    months: tuple[int, ...] | None = None,
) -> pd.DataFrame:
    """Per return period: thresholds in each series' own climatology + contingency + correlation."""
    ob5 = forward_sum(obs_daily, 5)
    fc = fc_5day.asfreq("D")
    idx = fc.dropna().index.intersection(ob5.dropna().index)
    if months:
        idx = idx[idx.month.isin(months)]
    fc, ob5 = fc.loc[idx], ob5.loc[idx]
    rows = []
    corr = fc.corr(ob5)
    for rp in rp_years:
        ft, ot = weibull_threshold(annual_max(fc), rp), weibull_threshold(annual_max(ob5), rp)
        c = contingency(fc, ob5, ft, ot, window_days=2)
        rows.append(dict(rp_years=rp, fc_thresh=ft, obs_thresh=ot, corr=corr, **c))
    return pd.DataFrame(rows)


def link2_rain_before_events(
    obs_daily: pd.Series, events: pd.DataFrame, windows=(1, 3, 5), lead_days: int = 3
) -> pd.DataFrame:
    """For each event: max observed N-day rainfall in [start - lead_days, start + 1], as value and
    as percentile of the whole daily climatology of that N-day sum."""
    out = []
    sums = {w: rolling_sum(obs_daily, w) for w in windows}
    for _, ev in events.iterrows():
        lo, hi = ev.start - pd.Timedelta(days=lead_days), ev.start + pd.Timedelta(days=1)
        row = dict(event_id=ev.event_id, start=ev.start, subtype=ev.subtype)
        for w, s in sums.items():
            win = s.loc[lo:hi]
            if win.dropna().empty:
                row[f"rain{w}d"] = np.nan
                row[f"rain{w}d_pctl"] = np.nan
                continue
            v = float(win.max())
            row[f"rain{w}d"] = v
            row[f"rain{w}d_pctl"] = float((s.dropna() < v).mean() * 100)
        out.append(row)
    return pd.DataFrame(out)
