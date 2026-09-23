"""Draft trigger mechanisms, one per zone, backtested season by season against dated impact.

One all-in trigger per zone; zones trigger independently of each other.

  teso_kyoga  GloFAS G5196 (Akokoro) daily discharge. REANALYSIS as a stand-in for the
              forecast until the reforecast is complete, so the backtest has no forecast
              error in it — an upper bound on what the forecast trigger could do.
  elgon       CHIRPS-GEFS 5-day forecast accumulation, mean over the zone's 15 districts
              (slopes and lowlands: every lowland flood year is also a slope flood year).
  karamoja    CHIRPS-GEFS 5-day forecast per district, each against its own threshold at a
              common rarity; the zone activates when any district does. Karamoja is the size
              of a small country and flash floods are local, so a zone mean would dilute the
              storms that matter.
  adjumani    Two legs, either activates. (1) The Nile high stand: Lake Kyoga's rise over 180
              days (NASA GWM altimetry since 1992; Kyoga tracks Lake Albert at r = 0.96 month to
              month, and Albert's own record only starts in 2016). Months of lead. (2) Flash
              floods on the tributaries: the CHIRPS-GEFS forecast per district, as in Karamoja.
              Each leg takes half the zone's rate and is calibrated on its own, so the single
              lake series is not outvoted by six rain series.

Season. Triggers can activate only from 1 September to the end of February — the window the
funding covers (it does not extend into March). A "season" is labelled by its start year:
season 2019 is 1 Sep 2019 to 29 Feb 2020. Indicators and impact outside the window are ignored.

Return period. Each zone activates about as often as it has a major-impact season (at least 5
deaths or 5,000 people affected recorded in a single event in the zone), and never more often
than 1-in-RP_FLOOR. Frequency-matching rather than choosing the return period that scores best
in the backtest, because with ~25 seasons the best score is noise.

Event matching. A season's first activation releases the envelope. It counts as catching a
major event when the event starts within the trigger's lead window after the activation
(LEAD_DAYS: 14 for the rain forecasts, 30 for GloFAS, 120 for the lake leg), or is still going
on when the activation comes (negative lead). Otherwise the activation is a false alarm, and a
major-impact season with no matching activation is a miss.

Outputs (outputs/triggers/): one CSV per zone (a season per row), events_<zone>.csv (the dated
impact events matched against), summary.csv, thresholds.csv, rp_sensitivity.csv. The page is
built by pipeline/build_trigger_page.py.

Run:  uv run python analysis/trigger_draft.py

History: an earlier draft shared one overall 1-in-3 budget across the four zones (tilted by
recorded people affected) and was scored by calendar year; both were replaced in Sep 2026 —
see the git history and docs/research-notes.md.
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
from impact_maps import CERF_YEARS, IMPLAUSIBLE_AFFECTED

from src.constants import GLOFAS_PIXEL_LONLAT, PROJECT_PREFIX, ZONES
from src.datasources import desinventar as di
from src.datasources import impact as imp
from src.zones import load_adm2

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "outputs" / "triggers"
GLOFAS_DIR = ROOT / "data" / "glofas" / "raw" / "reanalysis_uga_v4"

SEASON_MONTHS = (9, 10, 11, 12, 1, 2)  # 1 Sep - end Feb: the window the funding covers
FIRST_SEASON = 2000  # CHIRPS-GEFS hindcast starts 2000-01-01
MIN_COVERAGE = 0.6  # a series' season counts when at least this share of its days has data
RP_FLOOR = 3.0  # no zone activates more often than once in three seasons
LAKE_RISE_DAYS = 180
MAJOR_DEATHS, MAJOR_AFFECTED = 5, 5000  # a major event, per event, zone share
# How far ahead of a flood an activation may be and still count as catching it. Generous on
# purpose: reported impact dates lag the flood, and rain that falls inside the forecast window
# can pool for days before it floods. Widening them further barely adds catches while raising
# what random timing would score — see window_sensitivity() and the page.
LEAD_DAYS = {"glofas": 45, "rain": 30, "lake": 150}
TOLERANCE_DAYS = 3  # an activation up to this long after an event ends still counts (date noise)

# Series -> leg (which lead window applies). Anything not listed is a rain forecast.
SERIES_LEG = {"GloFAS G5196": "glofas", "Kyoga rise": "lake"}
# Zones whose trigger has separate legs for separate flood regimes (see module docstring).
LEGS = {"adjumani": {"lake": ["Kyoga rise"], "rain": None}}  # None = every other series


# --- seasons -------------------------------------------------------------------------------


def season_of(ts: pd.Timestamp) -> int | None:
    if ts.month >= 9:
        return ts.year
    if ts.month in (1, 2):
        return ts.year - 1
    return None


def season_bounds(season: int) -> tuple[pd.Timestamp, pd.Timestamp]:
    return pd.Timestamp(season, 9, 1), pd.Timestamp(season + 1, 3, 1) - pd.Timedelta(days=1)


def season_label(season: int) -> str:
    return f"{season}/{(season + 1) % 100:02d}"


def in_season(s: pd.Series) -> pd.Series:
    """Keep only in-season days, in seasons the series covers well enough."""
    s = s.dropna()
    s = s[s.index.month.isin(SEASON_MONTHS)]
    seasons = pd.Series([season_of(t) for t in s.index], index=s.index)
    days = seasons.value_counts()
    ok = {
        y
        for y, n in days.items()
        if n / ((season_bounds(y)[1] - season_bounds(y)[0]).days + 1) >= MIN_COVERAGE
    }
    return s[seasons.isin(ok)]


def coverage(s: pd.Series) -> pd.Series:
    """Share of each season's days that the series has data for."""
    s = s.dropna()
    s = s[s.index.month.isin(SEASON_MONTHS)]
    seasons = pd.Series([season_of(t) for t in s.index], index=s.index)
    return (
        seasons.value_counts()
        .sort_index()
        .rename_axis("season")
        .pipe(
            lambda c: (
                c / c.index.map(lambda y: (season_bounds(y)[1] - season_bounds(y)[0]).days + 1)
            )
        )
    )


