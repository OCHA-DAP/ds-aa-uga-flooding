"""Adjumani / Albert Nile zone: are West Nile floods lake-level events?

Plots monthly altimetry levels of Lakes Victoria, Kyoga and Albert (NASA GWM)
against every dated West Nile flood record we hold (DesInventar datacards for
Moyo, Nebbi, Adjumani, Yumbe, Arua 1990-2021; EM-DAT; curated 2019-2024
events), and tabulates the Kyoga/Albert level percentile in flood months vs
all months. If floods cluster at high lake stands, the lake series is a
multi-month-lead indicator for the zone; if not, the zone is a local-rain
(flash) problem and belongs with the rainfall trigger.

Writes outputs/adjumani_lake_levels.png and prints the percentile table.
Run:  uv run python analysis/adjumani_lake_levels.py
"""

import sys
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.datasources import desinventar as di
from src.datasources import impact
from src.datasources import lake_levels as ll

OUT = Path(__file__).resolve().parent.parent / "outputs" / "adjumani_lake_levels.png"
WEST_NILE = ["Adjumani", "Moyo", "Obongi", "Nebbi", "Pakwach", "Yumbe", "Arua", "Madi Okollo"]
NILE_SIDE = [
    "Adjumani",
    "Moyo",
    "Obongi",
    "Nebbi",
    "Pakwach",
]  # districts touching the Albert Nile / Lake Albert


def flood_months() -> pd.DataFrame:
    d = di.load_datacards()
    d = d[
        d.district.isin(NILE_SIDE)
        & d.event_type.isin(["FLOOD", "FLASH FLOOD"])
        & (d.date >= "1992-09-01")
    ]
    des = (
        d.assign(month=d.date.dt.to_period("M"))
        .groupby("month")
        .agg(
            n_cards=("serial", "size"),
            districts=("district", lambda s: ",".join(sorted(set(s)))),
            affected=("affected", "sum"),
            src=("serial", lambda s: "DesInventar"),
        )
    )
    ev = impact.events_by_district()
    ev = ev[ev.district.isin(NILE_SIDE) & (ev.start >= "1992-09-01")]
    rows = []
    for _, e in ev.drop_duplicates("event_id").iterrows():
        for m in pd.period_range(e.start, e.end, freq="M"):
            rows.append(
                {
                    "month": m,
                    "n_cards": 1,
                    "districts": e.district,
                    "affected": e.affected,
                    "src": e.source,
                }
            )
    other = (
        pd.DataFrame(rows)
        .groupby("month")
        .agg(
            n_cards=("n_cards", "sum"),
            districts=("districts", "first"),
            affected=("affected", "max"),
            src=("src", "first"),
        )
    )
    return (
        pd.concat([des, other])
        .groupby(level=0)
        .agg(
            n_cards=("n_cards", "sum"),
            districts=("districts", "first"),
            affected=("affected", "max"),
            src=("src", "first"),
        )
    )


def main() -> None:
    lev = ll.monthly(ll.load_lake_levels())
    lev.index = lev.index.to_period("M")
    fm = flood_months()

    pct = lev.rank(pct=True) * 100
    tab = pct.loc[pct.index.isin(fm.index)].join(fm[["n_cards", "districts", "src"]])
    pd.set_option("display.width", 200)
    print("Lake-level percentile (of all months 1992-2026) in West Nile flood months:")
    print(tab.round(0).to_string())
    print(
        "\nmedian percentile in flood months:",
        pct.loc[pct.index.isin(fm.index)].median().round(0).to_dict(),
    )
    print(
        "share of flood months with Kyoga above its 75th pctl:",
        round((pct.loc[pct.index.isin(fm.index), "kyoga"] > 75).mean(), 2),
    )

    fig, axes = plt.subplots(3, 1, figsize=(13, 9), sharex=True)
    for ax, lake, col in zip(
        axes, ["victoria", "kyoga", "albert"], ["#1b7837", "#2166ac", "#b2182b"], strict=True
    ):
        s = lev[lake].dropna()
        ax.plot(s.index.to_timestamp(), s.values, color=col, lw=1.2)
        ax.set_ylabel(f"Lake {lake.title()}\n(m a.s.l., EGM2008)")
        for m, r in fm.iterrows():
            t = m.to_timestamp()
            if s.index.min() <= m <= s.index.max():
                ax.axvline(t, color="#555555", alpha=0.25 if r.src == "DesInventar" else 0.7, lw=1)
        ax.grid(alpha=0.3)
    axes[0].set_title(
        "Lake levels (NASA GWM altimetry, monthly means) vs dated flood records in Albert Nile / Lake Albert districts\n"
        "grey lines: months with a flood record in Adjumani, Moyo, Obongi, Nebbi or Pakwach "
        "(faint = DesInventar datacard 1992-2021; dark = EM-DAT / curated 2019-2024)",
        fontsize=10,
    )
    axes[-1].set_xlim(pd.Timestamp("1992-06-01"), pd.Timestamp("2026-12-31"))
    fig.tight_layout()
    fig.savefig(OUT, dpi=150)
    print("wrote", OUT)


if __name__ == "__main__":
    main()
