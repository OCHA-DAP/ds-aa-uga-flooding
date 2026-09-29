"""One map per trigger zone: what the zone covers, and where each trigger indicator is measured.

The draft triggers read their indicators in very different places: one GloFAS river cell
(Teso), a single rainfall average over a block of districts (Elgon), each district on its own
(Karamoja), a lake 250 km from the zone (Adjumani). These maps put that geometry next to the
zone's tier-1 and tier-2 districts so a working group can see it at a glance.

What each zone's trigger reads is set in INDICATORS below. Edit it there; the drawing code is
generic. Basemap style, Natural Earth layers and zone colours come from pipeline/zones_map.py.
Optional local inputs, each skipped with a message if absent:
  data/glofas/thresholds/  GloFAS v4 5-year return levels, drawn as the GloFAS river cells
  outputs/triggers/ifrc_units.csv  the IFRC IBF portal's threshold cell per admin unit
                                   (level 2 = district: the cell of its highest official RL5)

Partner (unpublished) trigger names, e.g. which partner triggers also read a GloFAS point, are
looked up at run time in the gitignored config/private_frameworks.local.json and are never
written here. When that file is present the maps are restricted-page material. Pass --public
to leave partner names off.

Writes outputs/triggers/map_<zone>.png.
Run:  uv run python pipeline/zone_trigger_maps.py [--public]
"""

import argparse
import math
import sys
import textwrap
from pathlib import Path

import geopandas as gpd
import matplotlib.pyplot as plt
import pandas as pd
import xarray as xr
from matplotlib.colors import to_rgba
from matplotlib.lines import Line2D
from matplotlib.patches import FancyArrowPatch, Patch, Rectangle
from shapely.geometry import Point, box
from shapely.ops import nearest_points, unary_union

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from zones_map import (
    INK,
    INK2,
    LAND,
    MUTED,
    NEIGHBOUR,
    WATER,
    WATER_EDGE,
    XLIM,
    YLIM,
    ZONE_COL,
    halo,
    load_ne,
)

from src.constants import GLOFAS_PIXEL_LONLAT, ZONES
from src.frameworks import EXTERNAL, load_private
from src.zones import load_adm2

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "outputs" / "triggers"
RL5 = ROOT / "data" / "glofas" / "thresholds" / "flood_threshold_glofas_v4_rl_5.0.nc"
RL5_MIN = 25.0  # m3/s: a GloFAS cell is drawn as river if its 5-year flow is at least this
IFRC_UNITS = OUT_DIR / "ifrc_units.csv"

# G5220 is read at its LISFLOOD v4 cell (as in analysis/existing_triggers.py); the gauge itself
# sits 9 km east, at 34.158E 0.937N.
G5220_PIXEL_LONLAT = (34.075, 0.925)
G5075_LONLAT = (33.79, 0.827)  # Mpologoma at Budumba, a station on the Red Cross IBF portal

