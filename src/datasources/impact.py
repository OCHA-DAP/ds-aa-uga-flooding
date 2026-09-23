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

import numpy as np
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
    # EM-DAT leaves the day (and sometimes the month) blank. Filling those with the 1st and
    # calling the result a date is how an event gets pinned to a day it did not happen on, so
    # the precision is recorded and the end is stretched to cover the whole month or year.
    em["date_precision"] = np.where(
        em["Start Day"].notna(), "day", np.where(em["Start Month"].notna(), "month", "year")
    )
    em["start"] = pd.to_datetime(
        dict(
            year=em["Start Year"],
            month=em["Start Month"].fillna(1),
            day=em["Start Day"].fillna(1),
        )
    )
    end_month = em["End Month"].fillna(em["Start Month"]).fillna(12)
    end_first = pd.to_datetime(
        dict(year=em["End Year"].fillna(em["Start Year"]), month=end_month, day=1)
    )
    # a known end day is used as given; otherwise the event runs to the end of its last month
    em["end"] = np.where(
        em["End Day"].notna(),
        end_first + pd.to_timedelta(em["End Day"].fillna(1) - 1, unit="D"),
        end_first + pd.offsets.MonthEnd(0),
    )
    em["end"] = pd.to_datetime(em["end"])
    return em.rename(
        columns={
            "DisNo.": "event_id",
            "Disaster Subtype": "subtype",
            "Total Deaths": "deaths",
            "Total Affected": "affected",
        }
    )[
        [
            "event_id",
            "subtype",
            "start",
            "end",
            "deaths",
            "affected",
            "Location",
            "districts",
            "date_precision",
        ]
    ].assign(source="EM-DAT")


def load_curated_events() -> pd.DataFrame:
    df = pd.read_csv(CURATED, parse_dates=["start", "end"])
    df["districts"] = df["districts"].str.split(";").map(lambda xs: [x.strip() for x in xs])
    # these are hand-curated from press and agency reports, so they carry the date the report
    # gives; a row can say otherwise with a date_precision column
    if "date_precision" not in df:
        df["date_precision"] = "day"
    df["date_precision"] = df["date_precision"].fillna("day")
    return df


VERIFIED = Path(__file__).resolve().parents[1] / "data" / "event_dates.csv"


def load_verified_dates() -> pd.DataFrame:
    """Researched dates for events whose source dates are vague or wrong.

    One row per correction (src/data/event_dates.csv):

      event_id      the event to correct (EM-DAT DisNo., curated id, DTM id); blank matches on
                    source + original start instead
      source        source name to match when event_id is blank (e.g. DesInventar)
      match_start   the event's original start date, as a guard against silent drift
      districts     semicolon-separated; the correction applies only to these districts, which
                    lets one national event carry the dates it actually had in each zone
      start, end    the researched dates
      precision     day | month
      evidence      URL or citation the dates come from
    """
    if not VERIFIED.exists():
        return pd.DataFrame(
            columns=[
                "event_id",
                "source",
                "match_start",
                "districts",
                "start",
                "end",
                "precision",
                "evidence",
                "note",
            ]
        )
    v = pd.read_csv(VERIFIED, parse_dates=["match_start", "start", "end"])
    v["districts"] = v.districts.fillna("").map(
        lambda x: [d.strip() for d in str(x).split(";") if d.strip()]
    )
    return v


def apply_verified_dates(ev: pd.DataFrame) -> pd.DataFrame:
    """Override event dates from src/data/event_dates.csv, per district where a correction
    names districts. Adds `date_evidence` so the page can say where a date came from."""
    v = load_verified_dates()
    ev = ev.copy()
    if "date_precision" not in ev:
        ev["date_precision"] = "day"
    ev["date_evidence"] = ""
    for _, c in v.iterrows():
        m = pd.Series(True, index=ev.index)
        if isinstance(c.event_id, str) and c.event_id:
            m &= ev.event_id.astype(str) == c.event_id
        if isinstance(c.source, str) and c.source:
            m &= ev.source.astype(str).str.startswith(c.source)
        if pd.notna(c.match_start):
            m &= ev.start.dt.normalize() == c.match_start.normalize()
        if c.districts:
            m &= ev.district.isin(c.districts)
        if not m.any():
            continue
        ev.loc[m, "start"] = c.start
        ev.loc[m, "end"] = c.end if pd.notna(c.end) else c.start
        ev.loc[m, "date_precision"] = c.precision if isinstance(c.precision, str) else "day"
        ev.loc[m, "date_evidence"] = c.evidence if isinstance(c.evidence, str) else ""
    return ev


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
    return apply_verified_dates(ev.reset_index(drop=True))
