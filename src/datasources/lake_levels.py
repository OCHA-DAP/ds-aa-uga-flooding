"""Satellite-altimetry lake levels for Victoria, Kyoga and Albert (NASA Global Water Monitor).

The Albert Nile floods at Adjumani/Obongi/Pakwach are lake-driven backwater:
Lake Victoria -> Kyoga -> Albert with multi-month lags (mean 4.2 + 3.4 months;
EGUsphere 2025-5009), so the lake series ARE the long-lead indicator for that
zone. NASA GWM (successor of USDA G-REALM) publishes them as plain text:

  lake000314  Victoria  10-day (T/P -> Jason -> Sentinel-6A), 1992-
  lake000398  Kyoga     10-day, 1992-
  lake000405  Albert    27-day (Sentinel-3A only), 2016-   (monthly product, lake.30.tar.gz)

Column 15 = height in EGM2008 datum (m a.s.l.), 9999.99 = missing.
Bulk archives: https://earth.gsfc.nasa.gov/gwm/zip/lake.10.tar.gz and lake.30.tar.gz
(~320 MB / ~120 MB; only the three files are kept). Raw text mirrored to
{PROJECT_PREFIX}/raw/gwm/, tidy parquet to {PROJECT_PREFIX}/processed/gwm/lake_levels.parquet.

Alternatives with longer Albert coverage (Envisat/Jason from 2002): DAHITI id 85
(registration + API key) and Hydroweb L_albert (login) — worth adding if the
2016+ Sentinel-3 record proves too short for return periods.
"""

import io
import tarfile
from pathlib import Path

import ocha_stratus as stratus
import pandas as pd

from src.constants import PROJECT_PREFIX

LAKES = {
    "victoria": ("lake000314", "10"),
    "kyoga": ("lake000398", "10"),
    "albert": ("lake000405", "30"),
}
ARCHIVES = {
    "10": "https://earth.gsfc.nasa.gov/gwm/zip/lake.10.tar.gz",
    "30": "https://earth.gsfc.nasa.gov/gwm/zip/lake.30.tar.gz",
}
OUT_BLOB = f"{PROJECT_PREFIX}/processed/gwm/lake_levels.parquet"


def parse_gwm(text: str, lake: str) -> pd.DataFrame:
    rows = []
    for line in text.splitlines():
        if line.startswith("c") or line.startswith("Column") or not line.strip():
            continue
        p = line.split()
        if len(p) < 15 or not (p[2].isdigit() and len(p[2]) == 8) or p[2] == "99999999":
            continue
        try:
            h, err = float(p[14]), float(p[6])
        except ValueError:
            continue
        if h > 9000:
            continue
        rows.append(
            {
                "lake": lake,
                "date": pd.to_datetime(p[2], format="%Y%m%d"),
                "mission": p[0],
                "height_m": h,
                "error_m": float(p[6]),
            }
        )
    return pd.DataFrame(rows)


def extract_from_archives(archive_dir: Path) -> pd.DataFrame:
    """Pull the three lake files out of locally downloaded tarballs, mirror them, return tidy frame."""
    frames = []
    for lake, (lid, prod) in LAKES.items():
        with tarfile.open(archive_dir / f"lake.{prod}.tar.gz") as tf:
            member = next(m for m in tf.getmembers() if lid in m.name and m.name.endswith(".txt"))
            text = tf.extractfile(member).read().decode()
        stratus.upload_blob_data(
            text.encode(), f"{PROJECT_PREFIX}/raw/gwm/{Path(member.name).name}", stage="dev"
        )
        frames.append(parse_gwm(text, lake))
    df = pd.concat(frames, ignore_index=True).sort_values(["lake", "date"]).reset_index(drop=True)
    stratus.upload_parquet_to_blob(df, OUT_BLOB, stage="dev")
    return df


def load_lake_levels() -> pd.DataFrame:
    return stratus.load_parquet_from_blob(OUT_BLOB, stage="dev")


def monthly(df: pd.DataFrame) -> pd.DataFrame:
    """Month-end mean height per lake (wide), the resolution at which the lag analysis runs."""
    return df.set_index("date").groupby("lake").height_m.resample("ME").mean().unstack(0)
