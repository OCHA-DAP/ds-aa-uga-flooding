"""Adjumani: could a trigger have caught Oct-Nov 2023?

OND 2023 was a major season in the zone (Adjumani 2-7 Nov, 5,639 affected; Madi Okollo
5 Nov - 3 Dec, 10,281; IOM DTM counts for Moyo and Obongi over Oct-Nov) and the draft did not
activate. Nothing was extreme that season: each district's 5-day rain forecast peaked at 1-in-3
to 1-in-9 and Lake Kyoga's 180-day rise at about 1-in-6, against draft bars of about 1-in-30 per
series. What was unusual is that several moderate things happened at once. Options tested, each
on the same seasons and events as the draft:

  lower rain bar   any district at 1-in-R (the draft's rain leg, just lower)
  spatial          at least n districts at 1-in-R within the same 5 days
  compound         Lake Kyoga's rise at 1-in-L AND any district's rain at 1-in-R, the same day —
                   the Nile high (backwater) and local rain on top, the combination that floods
                   the Albert Nile banks

All return periods are on each series' own Oct-Dec maxima (Gumbel), as in trigger_draft.

Writes outputs/triggers/adjumani_options.csv (headline options) and adjumani_compound_grid.csv.
Run:  uv run python analysis/adjumani_options.py      (after trigger_draft.py)
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from trigger_draft import (
    CAL_LAST_SEASON,
    FIRST_SEASON,
    OUT,
    gumbel_fit,
    gumbel_rp,
    in_season,
    match,
    season_bounds,
    season_impact,
    season_label,
    season_max,
    zone_events,
    zone_series,
)

Z = "adjumani"
LAKE = "Kyoga rise"


def rp_frame(series: dict[str, pd.Series], cal: list[int]) -> pd.DataFrame:
    out = {}
    for k, s in series.items():
        f = gumbel_fit(season_max(s).reindex(cal).dropna())
        x = in_season(s)
        out[k] = pd.Series(gumbel_rp(x, *f), index=x.index)
    return pd.concat(out, axis=1)


def run(cond: pd.Series, leg: pd.Series | str, ev: pd.DataFrame, cal: list[int]) -> dict:
    """First in-window activation per season, matched to events on its leg."""
    acts, caught = {}, {}
    for y in cal:
        lo, hi = season_bounds(y)
        x = cond[(cond.index >= lo) & (cond.index <= hi)]
        if not x.any():
            continue
        d0 = x[x].index[0]
        lg = leg if isinstance(leg, str) else leg.loc[d0]
        acts[y] = d0
        caught[y] = bool(len(match(d0, lg, ev)))
    hit = sorted(y for y in acts if caught[y])
    return dict(
        activations=len(acts),
        rp=(len(cal) + 1) / max(1, len(acts)),
        caught=len(hit),
        false_alarms=len(acts) - len(hit),
        caught_seasons=", ".join(season_label(y) for y in sorted(hit, reverse=True)),
        false_alarm_seasons=", ".join(
            season_label(y) for y in sorted(set(acts) - set(hit), reverse=True)
        ),
        catches_2023=bool(caught.get(2023)),
        first_2023=acts[2023].date().isoformat() if 2023 in acts else "",
    )


def main() -> None:
    cal = list(range(FIRST_SEASON, CAL_LAST_SEASON + 1))
    series = zone_series()[Z]
    ev = zone_events(Z)
    rp = rp_frame(series, cal)
    lake = rp[LAKE].reindex(rp.index).ffill()
    rain = rp.drop(columns=LAKE)
    thr = pd.read_csv(OUT / "thresholds.csv").query("zone == @Z")
    lake_bar = float(thr[thr.series == LAKE].series_rp.iloc[0])
    rain_bar = float(thr[thr.leg == "rain"].series_rp.iloc[0])
    majors = [y for y in cal if season_impact(ev, y)["major"]]

    def either(rain_cond: pd.Series) -> tuple[pd.Series, pd.Series]:
        lake_cond = lake >= lake_bar
        cond = lake_cond | rain_cond
        return cond, pd.Series("rain", index=cond.index).where(~lake_cond, "lake")

    opts = {}
    draft = f"draft (lake 1-in-{lake_bar:.0f} or any district rain 1-in-{rain_bar:.0f})"
    opts[draft] = either((rain >= rain_bar).any(axis=1))
    for r in (12, 9):
        opts[f"lower rain bar: lake leg, or any district rain 1-in-{r}"] = either(
            (rain >= r).any(axis=1)
        )
    for n, r in ((3, 4), (2, 5)):
        win = (rain >= r).rolling(5, min_periods=1).max().sum(axis=1) >= n
        opts[f"spatial: lake leg, or {n}+ districts at 1-in-{r} within 5 days"] = either(win)
    # the review's point (30 Sep): the compound rule is close to a lake gate, so show the gate alone
    for lk in (6.5, 5):
        opts[f"lake leg alone at 1-in-{lk:g} (no rain leg)"] = (lake >= lk, "lake")
    for lk, r in ((5, 3), (4, 3)):
        c = (lake >= lk) & (rain >= r).any(axis=1)
        opts[f"compound: lake rise 1-in-{lk} AND any district rain 1-in-{r}, same day"] = (
            c,
            "rain",
        )
    rows = [dict(option=k, **run(c, leg, ev, cal)) for k, (c, leg) in opts.items()]
    o = pd.DataFrame(rows)
    o["major_seasons"] = ", ".join(season_label(y) for y in sorted(majors, reverse=True))
    o.to_csv(OUT / "adjumani_options.csv", index=False)

    grid = []
    for lk in (2, 3, 4, 5, 6, 8):
        for r in (2, 3, 4, 5, 6):
            c = (lake >= lk) & (rain >= r).any(axis=1)
            grid.append(dict(lake_rp=lk, rain_rp=r, **run(c, "rain", ev, cal)))
    pd.DataFrame(grid).to_csv(OUT / "adjumani_compound_grid.csv", index=False)

    peaks = rp.groupby([s for s in rp.index.map(lambda t: t.year)]).max()
    pd.set_option("display.width", 250)
    print("OND 2023 peaks (RP on own OND maxima):", peaks.loc[2023].round(1).to_dict())
    print("major seasons:", majors)
    print(o.drop(columns="major_seasons").round(1).to_string(index=False))
    g = pd.DataFrame(grid)
    print(
        g.pivot(index="lake_rp", columns="rain_rp", values="caught").astype(str)
        + "/"
        + g.pivot(index="lake_rp", columns="rain_rp", values="activations").astype(str)
    )


if __name__ == "__main__":
    main()