def season_max(s: pd.Series) -> pd.Series:
    s = in_season(s)
    return s.groupby([season_of(t) for t in s.index]).max()


# --- indicators ----------------------------------------------------------------------------


def load(path: str) -> pd.DataFrame:
    return stratus.load_parquet_from_blob(f"{PROJECT_PREFIX}/{path}", stage="dev")


def glofas_g5196() -> pd.Series:
    ds = xr.open_mfdataset(sorted(GLOFAS_DIR.glob("*.nc")), combine="by_coords")
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


def zone_series() -> dict[str, dict[str, pd.Series]]:
    adm = load_adm2().set_index("ADM2_EN").ADM2_PCODE
    name_of = {v: k for k, v in adm.items()}
    zd = {z: list(ZONES[z].core) + list(ZONES[z].tier2) for z in ZONES}
    series: dict[str, dict[str, pd.Series]] = {"teso_kyoga": {"GloFAS G5196": glofas_g5196()}}
    series["elgon"] = {
        "zone-mean 5-day forecast": chirps_gefs_wide([adm[d] for d in zd["elgon"]]).mean(axis=1)
    }
    kar = chirps_gefs_wide([adm[d] for d in ZONES["karamoja"].core])
    series["karamoja"] = {name_of[c]: kar[c].dropna() for c in kar.columns}
    adj = chirps_gefs_wide([adm[d] for d in zd["adjumani"]])
    series["adjumani"] = {"Kyoga rise": kyoga_rise()} | {
        name_of[c]: adj[c].dropna() for c in adj.columns
    }
    return series


# --- calibration ---------------------------------------------------------------------------


def gumbel_fit(am: pd.Series) -> tuple[float, float]:
    """Method-of-moments Gumbel fit to block maxima: (location, scale)."""
    beta = float(np.sqrt(6) * am.std() / np.pi)
    return float(am.mean() - 0.5772 * beta), beta


