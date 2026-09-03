"""Antecedent wetness for the flash-flood zones: does adding it separate events from wet non-events?

Uses an antecedent precipitation index (API) from IMERG as a soil-moisture proxy —
API_t = k * API_{t-1} + P_t with k = 0.9 (e-folding ~10 days) — plus the plain 30-day
sum, both on the zone-mean daily rainfall, lagged so the index describes the ground
BEFORE the 3-day rain window that precedes an event. ERA5-Land soil moisture replaces
the proxy once its download lands (src/datasources/era5_land.py).

Outputs, per zone:
  * a 2-D view: 3-day rain percentile (x) vs antecedent percentile (y) for all days
    (density) and for event days (points) — events should sit top-right if wetness matters;
  * a trigger grid: for thresholds on rain3d and API percentiles, the days that would
    activate, how many of them have a recorded event within +2 days (precision), how many
    events are caught (recall), and activations per year.

Writes outputs/flash_antecedent.png and outputs/flash_trigger_grid_{zone}.csv.
Run:  uv run python analysis/flash_flood_antecedent.py
"""

import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import ocha_stratus as stratus
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from analysis.flash_flood_rain_vs_events import ZONE_KEYS, zone_events, zone_rain  # noqa: E402
from src.constants import PROJECT_PREFIX, ZONES  # noqa: E402
from src.skill_chain import rolling_sum  # noqa: E402
from src.zones import load_adm2  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "outputs"
K = 0.9
RAIN_PCTLS = (80, 90, 95, 98)
API_PCTLS = (0, 50, 70, 85, 95)
MATCH_DAYS = (
    2  # an activation "hits" if an event is recorded within this many days after (or on) the day
)


def api_index(p: pd.Series, k: float = K) -> pd.Series:
    p = p.asfreq("D").fillna(0)
    out = np.empty(len(p))
    acc = 0.0
    for i, v in enumerate(p.to_numpy()):
        acc = k * acc + v
        out[i] = acc
    return pd.Series(out, index=p.index, name="api")


def pctl(s: pd.Series) -> pd.Series:
    return s.rank(pct=True) * 100


def trigger_grid(
    rain_p: pd.Series, ante_p: pd.Series, event_days: pd.DatetimeIndex
) -> pd.DataFrame:
    idx = rain_p.dropna().index.intersection(ante_p.dropna().index)
    years = idx.year.nunique()
    ev = pd.Series(1, index=event_days).reindex(idx, fill_value=0)
    # any event in [t, t+MATCH_DAYS]
    ev_ahead = ev[::-1].rolling(MATCH_DAYS + 1, min_periods=1).max()[::-1].astype(bool)
    rows = []
    for rp in RAIN_PCTLS:
        for ap in API_PCTLS:
            act = (rain_p.loc[idx] >= rp) & (ante_p.loc[idx] >= ap)
            # collapse consecutive activation days into episodes
            starts = act & ~act.shift(1, fill_value=False)
            n_act = int(starts.sum())
            hits = int((starts & ev_ahead).sum())
            # recall: events preceded by an activation within MATCH_DAYS before
            act_before = (
                act[::-1].rolling(MATCH_DAYS + 1, min_periods=1).max()[::-1].astype(bool).shift(-0)
            )
            act_window = act.rolling(MATCH_DAYS + 1, min_periods=1).max().astype(bool)
            caught = int(((ev == 1) & act_window).sum())
            rows.append(
                dict(
                    rain_pctl=rp,
                    api_pctl=ap,
                    activations=n_act,
                    act_per_year=n_act / years,
                    precision=hits / n_act if n_act else np.nan,
                    events=int(ev.sum()),
                    recall=caught / ev.sum() if ev.sum() else np.nan,
                )
            )
    return pd.DataFrame(rows)


