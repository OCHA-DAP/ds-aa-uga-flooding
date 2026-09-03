"""IOM DTM affected-people-by-district compilation (country team workbook, Aug 2026).

`Uganda_OND affected people by district.xlsx` (dev blob, raw/country_team/) is a
matrix of district x reporting round (Oct-Nov 2023 ... Sep-Oct 2025) of people
affected by floods/landslides, compiled by the country team from published DTM
Emergency Event Tracking reports. It is the finest recent impact record we hold
and is folded into the impact table as one event row per (district, round).
Round labels are mapped to a start/end month here; the workbook has no day.
"""

import io

import ocha_stratus as stratus
import pandas as pd

from src.constants import PROJECT_PREFIX

BLOB = f"{PROJECT_PREFIX}/raw/country_team/Uganda_OND affected people by district.xlsx"

# workbook column label -> (start, end)
ROUNDS = {
    "Sept-Oct 2025": ("2025-09-01", "2025-10-31"),
    "Nov- Dec 2024": ("2024-11-01", "2024-12-31"),
    "Sept-Oct 2024": ("2024-09-01", "2024-10-31"),
    "2024-08-01": ("2024-08-01", "2024-08-31"),
    "2024-05-01": ("2024-05-01", "2024-05-31"),
    "2024-04-01": ("2024-04-01", "2024-04-30"),
    "2024-03-01": ("2024-03-01", "2024-03-31"),
    "2023-12-01": ("2023-12-01", "2023-12-31"),
    "2023-11-01": ("2023-11-01", "2023-11-30"),
    "Oct-Nov 2023": ("2023-10-01", "2023-11-30"),
}
NAME_FIX = {"Budada": "Bududa", "Bunyagabu": "Bunyangabu", "Namisidwa": "Namisindwa"}


def load_dtm_events() -> pd.DataFrame:
    raw = pd.read_excel(io.BytesIO(stratus.load_blob_data(BLOB, stage="dev")), header=None)
    hdr = raw.iloc[3, 2:].tolist()
    labels = [h.strftime("%Y-%m-%d") if hasattr(h, "strftime") else str(h).strip() for h in hdr]
    body = raw.iloc[4:, 1:].dropna(how="all")
    body.columns = ["district", *labels]
    long = body.melt(id_vars="district", var_name="round", value_name="affected")
    long["affected"] = pd.to_numeric(
        long.affected, errors="coerce"
    )  # trailing rows hold source URLs
    long = long.dropna(subset=["affected"])
    long["district"] = long.district.str.strip().replace(NAME_FIX)
    long["start"] = pd.to_datetime(long["round"].map(lambda r: ROUNDS[r][0]))
    long["end"] = pd.to_datetime(long["round"].map(lambda r: ROUNDS[r][1]))
    long["event_id"] = (
        "DTM-" + long["round"].str.replace(r"[^0-9A-Za-z]", "", regex=True) + "-" + long.district
    )
    return pd.DataFrame(
        {
            "event_id": long.event_id,
            "subtype": "Flood/landslide (DTM round)",
            "start": long.start,
            "end": long.end,
            "deaths": pd.NA,
            "affected": long.affected.astype(float),
            "Location": long.district + " (" + long["round"] + ")",
            "districts": long.district.map(lambda d: [d]),
            "source": "IOM DTM EET (country team compilation, Aug 2026)",
        }
    ).reset_index(drop=True)