def gumbel_rp(x, mu: float, beta: float):
    """Return period of value x under the fitted Gumbel. Survival via expm1, so extreme values
    keep distinct return periods instead of underflowing to the same cap."""
    z = (np.asarray(x, dtype=float) - mu) / beta
    return 1.0 / -np.expm1(-np.exp(-z))


def gumbel_level(rp: float, mu: float, beta: float) -> float:
    return float(mu - beta * np.log(-np.log(1.0 - 1.0 / rp)))


def zone_statistic(cal_ms: dict[str, pd.Series]) -> tuple[pd.Series, dict]:
    """Per calibration season, the rarest value any of the zone's series reached, as a return
    period on that series' own Gumbel fit — so a wet district and a dry one are held to the same
    rarity. For a single series this is a monotone transform of the seasonal maximum."""
    fits = {key: gumbel_fit(a.dropna()) for key, a in cal_ms.items()}
    rp = pd.concat(
        {key: pd.Series(gumbel_rp(a, *fits[key]), index=a.index) for key, a in cal_ms.items()},
        axis=1,
    )
    return rp.max(axis=1).dropna(), fits


def calibrate_zone(
    cal_ms: dict[str, pd.Series], k: float
) -> tuple[dict[str, float], set[int], float]:
    """Thresholds so the zone activates in about k calibration seasons (k may be fractional).
    The threshold is interpolated (log scale) at rank k + 0.5 between the order statistics, so
    the backtest shows round(k) activations while the threshold sits where the target rate puts
    it. Per-series thresholds are each series' Gumbel return level at the resulting RP."""
    rp_season, fits = zone_statistic(cal_ms)
    v = np.log(rp_season.sort_values(ascending=False).to_numpy())
    pos = k + 0.5
    if pos <= 1:
        log_star = v[0] + (1 - pos) * ((v[0] - v[1]) if len(v) > 1 else 0.5)
    elif pos >= len(v):
        log_star = v[-1]
    else:
        i = int(np.floor(pos)) - 1
        log_star = v[i] + (pos - np.floor(pos)) * (v[i + 1] - v[i])
    rp_star = float(np.exp(log_star))
    seasons = {int(y) for y in rp_season[rp_season >= rp_star].index}
    return {key: gumbel_level(rp_star, *fits[key]) for key in cal_ms}, seasons, rp_star


def calibrate_zone_legs(z: str, cal_ms: dict[str, pd.Series], k: float):
    if z not in LEGS:
        return calibrate_zone(cal_ms, k)
    named = {x for v in LEGS[z].values() if v for x in v}
    thr, seasons, rps = {}, set(), {}
    for leg, keys in LEGS[z].items():
        keys = keys or [x for x in cal_ms if x not in named]
        t, y, rp = calibrate_zone({x: cal_ms[x] for x in keys}, k / len(LEGS[z]))
        thr |= t
        seasons |= y
        rps[leg] = rp
    return thr, seasons, rps


# --- impact --------------------------------------------------------------------------------


