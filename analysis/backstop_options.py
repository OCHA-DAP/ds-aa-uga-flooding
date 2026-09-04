"""Observational backstop options: FloodScan exposure, observed rainfall, or either.

The backstop exists so a forecast miss still activates. FloodScan alone cannot serve the
Elgon slopes, Karamoja or the Albert Nile (floodscan_vs_impact.py). This tests whether
adding an OBSERVED-RAINFALL leg — IMERG rainfall already fallen, not forecast — recovers
those misses, and at what cost in activations.

For each zone tier and each return period, three observational triggers are backtested
against the day-dated impact record:

  A  exposure  — flood-exposed population over its RP level (population-weighted, so it
                 keys on water where people are rather than water anywhere)
  B  rainfall  — observed 3-day district rainfall over its RP level in ANY district of the
                 tier (observed, so no forecast skill is involved — this is a nowcast leg)
  A or B       — either

Reported per option: recall (share of dated events with the trigger active within +/-3 days),
precision (share of activation episodes with an event in that window), and activations per
year. Precision is a floor, not a verdict: the impact record is incomplete, so an
"activation with no event" may be an unrecorded flood.

Writes outputs/backstop_options.csv and outputs/backstop_options.png.
Run:  uv run python analysis/backstop_options.py
"""

import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import ocha_stratus as stratus
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from analysis.exposure_vs_impact import dated_events_df, tier_districts
from src.constants import PROJECT_PREFIX, ZONES
from src.skill_chain import annual_max, weibull_threshold
from src.zones import load_adm2

OUT = Path(__file__).resolve().parent.parent / "outputs"
RPS = (2.0, 3.0, 5.0)
MATCH = 3  # days either side
ZONE_COL = {
    "teso_kyoga": "#2a78d6",
    "elgon": "#e34948",
    "karamoja": "#eda100",
    "adjumani": "#4a3aa7",
}


def score(active: pd.Series, events: pd.DatetimeIndex) -> dict:
    """Recall, precision and activations/year for a boolean daily series against dated events."""
    active = active.fillna(False).astype(bool)
    idx = active.index
    ev = pd.Series(False, index=idx)
    ev.loc[ev.index.intersection(events)] = True
    win = active.rolling(2 * MATCH + 1, center=True, min_periods=1).max().astype(bool)
    ev_win = ev.rolling(2 * MATCH + 1, center=True, min_periods=1).max().astype(bool)
    starts = active & ~active.shift(1, fill_value=False)
    n_act = int(starts.sum())
    return {
        "recall": float((ev & win).sum() / ev.sum()) if ev.sum() else np.nan,
        "precision": float((starts & ev_win).sum() / n_act) if n_act else np.nan,
        "act_per_year": n_act / idx.year.nunique(),
        "n_events": int(ev.sum()),
    }


