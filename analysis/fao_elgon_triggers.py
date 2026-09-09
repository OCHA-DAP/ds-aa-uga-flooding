"""Backtest of FAO's proposed Mt Elgon flood AAP triggers against the observed record.

FAO Uganda and FAO SWALIM circulated a Mt Elgon Flood Anticipatory Action Plan
(document dated 7 Sep 2026) covering Bududa, Bulambuli, Sironko, Manafwa, Mbale,
Butaleja and Namisindwa — 100,000 households, USD 150k readiness + USD 1.53M activation,
MAM and SOND seasons — with three triggers:

  T1 seasonal   ICPAC forecast ">50% of long-term mean rainfall" for MAM and OND, 30-90 d lead
  T2 immediate  GloFAS >=60% probability of a 5-year return-period flood affecting >1,000
                households, 5 d lead
  T3 landslide  cumulative rainfall >100 mm over 3 days AND soil-moisture saturation >80%,
                1-3 d lead

Only T3 is directly testable from the observed record we hold, and it is the one aimed at
the hazard that kills on these slopes. This script measures, per district and for the
sub-region:

  * how often the 100 mm / 3-day threshold is met (activations per year, per district and
    any-district), 1998-2026 from IMERG;
  * what it catches: recall and precision against the dated impact record, all events and
    major ones (5+ deaths or 5,000+ affected);
  * what the soil-moisture condition changes, using the IMERG antecedent index as a proxy
    at two readings of ">80%" — the 80th percentile of the local record, and a wet-season
    absolute floor. ERA5-Land volumetric soil water will replace the proxy when it lands.

T1 and T2 are assessed qualitatively in the report (see docs/research-notes.md).

Writes outputs/fao_elgon_triggers.csv and outputs/fao_elgon_triggers.png.
Run:  uv run python analysis/fao_elgon_triggers.py
"""

import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import ocha_stratus as stratus
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from analysis.backstop_options import score
from analysis.exposure_vs_impact import dated_events_df
from analysis.flash_flood_antecedent import api_index, pctl
from src.constants import PROJECT_PREFIX
from src.skill_chain import rolling_sum
from src.zones import load_adm2

OUT = Path(__file__).resolve().parent.parent / "outputs"
FAO_DISTRICTS = ("Bududa", "Bulambuli", "Sironko", "Manafwa", "Mbale", "Butaleja", "Namisindwa")
RAIN_MM = 100.0  # FAO's cumulative 3-day threshold
ANTE_PCTL = 80.0  # ">80% soil moisture saturation" read as the 80th percentile of the local record
RED, INK, INK2 = "#e34948", "#0b0b0b", "#52514e"


