"""DesInventar Uganda (UNDRR / OPM-NECOC) — district-level disaster datacards 1933-2020.

The public export (https://www.desinventar.net/DesInventar/download/DI_export_uga.zip,
~30 MB) holds ~5,400 "fichas" (datacards): one row per event x lowest admin
unit reported, with date (year/month/day), event type, deaths, injured,
missing, affected, houses destroyed/damaged, sectoral damage flags, source.
Geography: lev0 = district (137, 2011 vintage), lev1 = sub-county, lev2 = parish.

This is the only district-level, dated record of flash floods and landslides
before the DTM era (2023+), so it is the impact backbone for the Elgon and
Karamoja zones. Coverage ends in 2020; nothing after.

Raw zip is mirrored to {PROJECT_PREFIX}/raw/desinventar/DI_export_uga.zip; the
parsed table to {PROJECT_PREFIX}/processed/desinventar/datacards.parquet.
"""

import io
import re
import zipfile

import ocha_stratus as stratus
import pandas as pd

from src.constants import PROJECT_PREFIX
from src.zones import load_adm2

URL = "https://www.desinventar.net/DesInventar/download/DI_export_uga.zip"
RAW_BLOB = f"{PROJECT_PREFIX}/raw/desinventar/DI_export_uga.zip"
OUT_BLOB = f"{PROJECT_PREFIX}/processed/desinventar/datacards.parquet"

FLOOD_TYPES = ("FLOOD", "FLASH FLOOD", "LANDSLIDE", "MUDSLIDE", "RAINS", "RAINSTORM")

FIELDS = {
    "serial": "serial",
    "name0": "district_di",
    "name1": "subcounty",
    "name2": "parish",
    "evento": "event_type",
    "lugar": "place",
    "fechano": "year",
    "fechames": "month",
    "fechadia": "day",
    "muertos": "deaths",
    "heridos": "injured",
    "desaparece": "missing",
    "afectados": "affected",
    "vivdest": "houses_destroyed",
    "vivafec": "houses_damaged",
    "fuentes": "source_text",
    "evacuados": "evacuated",
    "damnificados": "victims",
    "reubicados": "relocated",
}

# DesInventar district names (2011 vintage, upper-case) that differ from CODAB ADM2_EN
DI_TO_CODAB = {
    "SEMBABULE": "Ssembabule",
    "MADI-OKOLLO": "Madi Okollo",
    "KABAALE": "Kabale",
}


def fetch_raw(force: bool = False) -> bytes:
    """Zip bytes — from the blob mirror if present, else downloaded and mirrored."""
    import requests

    if not force:
        try:
            return stratus.load_blob_data(RAW_BLOB, stage="dev")
        except Exception as e:  # noqa: BLE001 — any miss/auth issue falls through to the live download
            print(f"desinventar: blob mirror unavailable ({e}); downloading from desinventar.net")
    r = requests.get(URL, timeout=600)
    r.raise_for_status()
    stratus.upload_blob_data(r.content, RAW_BLOB, stage="dev")
    return r.content


def parse_datacards(zip_bytes: bytes) -> pd.DataFrame:
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        xml_name = next(n for n in z.namelist() if n.endswith(".xml"))
        text = z.read(xml_name).decode("utf-8", errors="replace")
    block = re.search(r"<fichas>(.*?)</fichas>", text, re.DOTALL).group(1)
    rows = []
    for tr in re.findall(r"<TR>(.*?)</TR>", block, re.DOTALL):
        rec = dict(re.findall(r"<(\w+)>([^<]*)</\1>", tr))
        rows.append({new: rec.get(old, "") for old, new in FIELDS.items()})
    df = pd.DataFrame(rows)
    for c in (
        "year",
        "month",
        "day",
        "deaths",
        "injured",
        "missing",
        "affected",
        "houses_destroyed",
        "houses_damaged",
        "evacuated",
        "victims",
        "relocated",
    ):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    # DesInventar writes 0 for an unknown day or month. An earlier version treated day 0 as the
    # 1st and called it day-precise — a quarter of all cards, and most of the deaths — and
    # clamped days 29-31 to the 28th. Unknown parts now lower the precision instead, and real
    # days are kept as they are (clipped only to the length of their month).
    month = df.month.where(df.month.between(1, 12))
    day = df.day.where(df.day >= 1)
    first = pd.to_datetime({"year": df.year, "month": month.fillna(1), "day": 1}, errors="coerce")
    df["date"] = first + pd.to_timedelta(
        day.fillna(1).clip(upper=first.dt.days_in_month) - 1, unit="D"
    )
    df["date_precision"] = (
        pd.Series("day", index=df.index)
        .where(day.notna() & month.notna(), "month")
        .where(month.notna(), "year")
    )
    df["district_di"] = df["district_di"].str.strip().str.upper()
    lookup = {n.upper(): n for n in load_adm2().ADM2_EN}
    lookup.update(DI_TO_CODAB)
    df["district"] = df["district_di"].map(lookup)
    return df


def build(force: bool = False) -> pd.DataFrame:
    df = parse_datacards(fetch_raw(force=force))
    stratus.upload_parquet_to_blob(df, OUT_BLOB, stage="dev")
    return df


def load_datacards(hydromet_only: bool = True, verified: bool = True) -> pd.DataFrame:
    """Datacards, with `date_end` (a month-precision card spans its month) and researched date
    corrections from src/data/event_dates.csv applied where they name a DesInventar card."""
    df = stratus.load_parquet_from_blob(OUT_BLOB, stage="dev")
    if hydromet_only:
        df = df[df.event_type.isin(FLOOD_TYPES)]
    df = df.copy()
    df["date_end"] = df.date.where(df.date_precision.eq("day"), df.date + pd.offsets.MonthEnd(0))
    df["date_evidence"] = ""
    if verified:
        from src.datasources.impact import load_verified_dates

        for _, c in load_verified_dates().iterrows():
            if not (isinstance(c.source, str) and c.source.startswith("DesInventar")):
                continue
            m = pd.Series(True, index=df.index)
            if pd.notna(c.match_start):
                m &= df.date.dt.normalize() == c.match_start.normalize()
            if c.districts:
                m &= df.district.isin(c.districts)
            if not m.any():
                continue
            df.loc[m, "date"] = c.start
            df.loc[m, "date_end"] = c.end if pd.notna(c.end) else c.start
            df.loc[m, "date_precision"] = c.precision if isinstance(c.precision, str) else "day"
            df.loc[m, "date_evidence"] = c.evidence if isinstance(c.evidence, str) else ""
    return df
