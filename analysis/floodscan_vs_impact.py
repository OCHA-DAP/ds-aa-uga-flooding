"""Does FloodScan see the recorded impact? — every district, 1998-2025.

Year level: for each district, the FloodScan annual maximum (daily district-mean SFED)
is ranked within the district's own 28-year record and compared between years with a
recorded flood/landslide impact and years without:

  * AUC — probability that a random impact year has a higher FloodScan annual max than a
    random non-impact year (0.5 = no relation, 1 = perfect separation);
  * hit rate — share of impact years in which the annual max reached the district's
    2-yr level (Weibull); precision — share of 2-yr years with a recorded impact;
  * "blind" — the district's 2-yr level is below the 0.01 extent, i.e. FloodScan
    essentially never registers flooding there (mountain slopes).

Event level: for day-dated impact events (DesInventar, EM-DAT, curated), the max SFED in
[start-3 d, end+7 d] as a percentile of the district's daily climatology.

Writes outputs/floodscan_vs_impact_district.csv, outputs/floodscan_vs_impact.png (map +
event histogram), and prints the summary by coverage class.
Run:  uv run python analysis/floodscan_vs_impact.py
"""

import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import ocha_stratus as stratus
import pandas as pd
from matplotlib.colors import LinearSegmentedColormap
from matplotlib.lines import Line2D
from matplotlib.patches import Patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from analysis.impact_coverage import classify
from src.constants import PROJECT_PREFIX, ZONES
from src.datasources import desinventar as di
from src.datasources import impact
from src.skill_chain import annual_max, weibull_threshold
from src.zones import load_adm2, zone_districts

OUT = Path(__file__).resolve().parent.parent / "outputs"
YEARS = range(1998, 2026)
BLIND_LEVEL = 0.01
ZONE_COL = {
    "teso_kyoga": "#2a78d6",
    "elgon": "#e34948",
    "karamoja": "#eda100",
    "adjumani": "#4a3aa7",
}
INK, INK2 = "#0b0b0b", "#52514e"
AUC_CMAP = LinearSegmentedColormap.from_list("auc", ["#f7f7f7", "#c7e9c0", "#41ab5d", "#00441b"])


def auc(pos: np.ndarray, neg: np.ndarray) -> float:
    if len(pos) == 0 or len(neg) == 0:
        return np.nan
    gt = (pos[:, None] > neg[None, :]).mean()
    eq = (pos[:, None] == neg[None, :]).mean()
    return float(gt + 0.5 * eq)


def district_year_scores(fs: pd.DataFrame, t: pd.DataFrame, adm: pd.Series) -> pd.DataFrame:
    rows = []
    for pcode, name in adm.items():
        s = fs[fs.pcode == pcode].set_index("date")["mean"].sort_index()
        if s.empty:
            continue
        am = annual_max(s).reindex(YEARS)
        thr2 = weibull_threshold(am.dropna(), 2.0)
        ty = t[t.district == name].set_index("year").reindex(YEARS)
        imp = ty.any_record.fillna(False).astype(bool)
        aff = ty.affected_any.fillna(0)
        pos, neg = am[imp].dropna().to_numpy(), am[~imp].dropna().to_numpy()
        hit = float((am[imp] >= thr2).mean()) if imp.any() else np.nan
        prec = float(imp[am >= thr2].mean()) if (am >= thr2).any() else np.nan
        rho = pd.Series(am).corr(aff, method="spearman") if aff.gt(0).sum() >= 3 else np.nan
        rows.append(
            dict(
                district=name,
                n_impact_years=int(imp.sum()),
                sfed_2yr=thr2,
                blind=thr2 < BLIND_LEVEL,
                auc=auc(pos, neg),
                hit_rate_2yr=hit,
                precision_2yr=prec,
                spearman_affected=rho,
            )
        )
    return pd.DataFrame(rows)


