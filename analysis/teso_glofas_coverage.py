"""Teso / Kyoga zone: which districts does the G5196 (Akokoro) GloFAS point cover?

Relates GloFAS v4 reanalysis discharge at the G5196 pixel to each candidate
district's FloodScan SFED daily mean (src/glofas_coverage.py): best lagged
correlation in the Aug-Dec flood season, and the conditional probability that
discharge is over its 2-yr level when the district's extent is over its own
2-yr level (and vice versa). Districts with best_corr >= 0.5 and
p_dis_given_sfed >= 0.4 are treated as covered.

Reads the local GloFAS reanalysis files (data/glofas/raw/reanalysis_uga_v4) and the
FloodScan district table (blob, or the local checkpoints while the build runs).
Writes outputs/teso_glofas_coverage.csv and outputs/teso_glofas_coverage.png.

Run:  uv run python analysis/teso_glofas_coverage.py
"""

import glob
import sys
from pathlib import Path

import geopandas as gpd
import matplotlib.pyplot as plt
import ocha_stratus as stratus
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.constants import GLOFAS_PIXEL_LONLAT, PROJECT_PREFIX, TESO_EXCLUDED
from src.datasources import glofas
from src.glofas_coverage import coverage_table
from src.zones import load_adm2, zone_districts

ROOT = Path(__file__).resolve().parent.parent
OUT_CSV = ROOT / "outputs" / "teso_glofas_coverage.csv"
OUT_PNG = ROOT / "outputs" / "teso_glofas_coverage.png"
COVERED = {
    "corr": 0.45,
    "p_dis_given_sfed": 0.5,
}  # anomaly corr (best lag <= 30 d); P on mean or max extent


def load_floodscan_adm2() -> pd.DataFrame:
    try:
        return stratus.load_parquet_from_blob(
            f"{PROJECT_PREFIX}/processed/floodscan/floodscan_adm2_daily.parquet", stage="dev"
        )
    except Exception as e:  # noqa: BLE001 — table not yet published; use the local checkpoints
        print(f"floodscan table not on blob yet ({e}); using local checkpoints")
        return pd.concat(
            [
                pd.read_parquet(p)
                for p in sorted(glob.glob(str(ROOT / "pipeline/.checkpoint_floodscan/*.parquet")))
            ]
        )


def main() -> None:
    lon, lat = GLOFAS_PIXEL_LONLAT
    dis = glofas.load_reanalysis_point(lat, lon)
    fs = load_floodscan_adm2()
    fs = fs[fs.date <= dis.index.max()]
    adm = load_adm2().set_index("ADM2_PCODE").ADM2_EN
    z = zone_districts("teso_kyoga")
    excl = load_adm2()[load_adm2().ADM2_EN.isin(TESO_EXCLUDED)].assign(
        zone="teso_kyoga", membership="excluded"
    )
    z = pd.concat([z, excl], ignore_index=True)
    z = gpd.GeoDataFrame(z, crs=load_adm2().crs)
    sfed = {adm[p]: fs[fs.pcode == p].set_index("date")["mean"].sort_index() for p in z.ADM2_PCODE}
    sfed_max = {
        adm[p]: fs[fs.pcode == p].set_index("date")["max"].sort_index() for p in z.ADM2_PCODE
    }
    tab = coverage_table(dis, sfed, sfed_max)
    tab["membership"] = tab.district.map(dict(zip(z.ADM2_EN, z.membership, strict=True)))
    p_best = tab[["p_dis_given_sfed", "p_dis_given_sfedmax"]].max(axis=1)
    tab["covered"] = (tab.best_corr >= COVERED["corr"]) & (p_best >= COVERED["p_dis_given_sfed"])
    # the district holding the point and its headwaters: FloodScan sees too little extent for a
    # correlation, but its rare floods coincide with high discharge — flag separately
    tab["catchment"] = tab.district.eq("Kapelebyong") & (p_best >= 0.7)
    tab["record"] = f"{dis.index.min():%Y}-{dis.index.max():%Y}"
    tab.to_csv(OUT_CSV, index=False)
    print(
        "\nEra split (anomaly corr, Aug-Dec): the point and the satellite agreed until ~2013 and drift after"
    )
    print(
        tab[["district", "membership", "corr_early", "corr_late", "best_corr"]]
        .round(2)
        .to_string(index=False)
    )
    pd.set_option("display.width", 200)
    print(tab.round(2).to_string())

    g = z.merge(tab, left_on="ADM2_EN", right_on="district")
    fig, axes = plt.subplots(1, 2, figsize=(13, 6))
    g.plot(
        column="best_corr",
        cmap="viridis",
        vmin=0,
        vmax=0.7,
        legend=True,
        ax=axes[0],
        edgecolor="white",
        linewidth=0.5,
        legend_kwds={"shrink": 0.6, "label": "best lagged corr, discharge -> SFED (Aug-Dec)"},
    )
    g.plot(
        column="p_dis_given_sfed",
        cmap="magma",
        vmin=0,
        vmax=0.6,
        legend=True,
        ax=axes[1],
        edgecolor="white",
        linewidth=0.5,
        legend_kwds={"shrink": 0.6, "label": "P(discharge > 2-yr | district extent > 2-yr)"},
    )
    for ax in axes:
        g[g.covered].boundary.plot(ax=ax, aspect=None, color="red", linewidth=1.5)
        g[g.catchment].boundary.plot(ax=ax, aspect=None, color="red", linewidth=1.5, linestyle="--")
        ax.plot(lon, lat, marker="^", color="black", markersize=10)
        for _, r in g.iterrows():
            c = r.geometry.representative_point()
            ax.annotate(r.district, (c.x, c.y), ha="center", fontsize=7)
        ax.set_axis_off()
    fig.suptitle(
        f"What G5196 covers — GloFAS v4 reanalysis vs FloodScan district extent, {tab.record.iloc[0]} (red = covered; dashed = point catchment)"
    )
    fig.tight_layout()
    fig.savefig(OUT_PNG, dpi=150)
    print("wrote", OUT_PNG)


if __name__ == "__main__":
    main()
