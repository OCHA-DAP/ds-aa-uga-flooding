"""FloodScan observed-flood fallback for every zone, and Karamoja's rain-or-FloodScan choice.

Part A — the fallback. The country team asked for an observed-flood backstop everywhere, so that
a forecast miss can still release money. For each zone it is designed exactly like the forecast
drafts in trigger_draft.py (Oct-Dec window, frequency RP floored at 1-in-3, then raised to shed
false alarms until a big catch would be lost), on FloodScan SFED flood extent in the zone
districts where FloodScan is usable on rank-based evidence (analysis/floodscan_vs_impact.py:
events beat the window chance rate by >= 0.10, >= 3 dated events, not flat). Every district is
held to the same rarity on its own record — the threshold is a percentile of each district's
own series, never an absolute extent. An observed-flood activation "catches" an event it sees
during the flood or up to 10 days after it ends (leg "obs" in trigger_draft).

Then the fallback is laid over the forecast draft: per season, did either activate, and which
major seasons does the fallback add that the forecast missed — at the cost of how many extra
false alarms.

Part B — Karamoja, one indicator per district. For each Karamoja district, rank-based evidence
for the 5-day rainfall FORECAST (CHIRPS-GEFS) and for observed FloodScan extent, scored the same
way (share of the district's dated events reaching its own top fifth, minus the chance that an
arbitrary window of the same length does). Four zone triggers, each calibrated with the zone
rule: rain in every district (the current draft), FloodScan where usable, per-district choice
(the better-evidenced indicator), and both (rain OR FloodScan where FloodScan is usable).
Thresholds are NOT tuned per district: with 1-3 dated OND events per district, a per-district
optimum would fit noise. Every series is held to one common rarity; only which indicator a
district uses is chosen, and that on all-season evidence (more events than Oct-Dec alone).

Outputs (outputs/triggers/):
  fallback_summary.csv          per zone: the fallback's scores alone and combined with the draft
  fallback_{zone}.csv           per season: forecast and fallback activation, catch, outcome
  fallback_thresholds.csv       per district FloodScan threshold (extent share) and its RP
  karamoja_indicator_choice.csv per district: evidence for rain forecast vs FloodScan
  karamoja_variants.csv         the four Karamoja designs side by side

Run:  uv run python analysis/floodscan_fallback.py     (after trigger_draft.py, floodscan_vs_impact.py)
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import ocha_stratus as stratus
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from trigger_draft import (
    CAL_LAST_SEASON,
    FIRST_SEASON,
    LEAD_DAYS,
    RP_FLOOR,
    backtest_zone,
    calibrate_zone_legs,
    raise_threshold,
    scores,
    season_impact,
    season_max,
    zone_events,
    zone_series,
)

from src.constants import PROJECT_PREFIX, ZONES
from src.datasources import desinventar as di
from src.datasources import impact
from src.zones import load_adm2

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "outputs" / "triggers"
USABILITY = ROOT / "outputs" / "floodscan_vs_impact_district.csv"
TOP = 0.80  # "reaches the district's own top fifth"
MIN_LIFT = 0.10  # as in floodscan_vs_impact.py
MIN_EVENTS = 3
# event windows, in days relative to the event [start - before, end + after]:
# FloodScan sees the water during and after the flood; a 5-day forecast is issued before it
WINDOW = {"floodscan": (3, 7), "rain": (7, 1)}


def floodscan_daily() -> pd.DataFrame:
    fs = stratus.load_parquet_from_blob(
        f"{PROJECT_PREFIX}/processed/floodscan/floodscan_adm2_daily.parquet", stage="dev"
    )
    return fs.pivot_table(index="date", columns="pcode", values="mean").sort_index()


def usable_districts(z: str) -> list[str]:
    u = pd.read_csv(USABILITY)
    ok = set(u[u.usable].district)
    return [d for d in ZONES[z].all_districts if d in ok]


def fs_series(fs: pd.DataFrame, adm: pd.Series, districts: list[str]) -> dict[str, pd.Series]:
    return {f"FloodScan {d}": fs[adm[d]].dropna() for d in districts if adm[d] in fs}


def design(z: str, series: dict[str, pd.Series], ev: pd.DataFrame, cal: list[int]):
    """The zone rule of trigger_draft.main(), on any set of series."""
    sms = {k: season_max(s) for k, s in series.items()}
    cal_ms = {k: a.reindex(cal) for k, a in sms.items()}
    have = [y for y in cal if any(pd.notna(a.get(y)) for a in cal_ms.values())]
    n_major = sum(season_impact(ev, y)["major"] for y in have)
    design_rp = max(RP_FLOOR, (len(have) + 1) / max(1, n_major))
    final_rp, _ = raise_threshold(z, series, cal_ms, ev, cal, design_rp)
    thr, _, _ = calibrate_zone_legs(z, cal_ms, len(have) / final_rp)
    # an extent threshold at or below zero would activate on every dry day
    for k in thr:
        if k.startswith("FloodScan"):
            pos = series[k][series[k] > 0]
            thr[k] = max(thr[k], float(pos.min()) if len(pos) else np.inf)
    t = backtest_zone(z, series, thr, ev, list(range(FIRST_SEASON, 2026)), cal)
    return thr, final_rp, design_rp, t


# --- Part B helpers: rank-based evidence per district --------------------------------------


def dated_events(district: str) -> pd.DataFrame:
    """Day-dated events in one district (any month): EM-DAT/curated/press and DesInventar cards."""
    ev = impact.events_by_district(include_dtm=False)
    ev = ev[(ev.district == district) & ((ev.end - ev.start).dt.days <= 14)]
    ev = ev[ev.date_precision.fillna("day") == "day"]
    d = di.load_datacards()
    d = d[(d.district == district) & (d.date_precision == "day")]
    out = pd.concat(
        [
            ev[["start", "end"]],
            d.assign(start=d.date.dt.normalize(), end=d.date.dt.normalize())[["start", "end"]],
        ],
        ignore_index=True,
    ).drop_duplicates()
    return out[out.start >= "1998-01-01"]


def evidence(s: pd.Series, events: pd.DataFrame, before: int, after: int) -> dict:
    s = s.dropna().sort_index()
    if s.empty or events.empty:
        return dict(n_events=0, top_share=np.nan, chance=np.nan, lift=np.nan)
    r = s.rank(pct=True)  # midrank percentiles: ties (zero days) share one rank
    hits = []
    for _, e in events.iterrows():
        w = r.loc[e.start - pd.Timedelta(days=before) : e.end + pd.Timedelta(days=after)]
        if len(w):
            hits.append(bool(w.max() >= TOP))
    # chance: an arbitrary window of the same shape, measured on the record itself
    fwd = r[::-1].rolling(after + 1, min_periods=1).max()[::-1]
    back = r.rolling(before + 1, min_periods=1).max()
    chance = float((pd.concat([fwd, back], axis=1).max(axis=1) >= TOP).mean())
    top = float(np.mean(hits)) if hits else np.nan
    return dict(n_events=len(hits), top_share=top, chance=chance, lift=top - chance)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    cal = list(range(FIRST_SEASON, CAL_LAST_SEASON + 1))
    adm = load_adm2().set_index("ADM2_EN").ADM2_PCODE
    fs = floodscan_daily()
    drafts = zone_series()
    events = {z: zone_events(z) for z in ZONES}

    # --- Part A: fallback per zone ---
    summary, thr_rows = [], []
    for z in ZONES:
        ev = events[z]
        dists = usable_districts(z)
        draft = pd.read_csv(OUT / f"{z}.csv").set_index("season")
        if not dists:
            summary.append(
                dict(zone=z, districts="", note="no zone district passes the FloodScan check")
            )
            print(f"{z}: no usable FloodScan district — no fallback")
            continue
        series = fs_series(fs, adm, dists)
        thr, rp, rp0, t = design(z, series, ev, cal)
        for k, v in thr.items():
            thr_rows.append(
                dict(zone=z, district=k.removeprefix("FloodScan "), extent_share=v, zone_rp=rp)
            )
        both = draft[["label", "in_calibration", "activated", "caught", "major", "outcome"]].join(
            t[["activated", "first_date", "via", "caught", "outcome"]], rsuffix="_fs"
        )
        both["activated_any"] = both.activated | both.activated_fs
        both["caught_any"] = both.caught | both.caught_fs
        both["added_catch"] = both.caught_fs & ~both.caught
        both["added_false_alarm"] = both.activated_fs & ~both.activated & ~both.caught_fs
        both.sort_index(ascending=False).to_csv(OUT / f"fallback_{z}.csv")
        c = both[both.in_calibration]
        sc = scores(t)
        summary.append(
            dict(
                zone=z,
                districts=";".join(dists),
                frequency_rp=rp0,
                design_rp=rp,
                fs_activations=sc["activations"],
                fs_caught=sc["caught"],
                fs_false_alarms=sc["false_alarms"],
                major_seasons=sc["major_seasons"],
                draft_activations=int(c.activated.sum()),
                draft_caught=int(c.caught.sum()),
                combined_activations=int(c.activated_any.sum()),
                combined_caught=int(c.caught_any.sum()),
                combined_rp=(len(c) + 1) / max(1, int(c.activated_any.sum())),
                added_catches=", ".join(c[c.added_catch].label),
                added_false_alarms=", ".join(c[c.added_false_alarm].label),
                fs_activated=", ".join(c[c.activated_fs].label),
            )
        )
    pd.DataFrame(summary).to_csv(OUT / "fallback_summary.csv", index=False)
    pd.DataFrame(thr_rows).to_csv(OUT / "fallback_thresholds.csv", index=False)
    pd.set_option("display.width", 250)
    print(pd.DataFrame(summary).round(1).to_string(index=False))

    # --- Part B: Karamoja, rain forecast or FloodScan per district ---
    z = "karamoja"
    rain = drafts[z]  # district -> 5-day forecast series (issue date)
    usable = set(usable_districts(z))
    rows = []
    for d in ZONES[z].core:
        e = dated_events(d)
        r = evidence(rain[d], e, *WINDOW["rain"]) if d in rain else {}
        f = evidence(fs[adm[d]], e, *WINDOW["floodscan"]) if adm[d] in fs else {}
        rain_ok = r.get("n_events", 0) >= MIN_EVENTS and r.get("lift", -1) >= MIN_LIFT
        fs_ok = d in usable
        choice = (
            "rain"
            if rain_ok and (not fs_ok or r["lift"] >= f.get("lift", -1))
            else "floodscan"
            if fs_ok
            else "rain (no evidence either way)"
        )
        rows.append(
            dict(
                district=d,
                n_events=r.get("n_events", 0),
                rain_top_share=r.get("top_share"),
                rain_chance=r.get("chance"),
                rain_lift=r.get("lift"),
                fs_top_share=f.get("top_share"),
                fs_chance=f.get("chance"),
                fs_lift=f.get("lift"),
                fs_usable=fs_ok,
                choice=choice,
            )
        )
    ch = pd.DataFrame(rows)
    ch.to_csv(OUT / "karamoja_indicator_choice.csv", index=False)
    print("\nKaramoja indicator evidence (all-season dated events):")
    print(ch.round(2).to_string(index=False))

    fsz = fs_series(fs, adm, sorted(usable))
    pick = {
        r.district: (
            {r.district: rain[r.district]}
            if r.choice.startswith("rain")
            else {f"FloodScan {r.district}": fsz[f"FloodScan {r.district}"]}
        )
        for r in ch.itertuples()
    }
    variants = {
        "rain forecast, every district (current draft)": rain,
        "FloodScan where usable": fsz,
        "per-district choice": {k: v for p in pick.values() for k, v in p.items()},
        "both where FloodScan is usable": rain | fsz,
    }
    vrows = []
    for name, series in variants.items():
        thr, rp, rp0, t = design(z, series, events[z], cal)
        sc = scores(t)
        c = t[t.in_calibration & t.data]
        vrows.append(
            dict(
                variant=name,
                series=len(series),
                frequency_rp=rp0,
                design_rp=rp,
                activations=sc["activations"],
                caught=sc["caught"],
                false_alarms=sc["false_alarms"],
                missed=sc["missed"],
                major_seasons=sc["major_seasons"],
                activated=", ".join(c[c.activated].label),
                caught_seasons=", ".join(c[c.caught].label),
                via=", ".join(
                    f"{lab}: {v}"
                    for lab, v in zip(c[c.activated].label, c[c.activated].via, strict=True)
                ),
            )
        )
    v = pd.DataFrame(vrows)
    v.to_csv(OUT / "karamoja_variants.csv", index=False)
    print("\nKaramoja designs (zone rule applied to each):")
    print(v.drop(columns="via").round(1).to_string(index=False))
    print(f"(lead windows: {LEAD_DAYS})")


if __name__ == "__main__":
    main()
