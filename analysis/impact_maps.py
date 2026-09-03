"""Historical flood / landslide impact by district: one map per year, plus a summary map.

Sources merged (src/datasources/impact.py + desinventar.py): EM-DAT events exploded
to districts, DesInventar datacards (1933-2021), IOM DTM district rounds (2023-2025),
curated events (2007-2025). Per district-year: whether any record exists, the sum of
people affected (max across overlapping sources per event, summed over events) and
deaths. The per-year grid colours districts by people affected (log scale) and marks
deaths; the summary map shows the number of years with a recorded impact per district
(1998-2025), with deaths as bubbles and the trigger zones outlined.

Writes outputs/impact_by_year.png, outputs/impact_summary.png, outputs/impact_district_year.csv.
Run:  uv run python analysis/impact_maps.py
"""

import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib import patheffects as pe
from matplotlib.colors import LinearSegmentedColormap, LogNorm
from matplotlib.lines import Line2D
from matplotlib.patches import Patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.constants import ZONES
from src.datasources import desinventar as di
from src.datasources import impact
from src.zones import load_adm2, zone_districts

OUT = Path(__file__).resolve().parent.parent / "outputs"
YEARS = list(range(1998, 2026))
ZONE_COL = {
    "teso_kyoga": "#2a78d6",
    "elgon": "#e34948",
    "karamoja": "#eda100",
    "adjumani": "#4a3aa7",
}
REDS = LinearSegmentedColormap.from_list(
    "imp", ["#fde5d9", "#f4a582", "#d6604d", "#b2182b", "#67001f"]
)
INK, INK2, MUTED = "#0b0b0b", "#52514e", "#8a8984"
# CERF rapid-response allocations for floods/landslides in Uganda (CERF Allocations dataset, HDX),
# keyed on the year of the flood event they responded to: USD 4.8 M in Oct 2007 (Teso/northern
# floods) and USD 3.95 M in Jan 2020 (Nov-Dec 2019 Rwenzori/Elgon floods and landslides).
CERF_YEARS = {2007: "CERF $4.8M Oct 2007", 2019: "CERF $4.0M Jan 2020"}
ONI_ELNINO, DMI_POSITIVE = (
    0.5,
    0.4,
)  # OND-mean thresholds on the NOAA ONI / DMI (ds-seas5-skill index table)
ENSO_COL, IOD_COL, CERF_COL = "#d95926", "#1baf7a", "#8a6d00"
IMPLAUSIBLE_AFFECTED = 100_000  # per district-card; above this it is a national total mis-filed


def district_year_table() -> pd.DataFrame:
    ev = impact.events_by_district()  # EM-DAT + curated + DTM, one row per (event, district)
    ev["year"] = ev.start.dt.year
    # affected/deaths are event totals; attribute to each named district in full for
    # "any impact", but split evenly across districts for the summed magnitude
    n_d = ev.groupby("event_id").district.transform("nunique")
    ev["affected_share"] = ev.affected.fillna(0) / n_d
    ev["deaths_share"] = ev.deaths.fillna(0) / n_d
    a = ev.groupby(["district", "year"]).agg(
        n_events=("event_id", "nunique"),
        affected=("affected_share", "sum"),
        deaths=("deaths_share", "sum"),
        sources=("source", lambda s: "|".join(sorted({x[:10] for x in s}))),
    )
    d = di.load_datacards()
    d = d[d.district.notna()].assign(year=d.date.dt.year)
    # A few datacards carry national/regional totals against one district (Agago 3,000,000 in
    # Jul 2007; Bududa 300,000 in Mar 2010 vs EM-DAT's 12,795): keep the record, drop the count.
    d.loc[d.affected >= IMPLAUSIBLE_AFFECTED, "affected"] = np.nan
    b = d.groupby(["district", "year"]).agg(
        n_cards=("serial", "size"), affected_di=("affected", "sum"), deaths_di=("deaths", "sum")
    )
    t = a.join(b, how="outer").fillna(
        {"n_events": 0, "affected": 0, "deaths": 0, "n_cards": 0, "affected_di": 0, "deaths_di": 0}
    )
    # DesInventar is independent of EM-DAT in scope; take the max of the two magnitude estimates
    t["affected_any"] = t[["affected", "affected_di"]].max(axis=1)
    # deaths: EM-DAT/curated where they exist (DesInventar double-counts across cards), else DesInventar
    t["deaths_any"] = np.where(t.deaths > 0, t.deaths, t.deaths_di)
    t["any_record"] = (t.n_events + t.n_cards) > 0
    return t.reset_index()


