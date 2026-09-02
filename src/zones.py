"""Resolve zones to CODAB geometries / pcodes."""

from functools import lru_cache

import geopandas as gpd
from ocha_stratus import codab

from src.constants import ISO3, ZONES


@lru_cache(maxsize=1)
def load_adm2() -> gpd.GeoDataFrame:
    """Uganda ADM2 (districts) from the team CODAB mirror, EPSG:4326."""
    return codab.load_codab_from_blob(ISO3.lower(), admin_level=2)


def zone_districts(zone_key: str, include_candidates: bool = True) -> gpd.GeoDataFrame:
    """Districts of one zone, with a `membership` column (core|candidate)."""
    zone = ZONES[zone_key]
    adm2 = load_adm2()
    names = zone.all_districts if include_candidates else zone.core
    missing = set(names) - set(adm2.ADM2_EN)
    if missing:
        raise KeyError(f"zone {zone_key}: districts not in CODAB: {sorted(missing)}")
    out = adm2[adm2.ADM2_EN.isin(names)].copy()
    out["zone"] = zone_key
    out["membership"] = out.ADM2_EN.map(lambda n: "core" if n in zone.core else "candidate")
    return out


def all_zone_districts() -> gpd.GeoDataFrame:
    """Every district in any zone, one row per (zone, district)."""
    import pandas as pd

    return gpd.GeoDataFrame(
        pd.concat([zone_districts(k) for k in ZONES], ignore_index=True), crs=load_adm2().crs
    )