# --- What each zone's trigger reads, and where ------------------------------------------------
# kinds:
#   point           a GloFAS reporting point (role "draft" = ours, "other" = comparator)
#   whole_district  a rule evaluated over each whole district (the IFRC EAP districts)
#   ifrc_cells      the IFRC portal's threshold cell for each listed district (ifrc_units.csv)
#   area_mean       one value averaged over the union of the districts
#   per_district    each district against its own threshold; any one activates the zone
#   lake            a lake-level series (satellite altimetry)
# "districts": "zone" means tier 1 + tier 2. "offset(s)" are label offsets in points.
INDICATORS = {
    "teso_kyoga": {
        "summary": (
            "Teso's trigger is the IFRC/URCS one as the IBF portal runs it: each district, and "
            "each of its counties and sub-counties, is judged at the cell of its highest official "
            "GloFAS 5-year flow. Amuria and Kapelebyong read the Akokoro; Katakwi, Soroti and "
            "Ngora the Lake Bisina–Awoja channel; Serere Lake Kyoga. G5196 is where we first read it."
        ),
        "glofas_cells": True,
        "items": [
            {
                "kind": "point",
                "role": "draft",
                "lonlat": GLOFAS_PIXEL_LONLAT,
                "label": "G5196 (earlier reading)",
                "offset": (56, 17),
                "legend": "GloFAS G5196 Akokorio at Uganda: where we first read the IFRC trigger, one cell only",
            },
            {
                "kind": "whole_district",
                "districts": EXTERNAL["ifrc_eap"].districts,
                "legend": "IFRC: each district assessed over its whole area (hatched: EAP districts)",
            },
            {
                "kind": "ifrc_cells",
                "districts": (*ZONES["teso_kyoga"].core, *ZONES["teso_kyoga"].tier2, "Kumi"),
                "offsets": {
                    "Kapelebyong": (61, 3),
                    "Amuria": (-92, 47),
                    "Katakwi": (-112, 16),
                    "Soroti": (-98, 2),
                    "Kumi": (62, -26),
                    "Ngora": (-60, -13),
                    "Serere": (0, 34),
                },
                "legend": "Teso's trigger (IFRC portal): district read here, at the cell of its highest official GloFAS 5-yr flow (RL5)",
            },
            {
                "kind": "point",
                "role": "other",
                "lonlat": G5075_LONLAT,
                "label": "G5075 Mpologoma at Budumba",
                "offset": (12, -14),
                "legend": "G5075 Mpologoma at Budumba: the other Red Cross portal station nearby",
            },
        ],
    },
    "elgon": {
        "summary": (
            "The draft trigger is a single number: the 5-day rainfall forecast averaged over all 15 "
            "districts, slopes and lowlands together. G5220 on the Manafwa is the only GloFAS "
            "reporting point in the sub-region; the IFRC portal reads each of its districts at "
            "that district's own cell."
        ),
        "glofas_cells": True,
        "items": [
            {
                "kind": "area_mean",
                "districts": "zone",
                "label": "rainfall averaged\nover this area",
                "label_at": (33.5, 1.74),
                "legend": "Draft trigger: 5-day rainfall forecast averaged over this whole area (all 15 districts)",
            },
            {
                "kind": "point",
                "role": "other",
                "lonlat": G5220_PIXEL_LONLAT,
                "label": "G5220",
                "base_tag": "IFRC",
                "offset": (60, -78),
                "legend": "GloFAS G5220 Manafwa at Butaleja",
            },
            {
                "kind": "ifrc_cells",
                "districts": ("Butaleja", "Manafwa", "Bududa", "Bulambuli", "Sironko"),
                "offsets": {
                    "Butaleja": (-62, -30),
                    "Manafwa": (96, -53),
                    "Bududa": (78, -2),
                    "Bulambuli": (-40, 72),
                    "Sironko": (-68, 12),
                },
                "legend": "Teso's trigger (IFRC portal): district read here, at the cell of its highest official GloFAS 5-yr flow (RL5)",
            },
        ],
    },
    "karamoja": {
        "summary": (
            "Each of the nine districts is assessed separately against its own rainfall threshold; "
            "any one district activates the zone. A FloodScan observed-flood option would use the "
            "same district geometry."
        ),
        "items": [
            {
                "kind": "per_district",
                "districts": "zone",
                "legend": "Draft trigger: 5-day rainfall forecast, each district assessed separately against its own threshold (any one activates the zone; a FloodScan option would be per district too)",
            },
        ],
    },
    "adjumani": {
        "summary": (
            "Two legs, measured about {lake_km} km apart. Rain leg: the 5-day rainfall forecast in "
            "each of the six zone districts separately. Lake leg: the water level of Lake Kyoga, "
            "upstream on the Nile system (Kyoga to Victoria Nile to Lake Albert to Albert Nile)."
        ),
        "extent_include": ("Lake Kyoga", "Lake Albert"),
        "highlight_rivers": ("Victoria Nile", "Albert Nile"),
        "items": [
            {
                "kind": "lake",
                "lake": "Lake Kyoga",
                "label": "Lake leg: Lake Kyoga water level\n(satellite altimetry)",
                "offset": (-10, -34),
                "legend": "Lake leg: Lake Kyoga water level (satellite altimetry)",
            },
            {
                "kind": "per_district",
                "districts": "zone",
                "legend": "Rain leg: 5-day rainfall forecast, each of the 6 districts assessed separately",
            },
        ],
    },
}

# --- Cosmetic placement, per zone: district-name offsets (points), river labels (lon, lat, deg)
LAYOUT = {
    "teso_kyoga": {"labels": {"Katakwi": (10, 30), "Amuria": (-10, 10)}, "rivers": {}},
    "elgon": {
        "labels": {"Manafwa": (-22, 4), "Namisindwa": (24, 2), "Mbale": (-8, 6)},
        "rivers": {},
    },
    "karamoja": {"labels": {"Amudat": (12, -11), "Nakapiripirit": (-12, -11)}, "rivers": {}},
    "adjumani": {
        "labels": {"Pakwach": (26, -2), "Nebbi": (-4, -11)},
        "rivers": {"Albert Nile": (31.55, 2.75, 62), "Victoria Nile": (32.1, 2.2, 0)},
    },
}