def zone_events(z: str) -> pd.DataFrame:
    """Dated impact events in the zone: start, end, affected and deaths (the zone's share),
    source. EM-DAT, press and DTM events naming several districts are split evenly across them,
    and only the zone's part counts; DesInventar cards are summed per day. National totals
    mis-filed against one district (>= 100,000 on a card) are dropped, as elsewhere."""
    ds = set(ZONES[z].core) | set(ZONES[z].tier2)
    ev = imp.events_by_district(include_dtm=True)
    n_named = ev.groupby("event_id").district.transform("nunique")
    ev = ev.assign(share=1.0 / n_named)[ev.district.isin(ds)]
    a = (
        ev.groupby("event_id")
        .agg(
            start=("start", "first"),
            end=("end", "first"),
            source=("source", "first"),
            share=("share", "sum"),
            affected=("affected", "first"),
            deaths=("deaths", "first"),
        )
        .assign(
            affected=lambda x: x.affected.fillna(0) * x.share,
            deaths=lambda x: x.deaths.fillna(0).astype(float) * x.share,
        )
        .drop(columns="share")
    )
    d = di.load_datacards()
    d = d[d.district.isin(ds) & d.date_precision.isin(("day", "month"))].copy()
    d.loc[d.affected >= IMPLAUSIBLE_AFFECTED, "affected"] = np.nan
    # month-precision cards (the export gives no day) span their whole month, so an activation
    # anywhere in that month can match them; day-precision cards are single days
    d["end_"] = np.where(d.date_precision.eq("month"), d.date + pd.offsets.MonthEnd(0), d.date)
    b = (
        d.groupby([d.date.dt.normalize().rename("start"), "end_"])
        .agg(affected=("affected", "sum"), deaths=("deaths", "sum"))
        .reset_index()
        .rename(columns={"end_": "end"})
        .assign(source="DesInventar")
    )
    out = pd.concat([a.reset_index(drop=True), b], ignore_index=True)
    out["end"] = out.end.fillna(out.start)
    out["major"] = (out.deaths >= MAJOR_DEATHS) | (out.affected >= MAJOR_AFFECTED)
    return out.sort_values("start").reset_index(drop=True)


def events_in_season(ev: pd.DataFrame, season: int) -> pd.DataFrame:
    lo, hi = season_bounds(season)
    return ev[(ev.end >= lo) & (ev.start <= hi)]


def season_impact(ev: pd.DataFrame, season: int) -> dict:
    e = events_in_season(ev, season)
    di_ = e[e.source == "DesInventar"]
    other = e[e.source != "DesInventar"]
    # EM-DAT/press/DTM and DesInventar are independent in scope: take the larger magnitude,
    # and deaths from EM-DAT/press where they exist (DesInventar double-counts across cards)
    return dict(
        affected=max(other.affected.sum(), di_.affected.sum()),
        deaths=other.deaths.sum() if other.deaths.sum() > 0 else di_.deaths.sum(),
        n_events=len(e),
        major=bool(e.major.any()),
        sources="|".join(sorted({s[:10] for s in e.source})),
    )


def match(activation: pd.Timestamp, leg: str, ev: pd.DataFrame) -> pd.DataFrame:
    """Major events this activation counts as catching: starting within the leg's lead window
    after it, or still under way when it comes."""
    lead = LEAD_DAYS[leg]
    m = ev[
        ev.major
        & (ev.start - pd.Timedelta(days=lead) <= activation)
        & (activation <= ev.end + pd.Timedelta(days=TOLERANCE_DAYS))
    ]
    return m.assign(lead_days=(m.start - activation).dt.days)


# --- per-zone backtest ---------------------------------------------------------------------


def activation_episodes(series: dict[str, pd.Series], thr: dict[str, float], season: int):
    """Every in-season activation, as (date, series names). Consecutive days above a threshold
    are one episode, dated by its first day. The first episode releases an all-in envelope; the
    later ones are kept because they show what the all-in rule costs — a season whose first
    activation is a false start can still have a later one that would have caught the flood."""
    lo, hi = season_bounds(season)
    hit: dict[pd.Timestamp, list[str]] = {}
    for key, s in series.items():
        x = s[(s.index >= lo) & (s.index <= hi) & (s >= thr[key])]
        for d0 in x.index:
            hit.setdefault(d0, []).append(key)
    out, prev = [], None
    for d0 in sorted(hit):
        if prev is None or (d0 - prev).days > 1:
            out.append((d0, hit[d0]))
        prev = d0
    return out