def main() -> None:
    imerg = stratus.load_parquet_from_blob(
        f"{PROJECT_PREFIX}/processed/imerg/imerg_adm2_daily.parquet", stage="dev"
    )
    adm = load_adm2()
    fig, axes = plt.subplots(1, len(ZONE_KEYS), figsize=(13, 6))
    pd.set_option("display.width", 200)
    for ax, zk in zip(axes, ZONE_KEYS, strict=True):
        z = ZONES[zk]
        pcodes = adm[adm.ADM2_EN.isin(z.core)].ADM2_PCODE.tolist()
        mean_s, _ = zone_rain(imerg, pcodes)
        rain3 = rolling_sum(mean_s, 3)
        ante = api_index(mean_s).shift(3)  # ground state before the 3-day window
        rain_p, ante_p = pctl(rain3), pctl(ante)
        events = zone_events(zk)
        ev_days = events.index
        # per event: max rain3 pctl in [d-3, d+1] and the antecedent pctl at that day
        pts = []
        for d in ev_days:
            win = rain_p.loc[d - pd.Timedelta(days=3) : d + pd.Timedelta(days=1)].dropna()
            if win.empty:
                continue
            dmax = win.idxmax()
            pts.append((win.max(), ante_p.get(dmax, np.nan), float(events.loc[d, "deaths"] or 0)))
        pts = pd.DataFrame(pts, columns=["rain_p", "ante_p", "deaths"])
        wet = pd.DataFrame({"r": rain_p, "a": ante_p}).dropna()
        ax.hexbin(wet.r, wet.a, gridsize=25, cmap="Greys", mincnt=1, bins="log")
        ax.scatter(
            pts.rain_p,
            pts.ante_p,
            s=18,
            color="#b2182b" if zk == "elgon" else "#e08214",
            alpha=0.8,
            label="event days",
        )
        big = pts[pts.deaths >= 5]
        ax.scatter(
            big.rain_p, big.ante_p, s=60, facecolors="none", edgecolors="black", label=">=5 deaths"
        )
        ax.set_xlabel("3-day rainfall percentile (zone mean, IMERG)")
        ax.set_ylabel("antecedent index percentile (API, k=0.9, lagged 3 d)")
        ax.set_title(f"{z.label}\n{len(pts)} event days", fontsize=10)
        ax.legend(loc="lower left", fontsize=8)
        print(
            f"\n=== {z.label}: median antecedent pctl at events {pts.ante_p.median():.0f} (deadly {big.ante_p.median():.0f}); "
            f"share of events with antecedent > 70th pctl: {(pts.ante_p > 70).mean():.2f}"
        )
        grid = trigger_grid(rain_p, ante_p, ev_days)
        grid.to_csv(OUT / f"flash_trigger_grid_{zk}.csv", index=False)
        print(grid.round(2).to_string())
    fig.suptitle(
        "Where do recorded flash floods / landslides sit in rain-vs-antecedent-wetness space? (grey = all days, log density)",
        fontsize=10,
    )
    fig.tight_layout()
    fig.savefig(OUT / "flash_antecedent.png", dpi=150)
    print("wrote", OUT / "flash_antecedent.png")


if __name__ == "__main__" and "--district" not in sys.argv:
    main()


# ---------------------------------------------------------------------------
# District-level variant: activate when ANY core district has 3-day rain >= rp
# AND its own antecedent >= ap; recall also reported for deadly events (>=5 deaths).
# ---------------------------------------------------------------------------
def district_grid(imerg: pd.DataFrame, zk: str, adm) -> pd.DataFrame:
    z = ZONES[zk]
    pc = adm[adm.ADM2_EN.isin(z.core)].set_index("ADM2_PCODE").ADM2_EN
    events = zone_events(zk)
    ev_days = events.index
    deadly_days = events[events.deaths.fillna(0) >= 5].index
    rain_p, ante_p = {}, {}
    for p in pc.index:
        s = imerg[imerg.pcode == p].set_index("date")["mean"].sort_index().asfreq("D")
        rain_p[p] = pctl(rolling_sum(s, 3))
        ante_p[p] = pctl(api_index(s).shift(3))
    rain_p, ante_p = pd.DataFrame(rain_p).dropna(how="all"), pd.DataFrame(ante_p).dropna(how="all")
    idx = rain_p.index.intersection(ante_p.index)
    years = idx.year.nunique()
    ev = pd.Series(1, index=ev_days).reindex(idx, fill_value=0)
    dev = pd.Series(1, index=deadly_days).reindex(idx, fill_value=0)
    ev_ahead = ev[::-1].rolling(MATCH_DAYS + 1, min_periods=1).max()[::-1].astype(bool)
    rows = []
    for rp in RAIN_PCTLS:
        for ap in API_PCTLS:
            act = ((rain_p.loc[idx] >= rp) & (ante_p.loc[idx] >= ap)).any(axis=1)
            starts = act & ~act.shift(1, fill_value=False)
            n_act, hits = int(starts.sum()), int((starts & ev_ahead).sum())
            act_window = act.rolling(MATCH_DAYS + 1, min_periods=1).max().astype(bool)
            rows.append(
                dict(
                    rain_pctl=rp,
                    api_pctl=ap,
                    activations=n_act,
                    act_per_year=n_act / years,
                    precision=hits / n_act if n_act else np.nan,
                    recall=((ev == 1) & act_window).sum() / ev.sum(),
                    recall_deadly=((dev == 1) & act_window).sum() / dev.sum()
                    if dev.sum()
                    else np.nan,
                )
            )
    return pd.DataFrame(rows)


def main_district() -> None:
    imerg = stratus.load_parquet_from_blob(
        f"{PROJECT_PREFIX}/processed/imerg/imerg_adm2_daily.parquet", stage="dev"
    )
    adm = load_adm2()
    pd.set_option("display.width", 200)
    for zk in ZONE_KEYS:
        g = district_grid(imerg, zk, adm)
        g.to_csv(OUT / f"flash_trigger_grid_district_{zk}.csv", index=False)
        print(f"\n=== {ZONES[zk].label} — district-level (any core district)")
        print(g.round(2).to_string())


if __name__ == "__main__" and "--district" in sys.argv:
    main_district()
