"""Backtest a partner's draft Mt Elgon flood AAP triggers against the observed record.

The plan is UNPUBLISHED. This repository and its GitHub Pages site are public, so the
partner's thresholds, districts, household target and budget are NOT hardcoded here and no
output of this script is committed. The parameters are read at runtime from

    config/partner_triggers.local.json        (gitignored)

with the shape {"districts": [...], "rain_mm": <float>, "antecedent_pctl": <float>,
"glofas_points": {"<label>": [lat, lon]}}. Without that file the script exits with a message.
Results are printed to the console and written to outputs/, which is gitignored.

What it measures, all against the same record used elsewhere in the repo:

  * how often the partner's cumulative-rainfall threshold is met, per district and for the
    sub-region, at two readings of "cumulative rainfall" — the district MEAN (an areal
    average) and the district's WETTEST PIXEL (closer to a rain gauge). The plan does not say
    which it intends and the answer differs by an order of magnitude;
  * what it catches: recall and precision against the dated impact record, all events and
    major ones (5+ deaths or 5,000+ affected);
  * what the soil-moisture condition changes, using the IMERG antecedent index as a proxy;
  * whether GloFAS at the only reporting points in the sub-region tracks observed flooding
    there at all, judged on correlation rather than Kling-Gupta efficiency.

Run:  uv run python analysis/fao_elgon_triggers.py
"""

import json
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
from src.datasources import glofas
from src.glofas_coverage import lagged_corr
from src.skill_chain import rolling_sum
from src.zones import load_adm2

OUT = Path(__file__).resolve().parent.parent / "outputs"
CONFIG = Path(__file__).resolve().parent.parent / "config" / "partner_triggers.local.json"


def load_config() -> dict:
    """Partner trigger parameters, kept out of this public repo."""
    if not CONFIG.exists():
        print(
            f"No partner trigger config at {CONFIG.relative_to(CONFIG.parents[2])}.\n"
            "The plan it describes is unpublished and this repo is public, so the parameters are "
            "not committed. Create the file (gitignored) to run this analysis; the expected shape "
            "is in the module docstring."
        )
        raise SystemExit(0)
    return json.loads(CONFIG.read_text())


RED, INK, INK2 = "#e34948", "#0b0b0b", "#52514e"


def main() -> None:
    cfg = load_config()
    fao_districts = tuple(cfg["districts"])
    rain_mm = float(cfg["rain_mm"])
    ante_pctl = float(cfg["antecedent_pctl"])
    adm = load_adm2().set_index("ADM2_EN").ADM2_PCODE
    im = stratus.load_parquet_from_blob(
        f"{PROJECT_PREFIX}/processed/imerg/imerg_adm2_daily.parquet", stage="dev"
    )
    pc = {d: adm[d] for d in fao_districts}

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

    ev = dated_events_df(fao_districts)
    major = ev[(ev.deaths.fillna(0) >= 5) | (ev.affected.fillna(0) >= 5000)]
    esets = {"all": pd.DatetimeIndex(ev.day), "major": pd.DatetimeIndex(major.day)}

    rows = []
    for d in fao_districts:
        for lbl, df in (("district mean", rain), ("wettest pixel", rain_max)):
            hits = (df[d] >= rain_mm).fillna(False)
            rows.append(
                dict(
                    scope=d,
                    rule=f"rain>=100mm/3d ({lbl})",
                    n_days=int(hits.sum()),
                    per_year=hits.sum() / years,
                    max_3d=float(df[d].max()),
                )
            )
    any_rain = (rain >= rain_mm).any(axis=1).fillna(False)
    any_rain_px = (rain_max >= rain_mm).any(axis=1).fillna(False)
    any_both = ((rain >= rain_mm) & (ante >= ante_pctl)).any(axis=1).fillna(False)
    any_both_px = ((rain_max >= rain_mm) & (ante >= ante_pctl)).any(axis=1).fillna(False)
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
    print("Per-district frequency of the partner threshold (IMERG, 1998-2026):")
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

    # --- T2: does GloFAS at the only Elgon point track observed flooding there? -----------
    # G5220 Manafwa at Butaleja, LISFLOOD v4 pixel; and the unnamed fixed point on the Mpologoma.
    print(
        "\nT2 check - GloFAS reanalysis vs observed flood extent, correlation at best lag (Aug-Dec anomalies):"
    )
    ex = stratus.load_parquet_from_blob(
        f"{PROJECT_PREFIX}/processed/exposure/floodscan_exposure_adm2_daily.parquet", stage="dev"
    )
    fs = stratus.load_parquet_from_blob(
        f"{PROJECT_PREFIX}/processed/floodscan/floodscan_adm2_daily.parquet", stage="dev"
    )
    for label, (plat, plon) in {
        k: tuple(v) for k, v in cfg.get("glofas_points", {}).items()
    }.items():
        try:
            dis = glofas.load_reanalysis_point(plat, plon).asfreq("D")
        except Exception as err:  # noqa: BLE001 - reanalysis not downloaded is a skip, not a failure
            print(f"  {label}: reanalysis unavailable ({err})")
            continue
        best = []
        for d in fao_districts:
            se = fs[fs.pcode == pc[d]].set_index("date")["mean"].asfreq("D")
            sx = ex[ex.pcode == pc[d]].set_index("date")["exposure"].asfreq("D")
            best.append((d, float(lagged_corr(dis, se).max()), float(lagged_corr(dis, sx).max())))
        print(f"  {label} (mean {dis.mean():.0f} m3/s)")
        for d, ce, cx in sorted(best, key=lambda t: -t[1]):
            print(f"    {d:11s} extent {ce:+.2f}  exposure {cx:+.2f}")
        print(
            f"    -> best of any district: extent {max(b[1] for b in best):.2f}, "
            f"versus 0.49 for Amuria at G5196, the point we do trust"
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
    ax.axvline(rain_mm, color=INK, lw=2)
    ax.annotate(
        f"FAO threshold {rain_mm:.0f} mm\n{any_rain.sum()} days in {years} years\n({any_rain.sum() / years:.1f}/yr)",
        (rain_mm, ax.get_ylim()[1] * 0.55),
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
    ax2.axvline(rain_mm, color=INK, lw=2)
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
