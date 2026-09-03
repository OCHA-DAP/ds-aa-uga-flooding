"""Coverage map: the four OCHA trigger zones, the GloFAS point, and other orgs' flood AA coverage.

Layout: one main map (zones, GloFAS points, lakes/rivers, FloodScan recurrence
backdrop, and a single hatched overlay for "any other organisation's flood AA")
plus a row of small panels, one per organisation, so each framework's footprint
is readable without stacking five hatch patterns on one map.

Backdrop: FloodScan Oct-Dec flood recurrence 1998-2025 (share of seasons with
SFED >= 0.05), from ds-seas5-skill/processed/uga/flood_ond_recurrence.tif (dev blob).
Basemap: Natural Earth 10m lakes, rivers and countries (data/ne/, downloaded once).
Zone colours: reference categorical slots blue/red/yellow/violet, validated all-pairs
(dataviz skill). External frameworks: src/frameworks.py.

Writes outputs/zones_coverage_map.png.   Run:  uv run python pipeline/zones_map.py
"""

import io
import sys
from pathlib import Path

import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
import ocha_stratus as stratus
import rasterio
from matplotlib import patheffects as pe
from matplotlib.colors import LinearSegmentedColormap
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
from rasterio.features import geometry_mask

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.constants import GLOFAS_KAPELEBYONG_LONLAT, GLOFAS_PIXEL_LONLAT, ZONES
from src.frameworks import EXTERNAL
from src.zones import load_adm2, zone_districts

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "outputs" / "zones_coverage_map.png"
NE = ROOT / "data" / "ne"
RECURRENCE_BLOB = "ds-seas5-skill/processed/uga/flood_ond_recurrence.tif"

ZONE_COL = {
    "teso_kyoga": "#2a78d6",
    "elgon": "#e34948",
    "karamoja": "#eda100",
    "adjumani": "#4a3aa7",
}
INK, INK2, MUTED = "#0b0b0b", "#52514e", "#8a8984"
WATER, WATER_EDGE = "#cfe3f3", "#8fb8d9"
LAND, NEIGHBOUR = "#fcfcfb", "#f1f0ec"
BLUES = LinearSegmentedColormap.from_list("rec", ["#ffffff", "#bcd7ee", "#4f93c9", "#0b4f8a"])
XLIM, YLIM = (29.4, 35.15), (-1.55, 4.35)
LAKE_LABELS = {
    "Lake Victoria": (33.0, -0.9),
    "Lake Kyoga": (32.9, 1.5),
    "Lake Albert": (30.9, 1.55),
}
KEY_DISTRICTS = {  # label a few anchor districts, offsets in points
    "Katakwi": (0, 0),
    "Amuria": (0, 0),
    "Kapelebyong": (0, 0),
    "Bududa": (-14, -8),
    "Bulambuli": (0, 6),
    "Moroto": (0, 0),
    "Kotido": (0, 0),
    "Kaabong": (0, 0),
    "Adjumani": (0, 0),
    "Moyo": (0, 0),
    "Obongi": (0, -6),
}


def halo(size=8, color=INK, weight="normal"):
    return {
        "fontsize": size,
        "color": color,
        "fontweight": weight,
        "path_effects": [pe.withStroke(linewidth=2.2, foreground="white", alpha=0.9)],
    }


def load_ne():
    box = (XLIM[0] - 1, YLIM[0] - 1, XLIM[1] + 1, YLIM[1] + 1)
    lakes = gpd.read_file(f"zip://{NE / 'ne_10m_lakes.zip'}").cx[box[0] : box[2], box[1] : box[3]]
    rivers = gpd.read_file(f"zip://{NE / 'ne_10m_rivers_lake_centerlines.zip'}").cx[
        box[0] : box[2], box[1] : box[3]
    ]
    countries = gpd.read_file(f"zip://{NE / 'ne_10m_admin_0_countries.zip'}").cx[
        box[0] : box[2], box[1] : box[3]
    ]
    return lakes, rivers, countries


def basemap(ax, adm2, lakes, rivers, countries, uganda, light=False):
    countries[countries.ADM0_A3 != "UGA"].plot(
        ax=ax, aspect=None, color=NEIGHBOUR, edgecolor="white", linewidth=0.8
    )
    gpd.GeoSeries([uganda], crs=adm2.crs).plot(ax=ax, aspect=None, color=LAND, edgecolor="none")
    if not light:
        adm2.boundary.plot(ax=ax, aspect=None, color="#dedcd6", linewidth=0.35)
    lakes.plot(ax=ax, aspect=None, color=WATER, edgecolor=WATER_EDGE, linewidth=0.5, zorder=4)
    rivers.plot(ax=ax, aspect=None, color=WATER_EDGE, linewidth=0.9, zorder=4)
    gpd.GeoSeries([uganda], crs=adm2.crs).boundary.plot(
        ax=ax, aspect=None, color=INK2, linewidth=0.9, zorder=5
    )
    ax.set_xlim(*XLIM)
    ax.set_ylim(*YLIM)
    ax.set_aspect("equal")
    ax.set_axis_off()