def climate_years() -> tuple[set[int], set[int]]:
    """Years whose Oct-Dec season was under El Nino (ONI >= 0.5) and positive IOD (DMI >= 0.4)."""
    import ocha_stratus as stratus

    idx = stratus.load_parquet_from_blob(
        "ds-seas5-skill/raw/climate_indices/ond_indices.parquet", stage="dev"
    )
    return set(idx[idx.oni_ond >= ONI_ELNINO].year), set(idx[idx.dmi_ond >= DMI_POSITIVE].year)


def main() -> None:
    adm = load_adm2()
    t = district_year_table()
    elnino, piod = climate_years()
    t = t[t.year.isin(YEARS)]
    t.to_csv(OUT / "impact_district_year.csv", index=False)
    uganda = adm.dissolve().geometry.iloc[0]
    zone_shapes = {
        k: zone_districts(k, include_candidates=False).dissolve().geometry.iloc[0] for k in ZONES
    }

    # ---- per-year grid --------------------------------------------------------------
    ncol = 7
    nrow = int(np.ceil(len(YEARS) / ncol))
    fig, axes = plt.subplots(nrow, ncol, figsize=(16, 2.6 * nrow + 1.2), facecolor="white")
    norm = LogNorm(vmin=100, vmax=200_000)
    for ax, year in zip(axes.flat, YEARS, strict=False):
        ty = t[t.year == year]
        g = adm.merge(ty, left_on="ADM2_EN", right_on="district", how="left")
        adm.plot(ax=ax, color="#f4f3ef", edgecolor="white", linewidth=0.3, aspect=None)
        rec = g[g.any_record.fillna(False)]
        # districts with a record but no count: light hatch; with a count: colour by affected
        rec[rec.affected_any <= 0].plot(
            ax=ax, color="#fbd0c4", edgecolor="white", linewidth=0.3, aspect=None
        )
        cnt = rec[rec.affected_any > 0]
        if len(cnt):
            cnt.plot(
                ax=ax,
                column="affected_any",
                cmap=REDS,
                norm=norm,
                edgecolor="white",
                linewidth=0.3,
                aspect=None,
            )
        dead = rec[rec.deaths_any >= 5]
        for _, r in dead.iterrows():
            c = r.geometry.representative_point()
            ax.plot(
                c.x,
                c.y,
                marker="o",
                markersize=max(3, min(12, 2 + r.deaths_any**0.5)),
                color="none",
                markeredgecolor=INK,
                markeredgewidth=0.9,
            )
        for k, shp in zone_shapes.items():
            ax.plot(
                *shp.exterior.xy, color=ZONE_COL[k], linewidth=0.7, alpha=0.9
            ) if shp.geom_type == "Polygon" else [
                ax.plot(*p.exterior.xy, color=ZONE_COL[k], linewidth=0.7, alpha=0.9)
                for p in shp.geoms
            ]
        tags = []
        if year in elnino:
            tags.append(("El Niño", ENSO_COL))
        if year in piod:
            tags.append(("+IOD", IOD_COL))
        if year in CERF_YEARS:
            tags.append((CERF_YEARS[year], CERF_COL))
        ax.set_title(str(year), fontsize=10, fontweight="bold", color=INK, pad=2)
        for j, (txt, col) in enumerate(tags):
            ax.text(
                0.98,
                0.96 - 0.09 * j,
                txt,
                transform=ax.transAxes,
                ha="right",
                va="top",
                fontsize=6.5,
                color="white",
                fontweight="bold",
                bbox={"boxstyle": "round,pad=0.25", "fc": col, "ec": "none"},
            )
        if year in CERF_YEARS:
            for sp in ax.spines.values():
                sp.set_visible(True)
                sp.set_edgecolor(CERF_COL)
                sp.set_linewidth(2.2)
        elif year in elnino:
            for sp in ax.spines.values():
                sp.set_visible(True)
                sp.set_edgecolor(ENSO_COL)
                sp.set_linewidth(1.2)
        ax.text(
            0.02,
            0.02,
            f"{int(ty.any_record.sum())} districts",
            transform=ax.transAxes,
            fontsize=7,
            color=INK2,
        )
        ax.set_xlim(29.4, 35.15)
        ax.set_ylim(-1.55, 4.35)
        ax.set_aspect("equal")
        ax.set_xticks([])
        ax.set_yticks([])
        if year in CERF_YEARS or year in elnino:
            ax.set_facecolor("#fff8f0" if year in elnino else "white")
            for sp in ax.spines.values():
                sp.set_visible(True)
                sp.set_edgecolor(CERF_COL if year in CERF_YEARS else ENSO_COL)
                sp.set_linewidth(2.4 if year in CERF_YEARS else 1.4)
        else:
            for sp in ax.spines.values():
                sp.set_visible(False)
    for ax in axes.flat[len(YEARS) :]:
        ax.set_axis_off()
    sm = plt.cm.ScalarMappable(norm=norm, cmap=REDS)
    cax = fig.add_axes([0.62, 0.035, 0.22, 0.012])
    cb = fig.colorbar(sm, cax=cax, orientation="horizontal")
    cb.set_label("people affected in the district that year (log scale)", fontsize=8, color=INK2)
    cb.ax.tick_params(labelsize=7, colors=INK2)
    handles = [
        Patch(facecolor="#fbd0c4", label="record, no count"),
        Line2D(
            [],
            [],
            marker="o",
            color="none",
            markeredgecolor=INK,
            markersize=7,
            label="≥5 deaths (size ∝ √deaths)",
        ),
    ]
    handles += [
        Line2D([], [], color=ZONE_COL[k], lw=1.2, label=z.label.split(" (")[0])
        for k, z in ZONES.items()
    ]
    handles += [
        Patch(
            facecolor="white",
            edgecolor=CERF_COL,
            linewidth=2.4,
            label="CERF rapid-response allocation for that flood",
        ),
        Patch(
            facecolor="#fff8f0",
            edgecolor=ENSO_COL,
            linewidth=1.4,
            label="El Niño Oct–Dec season (ONI ≥ 0.5)",
        ),
        Patch(facecolor=IOD_COL, edgecolor="none", label="positive IOD Oct–Dec (DMI ≥ 0.4)"),
    ]
    fig.legend(
        handles=handles,
        loc="lower left",
        bbox_to_anchor=(0.03, 0.005),
        ncol=3,
        fontsize=8,
        frameon=False,
    )
    fig.suptitle(
        "Recorded flood and landslide impact by district and year, 1998–2025",
        fontsize=15,
        fontweight="bold",
        x=0.03,
        ha="left",
        y=0.995,
    )
    fig.text(
        0.03,
        0.965,
        "EM-DAT, DesInventar Uganda (to 2021), IOM DTM (2023–25) and curated events; event totals split evenly across the districts named. "
        "DesInventar has no 2019 records and nothing after 2021, so 2019 and 2022 are under-recorded.",
        fontsize=8.5,
        color=INK2,
    )
    fig.subplots_adjust(left=0.01, right=0.99, top=0.92, bottom=0.07, wspace=0.02, hspace=0.12)
    fig.savefig(OUT / "impact_by_year.png", dpi=150, facecolor="white")
    print("wrote", OUT / "impact_by_year.png")

    # ---- summary map ------------------------------------------------------------------
    s = (
        t.groupby("district")
        .agg(
            years=("any_record", "sum"),
            affected=("affected_any", "sum"),
            deaths=("deaths_any", "sum"),
        )
        .reset_index()
    )
    g = adm.merge(s, left_on="ADM2_EN", right_on="district", how="left").fillna(
        {"years": 0, "affected": 0, "deaths": 0}
    )
    fig, ax = plt.subplots(figsize=(10.5, 11), facecolor="white")
    g.plot(
        ax=ax,
        column="years",
        cmap=REDS,
        vmin=0,
        vmax=g.years.max(),
        edgecolor="white",
        linewidth=0.4,
        aspect=None,
        legend=True,
        legend_kwds={
            "shrink": 0.45,
            "label": "years with a recorded flood / landslide impact, 1998–2025",
            "pad": 0.01,
        },
    )
    g[g.years == 0].plot(ax=ax, color="#f4f3ef", edgecolor="white", linewidth=0.4, aspect=None)
    for _, r in g[g.deaths >= 10].iterrows():
        c = r.geometry.representative_point()
        ax.plot(
            c.x,
            c.y,
            marker="o",
            markersize=4 + 2.2 * r.deaths**0.5,
            color="none",
            markeredgecolor=INK,
            markeredgewidth=1.1,
            zorder=6,
        )
    for k, shp in zone_shapes.items():
        polys = [shp] if shp.geom_type == "Polygon" else list(shp.geoms)
        for p in polys:
            ax.plot(*p.exterior.xy, color=ZONE_COL[k], linewidth=2.2, zorder=7)
    top = g.sort_values("affected", ascending=False).head(14)
    for _, r in top.iterrows():
        c = r.geometry.representative_point()
        ax.annotate(
            f"{r.ADM2_EN}\n{r.affected / 1000:,.0f}k",
            (c.x, c.y),
            ha="center",
            fontsize=6.5,
            color=INK,
            zorder=8,
            path_effects=[pe.withStroke(linewidth=2, foreground="white")],
        )
    ax.plot(*uganda.exterior.xy, color=INK2, linewidth=0.8)
    ax.set_xlim(29.4, 35.15)
    ax.set_ylim(-1.55, 4.35)
    ax.set_aspect("equal")
    ax.set_axis_off()
    handles = [
        Line2D(
            [],
            [],
            marker="o",
            color="none",
            markeredgecolor=INK,
            markersize=9,
            label="≥10 deaths recorded 1998–2025 (size ∝ √deaths)",
        )
    ]
    handles += [
        Line2D([], [], color=ZONE_COL[k], lw=2, label=z.label.split(" (")[0])
        for k, z in ZONES.items()
    ]
    ax.legend(
        handles=handles, loc="lower right", bbox_to_anchor=(1.0, 0.03), fontsize=8, frameon=False
    )
    ax.set_title(
        "Where flood and landslide impact has been recorded, 1998–2025",
        fontsize=14,
        fontweight="bold",
        loc="left",
        pad=14,
    )
    ax.text(
        0,
        1.005,
        "Labels: the 14 districts with the largest cumulative people affected (thousands). "
        "Sources: EM-DAT, DesInventar (to 2021), IOM DTM (2023–25), curated events.",
        transform=ax.transAxes,
        fontsize=8.5,
        color=INK2,
        va="bottom",
    )
    fig.savefig(OUT / "impact_summary.png", dpi=160, facecolor="white", bbox_inches="tight")
    print("wrote", OUT / "impact_summary.png")
    print(s.sort_values("affected", ascending=False).head(15).to_string(index=False))


if __name__ == "__main__":
    main()