GLOFAS_CELL = "#5b9bd0"
NILE = "#4f8fc4"
DISTRICT_EDGE = "#cfcdc6"
FIG_W, PAD, FOOT_H = 9.0, 0.18, 0.42  # inches
SOURCES = {
    "base": "Draft for discussion. Districts: CODAB (FieldMaps). Lakes, rivers, borders: Natural Earth 10m.",
    "glofas": "GloFAS v4 reporting points and 5-yr return levels: Copernicus EMS.",
    "ifrc": "IFRC portal cells: our reconstruction from the official GloFAS RL5 (outputs/triggers/ifrc_units.csv).",
    "end": "OCHA Centre for Humanitarian Data, Sep 2026.",
}


# --- geometry helpers -------------------------------------------------------------------------
def km(a, b) -> float:
    """Great-circle distance between two (lon, lat) points."""
    lon1, lat1, lon2, lat2 = map(math.radians, (*a, *b))
    h = (
        math.sin((lat2 - lat1) / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    )
    return 2 * 6371 * math.asin(math.sqrt(h))


def compass(a, b) -> str:
    ang = math.degrees(math.atan2(b[1] - a[1], (b[0] - a[0]) * math.cos(math.radians(a[1]))))
    return ["E", "NE", "N", "NW", "W", "SW", "S", "SE"][int(((ang + 22.5) % 360) // 45)]


def zone_names(zone_key: str, which) -> tuple[str, ...]:
    z = ZONES[zone_key]
    return z.core + z.tier2 if which == "zone" else tuple(which)


def frame(zone_key: str, adm2, lakes):
    """Zone extent (plus any lakes the zone's trigger reads) with a margin, as (W, S, E, N)."""
    geoms = list(adm2[adm2.ADM2_EN.isin(zone_names(zone_key, "zone"))].geometry)
    geoms += list(lakes[lakes.name.isin(INDICATORS[zone_key].get("extent_include", ()))].geometry)
    w, s, e, n = unary_union(geoms).bounds
    pad = max(0.2, 0.07 * max(e - w, n - s))
    return w - pad, s - pad, e + pad, n + pad


def fit(ext, aspect):
    """Grow the shorter side of an extent so it fills axes of the given width/height ratio."""
    w, s, e, n = ext
    cx, cy, dx, dy = (w + e) / 2, (s + n) / 2, e - w, n - s
    if dx / dy < aspect:
        dx = dy * aspect
    else:
        dy = dx / aspect
    return cx - dx / 2, cy - dy / 2, cx + dx / 2, cy + dy / 2


def inside(ext, x, y, margin=0.0) -> bool:
    w, s, e, n = ext
    mx, my = margin * (e - w), margin * (n - s)
    return w + mx <= x <= e - mx and s + my <= y <= n - my


# --- figure layout ----------------------------------------------------------------------------
def make_figure(ext, top_h: float):
    """Map left with a legend column (tall or square zones), or map on top with a legend row
    (wide zones). Returns the figure, map and locator axes, the extent fitted to the map axes,
    where the legends go, and the figure height in inches."""
    aspect = (ext[2] - ext[0]) / (ext[3] - ext[1])
    if aspect < 1.15:
        map_w = 5.75
        map_h = min(max(map_w / aspect, 6.2), 7.0)
        fig_h = top_h + map_h + FOOT_H
        fig = plt.figure(figsize=(FIG_W, fig_h), facecolor="white")
        ax = fig.add_axes((PAD / FIG_W, FOOT_H / fig_h, map_w / FIG_W, map_h / fig_h))
        px, inset_h = PAD + map_w + 0.2, 1.75
        iax = fig.add_axes(
            (
                px / FIG_W,
                (FOOT_H + map_h - inset_h) / fig_h,
                (FIG_W - px - PAD) / FIG_W,
                inset_h / fig_h,
            )
        )
        legend_at = {
            "mode": "column",
            "x": px / FIG_W,
            "y": (FOOT_H + map_h - inset_h - 0.2) / fig_h,
            "wrap": (36, 36),
        }
    else:
        map_w, panel_h = FIG_W - 2 * PAD, 2.45
        map_h = min(max(map_w / aspect, 4.4), 6.0)
        fig_h = top_h + map_h + panel_h + FOOT_H
        fig = plt.figure(figsize=(FIG_W, fig_h), facecolor="white")
        ax = fig.add_axes((PAD / FIG_W, (FOOT_H + panel_h) / fig_h, map_w / FIG_W, map_h / fig_h))
        inset_w = 2.1
        iax = fig.add_axes(
            (
                (FIG_W - PAD - inset_w) / FIG_W,
                (FOOT_H + 0.05) / fig_h,
                inset_w / FIG_W,
                (panel_h - 0.2) / fig_h,
            )
        )
        legend_at = {
            "mode": "row",
            "x": PAD / FIG_W,
            "x2": (PAD + 3.5) / FIG_W,
            "y": (FOOT_H + panel_h - 0.12) / fig_h,
            "wrap": (46, 38),
        }
    return fig, ax, iax, fit(ext, map_w / map_h), legend_at, fig_h


# --- layers -----------------------------------------------------------------------------------
# z-order: land 1-2, zone fills 6, water 6.3-6.4 (district polygons include lake water),
# GloFAS cells 6.5, border 6.6, zone outlines 7-7.2, indicators 8-11, labels 12, scale bar 13.
def draw_basemap(ax, ext, adm2, uganda, lakes, rivers, countries, spec, zone_key):
    countries[countries.ADM0_A3 != "UGA"].plot(
        ax=ax, aspect=None, color=NEIGHBOUR, edgecolor="white", linewidth=0.8, zorder=1
    )
    gpd.GeoSeries([uganda], crs=adm2.crs).plot(
        ax=ax, aspect=None, color=LAND, edgecolor="none", zorder=1.5
    )
    adm2.boundary.plot(ax=ax, aspect=None, color=DISTRICT_EDGE, linewidth=0.5, zorder=2)
    lakes.plot(ax=ax, aspect=None, color=WATER, edgecolor=WATER_EDGE, linewidth=0.5, zorder=6.3)
    rivers.plot(ax=ax, aspect=None, color=WATER_EDGE, linewidth=0.9, zorder=6.35)
    hl = rivers[rivers.name.isin(spec.get("highlight_rivers", ()))]
    if len(hl):
        hl.plot(ax=ax, aspect=None, color=NILE, linewidth=2.2, zorder=6.4)
    gpd.GeoSeries([uganda], crs=adm2.crs).boundary.plot(
        ax=ax, aspect=None, color=INK2, linewidth=1.0, zorder=6.6
    )

    # neighbouring countries: name at the middle of the part that is on the map
    frame_box = box(*ext)
    for _, c in countries[countries.ADM0_A3 != "UGA"].iterrows():
        part = c.geometry.intersection(frame_box)
        if part.area > 0.04 * frame_box.area:
            p = part.representative_point()
            ax.text(p.x, p.y, c.NAME.upper(), ha="center", fontsize=7.5, color=MUTED, zorder=3)

    # lakes on the map get a name, unless an indicator already labels them
    labelled = {i.get("lake") for i in spec["items"]}
    for _, lk in lakes.dropna(subset=["name"]).iterrows():
        p = lk.geometry.representative_point()
        if lk["name"] in labelled or lk.geometry.area < 0.004 or not inside(ext, p.x, p.y, 0.03):
            continue
        ax.text(
            p.x,
            p.y,
            lk["name"],
            ha="center",
            va="center",
            fontsize=7.5,
            color="#3d6d95",
            style="italic",
            zorder=12,
        )
    for name, (x, y, rot) in LAYOUT[zone_key]["rivers"].items():
        if inside(ext, x, y):
            ax.text(
                x,
                y,
                name,
                ha="center",
                va="center",
                rotation=rot,
                zorder=12,
                style="italic",
                **halo(7.5, "#3d6d95"),
            )


def draw_glofas_cells(ax, ext, lakes) -> bool:
    """GloFAS river network as the cells whose 5-year flow reaches RL5_MIN (dots, sized by flow)."""
    if not RL5.exists():
        print(f"  ({RL5.relative_to(ROOT)} absent: GloFAS river cells not drawn)")
        return False
    da = xr.open_dataset(RL5)["rl_5.0"].sel(
        lat=slice(ext[3] + 0.05, ext[1] - 0.05), lon=slice(ext[0] - 0.05, ext[2] + 0.05)
    )
    df = da.where(da >= RL5_MIN).to_dataframe().dropna().reset_index()
    pts = gpd.GeoDataFrame(df, geometry=gpd.points_from_xy(df.lon, df.lat), crs=lakes.crs)
    pts = pts[~pts.within(lakes.union_all())]
    size = 5 + 9 * (pts["rl_5.0"].clip(upper=3000) / RL5_MIN).apply(math.log10)
    ax.scatter(pts.lon, pts.lat, s=size, color=GLOFAS_CELL, linewidths=0, zorder=6.5)
    return True


def draw_zone(ax, zone_key, adm2):
    z, col = ZONES[zone_key], ZONE_COL[zone_key]
    t1, t2 = adm2[adm2.ADM2_EN.isin(z.core)], adm2[adm2.ADM2_EN.isin(z.tier2)]
    if len(t2):
        t2.plot(ax=ax, aspect=None, facecolor=to_rgba(col, 0.10), edgecolor="none", zorder=6)
        t2.plot(
            ax=ax,
            aspect=None,
            facecolor="none",
            edgecolor=to_rgba(col, 0.55),
            hatch="....",
            linewidth=0,
            zorder=6,
        )
        t2.boundary.plot(
            ax=ax, aspect=None, color=col, linewidth=1.4, linestyle=(0, (3, 2)), zorder=7
        )
    t1.plot(ax=ax, aspect=None, facecolor=to_rgba(col, 0.35), edgecolor="none", zorder=6)
    t1.boundary.plot(ax=ax, aspect=None, color=col, linewidth=1.5, zorder=7.2)


def draw_district_names(ax, ext, zone_key, adm2, marked: set[str]):
    """Zone districts in ink (tier 1 bold); districts with a marker get their name below it;
    every other district on the map gets a small grey name."""
    z = ZONES[zone_key]
    offsets = LAYOUT[zone_key]["labels"]
    for _, d in adm2.iterrows():
        name, p = d.ADM2_EN, d.geometry.representative_point()
        if name in z.core or name in z.tier2:
            dx, dy = offsets.get(name, (0, -11) if name in marked else (0, 0))
            ax.annotate(
                name,
                (p.x, p.y),
                xytext=(dx, dy),
                textcoords="offset points",
                ha="center",
                va="center",
                zorder=12,
                **halo(8, INK, "bold" if name in z.core else "normal"),
            )
        elif inside(ext, p.x, p.y, 0.025):
            ax.text(p.x, p.y, name, ha="center", va="center", fontsize=6, color=MUTED, zorder=3.5)


def point_label(item, public: bool) -> tuple[str, str]:
    """Map label and legend label for a GloFAS point, with any partner triggers that read the
    same cell (from the gitignored config) unless --public."""
    tags = [item["base_tag"]] if item.get("base_tag") else []
    extra = []
    if not public:
        x, y = item["lonlat"]
        for s in load_private().get("trigger_specs", []):
            if "lat" in s and abs(s["lon"] - x) < 0.03 and abs(s["lat"] - y) < 0.03:
                extra.append(s["short"])
    label, legend = item["label"], item["legend"]
    if tags or extra:
        label = f"{label} ({' / '.join(tags + extra)} point)"
    if tags:
        legend += f": {' and '.join(tags)} stand-in point"
    if extra:
        legend += f"; also read by {', '.join(extra)} [partner, restricted]"
    return label, legend


def off_map_pointer(ax, ext, xy, text):
    """An arrow at the map edge pointing towards a point that is off the map."""
    x, y = xy
    w, s, e, n = ext
    cx = min(max(x, w + 0.12 * (e - w)), e - 0.12 * (e - w))
    cy = min(max(y, s + 0.01 * (n - s)), n - 0.01 * (n - s))
    ux = 0 if cx == x else (1 if x > cx else -1)
    uy = 0 if cy == y else (1 if y > cy else -1)
    ax.annotate(
        text,
        (cx, cy),
        xytext=(-ux * 34, -uy * 34),
        textcoords="offset points",
        ha="center",
        va="center",
        arrowprops={
            "arrowstyle": "-|>",
            "color": INK2,
            "lw": 1.0,
            "relpos": (0.5 + 0.5 * ux, 0.5 + 0.5 * uy),
            "shrinkA": 3,
        },
        zorder=11,
        **halo(7.5, INK2),
    )


def lake_geometry(zone_key, adm2, lakes, lake_name):
    """The measured lake's marker point, the nearest point of the zone's tier 1 to it, and the
    distances (km) from the lake to that edge and to the tier-1 centroid."""
    p = unary_union(lakes[lakes.name == lake_name].geometry).representative_point()
    core = unary_union(adm2[adm2.ADM2_EN.isin(ZONES[zone_key].core)].geometry)
    edge = nearest_points(core, p)[0]
    return (
        p,
        edge,
        km((p.x, p.y), (edge.x, edge.y)),
        km((p.x, p.y), (core.centroid.x, core.centroid.y)),
    )


def lake_distance_km(zone_key, adm2, lakes) -> str:
    """Lake-to-zone-centre distance for the subtitle, rounded to 10 km ("" if no lake leg)."""
    for item in INDICATORS[zone_key]["items"]:
        if item["kind"] == "lake":
            return f"{round(lake_geometry(zone_key, adm2, lakes, item['lake'])[3], -1):.0f}"
    return ""


def draw_indicators(ax, ext, zone_key, adm2, lakes, public: bool):
    """Draw each indicator; return (legend handle, label) pairs, the districts given a marker,
    and the set of indicator kinds actually drawn."""
    spec, handles, marked, drawn = INDICATORS[zone_key], [], set(), set()
    draft = next(
        (i["lonlat"] for i in spec["items"] if i["kind"] == "point" and i["role"] == "draft"),
        None,
    )
    for item in spec["items"]:
        kind = item["kind"]
        if kind == "point":
            x, y = item["lonlat"]
            is_draft = item["role"] == "draft"
            label, legend = point_label(item, public)
            style = {
                "marker": "^",
                "linestyle": "",
                "markersize": 13 if is_draft else 10,
                "color": INK if is_draft else "white",
                "markeredgecolor": "white" if is_draft else INK,
                "markeredgewidth": 1.2 if is_draft else 1.5,
            }
            if inside(ext, x, y):
                ax.plot(x, y, zorder=10.5, **style)
                ax.annotate(
                    label,
                    (x, y),
                    xytext=item.get("offset", (10, -14)),
                    textcoords="offset points",
                    ha="center",
                    va="center",
                    arrowprops={"arrowstyle": "-", "color": INK, "lw": 0.8, "shrinkB": 6},
                    zorder=11,
                    **halo(8.5, INK, "bold" if is_draft else "normal"),
                )
            else:
                ref = draft or ((ext[0] + ext[2]) / 2, (ext[1] + ext[3]) / 2)
                away = f"{km(ref, (x, y)):.0f} km {compass(ref, (x, y))}"
                away += " of G5196" if draft else " of the map centre"
                off_map_pointer(ax, ext, (x, y), f"{label}\n{away} (off map)")
                legend += " (off map: see arrow)"
            handles.append((Line2D([], [], **style), legend))

        elif kind == "whole_district":
            g = adm2[adm2.ADM2_EN.isin(item["districts"])]
            g.plot(
                ax=ax,
                aspect=None,
                facecolor="none",
                edgecolor=to_rgba(INK2, 0.6),
                hatch="////",
                linewidth=0,
                zorder=8,
            )
            g.boundary.plot(ax=ax, aspect=None, color=INK2, linewidth=1.1, zorder=8)
            h = Patch(facecolor="white", edgecolor=to_rgba(INK2, 0.8), hatch="////", linewidth=1.1)
            handles.append((h, item["legend"]))

        elif kind == "ifrc_cells":
            if not IFRC_UNITS.exists():
                print(f"  ({IFRC_UNITS.relative_to(ROOT)} absent: IFRC portal cells not drawn)")
                continue
            units = pd.read_csv(IFRC_UNITS)
            units = units[(units.level == 2) & units.name.isin(item["districts"])]
            style = {
                "marker": "s",
                "linestyle": "",
                "markersize": 7.5,
                "color": INK2,
                "markeredgecolor": "white",
                "markeredgewidth": 1.1,
            }
            for _, u in units.iterrows():
                ax.plot(u.thr_lon, u.thr_lat, zorder=10.2, **style)
                ax.annotate(
                    f"IFRC: {u['name']} read here\n(RL5 {u.threshold:.0f} m³/s)",
                    (u.thr_lon, u.thr_lat),
                    xytext=item["offsets"].get(u["name"], (40, -20)),
                    textcoords="offset points",
                    ha="center",
                    va="center",
                    arrowprops={"arrowstyle": "-", "color": INK2, "lw": 0.6, "shrinkB": 4},
                    zorder=11,
                    **halo(6.8, INK2),
                )
            handles.append((Line2D([], [], **style), item["legend"]))

        elif kind == "area_mean":
            names = zone_names(zone_key, item["districts"])
            area = unary_union(adm2[adm2.ADM2_EN.isin(names)].geometry)
            ring = gpd.GeoSeries([area], crs=adm2.crs).boundary
            ring.plot(ax=ax, aspect=None, color="white", linewidth=5.0, zorder=8.8)
            ring.plot(ax=ax, aspect=None, color=INK, linewidth=2.4, zorder=9)
            tx, ty = item["label_at"]
            target = nearest_points(area.boundary, Point(tx, ty))[0]
            ax.annotate(
                item["label"],
                (target.x, target.y),
                xytext=(tx, ty),
                ha="center",
                va="center",
                arrowprops={"arrowstyle": "-|>", "color": INK, "lw": 1.1, "shrinkA": 4},
                zorder=11,
                **halo(9, INK, "bold"),
            )
            handles.append((Line2D([], [], color=INK, linewidth=2.4), item["legend"]))

        elif kind == "per_district":
            g = adm2[adm2.ADM2_EN.isin(zone_names(zone_key, item["districts"]))]
            style = {
                "marker": "o",
                "linestyle": "",
                "markersize": 7,
                "color": INK,
                "markeredgecolor": "white",
                "markeredgewidth": 1.2,
            }
            for _, d in g.iterrows():
                p = d.geometry.representative_point()
                ax.plot(p.x, p.y, zorder=10, **style)
                marked.add(d.ADM2_EN)
            handles.append((Line2D([], [], **style), item["legend"]))

        elif kind == "lake":
            lakes[lakes.name == item["lake"]].boundary.plot(
                ax=ax, aspect=None, color=INK, linewidth=1.6, zorder=9
            )
            p, edge, to_edge, to_centre = lake_geometry(zone_key, adm2, lakes, item["lake"])
            style = {
                "marker": "D",
                "linestyle": "",
                "markersize": 10,
                "color": INK,
                "markeredgecolor": "white",
                "markeredgewidth": 1.3,
            }
            ax.plot(p.x, p.y, zorder=10, **style)
            ax.annotate(
                item["label"],
                (p.x, p.y),
                xytext=item.get("offset", (10, -24)),
                textcoords="offset points",
                ha="center",
                va="top",
                zorder=11,
                **halo(8.5, INK, "bold"),
            )
            # how far the measured lake is from the zone it triggers for
            ax.add_patch(
                FancyArrowPatch(
                    (p.x - 0.05, p.y + 0.12),
                    (edge.x, edge.y - 0.03),
                    arrowstyle="-|>",
                    mutation_scale=16,
                    connectionstyle="arc3,rad=-0.18",
                    color=INK2,
                    linewidth=1.6,
                    linestyle=(0, (5, 3)),
                    zorder=9.5,
                )
            )
            mx, my = (p.x + edge.x) / 2, (p.y + edge.y) / 2
            ax.text(
                mx + 0.15,
                my + 0.2,
                f"the lake leg is read\n~{round(to_edge, -1):.0f} km from the zone\n"
                f"(~{round(to_centre, -1):.0f} km from its centre)",
                ha="left",
                va="center",
                zorder=11,
                **halo(8.5, INK2, "bold"),
            )
            handles.append((Line2D([], [], **style), item["legend"]))
        drawn.add(kind)
    return handles, marked, drawn


def draw_scale_bar(ax, ext):
    w, s, e, n = ext
    lat = (s + n) / 2
    target = km((w, lat), (e, lat)) * 0.18
    length = max(v for v in (10, 20, 25, 50, 100, 200) if v <= target)
    deg = length / (111.32 * math.cos(math.radians(lat)))
    x0, y0 = w + 0.03 * (e - w), s + 0.035 * (n - s)
    ax.plot([x0, x0 + deg], [y0, y0], color=INK2, linewidth=2.2, solid_capstyle="butt", zorder=13)
    ax.text(
        x0 + deg / 2,
        y0 + 0.012 * (n - s),
        f"{length} km",
        ha="center",
        va="bottom",
        zorder=13,
        **halo(7.5, INK2),
    )


def draw_locator(iax, zone_key, ext, adm2, uganda, lakes, countries):
    countries[countries.ADM0_A3 != "UGA"].plot(
        ax=iax, aspect=None, color=NEIGHBOUR, edgecolor="white", linewidth=0.4
    )
    gpd.GeoSeries([uganda], crs=adm2.crs).plot(
        ax=iax, aspect=None, color=LAND, edgecolor=INK2, linewidth=0.6
    )
    lakes.plot(ax=iax, aspect=None, color=WATER, edgecolor="none")
    adm2[adm2.ADM2_EN.isin(zone_names(zone_key, "zone"))].plot(
        ax=iax, aspect=None, color=ZONE_COL[zone_key], edgecolor="none", zorder=3
    )
    iax.add_patch(
        Rectangle(
            (ext[0], ext[1]),
            ext[2] - ext[0],
            ext[3] - ext[1],
            facecolor="none",
            edgecolor=INK,
            linewidth=0.9,
            zorder=4,
        )
    )
    iax.set_xlim(*XLIM)
    iax.set_ylim(*YLIM)
    iax.set_aspect("equal")
    iax.set_xticks([])
    iax.set_yticks([])
    for sp in iax.spines.values():
        sp.set_color("#e3e1db")
    iax.set_title("Uganda, map area boxed", fontsize=7.5, color=INK2, loc="left", pad=3)


def key_entries(zone_key, spec, glofas_drawn):
    z, col = ZONES[zone_key], ZONE_COL[zone_key]
    out = [
        (
            Patch(facecolor=to_rgba(col, 0.35), edgecolor=col, linewidth=1.5),
            f"Tier 1: the {len(z.core)} districts the zone is for",
        )
    ]
    if z.tier2:
        tier2 = Patch(
            facecolor=to_rgba(col, 0.10),
            edgecolor=col,
            hatch="....",
            linewidth=1.4,
            linestyle=(0, (3, 2)),
        )
        out.append((tier2, f"Tier 2: {z.tier2_label}"))
    out.append((Patch(facecolor=WATER, edgecolor=WATER_EDGE, linewidth=0.6), "lake"))
    if spec.get("highlight_rivers"):
        out.append(
            (
                Line2D([], [], color=NILE, linewidth=2.2),
                "the Nile: Lake Kyoga to Lake Albert to the Albert Nile",
            )
        )
    out.append((Line2D([], [], color=WATER_EDGE, linewidth=1.2), "main river (Natural Earth)"))
    if glofas_drawn:
        dot = Line2D([], [], marker="o", linestyle="", markersize=4, color=GLOFAS_CELL)
        out.append((dot, f"GloFAS river cells, 5-yr flow ≥ {RL5_MIN:.0f} m³/s (bigger = more)"))
    return out


def add_legends(fig, legend_at, trigger_handles, key_handles):
    """Two legends: what the trigger reads, then the zone and base map."""
    common = {
        "fontsize": 7.6,
        "frameon": False,
        "alignment": "left",
        "labelspacing": 0.7,
        "handlelength": 2.0,
        "borderaxespad": 0,
        "title_fontproperties": {"weight": "bold", "size": 8.2},
        "loc": "upper left",
    }
    w1, w2 = legend_at["wrap"]
    leg1 = fig.legend(
        [h for h, _ in trigger_handles],
        [textwrap.fill(t, w1) for _, t in trigger_handles],
        title="Where the trigger is measured",
        bbox_to_anchor=(legend_at["x"], legend_at["y"]),
        **common,
    )
    if legend_at["mode"] == "row":
        anchor = (legend_at["x2"], legend_at["y"])
    else:
        fig.canvas.draw()
        bb = leg1.get_window_extent().transformed(fig.transFigure.inverted())
        anchor = (legend_at["x"], bb.y0 - 0.025)
    fig.legend(
        [h for h, _ in key_handles],
        [textwrap.fill(t, w2) for _, t in key_handles],
        title="Zone and map",
        bbox_to_anchor=anchor,
        **common,
    )


# --- one map ----------------------------------------------------------------------------------
def render(zone_key, adm2, uganda, lakes, rivers, countries, public: bool) -> Path:
    zone, spec = ZONES[zone_key], INDICATORS[zone_key]
    lake_km = lake_distance_km(zone_key, adm2, lakes)
    summary = textwrap.fill(spec["summary"].format(lake_km=lake_km), 128)
    top_h = 0.92 + 0.2 * summary.count("\n")  # kicker, title, summary lines
    fig, ax, iax, ext, legend_at, fig_h = make_figure(frame(zone_key, adm2, lakes), top_h)

    draw_basemap(ax, ext, adm2, uganda, lakes, rivers, countries, spec, zone_key)
    glofas_drawn = spec.get("glofas_cells", False) and draw_glofas_cells(ax, ext, lakes)
    draw_zone(ax, zone_key, adm2)
    trigger_handles, marked, drawn = draw_indicators(ax, ext, zone_key, adm2, lakes, public)
    draw_district_names(ax, ext, zone_key, adm2, marked)
    draw_scale_bar(ax, ext)
    ax.set_xlim(ext[0], ext[2])
    ax.set_ylim(ext[1], ext[3])
    ax.set_aspect("equal")
    ax.set_axis_off()
    draw_locator(iax, zone_key, ext, adm2, uganda, lakes, countries)
    add_legends(fig, legend_at, trigger_handles, key_entries(zone_key, spec, glofas_drawn))

    x0, top = PAD / FIG_W, 1 - 0.14 / fig_h
    fig.text(
        x0,
        top,
        "UGANDA FLOOD ANTICIPATORY ACTION · WHERE EACH TRIGGER IS MEASURED",
        fontsize=7.5,
        color=MUTED,
        ha="left",
        va="top",
    )
    fig.text(
        x0, top - 0.2 / fig_h, zone.label, fontsize=14.5, fontweight="bold", color=INK, va="top"
    )
    fig.text(
        x0,
        top - 0.52 / fig_h,
        summary,
        fontsize=9,
        color=INK2,
        va="top",
        linespacing=1.35,
    )
    used = ["base"] + (["glofas"] if glofas_drawn or "ifrc_cells" in drawn else [])
    used += ["ifrc"] if "ifrc_cells" in drawn else []
    sources = " ".join(SOURCES[k] for k in [*used, "end"])
    fig.text(x0, 0.08 / fig_h, textwrap.fill(sources, 175), fontsize=6.5, color=MUTED)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"map_{zone_key}.png"
    fig.savefig(out, dpi=160, facecolor="white")
    plt.close(fig)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument(
        "--public", action="store_true", help="leave partner (unpublished) trigger names off"
    )
    args = ap.parse_args()
    if not args.public and load_private().get("trigger_specs"):
        print("partner config found: maps may name unpublished partner triggers (restricted only)")

    adm2 = load_adm2()
    uganda = adm2.union_all()
    lakes, rivers, countries = load_ne()
    for key in ZONES:
        print(f"wrote {render(key, adm2, uganda, lakes, rivers, countries, args.public)}")


if __name__ == "__main__":
    main()