def main() -> None:
    adm = load_adm2().set_index("ADM2_EN").ADM2_PCODE
    im = stratus.load_parquet_from_blob(
        f"{PROJECT_PREFIX}/processed/imerg/imerg_adm2_daily.parquet", stage="dev"
    )
    pc = {d: adm[d] for d in FAO_DISTRICTS}

    # Two readings of "cumulative rainfall": the district MEAN (an areal average, what a
    # zone-scale product reports) and the district's WETTEST PIXEL (closer to what a rain
    # gauge on the slope would record). FAO's document does not say which it intends, and
    # the answer differs by an order of magnitude, so both are measured.
    rain, rain_max, ante = {}, {}, {}
    for d, p in pc.items():
        sub = im[im.pcode == p].set_index("date").sort_index()
        s, smax = sub["mean"].asfreq("D"), sub["max"].asfreq("D")
        rain[d] = rolling_sum(s, 3)
        rain_max[d] = rolling_sum(smax, 3)
        ante[d] = pctl(api_index(s).shift(3))
    rain, rain_max, ante = pd.DataFrame(rain), pd.DataFrame(rain_max), pd.DataFrame(ante)
    years = rain.index.year.nunique()

    ev = dated_events_df(FAO_DISTRICTS)
    major = ev[(ev.deaths.fillna(0) >= 5) | (ev.affected.fillna(0) >= 5000)]
    esets = {"all": pd.DatetimeIndex(ev.day), "major": pd.DatetimeIndex(major.day)}

    rows = []
    for d in FAO_DISTRICTS:
        for lbl, df in (("district mean", rain), ("wettest pixel", rain_max)):
            hits = (df[d] >= RAIN_MM).fillna(False)
            rows.append(
                dict(
                    scope=d,
                    rule=f"rain>=100mm/3d ({lbl})",
                    n_days=int(hits.sum()),
                    per_year=hits.sum() / years,
                    max_3d=float(df[d].max()),
                )
            )
    any_rain = (rain >= RAIN_MM).any(axis=1).fillna(False)
    any_rain_px = (rain_max >= RAIN_MM).any(axis=1).fillna(False)
    any_both = ((rain >= RAIN_MM) & (ante >= ANTE_PCTL)).any(axis=1).fillna(False)
    any_both_px = ((rain_max >= RAIN_MM) & (ante >= ANTE_PCTL)).any(axis=1).fillna(False)
    for name, act in (
        ("T3, district mean", any_rain),
        ("T3, district mean + antecedent >= 80th pctl", any_both),
        ("T3, wettest pixel", any_rain_px),
        ("T3, wettest pixel + antecedent >= 80th pctl", any_both_px),
    ):
        for eset, evs in esets.items():
            rows.append(
                dict(
                    scope="any of the 7 districts",
                    rule=name,
                    events=eset,
                    n_days=int(act.sum()),
                    per_year=act.sum() / years,
                    **score(act, evs),
                )
            )
    tab = pd.DataFrame(rows)
    tab.to_csv(OUT / "fao_elgon_triggers.csv", index=False)
    pd.set_option("display.width", 220)
    print("Per-district frequency of FAO's 100 mm / 3-day threshold (IMERG, 1998-2026):")
    print(
        tab[tab.scope != "any of the 7 districts"][
            ["scope", "rule", "n_days", "per_year", "max_3d"]
        ]
        .round(2)
        .to_string(index=False)
    )
    print("\nSub-region rule performance:")
    print(
        tab[tab.scope == "any of the 7 districts"][
            ["rule", "events", "n_events", "n_days", "per_year", "recall", "precision"]
        ]
        .round(2)
        .to_string(index=False)
    )

    # what threshold WOULD give a usable activation rate, for comparison
    for lbl, df in (("district mean", rain), ("wettest pixel", rain_max)):
        print(f"\nAny-district 3-day rainfall thresholds, {lbl}:")
        for thr in (40, 50, 60, 70, 80, 100, 130, 160):
            a = (df >= thr).any(axis=1).fillna(False)
            sm = score(a, esets["major"])
            print(
                f"  >={thr:3d} mm: {a.sum() / years:5.1f} activations/yr, "
                f"major-event recall {sm['recall']:.0%}, precision {sm['precision']:.0%}"
            )

    fig, (ax, ax2) = plt.subplots(1, 2, figsize=(14, 5.2), gridspec_kw={"width_ratios": [1.1, 1]})
    ax.hist(
        rain.max(axis=1).dropna(),
        bins=np.arange(0, 320, 5),
        color=RED,
        alpha=0.85,
        label="district mean",
    )
    ax.hist(
        rain_max.max(axis=1).dropna(),
        bins=np.arange(0, 320, 5),
        color=INK2,
        alpha=0.45,
        label="wettest pixel",
    )
    ax.legend(fontsize=8, frameon=False)
    ax.axvline(RAIN_MM, color=INK, lw=2)
    ax.annotate(
        f"FAO threshold {RAIN_MM:.0f} mm\n{any_rain.sum()} days in {years} years\n({any_rain.sum() / years:.1f}/yr)",
        (RAIN_MM, ax.get_ylim()[1] * 0.55),
        xytext=(14, 0),
        textcoords="offset points",
        fontsize=9,
        arrowprops={"arrowstyle": "-", "color": INK},
    )
    ax.set_yscale("log")
    ax.set_xlabel("wettest district's 3-day rainfall, mm (IMERG)")
    ax.set_ylabel("days (log)")
    ax.set_title(
        "Where FAO's 100 mm / 3-day threshold sits in the record",
        fontsize=11,
        fontweight="bold",
        loc="left",
    )
    ax.spines[["top", "right"]].set_visible(False)

    thrs = np.arange(30, 205, 5)
    rec = [score((rain >= t).any(axis=1).fillna(False), esets["major"])["recall"] for t in thrs]
    rec_px = [
        score((rain_max >= t).any(axis=1).fillna(False), esets["major"])["recall"] for t in thrs
    ]
    acts = [(rain >= t).any(axis=1).fillna(False).sum() / years for t in thrs]
    ax2.plot(thrs, rec, color=RED, lw=2, marker="o", ms=3, label="recall, district mean")
    ax2.plot(thrs, rec_px, color=INK2, lw=2, ls=":", label="recall, wettest pixel")
    ax2.set_xlabel("3-day rainfall threshold, mm (any of the 7 districts)")
    ax2.set_ylabel("share of major events caught")
    ax2.axvline(RAIN_MM, color=INK, lw=2)
    ax3 = ax2.twinx()
    ax3.plot(thrs, acts, color=INK2, lw=1.4, ls="--", label="activations per year")
    ax3.set_ylabel("activations per year")
    ax2.set_title(
        "The trade-off FAO's threshold implies", fontsize=11, fontweight="bold", loc="left"
    )
    ax2.spines[["top"]].set_visible(False)
    ax3.spines[["top"]].set_visible(False)
    h1, l1 = ax2.get_legend_handles_labels()
    h2, l2 = ax3.get_legend_handles_labels()
    ax2.legend(h1 + h2, l1 + l2, fontsize=8, frameon=False, loc="upper right")
    fig.suptitle(
        "FAO Mt Elgon flood AAP, Trigger 3 (rainfall >100 mm / 3 days) against the observed record, 1998-2026",
        fontsize=12,
        fontweight="bold",
        x=0.02,
        ha="left",
    )
    fig.tight_layout(rect=(0, 0, 1, 0.93))
    fig.savefig(OUT / "fao_elgon_triggers.png", dpi=150, facecolor="white")
    print("wrote", OUT / "fao_elgon_triggers.png")


if __name__ == "__main__":
    main()
