"""ERA5-Land daily soil moisture (CDS `derived-era5-land-daily-statistics`) for the Uganda box.

Volumetric soil water, layers 1 (0-7 cm) and 2 (7-28 cm), daily mean from 6-hourly,
0.1 deg, 1998-present, ~5-day latency (so usable operationally as an antecedent-
wetness qualifier, not only in hindcast). The CDS cost limit (400) forces one
request per variable-year (366 days). Same CDS/EWDS key as GloFAS.

Raw: data/era5_land/raw/{var}_{year}.nc (gitignored) -> mirrored to
{PROJECT_PREFIX}/raw/era5_land/. Per-district daily means -> pipeline/build_soil_moisture_adm2.py.
"""

from pathlib import Path

import cdsapi

from src.datasources.glofas import _key, _submit_and_download_all

CDS_URL = "https://cds.climate.copernicus.eu/api"
DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "era5_land"
UGA_AREA = [4.5, 29.4, -1.7, 35.2]  # N, W, S, E
VARIABLES = ("volumetric_soil_water_layer_1", "volumetric_soil_water_layer_2")
YEARS = range(1998, 2027)


def download(years=YEARS, variables=VARIABLES) -> dict:
    import src.datasources.glofas as g

    # reuse the EWDS submit/poll loop but against the CDS host
    g_client_orig = g._client

    def cds_client(wait_until_complete=True):
        return cdsapi.Client(url=CDS_URL, key=_key(), wait_until_complete=wait_until_complete)

    g._client = cds_client
    try:
        jobs = {}
        for var in variables:
            for year in years:
                req = {
                    "variable": [var],
                    "year": str(year),
                    "month": [f"{m:02d}" for m in range(1, 13)],
                    "day": [f"{d:02d}" for d in range(1, 32)],
                    "daily_statistic": "daily_mean",
                    "time_zone": "utc+00:00",
                    "frequency": "6_hourly",
                    "area": UGA_AREA,
                }
                jobs[f"{var}_{year}"] = (
                    "derived-era5-land-daily-statistics",
                    req,
                    DATA_DIR / "raw" / f"{var}_{year}.nc",
                )
        return _submit_and_download_all(jobs, log_prefix="[era5-land] ")
    finally:
        g._client = g_client_orig