def backtest_zone(z, series, thr, ev, seasons, cal) -> pd.DataFrame:
    rows = []
    sms = {k: season_max(s) for k, s in series.items()}
    fits = {k: gumbel_fit(sms[k].reindex(cal).dropna()) for k in series}
    cov = pd.concat({k: coverage(s) for k, s in series.items()}, axis=1).max(axis=1)
    for y in seasons:
        have = [k for k in series if y in sms[k].index]
        eps = activation_episodes({k: in_season(series[k]) for k in have}, thr, y) if have else []
        a, via = eps[0] if eps else (None, [])
        leg = SERIES_LEG.get(via[0], "rain") if via else None
        m = match(a, leg, ev) if a is not None else ev.iloc[0:0]
        later = [(d0, match(d0, SERIES_LEG.get(v[0], "rain"), ev)) for d0, v in eps[1:]]
        later = [(d0, mm) for d0, mm in later if len(mm)]
        peaks = {k: float(gumbel_rp(sms[k].get(y, np.nan), *fits[k])) for k in have}
        where = max(peaks, key=peaks.get) if peaks else ""
        imp_ = season_impact(ev, y)
        first_major = events_in_season(ev, y).query("major").start.min()
        rows.append(
            dict(
                season=y,
                label=season_label(y),
                in_calibration=y in cal,
                data=bool(have),
                coverage=round(float(cov.get(y, 0.0)), 2),
                activated=a is not None,
                first_date=a.date().isoformat() if a is not None else "",
                via=", ".join(via),
                leg=leg or "",
                window_days=LEAD_DAYS.get(leg, np.nan),
                n_activations=len(eps),
                later_catch=(later[0][0].date().isoformat() if later else ""),
                later_lead=(int(later[0][1].lead_days.max()) if later else np.nan),
                caught=bool(len(m)),
                lead_days=int(m.lead_days.max()) if len(m) else np.nan,
                caught_event=(
                    m.sort_values("start").iloc[0].start.date().isoformat() if len(m) else ""
                ),
                first_major=first_major.date().isoformat() if pd.notna(first_major) else "",
                peak_rp=peaks.get(where, np.nan),
                peak_where=where,
                **imp_,
                cerf=CERF_YEARS.get(y, ""),
            )
        )
    t = pd.DataFrame(rows).set_index("season")
    t["outcome"] = np.select(
        [~t.data, t.activated & t.caught, t.activated & ~t.caught, ~t.activated & t.major],
        ["no data", "caught", "false alarm", "missed"],
        default="",
    )
    return t


def scores(t: pd.DataFrame) -> dict:
    c = t[t.in_calibration & t.data]
    caught = c[c.outcome == "caught"]
    return dict(
        seasons_with_data=len(c),
        activations=int(c.activated.sum()),
        caught=len(caught),
        false_alarms=int((c.outcome == "false alarm").sum()),
        # a major season counts as missed unless an activation actually caught an event in it —
        # the same definition the page uses for every trigger, ours and the partners'
        missed=int((c.major & ~c.caught).sum()),
        no_activation=int((c.outcome == "missed").sum()),
        major_seasons=int(c.major.sum()),
        median_lead_days=float(caught.lead_days.median()) if len(caught) else np.nan,
        caught_by_later=int(((c.outcome != "caught") & c.later_catch.astype(bool)).sum()),
    )


