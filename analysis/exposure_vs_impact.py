"""Flood-exposed population vs the impact record — timeseries by zone, and is it a better witness than extent?

Extent answers "is there water"; exposure answers "is there water where people are", which
is what an observational trigger should key on. This repeats the FloodScan validation on
exposure (population under water, WorldPop 2020 x SFED, from build_floodscan_exposure.py)
and compares it with the extent result:

  * timeseries per zone, tier 1 and tier 2, with the dated impact events marked;
  * per tier: AUC of the annual maximum in impact vs non-impact years, and the median
    percentile of the event window, computed identically for extent and exposure so the
    two are directly comparable.

Writes outputs/exposure_timeseries.png, outputs/exposure_vs_extent.csv.
Run:  uv run python analysis/exposure_vs_impact.py
"""

import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import ocha_stratus as stratus
import pandas as pd
from matplotlib.lines import Line2D

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from analysis.floodscan_vs_impact import auc
from src.constants import PROJECT_PREFIX, ZONES
from src.datasources import desinventar as di
from src.datasources import impact
from src.skill_chain import annual_max
from src.zones import load_adm2

OUT = Path(__file__).resolve().parent.parent / "outputs"
ZONE_COL = {
    "teso_kyoga": "#2a78d6",
    "elgon": "#e34948",
    "karamoja": "#eda100",
    "adjumani": "#4a3aa7",
}
INK, INK2 = "#0b0b0b", "#52514e"
YEARS = range(1998, 2026)


def tier_districts() -> list[tuple[str, str, tuple[str, ...]]]:
    out = []
    for k, z in ZONES.items():
        out.append((k, "tier 1", z.core))
        if z.tier2:
            out.append((k, "tier 2", z.tier2))
    return out


def dated_events_df(districts) -> pd.DataFrame:
    """Day-dated impact events in these districts, with severity (DesInventar + EM-DAT + curated).

    One row per day: the worst deaths / affected reported that day across the districts.
    """
    d = di.load_datacards()
    d = d[d.district.isin(districts) & (d.date_precision == "day") & (d.date >= "1998-01-01")]
    # DesInventar already has a `day` column (day-of-month), so build explicitly
    a = pd.DataFrame(
        {"day": d.date.to_numpy(), "deaths": d.deaths.to_numpy(), "affected": d.affected.to_numpy()}
    )
    ev = impact.events_by_district(include_dtm=False)
    ev = ev[
        ev.district.isin(districts)
        & (ev.start >= "1998-01-01")
        & ((ev.end - ev.start).dt.days <= 14)
    ]
    b = pd.DataFrame(
        {
            "day": ev.start.to_numpy(),
            "deaths": ev.deaths.to_numpy(),
            "affected": ev.affected.to_numpy(),
        }
    )
    out = pd.concat([a, b], ignore_index=True)
    out["day"] = out.day.dt.normalize()
    return out.groupby("day").max(numeric_only=True).reset_index()


def dated_events(districts) -> pd.DatetimeIndex:
    return pd.DatetimeIndex(dated_events_df(districts).day)


