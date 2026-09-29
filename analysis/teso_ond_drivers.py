"""What drives October-December flooding in Teso, and could anything anticipate it?

The G5196 GloFAS trigger has no anticipatory skill in an Oct-Dec window: the Akokoro peaks in
August-September and every activation lands on 1 October with the river already high. The
October-December records in the Teso zone are mostly typed RAINS or rainstorm rather than
riverine flooding, in the flat Katakwi and Amuria plains - which points to pluvial waterlogging:
second-season rain on ground still saturated from the first.

This script scores candidate indicators, season by season 2000-2024, on how well they separate
windows with a recorded Oct-Dec flood start in the zone from windows without one. Scores are
rank-based (AUC: the chance a flood window ranks above a quiet one; 0.5 is no skill), because
the question is which indicator to set a local threshold on, not the absolute values. With
five to eight flood windows in 25 the AUCs are noisy; treat differences under ~0.1 as ties.

  uv run python analysis/teso_ond_drivers.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import trigger_draft as td
from flash_flood_antecedent import api_index

from src.constants import ZONES
from src.zones import load_adm2

OUT = Path(__file__).resolve().parent.parent / "outputs" / "triggers"
SEASONS = list(range(2000, 2025))


def auc(pos, neg) -> float:
    pos, neg = np.asarray(pos, float), np.asarray(neg, float)
    pos, neg = pos[~np.isnan(pos)], neg[~np.isnan(neg)]
    if not len(pos) or not len(neg):
        return float("nan")
    gt = (pos[:, None] > neg[None, :]).mean()
    eq = (pos[:, None] == neg[None, :]).mean()
    return float(gt + 0.5 * eq)


def main() -> None:
    adm = load_adm2().set_index("ADM2_EN").ADM2_PCODE
    ds = list(ZONES["teso_kyoga"].core) + list(ZONES["teso_kyoga"].tier2)
    pcs = [adm[d] for d in ds]
    ev = td.zone_events("teso_kyoga")

    # targets: a recorded flood STARTING in the Oct-Dec window (any impact; and major only)
    def starts_in(y, major_only):
        lo, hi = td.season_bounds(y)
        e = ev[(ev.start >= lo) & (ev.start <= hi) & ((ev.affected > 0) | (ev.deaths > 0))]
        return bool(e.major.any()) if major_only else bool(len(e))

    any_flood = pd.Series({y: starts_in(y, False) for y in SEASONS})
    major = pd.Series({y: starts_in(y, True) for y in SEASONS})

    im = td.load("processed/imerg/imerg_adm2_daily.parquet")
    rain = (
        im[im.pcode.isin(pcs)]
        .pivot_table(index="date", columns="pcode", values="mean")
        .mean(axis=1)
    )
    rain.index = pd.to_datetime(rain.index)
    api = api_index(rain)
    cg = td.chirps_gefs_wide(pcs).mean(axis=1)
    fs = td.load("processed/floodscan/floodscan_adm2_daily.parquet")
    ext = (
        fs[fs.pcode.isin(pcs)]
        .pivot_table(index="date", columns="pcode", values="mean")
        .mean(axis=1)
    )
    ext.index = pd.to_datetime(ext.index)
    q = td.glofas_g5196()
    ll = td.load("processed/gwm/lake_levels.parquet")
    ky = (
        ll[ll.lake == "kyoga"]
        .set_index("date")
        .height_m.sort_index()
        .resample("D")
        .mean()
        .interpolate(limit=40)
    )

    def window(s, y, lo_md=(10, 1), hi_md=(12, 31)):
        return s[(s.index >= pd.Timestamp(y, *lo_md)) & (s.index <= pd.Timestamp(y, *hi_md))]

    ind = {}
    ind["forecast 5-day rain, OND max (CHIRPS-GEFS)"] = {y: window(cg, y).max() for y in SEASONS}
    ind["observed 30-day rain, OND max (IMERG)"] = {
        y: window(rain.rolling(30).sum(), y).max() for y in SEASONS
    }
    ind["observed Aug-Sep rain total (wetness at window open)"] = {
        y: window(rain, y, (8, 1), (9, 30)).sum() for y in SEASONS
    }
    ind["antecedent index on 1 Oct (IMERG API)"] = {
        y: api.get(pd.Timestamp(y, 10, 1), np.nan) for y in SEASONS
    }
    ind["antecedent index, OND max"] = {y: window(api, y).max() for y in SEASONS}
    ind["FloodScan extent, OND max (observation)"] = {y: window(ext, y).max() for y in SEASONS}
    ind["FloodScan extent on 1 Oct"] = {y: ext.get(pd.Timestamp(y, 10, 1), np.nan) for y in SEASONS}
    ind["GloFAS G5196 on 1 Oct (river carry-over)"] = {
        y: q.get(pd.Timestamp(y, 10, 1), np.nan) for y in SEASONS
    }
    ind["Lake Kyoga level on 1 Oct"] = {y: ky.get(pd.Timestamp(y, 10, 1), np.nan) for y in SEASONS}
    # compound: forecast rain while the ground is already wet (antecedent above its median)
    wet = api > api.median()
    ind["forecast 5-day rain on wet ground, OND max"] = {
        y: window(cg.where(wet.reindex(cg.index).fillna(False)), y).max() for y in SEASONS
    }

    rows = []
    for name, v in ind.items():
        s = pd.Series(v, dtype=float)
        rows.append(
            dict(
                indicator=name,
                auc_any_flood=auc(s[any_flood], s[~any_flood]),
                auc_major=auc(s[major], s[~major]),
                rank_corr_affected=s.corr(
                    pd.Series(
                        {
                            y: ev[
                                (ev.start >= td.season_bounds(y)[0])
                                & (ev.start <= td.season_bounds(y)[1])
                            ].affected.sum()
                            for y in SEASONS
                        }
                    ),
                    method="spearman",
                ),
            )
        )
    r = pd.DataFrame(rows).sort_values("auc_any_flood", ascending=False)
    r.to_csv(OUT / "teso_ond_drivers.csv", index=False)

    # the practical consequence: decide on 1 October from the state of the landscape
    state = {
        "GloFAS G5196 on 1 Oct": pd.Series(ind["GloFAS G5196 on 1 Oct (river carry-over)"]),
        "FloodScan extent, week to 1 Oct": pd.Series(
            {y: window(ext, y, (9, 24), (10, 1)).mean() for y in SEASONS}
        ),
    }
    flood_y, major_y = set(any_flood[any_flood].index), set(major[major].index)
    trows = []
    for name, sv in state.items():
        sv = sv.dropna().sort_values(ascending=False)
        for k in (5, 7, 8):
            act = set(sv.index[:k])
            trows.append(
                dict(
                    indicator=name,
                    rp=round((len(sv) + 1) / k, 1),
                    activations=k,
                    flood_windows_caught=len(act & flood_y),
                    flood_windows=len(flood_y),
                    majors_caught=len(act & major_y),
                    majors=len(major_y),
                    false_alarms=len(act - flood_y),
                    seasons=", ".join(str(y) for y in sorted(act)),
                )
            )
    pd.DataFrame(trows).to_csv(OUT / "teso_oct1_trigger.csv", index=False)
    pd.set_option("display.width", 200)
    print(f"flood windows (any impact): {sorted(any_flood[any_flood].index)}")
    print(f"major windows:              {sorted(major[major].index)}\n")
    print(r.round(2).to_string(index=False))


if __name__ == "__main__":
    main()
