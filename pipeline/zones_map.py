"""Coverage map: the four OCHA trigger zones, the GloFAS point, and other orgs' flood AA coverage.

Backdrop: FloodScan Oct-Dec flood recurrence 1998-2025 (share of seasons with
SFED >= 0.05), reused from ds-seas5-skill/processed/uga/flood_ond_recurrence.tif
(dev blob) — the "where does the satellite see recurrent flooding" layer.
Zones: filled by regime colour (core solid, candidate lighter). External
frameworks (src/frameworks.py): hatched outlines, one hatch per org.
GloFAS point plotted only once its coordinates are verified (src/constants).

Writes outputs/zones_coverage_map.png

Run:  uv run python pipeline/zones_map.py
"""

import io
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import ocha_stratus as stratus
import rasterio
from matplotlib.lines import Line2D
from matplotlib.patches import Patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.constants import ZONES
from src.frameworks import EXTERNAL
from src.zones import load_adm2, zone_districts

OUT = Path(__file__).resolve().parent.parent / "outputs" / "zones_coverage_map.png"
RECURRENCE_BLOB = "ds-seas5-skill/processed/uga/flood_ond_recurrence.tif"

ZONE_COL = {
    "teso_kyoga": "#1f77b4",
    "elgon": "#b2182b",
    "karamoja": "#e08214",
    "adjumani": "#5e3c99",
}
HATCH = ["///", "\\\\\\", "xxx", "..."]
from src.constants import GLOFAS_PIXEL_LONLAT

GLOFAS_POINT = GLOFAS_PIXEL_LONLAT


def main() -> None:
    adm2 = load_adm2()
    fig, ax = plt.subplots(figsize=(10, 11))

    # backdrop
    try:
        data = stratus.load_blob_data(RECURRENCE_BLOB, container_name="projects", stage="dev")
        with rasterio.open(io.BytesIO(data)) as ds:
            rec = ds.read(1)
            b = ds.bounds
        rec = np.where(rec > 0.02, rec, np.nan)
        # clip to Uganda so neighbouring countries' wetlands don't distract
        from rasterio.features import geometry_mask

        with rasterio.open(io.BytesIO(data)) as ds:
            inside = ~geometry_mask(
                [adm2.dissolve().geometry.iloc[0]],
                out_shape=rec.shape,
                transform=ds.transform,
                invert=False,
            )
        rec = np.where(inside, rec, np.nan)
        im = ax.imshow(
            rec,
            extent=(b.left, b.right, b.bottom, b.top),
            cmap="Blues",
            vmin=0,
            vmax=1,
            alpha=0.85,
            zorder=1,
        )
        cb = fig.colorbar(im, ax=ax, shrink=0.35, pad=0.01, location="left")
        cb.set_label("FloodScan: share of Oct–Dec seasons flooded (1998–2025)", fontsize=8)
        cb.ax.tick_params(labelsize=7)
    except Exception as e:  # noqa: BLE001 — backdrop is optional; say so on the figure
        ax.text(
            0.01,
            0.01,
            f"(recurrence backdrop unavailable: {e})",
            transform=ax.transAxes,
            fontsize=7,
        )

    adm2.boundary.plot(ax=ax, aspect=None, color="#bbbbbb", linewidth=0.3, zorder=2)

    # zones
    for key in ZONES:
        g = zone_districts(key)
        col = ZONE_COL[key]
        g[g.membership == "candidate"].plot(
            ax=ax, aspect=None, color=col, alpha=0.18, edgecolor=col, linewidth=0.6, zorder=3
        )
        g[g.membership == "core"].plot(
            ax=ax, aspect=None, color=col, alpha=0.45, edgecolor=col, linewidth=1.2, zorder=4
        )
        g.dissolve().boundary.plot(ax=ax, aspect=None, color=col, linewidth=1.8, zorder=5)

    # external frameworks
    ext_handles = []
    for i, fw in enumerate(EXTERNAL.values()):
        g = adm2[adm2.ADM2_EN.isin(fw.districts)]
        missing = set(fw.districts) - set(g.ADM2_EN)
        if missing:
            print(f"{fw.key}: districts not in CODAB: {sorted(missing)}")
        g.plot(
            ax=ax,
            aspect=None,
            facecolor="none",
            edgecolor="#222222",
            hatch=HATCH[i % len(HATCH)],
            linewidth=0.8,
            zorder=6,
        )
        ext_handles.append(
            Patch(
                facecolor="none",
                edgecolor="#222222",
                hatch=HATCH[i % len(HATCH)],
                label=f"{fw.org} — {fw.label}" + ("" if fw.verified else " (unverified)"),
            )
        )

    if GLOFAS_POINT:
        ax.plot(*GLOFAS_POINT, marker="^", color="black", markersize=11, zorder=8)
        ax.annotate(
            "GloFAS G5196\nAkokoro",
            GLOFAS_POINT,
            xytext=(6, 6),
            textcoords="offset points",
            fontsize=8,
        )

    # labels
    for key, zone in ZONES.items():
        c = (
            zone_districts(key, include_candidates=False)
            .dissolve()
            .geometry.iloc[0]
            .representative_point()
        )
        ax.annotate(
            zone.label.split(" (")[0],
            (c.x, c.y),
            ha="center",
            fontsize=9,
            fontweight="bold",
            color=ZONE_COL[key],
            zorder=9,
            bbox=dict(boxstyle="round,pad=0.2", fc="white", ec="none", alpha=0.75),
        )

    zone_handles = [
        Patch(facecolor=ZONE_COL[k], alpha=0.45, edgecolor=ZONE_COL[k], label=f"{z.label} — core")
        for k, z in ZONES.items()
    ]
    zone_handles.append(
        Patch(
            facecolor="#888888",
            alpha=0.18,
            edgecolor="#888888",
            label="candidate districts (to be ruled in/out)",
        )
    )
    if GLOFAS_POINT:
        zone_handles.append(
            Line2D(
                [],
                [],
                marker="^",
                color="black",
                linestyle="",
                markersize=9,
                label="GloFAS reporting point G5196",
            )
        )
    leg1 = ax.legend(
        handles=zone_handles,
        loc="lower left",
        fontsize=7.5,
        title="OCHA/CERF trigger zones",
        title_fontsize=8,
        framealpha=0.9,
    )
    ax.add_artist(leg1)
    if ext_handles:
        ax.legend(
            handles=ext_handles,
            loc="lower right",
            fontsize=7.5,
            title="Other organisations' flood AA",
            title_fontsize=8,
            framealpha=0.9,
        )

    ax.set_xlim(29.4, 35.2)
    ax.set_ylim(-1.6, 4.4)
    ax.set_aspect("equal")
    ax.set_axis_off()
    ax.set_title(
        "Uganda flood anticipatory action — trigger zones and existing coverage", fontsize=12
    )
    fig.tight_layout()
    OUT.parent.mkdir(exist_ok=True)
    fig.savefig(OUT, dpi=170, bbox_inches="tight")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
