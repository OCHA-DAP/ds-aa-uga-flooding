"""GloFAS v4 reanalysis and reforecast from the Early Warning Data Store (EWDS).

Adapted from ds-aa-som-floods/src/datasources/glofas.py (same EWDS quirks:
per-request cost limit -> reanalysis chunked by year, reforecast ~8 lead
times per station-month; all chunks submitted asynchronously then polled).

Reanalysis is downloaded once for a box covering all of Uganda (cost scales
with time only, not area), so any reporting point — G5196 on the Akokoro,
any Albert Nile point — can be extracted later. Reforecast is per point.

Raw files: data/glofas/raw/{reanalysis_uga_v4,reforecast_<station>}/  (gitignored)
Mirrored to blob under {PROJECT_PREFIX}/raw/glofas/ by the pipeline script.
"""

import os
import time
import zipfile
from pathlib import Path

import cdsapi
import pandas as pd
import xarray as xr

EWDS_URL = "https://ewds.climate.copernicus.eu/api"
DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "glofas"

# N, W, S, E — whole of Uganda plus a margin so border reaches are included
UGA_AREA = [4.5, 29.4, -1.7, 35.2]
REANALYSIS_YEARS = [str(y) for y in range(1999, 2025)]
ALL_MONTHS = [f"{m:02d}" for m in range(1, 13)]
ALL_DAYS = [f"{d:02d}" for d in range(1, 32)]
LEADTIME_DAYS = [1, 3, 5, 7, 10, 14, 21, 30]  # ~8 fits the EWDS cost limit
POLL_INTERVAL_SECONDS = 60


def snap(v: float) -> float:
    """Nearest GloFAS v4 0.05 deg cell centre (x.x25 / x.x75)."""
    return round((v - 0.025) / 0.05) * 0.05 + 0.025


def _key() -> str:
    key = os.getenv("CDSAPI_KEY")
    if key:
        return key
    rc = Path.home() / ".cdsapirc"
    lines = dict(line.strip().split(": ", 1) for line in rc.read_text().splitlines() if ":" in line)
    return lines["key"]


def _client(wait_until_complete: bool = True) -> cdsapi.Client:
    return cdsapi.Client(url=EWDS_URL, key=_key(), wait_until_complete=wait_until_complete)


def _submit_and_download_all(jobs: dict, log_prefix: str = "") -> dict:
    """jobs: key -> (collection, request, out_path). Submits all, polls, downloads."""
    client = _client(wait_until_complete=False)
    remotes = {}
    for key, (collection, request, out_path) in jobs.items():
        out_path.parent.mkdir(parents=True, exist_ok=True)
        if out_path.exists():
            print(f"{log_prefix}{key}: exists, skipping")
            continue
        remotes[key] = client.retrieve(collection, request)
        print(f"{log_prefix}{key}: submitted")
    done = {k: jobs[k][2] for k in jobs if jobs[k][2].exists()}
    pending = dict(remotes)
    while pending:
        for key, remote in list(pending.items()):
            remote.update()
            if remote.status == "successful":
                remote.download(str(jobs[key][2]))
                done[key] = jobs[key][2]
                del pending[key]
                print(f"{log_prefix}{key}: downloaded")
            elif remote.status == "failed":
                print(f"{log_prefix}{key}: FAILED — {remote.get_receipt()}")
                del pending[key]
        if pending:
            time.sleep(POLL_INTERVAL_SECONDS)
    return done


def download_reanalysis_box(years=None, version: str = "version_4_0") -> dict:
    raw_dir = (
        DATA_DIR / "raw" / f"reanalysis_uga_{version.replace('version_', 'v').replace('_0', '')}"
    )
    jobs = {}
    for year in years or REANALYSIS_YEARS:
        query = {
            "system_version": version,
            "hydrological_model": "lisflood",
            "product_type": "consolidated",
            "variable": "average_river_discharge_in_the_last_24_hours",
            "timespan": "time_mean",
            "year": year,
            "month": ALL_MONTHS,
            "day": ALL_DAYS,
            "data_format": "netcdf",
            "download_format": "unarchived",
            "area": UGA_AREA,
        }
        jobs[year] = ("cems-glofas-historical", query, raw_dir / f"{year}.nc")
    return _submit_and_download_all(jobs, log_prefix=f"[reanalysis/{version}] ")


def download_reforecast_point(
    station_key: str,
    lat: float,
    lon: float,
    years=range(2003, 2024),
    months=range(1, 13),
    buffer: float = 0.1,
) -> dict:
    """Reforecast (11-member, twice weekly, 2003-2023) in a small box around one point."""
    raw_dir = DATA_DIR / "raw" / f"reforecast_{station_key}"
    area = [lat + buffer, lon - buffer, lat - buffer, lon + buffer]
    jobs = {}
    for year in years:
        for month in months:
            query = {
                "system_version": "version_4_0",
                "hydrological_model": "lisflood",
                "product_type": "ensemble_perturbed_reforecast",
                "variable": "river_discharge_in_the_last_24_hours",
                "hyear": str(year),
                "hmonth": f"{month:02d}",
                "hday": ALL_DAYS,
                "leadtime_hour": [str(24 * d) for d in LEADTIME_DAYS],
                "data_format": "netcdf",
                "download_format": "unarchived",
                "area": area,
            }
            jobs[f"{year}-{month:02d}"] = (
                "cems-glofas-reforecast",
                query,
                raw_dir / f"{year}-{month:02d}.nc",
            )
    return _submit_and_download_all(jobs, log_prefix=f"[reforecast/{station_key}] ")


def _unwrap(path: Path) -> list[Path]:
    if zipfile.is_zipfile(path):
        out = path.parent / (path.stem + "_extracted")
        out.mkdir(exist_ok=True)
        with zipfile.ZipFile(path) as z:
            z.extractall(out)
            return [out / n for n in z.namelist()]
    return [path]


def load_reanalysis_point(lat: float, lon: float, version: str = "version_4_0") -> pd.Series:
    """Daily discharge series at the GloFAS cell nearest (lat, lon) from the box files."""
    raw_dir = (
        DATA_DIR / "raw" / f"reanalysis_uga_{version.replace('version_', 'v').replace('_0', '')}"
    )
    files = [f for p in sorted(raw_dir.glob("*.nc")) for f in _unwrap(p) if f.suffix == ".nc"]
    ds = xr.open_mfdataset(files, combine="by_coords")
    var = next(v for v in ds.data_vars if "dis" in v)
    lat_name = "latitude" if "latitude" in ds.coords else "lat"
    lon_name = "longitude" if "longitude" in ds.coords else "lon"
    s = ds[var].sel({lat_name: snap(lat), lon_name: snap(lon)}, method="nearest").to_series()
    s.index = pd.to_datetime(s.index.get_level_values(-1) if s.index.nlevels > 1 else s.index)
    return s.rename("discharge")