def event_percentiles(fs: pd.DataFrame, adm: pd.Series) -> pd.DataFrame:
    pc_of = {v: k for k, v in adm.items()}
    ev = impact.events_by_district(include_dtm=False)
    ev = ev[(ev.end - ev.start).dt.days <= 14]
    d = di.load_datacards()
    d = d[(d.date_precision == "day") & d.district.notna() & (d.date >= "1998-01-01")]
    des = d.rename(columns={"date": "start"}).assign(
        end=lambda x: x.start, event_id=lambda x: "DI-" + x.serial.astype(str), source="DesInventar"
    )[["event_id", "start", "end", "district", "source", "deaths"]]
    allev = pd.concat(
        [ev[["event_id", "start", "end", "district", "source", "deaths"]], des], ignore_index=True
    )
    allev = allev[allev.start.dt.year >= 1998]
    series = {p: fs[fs.pcode == p].set_index("date")["mean"].sort_index() for p in adm.index}
    zone_of = {dd: k for k, z in ZONES.items() for dd in z.core + z.tier2}
    rows = []
    for _, e in allev.iterrows():
        p = pc_of.get(e.district)
        if p is None:
            continue
        s = series[p]
        win = s.loc[e.start - pd.Timedelta(days=3) : e.end + pd.Timedelta(days=7)].dropna()
        if win.empty:
            continue
        v = float(win.max())
        rows.append(
            dict(
                event_id=e.event_id,
                district=e.district,
                zone=zone_of.get(e.district, "outside"),
                source=e.source,
                deaths=e.deaths,
                start=e.start,
                sfed_max=v,
                sfed_pctl=float((s < v).mean() * 100),
            )
        )
    return pd.DataFrame(rows)