def window_sensitivity(
    series, thr_by_zone, events, cal, draws: int = 300, seed: int = 0
) -> pd.DataFrame:
    """How the catch count depends on the matching window, against what random timing scores.

    For each candidate window: the events our activations actually catch, and the average a
    trigger activating on random in-window dates (the same number of seasons) would catch. The
    gap between them is what the matching is really telling us."""
    rng = np.random.default_rng(seed)
    rows = []
    for z, thr in thr_by_zone.items():
        ev = events[z]
        acts = {}
        for y in cal:
            eps = activation_episodes({k: in_season(v) for k, v in series[z].items()}, thr, y)
            if eps:
                acts[y] = (eps[0][0], SERIES_LEG.get(eps[0][1][0], "rain"))
        for w in (7, 14, 21, 30, 45, 60, 90):
            old = LEAD_DAYS.copy()
            LEAD_DAYS.update({k: (max(w, old["lake"]) if k == "lake" else w) for k in LEAD_DAYS})
            caught = sum(len(match(a, leg, ev)) > 0 for a, leg in acts.values())
            exp = []
            for _ in range(draws):
                c = 0
                for y, (_, leg) in acts.items():
                    lo, hi = season_bounds(y)
                    d = lo + pd.Timedelta(days=int(rng.integers(0, (hi - lo).days + 1)))
                    c += len(match(d, leg, ev)) > 0
                exp.append(c)
            LEAD_DAYS.update(old)
            rows.append(
                dict(
                    zone=z,
                    window=w,
                    activations=len(acts),
                    caught=caught,
                    chance=round(float(np.mean(exp)), 1),
                )
            )
    return pd.DataFrame(rows)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    series = zone_series()
    q = series["teso_kyoga"]["GloFAS G5196"]
    last = min(season_of(q.index.max()) - (0 if q.index.max().month in (2,) else 1), 2024)
    cal = list(range(FIRST_SEASON, last + 1))
    show = list(range(FIRST_SEASON, 2026))
    n = len(cal)

    sms = {z: {k: season_max(s) for k, s in d.items()} for z, d in series.items()}
    cal_ms = {z: {k: a.reindex(cal) for k, a in d.items()} for z, d in sms.items()}
    events = {z: zone_events(z) for z in ZONES}

    summary, thr_rows, sens, thr_by_zone = [], [], [], {}
    for z in ZONES:
        have = [y for y in cal if any(pd.notna(a.get(y)) for a in cal_ms[z].values())]
        n_major = sum(season_impact(events[z], y)["major"] for y in have)
        major_rp = (len(have) + 1) / max(1, n_major)
        design_rp = max(RP_FLOOR, major_rp)
        thr, _, rp_star = calibrate_zone_legs(z, cal_ms[z], len(have) / design_rp)
        thr_by_zone[z] = thr
        t = backtest_zone(z, series[z], thr, events[z], show, cal)
        t.sort_index(ascending=False).to_csv(OUT / f"{z}.csv")
        events[z].to_csv(OUT / f"events_{z}.csv", index=False)
        sc = scores(t)
        summary.append(
            dict(
                zone=z,
                major_rp=major_rp,
                design_rp=design_rp,
                individual_rp=(sc["seasons_with_data"] + 1) / max(1, sc["activations"]),
                activated_seasons=", ".join(t[t.activated & t.in_calibration].label),
                **sc,
            )
        )
        for key, v in thr.items():
            leg = SERIES_LEG.get(key, "rain")
            thr_rows.append(
                dict(
                    zone=z,
                    series=key,
                    leg=leg,
                    threshold=v,
                    series_rp=rp_star[leg] if isinstance(rp_star, dict) else rp_star,
                )
            )
        for rp in (3, 4, 5, 6, 8, 10):
            th, _, _ = calibrate_zone_legs(z, cal_ms[z], len(have) / rp)
            sens.append(
                dict(zone=z, rp=rp, **scores(backtest_zone(z, series[z], th, events[z], cal, cal)))
            )
    s = pd.DataFrame(summary)
    s["calibration"] = f"{season_label(cal[0])}–{season_label(cal[-1])}"
    s.to_csv(OUT / "summary.csv", index=False)
    pd.DataFrame(thr_rows).to_csv(OUT / "thresholds.csv", index=False)
    pd.DataFrame(sens).to_csv(OUT / "rp_sensitivity.csv", index=False)
    window_sensitivity(series, thr_by_zone, events, cal).to_csv(
        OUT / "window_sensitivity.csv", index=False
    )
    pd.set_option("display.width", 220)
    print(
        f"calibration seasons {s.calibration.iloc[0]} (n={n}); window Sep-Feb; RP floor {RP_FLOOR}"
    )
    print(s.drop(columns=["calibration"]).round(1).to_string(index=False))


if __name__ == "__main__":
    main()
