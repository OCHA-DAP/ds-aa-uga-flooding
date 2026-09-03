"""CEMS pass: the three Copernicus EMS rapid-mapping flood activations in Uganda vs FloodScan and the impact record.

From the team's CEMS flood archive (global container, silver tier — pipelines/cems-flood-archive):
  EMSR438  May 2020        East Africa rains: 7 AOIs incl. Lake Kyoga, monitoring series
  EMSR446  Jul-Sep 2020    Ministry of Water request on rising lake levels: 3 AOIs, monitoring series
  EMSR662  May 2023        Katonga river (Nkozi), 1 AOI — outside every zone

For every (activation, AOI, acquisition date): the CEMS flooded area per district (km2,
equal-area projection) against the FloodScan district-mean extent on the same day
(SFED x district area = km2 equivalent) and its percentile in the district record, plus
whether the district has an impact record that year. Also, for FloodScan validation:
correlation across districts between CEMS km2 and FloodScan km2 on the same date.

Writes outputs/cems_pass.csv, outputs/cems_pass.png.  Run:  uv run python analysis/cems_pass.py
"""

import io
import sys
from pathlib import Path

import geopandas as gpd
import matplotlib.pyplot as plt
import ocha_stratus as stratus
import pandas as pd
from matplotlib.lines import Line2D
from matplotlib.patches import Patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.constants import PROJECT_PREFIX, ZONES
from src.zones import load_adm2, zone_districts

OUT = Path(__file__).resolve().parent.parent / "outputs"
CODES = {
    "EMSR438": "May 2020 East Africa rains",
    "EMSR446": "Jul–Sep 2020 rising lake levels",
    "EMSR662": "May 2023 Katonga river",
}
EA = "EPSG:6933"  # equal-area for km2
ZONE_COL = {
    "teso_kyoga": "#2a78d6",
    "elgon": "#e34948",
    "karamoja": "#eda100",
    "adjumani": "#4a3aa7",
}
INK, INK2 = "#0b0b0b", "#52514e"


def load_silver(code: str, tbl: str) -> gpd.GeoDataFrame:
    b = stratus.load_blob_data(
        f"copernicus_ems/flood/silver/{tbl}/code={code}/data.parquet",
        container_name="global",
        stage="dev",
    )
    return gpd.read_parquet(io.BytesIO(b))


