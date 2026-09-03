"""Historical impact record: EM-DAT (team blob mirror) exploded to districts, plus curated events.

Trigger validation needs TWO records — impact and observed hazard. This module
is the impact side. EM-DAT (via ocha_stratus) gives 47 flood / wet mass-movement
events for Uganda 2001-2024 with free-text `Location` and a JSON `Admin Units`
field; both are matched to CODAB ADM2 names so every event becomes a set of
(event, district) rows tagged with the zone(s) it touches.

`src/data/events_curated.csv` holds the hand-curated supplement (IOM DTM
district counts 2023-2025, OPM/URCS-reported events, landslides missing from
EM-DAT) with a source per row; it is the file to grow as the country team
shares more impact data. Keep district names as in CODAB ADM2_EN.
"""

import json
import re
from pathlib import Path

import pandas as pd
from ocha_stratus import emdat

from src.constants import ISO3, ZONES
from src.zones import load_adm2

CURATED = Path(__file__).resolve().parents[1] / "data" / "events_curated.csv"
HAZARD_TYPES = ("Flood", "Mass movement (wet)")


def _district_lookup() -> dict[str, str]:
    """lowercase name -> ADM2_EN, with a few spelling aliases seen in EM-DAT text."""
    names = load_adm2().ADM2_EN.tolist()
    lk = {n.lower(): n for n in names}
    lk.update(
        {
            "madi-okollo": "Madi Okollo",
            "madi okollo": "Madi Okollo",
            "ntokoro": "Ntoroko",
            "bundinbugyo": "Bundibugyo",
            "butalega": "Butaleja",
            "kabaale": "Kabale",
            "sembabule": "Ssembabule",
        }
    )
    return lk


def _districts_in_text(text: str, lookup: dict[str, str]) -> set[str]:
    if not isinstance(text, str):
        return set()
    tokens = set(re.findall(r"[A-Za-z][A-Za-z\-]+", text.lower()))
    found = {lookup[t] for t in tokens if t in lookup}
    for k in ("madi okollo", "madi-okollo"):
        if k in text.lower():
            found.add("Madi Okollo")
    return found


def _districts_in_admin_units(cell, lookup: dict[str, str]) -> set[str]:
    if not isinstance(cell, str):
        return set()
    try:
        units = json.loads(cell)
    except json.JSONDecodeError:
        return set()
    out = set()
    for u in units:
        for key in ("adm2_name", "adm1_name"):
            name = u.get(key)
            if isinstance(name, str):
                for cand in (name, name.replace(" District", "")):
                    if cand.lower() in lookup:
                        out.add(lookup[cand.lower()])
    return out


def load_emdat_events() -> pd.DataFrame:
    """One row per EM-DAT flood / wet mass-movement event, with a `districts` list column."""
    em = emdat.load_emdat_from_blob(iso3=ISO3)
    em = em[em["Disaster Type"].isin(HAZARD_TYPES)].copy()
    lookup = _district_lookup()
    em["districts"] = [
        sorted(_districts_in_text(loc, lookup) | _districts_in_admin_units(au, lookup))
        for loc, au in zip(em["Location"], em["Admin Units"], strict=True)
    ]
    em["start"] = pd.to_datetime(
        dict(
            year=em["Start Year"], month=em["Start Month"].fillna(1), day=em["Start Day"].fillna(1)
        )
    )
    em["end"] = pd.to_datetime(
        dict(
            year=em["End Year"].fillna(em["Start Year"]),
            month=em["End Month"].fillna(em["Start Month"]).fillna(12),
            day=em["End Day"].fillna(28),
        )
    )
    return em.rename(
        columns={
            "DisNo.": "event_id",
            "Disaster Subtype": "subtype",
            "Total Deaths": "deaths",
            "Total Affected": "affected",
        }
    )[
        ["event_id", "subtype", "start", "end", "deaths", "affected", "Location", "districts"]
    ].assign(source="EM-DAT")


def load_curated_events() -> pd.DataFrame:
    df = pd.read_csv(CURATED, parse_dates=["start", "end"])
    df["districts"] = df["districts"].str.split(";").map(lambda xs: [x.strip() for x in xs])
    return df


def events_by_district(include_curated: bool = True, include_dtm: bool = True) -> pd.DataFrame:
    """Long table: one row per (event, district), tagged with zone and membership."""
    frames = [load_emdat_events()]
    if include_curated and CURATED.exists():
        frames.append(load_curated_events())
    if include_dtm:
        from src.datasources.dtm import load_dtm_events

        frames.append(load_dtm_events())
    ev = (
        pd.concat(frames, ignore_index=True)
        .explode("districts")
        .rename(columns={"districts": "district"})
    )
    ev = ev.dropna(subset=["district"])
    zone_of = {d: (z.key, "core") for z in ZONES.values() for d in z.core}
    zone_of.update({d: (z.key, "candidate") for z in ZONES.values() for d in z.candidate})
    ev["zone"] = ev.district.map(lambda d: zone_of.get(d, (None, None))[0])
    ev["membership"] = ev.district.map(lambda d: zone_of.get(d, (None, None))[1])
    return ev.reset_index(drop=True)