def main() -> None:
    adm = load_adm2().set_index("ADM2_EN").ADM2_PCODE
    exp = stratus.load_parquet_from_blob(
        f"{PROJECT_PREFIX}/processed/exposure/floodscan_exposure_adm2_daily.parquet", stage="dev"
    )
    im = stratus.load_parquet_from_blob(
        f"{PROJECT_PREFIX}/processed/imerg/imerg_adm2_daily.parquet", stage="dev"
    )

    rows = []
    for key, tier, ds in tier_districts():
        pc = [adm[d] for d in ds if d in adm.index]
        e = exp[exp.pcode.isin(pc)].groupby("date").exposure.sum().asfreq("D")
        rain = im[im.pcode.isin(pc)].pivot(index="date", columns="pcode", values="mean").asfreq("D")
        r3 = rain.rolling(3).sum()
        idx = e.dropna().index.intersection(r3.dropna(how="all").index)
        e, r3 = e.reindex(idx), r3.reindex(idx)
        ev_df = dated_events_df(ds)
        major = ev_df[(ev_df.deaths.fillna(0) >= 5) | (ev_df.affected.fillna(0) >= 5000)]
        event_sets = {"all": pd.DatetimeIndex(ev_df.day), "major": pd.DatetimeIndex(major.day)}
        for rp in RPS:
            e_thr = weibull_threshold(annual_max(e), rp)
            a = e >= e_thr
            # rainfall: any district in the tier over its own RP level
            b = pd.Series(False, index=idx)
            for c in r3.columns:
                thr = weibull_threshold(annual_max(r3[c].dropna()), rp)
                b |= r3[c] >= thr
            for name, act in (("exposure", a), ("rainfall", b), ("either", a | b)):
                for eset, evs in event_sets.items():
                    rows.append(
                        dict(
                            zone=key,
                            tier=tier,
                            rp_years=rp,
                            option=name,
                            events=eset,
                            exposure_thr=e_thr,
                            **score(act, evs),
                        )
                    )
    tab = pd.DataFrame(rows)
    tab.to_csv(OUT / "backstop_options.csv", index=False)
    pd.set_option("display.width", 220)
    for eset in ("major", "all"):
        show = (
            tab[(tab.rp_years == 3) & (tab.events == eset)]
            .pivot_table(
                index=["zone", "tier"],
                columns="option",
                values=["recall", "act_per_year", "n_events"],
            )
            .round(2)
        )
        print(f"\n=== {eset} events, 3-year return period\n", show.to_string())
    g = tab[(tab.rp_years == 3) & (tab.events == "major")].pivot_table(
        index=["zone", "tier"], columns="option", values="recall"
    )
    print(
        "\nrecall gain on MAJOR events from adding the rainfall leg:",
        (g["either"] - g["exposure"]).round(2).to_dict(),
    )

    tiers = [(k, t) for k, t, _ in tier_districts()]
    fig, ax = plt.subplots(figsize=(12, 5.5))
    x = np.arange(len(tiers))
    w = 0.26
    sub = tab[(tab.rp_years == 3) & (tab.events == "major")].set_index(["zone", "tier", "option"])
    for i, (opt, hatch, alpha) in enumerate(
        (("exposure", "", 0.95), ("rainfall", "///", 0.55), ("either", "", 0.35))
    ):
        vals = [sub.loc[(k, t, opt), "recall"] for k, t in tiers]
        cols = [ZONE_COL[k] for k, _ in tiers]
        ax.bar(
            x + (i - 1) * w,
            vals,
            w,
            color=cols,
            alpha=alpha,
            hatch=hatch,
            edgecolor="white",
            label={
                "exposure": "exposure only",
                "rainfall": "observed rainfall only",
                "either": "either (OR)",
            }[opt],
        )
    for j, (k, t) in enumerate(tiers):
        n = int(sub.loc[(k, t, "either"), "n_events"])
        ax.text(j, 1.02, f"n={n}", ha="center", fontsize=7.5, color="#52514e")
    ax.set_xticks(x)
    ax.set_xticklabels([f"{ZONES[k].label.split(' (')[0]}\n{t}" for k, t in tiers], fontsize=8)
    ax.set_ylabel("share of MAJOR impact events caught (±3 days)")
    ax.set_ylim(0, 1.1)
    ax.legend(fontsize=8, frameon=False, ncol=3)
    ax.grid(axis="y", alpha=0.25)
    ax.spines[["top", "right"]].set_visible(False)
    ax.set_title(
        "Observational backstop: does adding an observed-rainfall leg recover the events FloodScan misses?\n"
        "Major events (>=5 deaths or >=5,000 affected); both legs at a 3-year return period; bars by zone, hatched = rainfall, pale = either",
        fontsize=11,
        fontweight="bold",
        loc="left",
    )
    fig.tight_layout()
    fig.savefig(OUT / "backstop_options.png", dpi=150, facecolor="white")
    print("wrote", OUT / "backstop_options.png")


if __name__ == "__main__":
    main()