def main() -> None:
    adm = load_adm2()[["ADM2_PCODE", "ADM2_EN", "geometry"]]
    adm_ea = adm.to_crs(EA)
    adm_ea["district_km2"] = adm_ea.area / 1e6
    fs = stratus.load_parquet_from_blob(
        f"{PROJECT_PREFIX}/processed/floodscan/floodscan_adm2_daily.parquet", stage="dev"
    )
    imp = pd.read_csv(OUT / "impact_district_year.csv")
    zone_of = {d: k for k, z in ZONES.items() for d in z.core + z.tier2}
    tier_of = {d: "tier 1" for z in ZONES.values() for d in z.core} | {
        d: "tier 2" for z in ZONES.values() for d in z.tier2
    }

    rows, polys = [], {}
    for code in CODES:
        ev = load_silver(code, "observed_event")
        ev = ev[ev.layer_kind.eq("observed") & ev.geometry.notna()].copy()
        ev["acq_date"] = pd.to_datetime(ev.acq_datetime).dt.normalize()
        ev["aoi"] = ev.aoi.fillna("AOI?")
        polys[code] = ev
        for (aoi, day), g in ev.groupby(["aoi", "acq_date"]):
            inter = gpd.overlay(g[["geometry"]].to_crs(EA), adm_ea, how="intersection")
            inter["cems_km2"] = inter.area / 1e6
            per = (
                inter.groupby(["ADM2_PCODE", "ADM2_EN", "district_km2"])
                .cems_km2.sum()
                .reset_index()
            )
            for _, r in per.iterrows():
                s = fs[fs.pcode == r.ADM2_PCODE].set_index("date")["mean"].sort_index()
                same = s.get(day, float("nan"))
                win = s.loc[day - pd.Timedelta(days=3) : day + pd.Timedelta(days=3)]
                pct = float((s < same).mean() * 100) if pd.notna(same) else float("nan")
                yr = imp[(imp.district == r.ADM2_EN) & (imp.year == day.year)]
                rows.append(
                    dict(
                        code=code,
                        aoi=aoi,
                        acq_date=day.date(),
                        district=r.ADM2_EN,
                        zone=zone_of.get(r.ADM2_EN, "outside"),
                        tier=tier_of.get(r.ADM2_EN, ""),
                        cems_km2=round(r.cems_km2, 1),
                        cems_share=round(r.cems_km2 / r.district_km2, 4),
                        floodscan_share=round(same, 4) if pd.notna(same) else float("nan"),
                        floodscan_km2=round(same * r.district_km2, 1)
                        if pd.notna(same)
                        else float("nan"),
                        floodscan_pctl=round(pct) if pd.notna(pct) else float("nan"),
                        floodscan_max_pm3d=round(float(win.max()), 4) if len(win) else float("nan"),
                        impact_record_that_year=bool(len(yr) and yr.any_record.iloc[0]),
                    )
                )
    t = pd.DataFrame(rows)
    t.to_csv(OUT / "cems_pass.csv", index=False)
    pd.set_option("display.width", 220)
    print("acquisitions per activation:")
    print(
        t.groupby("code")
        .agg(
            aois=("aoi", "nunique"),
            dates=("acq_date", "nunique"),
            districts=("district", "nunique"),
            first=("acq_date", "min"),
            last=("acq_date", "max"),
        )
        .to_string()
    )
    big = t[t.cems_km2 >= 5]
    print("\ndistrict-dates with >=5 km2 CEMS flooding: FloodScan same-day share and percentile")
    print(
        big.sort_values("cems_km2", ascending=False)
        .head(25)[
            [
                "code",
                "aoi",
                "acq_date",
                "district",
                "zone",
                "tier",
                "cems_km2",
                "cems_share",
                "floodscan_share",
                "floodscan_pctl",
                "impact_record_that_year",
            ]
        ]
        .to_string(index=False)
    )
    print(
        "\nSpearman corr CEMS km2 vs FloodScan km2 across district-dates (>=1 km2 CEMS):",
        round(
            t[t.cems_km2 >= 1][["cems_km2", "floodscan_km2"]].corr(method="spearman").iloc[0, 1], 2
        ),
    )
    print(
        "share of district-dates with >=5 km2 CEMS flooding where FloodScan is above its 90th pctl:",
        round((big.floodscan_pctl >= 90).mean(), 2),
        "| where FloodScan shows nothing (<0.005):",
        round((big.floodscan_share < 0.005).mean(), 2),
    )
    print(
        "by zone:",
        big.groupby("zone")
        .agg(n=("district", "size"), fs_p90=("floodscan_pctl", lambda x: (x >= 90).mean()))
        .round(2)
        .to_dict(),
    )

    # ---- figure: CEMS polygons per activation over the zones ----
    fig, axes = plt.subplots(1, 3, figsize=(16, 6), facecolor="white")
    for ax, (code, label) in zip(axes, CODES.items(), strict=True):
        adm.plot(ax=ax, color="#f4f3ef", edgecolor="white", linewidth=0.3, aspect=None)
        for k in ZONES:
            zz = zone_districts(k)
            zz[zz.membership == "core"].dissolve().boundary.plot(
                ax=ax, color=ZONE_COL[k], linewidth=1.3, aspect=None
            )
            t2 = zz[zz.membership == "tier2"]
            if len(t2):
                t2.dissolve().boundary.plot(
                    ax=ax, color=ZONE_COL[k], linewidth=1.1, linestyle=(0, (2.5, 1.5)), aspect=None
                )
        ev = polys[code]
        cov = load_silver(code, "coverage")
        if len(cov):
            cov.dissolve().boundary.plot(
                ax=ax, color="#555555", linewidth=0.6, linestyle=":", aspect=None
            )
        ev.plot(ax=ax, color="#0b4f8a", edgecolor="none", alpha=0.9, aspect=None)
        dates = sorted(ev.acq_date.dt.date.unique())
        ax.set_title(
            f"{code} — {label}\n{len(dates)} acquisition dates, {ev.aoi.nunique()} AOIs, {dates[0]} → {dates[-1]}",
            fontsize=9.5,
            loc="left",
        )
        ax.set_xlim(29.4, 35.15)
        ax.set_ylim(-1.55, 4.35)
        ax.set_aspect("equal")
        ax.set_axis_off()
    axes[0].legend(
        handles=[
            Patch(facecolor="#0b4f8a", label="CEMS observed flood extent (all acquisitions)"),
            Line2D([], [], color="#555555", ls=":", label="CEMS area of interest"),
            Line2D([], [], color=INK2, lw=1.3, label="zone tier 1"),
            Line2D([], [], color=INK2, lw=1.1, ls=(0, (2.5, 1.5)), label="zone tier 2"),
        ],
        loc="lower left",
        fontsize=7.5,
        frameon=False,
    )
    fig.suptitle(
        "Copernicus EMS rapid-mapping flood activations in Uganda (team CEMS archive) against the trigger zones",
        fontsize=12,
        fontweight="bold",
        x=0.02,
        ha="left",
    )
    fig.tight_layout(rect=(0, 0, 1, 0.9))
    fig.savefig(OUT / "cems_pass.png", dpi=150, facecolor="white")
    print("wrote", OUT / "cems_pass.png")


if __name__ == "__main__":
    main()