def recurrence_layer(ax, uganda):
    data = stratus.load_blob_data(RECURRENCE_BLOB, container_name="projects", stage="dev")
    with rasterio.open(io.BytesIO(data)) as ds:
        rec = ds.read(1)
        b = ds.bounds
        inside = ~geometry_mask([uganda], out_shape=rec.shape, transform=ds.transform, invert=False)
    rec = np.where(inside & (rec >= 0.1), rec, np.nan)
    return ax.imshow(
        rec,
        extent=(b.left, b.right, b.bottom, b.top),
        cmap=BLUES,
        vmin=0,
        vmax=1,
        alpha=0.9,
        zorder=3,
        interpolation="nearest",
    )


def main() -> None:
    adm2 = load_adm2()
    uganda = adm2.dissolve().geometry.iloc[0]
    lakes, rivers, countries = load_ne()
    ext = list(EXTERNAL.values())

    fig = plt.figure(figsize=(12.5, 15.2), facecolor="white")
    gs = fig.add_gridspec(
        2,
        len(ext),
        height_ratios=[4.6, 1.25],
        hspace=0.02,
        wspace=0.04,
        left=0.02,
        right=0.98,
        top=0.93,
        bottom=0.03,
    )
    ax = fig.add_subplot(gs[0, :])
    basemap(ax, adm2, lakes, rivers, countries, uganda)
    im = recurrence_layer(ax, uganda)

    # zones: candidates light, core solid, one outline round the whole zone
    for key in ZONES:
        g = zone_districts(key)
        col = ZONE_COL[key]
        g[g.membership == "candidate"].plot(
            ax=ax, aspect=None, color=col, alpha=0.16, edgecolor="white", linewidth=0.5, zorder=6
        )
        g[g.membership == "core"].plot(
            ax=ax, aspect=None, color=col, alpha=0.42, edgecolor="white", linewidth=0.5, zorder=6
        )
        g.dissolve().boundary.plot(ax=ax, aspect=None, color=col, linewidth=2.0, zorder=7)

    # any other organisation's flood AA: one hatch, no fill
    covered = sorted({d for fw in ext for d in fw.districts})
    adm2[adm2.ADM2_EN.isin(covered)].plot(
        ax=ax,
        aspect=None,
        facecolor="none",
        edgecolor=INK2,
        hatch="////",
        linewidth=0.5,
        alpha=0.85,
        zorder=8,
    )

    # GloFAS points
    ax.plot(
        *GLOFAS_PIXEL_LONLAT,
        marker="^",
        color=INK,
        markeredgecolor="white",
        markeredgewidth=1.2,
        linestyle="",
        markersize=13,
        zorder=10,
    )
    ax.plot(
        *GLOFAS_KAPELEBYONG_LONLAT,
        marker="^",
        color="white",
        markeredgecolor=INK,
        markeredgewidth=1.2,
        linestyle="",
        markersize=10,
        zorder=10,
    )
    ax.annotate(
        "GloFAS G5196\nAkokoro",
        GLOFAS_PIXEL_LONLAT,
        xytext=(-88, -40),
        textcoords="offset points",
        arrowprops={"arrowstyle": "-", "color": INK2, "lw": 0.7},
        zorder=11,
        **halo(8.5),
    )

    # labels
    for key, z in ZONES.items():
        c = (
            zone_districts(key, include_candidates=False)
            .dissolve()
            .geometry.iloc[0]
            .representative_point()
        )
        dx, dy = {
            "teso_kyoga": (-1.05, -0.05),
            "adjumani": (0.62, 0.25),
            "karamoja": (0, 0.25),
            "elgon": (0.25, -0.35),
        }[key]
        ax.annotate(
            z.label.split(" (")[0],
            (c.x + dx, c.y + dy),
            ha="center",
            zorder=12,
            **halo(11.5, ZONE_COL[key], "bold"),
        )
    for name, (dx, dy) in KEY_DISTRICTS.items():
        row = adm2[name == adm2.ADM2_EN]
        if len(row):
            c = row.geometry.iloc[0].representative_point()
            ax.annotate(
                name,
                (c.x, c.y),
                xytext=(dx, dy),
                textcoords="offset points",
                ha="center",
                zorder=12,
                **halo(7, INK2),
            )
    for name, (x, y) in LAKE_LABELS.items():
        ax.text(x, y, name, ha="center", fontsize=8, color="#3d6d95", style="italic", zorder=12)
    for name, (x, y) in {"Albert Nile": (31.32, 2.55), "Victoria Nile": (32.35, 2.2)}.items():
        ax.text(
            x,
            y,
            name,
            ha="center",
            fontsize=7,
            color="#3d6d95",
            style="italic",
            rotation=60 if "Albert" in name else 0,
            zorder=12,
        )
    for name, (x, y) in {
        "SOUTH SUDAN": (32.2, 4.15),
        "KENYA": (34.85, 0.35),
        "DR CONGO": (29.75, 1.0),
        "TANZANIA": (32.0, -1.4),
        "RWANDA": (29.9, -1.45),
    }.items():
        ax.text(x, y, name, ha="center", fontsize=7, color=MUTED, zorder=12)

    # title block
    fig.text(
        0.02,
        0.975,
        "Uganda flood anticipatory action — trigger zones and existing coverage",
        fontsize=17,
        fontweight="bold",
        color=INK,
        ha="left",
        va="top",
    )
    fig.text(
        0.02,
        0.952,
        "Four OCHA/CERF zones under design (solid = core districts, pale = candidates), the GloFAS reporting point, "
        "and the districts where other organisations already run flood anticipatory action (hatched; detail below).",
        fontsize=9.5,
        color=INK2,
        ha="left",
        va="top",
        wrap=True,
    )

    # legend + colorbar inside the main axes, top-left (over South Sudan / empty)
    handles = [
        Patch(
            facecolor=ZONE_COL[k],
            alpha=0.42,
            edgecolor=ZONE_COL[k],
            linewidth=1.5,
            label=z.label.split(" (")[0],
        )
        for k, z in ZONES.items()
    ]
    handles += [
        Patch(
            facecolor="#cccccc",
            alpha=0.35,
            edgecolor="none",
            label="candidate districts (to be ruled in/out)",
        ),
        Patch(
            facecolor="none",
            edgecolor=INK2,
            hatch="////",
            label="another organisation's flood AA (see panels)",
        ),
        Line2D(
            [],
            [],
            marker="^",
            color=INK,
            markeredgecolor="white",
            linestyle="",
            markersize=10,
            label="GloFAS G5196 (calibrated)",
        ),
        Line2D(
            [],
            [],
            marker="^",
            color="white",
            markeredgecolor=INK,
            linestyle="",
            markersize=8,
            label="other GloFAS fixed point (Kapelebyong)",
        ),
    ]
    leg = ax.legend(
        handles=handles,
        loc="upper left",
        bbox_to_anchor=(0.0, 1.0),
        fontsize=8,
        frameon=True,
        framealpha=0.95,
        edgecolor="#e6e6e6",
        borderpad=0.8,
        labelspacing=0.55,
    )
    leg.set_zorder(20)
    cax = ax.inset_axes([0.035, 0.53, 0.16, 0.014])
    cb = fig.colorbar(im, cax=cax, orientation="horizontal", ticks=[0.1, 0.5, 1.0])
    cb.ax.tick_params(labelsize=7, colors=INK2, length=2)
    cb.outline.set_edgecolor("#e6e6e6")
    cax.set_title(
        "FloodScan: share of Oct–Dec seasons flooded, 1998–2025",
        fontsize=7.5,
        color=INK2,
        loc="left",
        pad=3,
    )

    # small multiples: one per organisation
    for i, fw in enumerate(ext):
        sax = fig.add_subplot(gs[1, i])
        basemap(sax, adm2, lakes, rivers, countries, uganda, light=True)
        for key in ZONES:  # faint zone outlines for orientation
            zone_districts(key).dissolve().boundary.plot(
                ax=sax, aspect=None, color=ZONE_COL[key], linewidth=0.8, alpha=0.6, zorder=6
            )
        adm2[adm2.ADM2_EN.isin(fw.districts)].plot(
            ax=sax, aspect=None, color=INK2, alpha=0.75, edgecolor="white", linewidth=0.4, zorder=7
        )
        sax.set_title(
            f"{fw.org}\n{fw.label.split(' (')[0].split(' — ')[0].split(',')[0]}",
            fontsize=7.6,
            color=INK,
            loc="left",
            pad=2,
        )
        sax.text(
            0.97,
            0.97,
            f"{len(fw.districts)} district{'s' if len(fw.districts) != 1 else ''}",
            transform=sax.transAxes,
            fontsize=7,
            color=INK2,
            ha="right",
            va="top",
        )

    fig.text(
        0.02,
        0.005,
        "Sources: CODAB (FieldMaps); FloodScan (AER) via the team raster blob; GloFAS OWS reporting-point layers; "
        "framework documents as cited in docs/research-notes.md; Natural Earth 10m. OCHA Centre for Humanitarian Data, Sep 2026.",
        fontsize=7,
        color=MUTED,
        ha="left",
        va="bottom",
    )
    fig.savefig(OUT, dpi=170, facecolor="white")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