def main() -> None:
    fs = stratus.load_parquet_from_blob(
        f"{PROJECT_PREFIX}/processed/floodscan/floodscan_adm2_daily.parquet", stage="dev"
    )
    t = pd.read_csv(OUT / "impact_district_year.csv")
    adm_g = load_adm2()
    adm = adm_g.set_index("ADM2_PCODE").ADM2_EN
    sc = district_year_scores(fs, t, adm).merge(
        classify()[["district", "cls", "zone"]], on="district", how="left"
    )
    sc.to_csv(OUT / "floodscan_vs_impact_district.csv", index=False)
    evp = event_percentiles(fs, adm)
    evp.to_csv(OUT / "floodscan_vs_impact_events.csv", index=False)

    pd.set_option("display.width", 200)
    ok = sc[(sc.n_impact_years >= 3) & ~sc.blind]
    print(
        f"districts with >=3 impact years: {int((sc.n_impact_years >= 3).sum())}, of which FloodScan-blind: "
        f"{int(sc[(sc.n_impact_years >= 3)].blind.sum())}"
    )
    print(
        "\nby coverage class (districts with >=3 impact years, not blind): median AUC / hit rate / precision"
    )
    print(ok.groupby("cls")[["auc", "hit_rate_2yr", "precision_2yr"]].median().round(2).to_string())
    print("\nby zone (core + tier 2):")
    print(
        ok.groupby("zone")[["auc", "hit_rate_2yr", "precision_2yr"]].median().round(2).to_string()
    )
    print(
        "\nnational: median AUC",
        round(ok.auc.median(), 2),
        "| share of districts with AUC >= 0.7:",
        round((ok.auc >= 0.7).mean(), 2),
    )
    print("\nbest and worst (>=5 impact years):")
    big = sc[sc.n_impact_years >= 5].sort_values("auc", ascending=False)
    print(
        pd.concat([big.head(8), big.tail(8)])[
            [
                "district",
                "cls",
                "n_impact_years",
                "sfed_2yr",
                "blind",
                "auc",
                "hit_rate_2yr",
                "precision_2yr",
            ]
        ]
        .round(2)
        .to_string(index=False)
    )
    print("\nevent-level: median SFED percentile in the event window, by zone")
    print(evp.groupby("zone").sfed_pctl.agg(["median", "size"]).round(0).to_string())
    print(
        "deadly events (>=5 deaths):",
        evp[evp.deaths.fillna(0) >= 5].groupby("zone").sfed_pctl.median().round(0).to_dict(),
    )

    # ---- figure: AUC map + event histogram ------------------------------------------
    fig, (ax, ax2) = plt.subplots(
        1, 2, figsize=(15, 7.2), gridspec_kw={"width_ratios": [1.15, 1]}, facecolor="white"
    )
    g = adm_g.merge(sc, left_on="ADM2_EN", right_on="district", how="left")
    g.plot(ax=ax, color="#f4f3ef", edgecolor="white", linewidth=0.4, aspect=None)
    g[g.blind.fillna(False)].plot(
        ax=ax, facecolor="none", edgecolor="#999999", hatch="////", linewidth=0.3, aspect=None
    )
    scored = g[(g.n_impact_years >= 3) & ~g.blind.fillna(True)]
    scored.plot(
        ax=ax,
        column="auc",
        cmap=AUC_CMAP,
        vmin=0.4,
        vmax=1.0,
        edgecolor="white",
        linewidth=0.4,
        aspect=None,
        legend=True,
        legend_kwds={
            "shrink": 0.5,
            "label": "AUC: FloodScan annual max in impact vs non-impact years",
            "pad": 0.01,
        },
    )
    for k in ZONES:
        for tier, ls in (("core", "-"), ("tier2", (0, (2.5, 1.5)))):
            zz = zone_districts(k)
            sub = zz[zz.membership == tier]
            if len(sub):
                sub.dissolve().boundary.plot(
                    ax=ax, color=ZONE_COL[k], linewidth=1.6, linestyle=ls, aspect=None
                )
    ax.set_xlim(29.4, 35.15)
    ax.set_ylim(-1.55, 4.35)
    ax.set_aspect("equal")
    ax.set_axis_off()
    ax.set_title(
        "Does FloodScan separate impact years from other years?",
        fontsize=11,
        fontweight="bold",
        loc="left",
    )
    ax.legend(
        handles=[
            Patch(
                facecolor="none",
                edgecolor="#999999",
                hatch="////",
                label="FloodScan blind (2-yr extent < 0.01)",
            ),
            Patch(facecolor="#f4f3ef", label="fewer than 3 impact years"),
            Line2D([], [], color=INK2, lw=1.5, label="zone tier 1"),
            Line2D([], [], color=INK2, lw=1.5, ls=(0, (2.5, 1.5)), label="zone tier 2"),
        ],
        loc="lower right",
        fontsize=8,
        frameon=False,
    )

    bins = np.arange(0, 101, 10)
    order = ["teso_kyoga", "adjumani", "elgon", "karamoja", "outside"]
    cols = {**ZONE_COL, "outside": "#999999"}
    labels = {k: ZONES[k].label.split(" (")[0] for k in ZONES} | {"outside": "outside the zones"}
    data = [evp[evp.zone == z].sfed_pctl.dropna().to_numpy() for z in order]
    ax2.hist(
        data,
        bins=bins,
        stacked=True,
        color=[cols[z] for z in order],
        label=[f"{labels[z]} (n={len(d)})" for z, d in zip(order, data, strict=True)],
        alpha=0.85,
    )
    ax2.axhline(len(evp) / 10, color="grey", ls="--", lw=1, label="uniform (no relation)")
    ax2.set_xlabel("percentile of max FloodScan extent in the event window (district climatology)")
    ax2.set_ylabel("dated impact events")
    ax2.set_title(
        "Where do recorded events sit in FloodScan's distribution?",
        fontsize=11,
        fontweight="bold",
        loc="left",
    )
    ax2.legend(fontsize=8, frameon=False)
    ax2.spines[["top", "right"]].set_visible(False)
    fig.suptitle(
        "FloodScan flood extent vs the recorded impact, all districts 1998–2025",
        fontsize=13,
        fontweight="bold",
        x=0.02,
        ha="left",
    )
    fig.tight_layout()
    fig.savefig(OUT / "floodscan_vs_impact.png", dpi=150, facecolor="white")
    print("wrote", OUT / "floodscan_vs_impact.png")


if __name__ == "__main__":
    main()