def main() -> None:
    adm = load_adm2().set_index("ADM2_EN").ADM2_PCODE
    exp = stratus.load_parquet_from_blob(
        f"{PROJECT_PREFIX}/processed/exposure/floodscan_exposure_adm2_daily.parquet", stage="dev"
    )
    ext = stratus.load_parquet_from_blob(
        f"{PROJECT_PREFIX}/processed/floodscan/floodscan_adm2_daily.parquet", stage="dev"
    )
    t = pd.read_csv(OUT / "impact_district_year.csv")

    rows, series = [], {}
    for key, tier, ds in tier_districts():
        pc = [adm[d] for d in ds if d in adm.index]
        s_exp = exp[exp.pcode.isin(pc)].groupby("date").exposure.sum().asfreq("D")
        s_ext = ext[ext.pcode.isin(pc)].groupby("date")["mean"].mean().asfreq("D")
        series[(key, tier)] = s_exp
        evd = dated_events(ds)
        ty = t[t.district.isin(ds)].astype({"year": int}).groupby("year").any_record.any()
        row = {
            "zone": key,
            "tier": tier,
            "districts": len(pc),
            "n_events": len(evd),
            "peak_exposure": float(s_exp.max()),
            "median_exposure": float(s_exp.median()),
        }
        for name, s in (("extent", s_ext), ("exposure", s_exp)):
            am = annual_max(s).reindex(list(YEARS))
            mask = ty.reindex(am.index).fillna(False).to_numpy(dtype=bool)
            pos, neg = am.to_numpy()[mask], am.to_numpy()[~mask]
            pos, neg = pos[np.isfinite(pos)], neg[np.isfinite(neg)]
            row[f"auc_{name}"] = auc(pos, neg)
            pct = []
            for d0 in evd:
                win = s.loc[d0 - pd.Timedelta(days=3) : d0 + pd.Timedelta(days=7)].dropna()
                if len(win):
                    pct.append(float((s.dropna() < win.max()).mean() * 100))
            row[f"event_pctl_{name}"] = float(np.median(pct)) if pct else np.nan
        rows.append(row)
    tab = pd.DataFrame(rows)
    tab.to_csv(OUT / "exposure_vs_extent.csv", index=False)
    pd.set_option("display.width", 200)
    print(tab.round(2).to_string(index=False))
    print(
        "\nAUC improves with exposure in",
        int((tab.auc_exposure > tab.auc_extent).sum()),
        "of",
        len(tab),
        "tiers;",
        "event percentile improves in",
        int((tab.event_pctl_exposure > tab.event_pctl_extent).sum()),
    )

    fig, axes = plt.subplots(len(ZONES), 1, figsize=(14, 11), sharex=True)
    for ax, (key, z) in zip(axes, ZONES.items(), strict=True):
        for tier, ls in (("tier 1", "-"), ("tier 2", (0, (3, 1.5)))):
            s = series.get((key, tier))
            if s is None:
                continue
            ax.plot(
                s.index,
                s.values / 1000,
                color=ZONE_COL[key],
                lw=0.7,
                ls=ls,
                label=f"{tier} ({', '.join(ZONES[key].core if tier == 'tier 1' else ZONES[key].tier2)[:60]}…)"
                if False
                else tier,
            )
        ds_all = ZONES[key].core + ZONES[key].tier2
        for d0 in dated_events(ds_all):
            ax.axvline(d0, color=INK, alpha=0.10, lw=0.8, zorder=0)
        ax.set_ylabel(f"{z.label.split(' (')[0]}\nthousand people", fontsize=9)
        ax.legend(fontsize=7.5, frameon=False, loc="upper left", ncol=2)
        ax.grid(alpha=0.25)
        ax.spines[["top", "right"]].set_visible(False)
    axes[-1].set_xlim(pd.Timestamp("1998-01-01"), pd.Timestamp("2026-09-01"))
    handles = [Line2D([], [], color=INK, alpha=0.3, lw=1.5, label="dated impact event in the zone")]
    axes[0].legend(
        handles=axes[0].get_legend_handles_labels()[0] + handles,
        fontsize=7.5,
        frameon=False,
        loc="upper left",
        ncol=3,
    )
    fig.suptitle(
        "Flood-exposed population by zone, 1998–2026 (FloodScan SFED × WorldPop), against the dated impact record",
        fontsize=13,
        fontweight="bold",
        x=0.02,
        ha="left",
    )
    fig.text(
        0.02,
        0.955,
        "Daily population living under water in each tier's districts. Grey lines mark days with a recorded flood or landslide "
        "impact anywhere in the zone (DesInventar, EM-DAT, curated).",
        fontsize=9,
        color=INK2,
        ha="left",
    )
    fig.tight_layout(rect=(0, 0, 1, 0.94))
    fig.savefig(OUT / "exposure_timeseries.png", dpi=150, facecolor="white")
    print("wrote", OUT / "exposure_timeseries.png")


if __name__ == "__main__":
    main()
