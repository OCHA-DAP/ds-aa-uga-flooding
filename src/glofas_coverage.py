"""What does the G5196 (Akokoro) GloFAS point "cover"? — discharge vs district flood extent.

For each candidate district of the Teso/Kyoga zone, relate the daily GloFAS
reanalysis discharge at the point to the district's FloodScan SFED daily mean:

  * peak-season correlation at lags 0..L days (discharge leading extent) — a
    district the point covers should track it with a short positive lag;
  * event agreement: for each season, does the district's SFED annual maximum
    fall within +/- k days of the discharge annual maximum;
  * threshold agreement: share of district flood days (SFED above its RP-2
    level) on which discharge was also above its RP-2 level.

Districts that score high on all three are "covered"; the rest need another
indicator. Output is one tidy frame per district for the notebook to plot.
"""

import numpy as np
import pandas as pd

from src.skill_chain import annual_max, weibull_threshold


def lagged_corr(
    dis: pd.Series, sfed: pd.Series, max_lag: int = 30, months=(8, 9, 10, 11, 12)
) -> pd.Series:
    """corr(discharge(t - lag), sfed(t)) for lag 0..max_lag, restricted to flood-season months."""
    d, s = dis.asfreq("D"), sfed.asfreq("D")
    idx = d.index.intersection(s.index)
    out = {}
    for lag in range(max_lag + 1):
        dl = d.shift(lag).loc[idx]
        m = idx.month.isin(months)
        out[lag] = dl[m].corr(s.loc[idx][m])
    return pd.Series(out, name="corr")


def peak_agreement(dis: pd.Series, sfed: pd.Series, tolerance_days: int = 15) -> pd.DataFrame:
    """Per year: date of discharge max, date of SFED max, gap in days, and whether within tolerance."""
    d, s = dis.asfreq("D"), sfed.asfreq("D")
    years = sorted(set(d.dropna().index.year) & set(s.dropna().index.year))
    rows = []
    for y in years:
        dy, sy = d[str(y)], s[str(y)]
        if dy.dropna().empty or sy.dropna().empty:
            continue
        td, ts = dy.idxmax(), sy.idxmax()
        gap = (ts - td).days
        rows.append(
            dict(
                year=y,
                dis_peak=td,
                sfed_peak=ts,
                gap_days=gap,
                agree=abs(gap) <= tolerance_days,
                dis_max=float(dy.max()),
                sfed_max=float(sy.max()),
            )
        )
    return pd.DataFrame(rows)


def threshold_agreement(dis: pd.Series, sfed: pd.Series, rp_years: float = 2.0) -> dict:
    """Share of district flood days (SFED >= its RP threshold) with discharge >= its RP threshold, and vice versa."""
    d, s = dis.asfreq("D"), sfed.asfreq("D")
    idx = d.dropna().index.intersection(s.dropna().index)
    d, s = d.loc[idx], s.loc[idx]
    dt, st = weibull_threshold(annual_max(d), rp_years), weibull_threshold(annual_max(s), rp_years)
    fd, fs = d >= dt, s >= st
    return dict(
        rp_years=rp_years,
        dis_thresh=dt,
        sfed_thresh=st,
        p_dis_given_sfed=float(fd[fs].mean()) if fs.any() else np.nan,
        p_sfed_given_dis=float(fs[fd].mean()) if fd.any() else np.nan,
        n_sfed_days=int(fs.sum()),
        n_dis_days=int(fd.sum()),
    )


def coverage_table(
    dis: pd.Series,
    sfed_by_district: dict[str, pd.Series],
    sfed_max_by_district: dict[str, pd.Series] | None = None,
) -> pd.DataFrame:
    """One row per district: anomaly correlation (best lag) and 2-yr threshold agreement on the
    district mean extent and, if given, on the district max-pixel extent (small wetlands)."""
    rows = []
    for name, s in sfed_by_district.items():
        lc = lagged_corr(dis, s)
        ta = threshold_agreement(dis, s)
        row = {
            "district": name,
            "best_lag": int(lc.idxmax()),
            "best_corr": float(lc.max()),
            "corr_lag0": float(lc.iloc[0]),
            "p_dis_given_sfed": ta["p_dis_given_sfed"],
            "p_sfed_given_dis": ta["p_sfed_given_dis"],
        }
        if sfed_max_by_district is not None:
            row["p_dis_given_sfedmax"] = threshold_agreement(dis, sfed_max_by_district[name])[
                "p_dis_given_sfed"
            ]
        rows.append(row)
    return pd.DataFrame(rows).sort_values("best_corr", ascending=False).reset_index(drop=True)
