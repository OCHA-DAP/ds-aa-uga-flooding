"""Live data feeds for the Uganda flood trigger monitor.

One reader per operational source, each returning a small table for one issue day:

  chirps3_gefs   CHIRPS3-GEFS 5-day rainfall forecast (CHC), per district mean and max.
                 Same file and zonal statistics as pipeline/build_chirps3_gefs_adm2.py, which
                 built the v3 calibration record. Published the same day, usually by mid-morning UTC.
  cpc_soil       NOAA CPC daily soil moisture (Leaky Bucket, 0.5 deg), per district mean, from the
                 daily GeoTIFF folder (about 2 days behind). Same reduction as
                 pipeline/build_cpc_soil_adm2.py.
  kyoga_levels   NASA Global Water Monitor 10-day altimetry for Lake Kyoga (lake000398), streamed
                 out of the bulk archive (the lake's file is near the start, so ~1 s). About a
                 week behind.
  gefs_c00_72h   72-hour rainfall from the 00 UTC GEFS control run (NOAA, 0.25 deg), district
                 mean: the series the Mount Elgon rain backtest used (the GEFS v12 reforecast
                 control, pipeline/build_gefs_reforecast_adm2.py), read the same way. Published
                 about 04:30 UTC.
  openmeteo_72h  GFS and ICON 72-hour rainfall from the Open-Meteo forecast API, averaged over
                 points inside each district, as in pipeline/build_openmeteo_runs_adm2.py.
                 Not used by the triggers since 25 Nov 2026 (kept for the replay page).
  glofas         GloFAS operational forecast (EWDS cems-glofas-forecast), control + 50
                 perturbed members, daily steps. EWDS cannot pin a model version and the netCDF
                 carries none, so glofas_legacy_versions() reads the dataset's request form: the
                 day v4 appears under Legacy Versions, "operational" is no longer v4.
"""

from __future__ import annotations

import json
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
import xarray as xr
from rasterio.io import MemoryFile
from rasterio.windows import bounds as window_bounds
from rasterio.windows import from_bounds

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipeline.build_openmeteo_runs_adm2 import district_points
from src.constants import UGA_BOX
from src.datasources.chirps_gefs import read_windowed_url, url_5day_v3
from src.datasources.lake_levels import parse_gwm
from src.zonal import zonal_stats

CPC_DAILY = "https://ftp.cpc.ncep.noaa.gov/wd51yf/global_daily/GeoTIFF/w.{day:%Y%m%d}.tif"
GWM_ARCHIVE = "https://earth.gsfc.nasa.gov/gwm/zip/lake.10.tar.gz"
KYOGA_ID = "lake000398"
OPENMETEO = "https://api.open-meteo.com/v1/forecast"
OPENMETEO_MODELS = ("gfs_seamless", "icon_global")


def _retry(fn, attempts: int = 4, wait: float = 5.0):
    for i in range(attempts):
        try:
            return fn()
        except Exception:
            if i == attempts - 1:
                raise
            time.sleep(wait * 2**i)
    raise RuntimeError("unreachable")


# --- CHIRPS3-GEFS ------------------------------------------------------------------------------


def _http_status(url: str) -> int:
    req = urllib.request.Request(url, method="HEAD")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status
    except urllib.error.HTTPError as err:
        return err.code


def chirps3_gefs(issue: date, polys) -> pd.DataFrame | None:
    """5-day forecast accumulation from `issue`, per district (pcode, mean, max).
    None only when CHC answers 404 (not published yet). CHC also rate-limits (429): any other
    failure is retried with backoff and then raised, so it is reported as a failure, never as
    "not published"."""
    url = url_5day_v3(issue)
    if _http_status(url) == 404:  # one request while the file is not out yet
        return None
    try:
        arr, bounds, wkt = _retry(lambda: read_windowed_url(url), attempts=4, wait=10.0)
    except rasterio.errors.RasterioIOError:
        if _http_status(url) == 404:
            return None
        raise
    df = zonal_stats(arr, bounds, wkt, polys)
    df.insert(0, "issue_date", pd.Timestamp(issue))
    return df


# --- CPC soil moisture -------------------------------------------------------------------------


def _read_cpc(data: bytes):
    with MemoryFile(data) as mf, mf.open() as ds:
        w = from_bounds(*UGA_BOX, ds.transform).round_offsets(op="floor").round_lengths(op="ceil")
        arr = ds.read(1, window=w).astype("float32")
        if ds.nodata is not None:
            arr[arr == ds.nodata] = np.nan
        arr[arr < 0] = np.nan
        crs = ds.crs.to_wkt() if ds.crs else rasterio.crs.CRS.from_epsg(4326).to_wkt()
        return arr, window_bounds(w, ds.transform), crs


def cpc_soil(day: date, polys) -> pd.DataFrame | None:
    """CPC soil moisture (mm) for one day, per district (pcode, mean, max). None if not out yet."""
    url = CPC_DAILY.format(day=day)
    try:
        data = _retry(lambda: urllib.request.urlopen(url, timeout=120).read(), attempts=2)
    except urllib.error.HTTPError as err:
        if err.code == 404:
            return None
        raise
    df = zonal_stats(*_read_cpc(data), polys)
    df.insert(0, "date", pd.Timestamp(day))
    return df


def cpc_soil_latest(before: date, polys, max_back: int = 7) -> pd.DataFrame | None:
    """The most recent CPC day strictly before `before` (the backtest reads the day before issue;
    the live file is ~2 days behind, so the day actually used is reported with the value)."""
    for k in range(1, max_back + 1):
        df = cpc_soil(before - timedelta(days=k), polys)
        if df is not None:
            return df
    return None


# --- Lake Kyoga --------------------------------------------------------------------------------


def kyoga_levels() -> pd.DataFrame:
    """All Lake Kyoga passes (date, height_m, ...) from the current NASA GWM 10-day archive."""

    def get() -> str:
        with (
            urllib.request.urlopen(GWM_ARCHIVE, timeout=600) as r,
            tarfile.open(fileobj=r, mode="r|gz") as tar,
        ):
            for m in tar:
                if KYOGA_ID in m.name and m.name.endswith(".txt"):
                    return tar.extractfile(m).read().decode("latin-1")
        raise FileNotFoundError(f"{KYOGA_ID} not in {GWM_ARCHIVE}")

    return parse_gwm(_retry(get), "kyoga")


# --- Open-Meteo GFS / ICON ---------------------------------------------------------------------


def openmeteo_72h(issue: date, adm) -> pd.DataFrame:
    """72-hour rainfall forecast from 00 UTC on `issue` (valid days issue .. issue+2), per district
    and model: the mean over points inside the district of each point's 72-hour total.
    Returns (pcode, district, model, mm_72h, n_points, hours)."""
    rows = []
    for _, r in adm.iterrows():
        pts = district_points(r.geometry)
        q = dict(
            latitude=",".join(str(p[0]) for p in pts),
            longitude=",".join(str(p[1]) for p in pts),
            hourly="precipitation",
            models=",".join(OPENMETEO_MODELS),
            start_date=issue.isoformat(),
            end_date=(issue + timedelta(days=2)).isoformat(),
            timezone="UTC",
        )
        url = f"{OPENMETEO}?{urllib.parse.urlencode(q)}"
        out = _retry(lambda url=url: json.load(urllib.request.urlopen(url, timeout=120)))
        out = out if isinstance(out, list) else [out]
        for m in OPENMETEO_MODELS:
            col = f"precipitation_{m}"
            tot = [pd.Series(p["hourly"][col], dtype="float64") for p in out]
            hours = min(int(s.notna().sum()) for s in tot)
            # a total over fewer than 72 hours would read low and could hide a trigger
            mm = float(np.mean([s.sum() for s in tot])) if hours == 72 else np.nan
            rows.append(
                dict(
                    pcode=r.ADM2_PCODE,
                    district=r.ADM2_EN,
                    model=m,
                    mm_72h=mm,
                    n_points=len(pts),
                    hours=hours,
                )
            )
        time.sleep(1)
    return pd.DataFrame(rows)


# --- GEFS control run -------------------------------------------------------------------------

GEFS_C00 = (
    "https://noaa-gefs-pds.s3.amazonaws.com/gefs.{day:%Y%m%d}/00/atmos/pgrb2sp25/"
    "gec00.t00z.pgrb2s.0p25.f{hour:03d}"
)


def _apcp_range(idx: str, hour: int) -> tuple[int, int | None]:
    """Byte range of the 6-hour APCP accumulation ending at `hour` in one GEFS file's index."""
    lines = [ln.split(":") for ln in idx.strip().splitlines()]
    for i, ln in enumerate(lines):
        if ln[3] == "APCP" and ln[5].startswith(f"{hour - 6}-{hour} hour acc"):
            end = int(lines[i + 1][1]) - 1 if i + 1 < len(lines) else None
            return int(ln[1]), end
    raise ValueError(f"no {hour - 6}-{hour} h APCP message in the index")


def gefs_c00_72h(issue: date, adm) -> pd.DataFrame | None:
    """72-hour rainfall from the 00 UTC GEFS control run of `issue`, per district: the 6-hour
    accumulations ending at 6, 12, ..., 72 h summed, then the area-weighted district mean, as
    pipeline/build_gefs_reforecast_adm2.py built the backtest series from the v12 reforecast.
    Returns (pcode, district, model, mm_72h); None when the run is not published (404)."""
    total = bounds = wkt = None
    for hour in range(6, 73, 6):
        u = GEFS_C00.format(day=issue, hour=hour)
        try:
            idx = _retry(lambda u=u: urllib.request.urlopen(u + ".idx", timeout=60).read())
        except urllib.error.HTTPError as err:
            if err.code == 404:
                return None
            raise
        a, b = _apcp_range(idx.decode(), hour)
        rng = f"bytes={a}-{'' if b is None else b}"
        req = urllib.request.Request(u, headers={"Range": rng})
        data = _retry(lambda req=req: urllib.request.urlopen(req, timeout=120).read())
        with tempfile.NamedTemporaryFile(suffix=".grib2", delete=False) as f:
            f.write(data)
            path = f.name
        try:
            with rasterio.open(path) as ds:
                w = (
                    from_bounds(*UGA_BOX, ds.transform)
                    .round_offsets(op="floor")
                    .round_lengths(op="ceil")
                )
                arr = ds.read(1, window=w).astype("float32")
                if total is None:
                    total, bounds, wkt = arr, window_bounds(w, ds.transform), ds.crs.to_wkt()
                else:
                    total = total + arr
        finally:
            Path(path).unlink(missing_ok=True)
    df = zonal_stats(total, bounds, wkt, adm[["ADM2_PCODE", "geometry"]])
    df["district"] = df.pcode.map(dict(zip(adm.ADM2_PCODE, adm.ADM2_EN, strict=True)))
    return df.rename(columns={"mean": "mm_72h"}).assign(model="gefs_c00")[
        ["pcode", "district", "model", "mm_72h"]
    ]


# --- GloFAS forecast ---------------------------------------------------------------------------


def glofas_legacy_versions() -> list[str]:
    """System versions EWDS lists under "Legacy Versions" for the GloFAS forecast (2.1 and 3.1
    in Nov 2026). When v4 is retired from the operational slot it appears here, as 3.1 did when
    v4 went live: from then "operational" is not the version the thresholds were fitted on.
    Same check as ds-aa-som-floods (src/monitoring/etl.check_glofas_version)."""
    from src.datasources.glofas import _client

    form = (
        _client(wait_until_complete=False, retry_max=3, sleep_max=10)
        .client.get_collection("cems-glofas-forecast")
        .form
    )
    for w in form:
        if w.get("name") == "system_version":
            for grp in w.get("details", {}).get("groups", []):
                if grp.get("label", "").lower().startswith("legacy"):
                    return list(grp.get("values", []))
    return []


# N, W, S, E: Teso (every admin area at levels 2-4 of the six districts, all_touched) and the
# Elgon zone, with a margin. monitoring/static.py checks that every cell it uses is inside.
GLOFAS_AREA = [2.75, 32.85, 0.45, 35.1]
# A step's valid_time is the END of its 24-hour mean (the reanalysis is labelled the same way).
# The 24 h step is the issue day itself, the IBF portal's lead day 0, so its lead days 0-5 are
# the steps to 144 h. The Elgon exposure backtest dated an exceedance 5 days early: the 120 h step.
GLOFAS_LEAD_HOURS = list(range(24, 145, 24))  # Teso reads to 144 h, Elgon to 120 h


def glofas_request(issue: date, nudge: int = 0, hours: list[int] | None = None) -> dict:
    """`nudge` moves the east edge by 0.001 deg per retry: EWDS caches a partial issue (members
    still being published) and serves it back to identical requests for hours (Somalia,
    12 Oct 2026); a different area forces a fresh product. The grid is unchanged."""
    n, w, s, e = GLOFAS_AREA
    return {
        "system_version": ["operational"],
        "hydrological_model": ["lisflood"],
        "product_type": ["control_forecast", "ensemble_perturbed_forecasts"],
        "variable": "river_discharge_in_the_last_24_hours",
        "year": [f"{issue:%Y}"],
        "month": [f"{issue:%m}"],
        "day": [f"{issue:%d}"],
        "leadtime_hour": [str(h) for h in (hours or GLOFAS_LEAD_HOURS)],
        "data_format": "netcdf",
        "download_format": "zip",
        "area": [n, w, s, round(e + 0.001 * nudge, 3)],
    }


def download_glofas(
    issue: date, out: Path, nudge: int = 0, deadline: datetime | None = None, poll: int = 60
) -> Path:
    """One forecast issue to `out` (a zip of netCDFs). Submits, then polls EWDS until it delivers
    or `deadline` (UTC) passes; at the deadline the request is deleted, so it does not hold the
    account's one-at-a-time queue, and TimeoutError is raised. A request EWDS refuses (400 while
    the issue is not published yet) raises at submission."""
    from src.datasources.glofas import _client

    out.parent.mkdir(parents=True, exist_ok=True)
    # Few, short retries: the client's defaults (500 retries, up to 120 s apart) would hold one
    # call through an EWDS outage for hours, past the deadline and the task timeout.
    client = _client(wait_until_complete=False, retry_max=5, sleep_max=30)
    remote = client.retrieve("cems-glofas-forecast", glofas_request(issue, nudge))
    done = False
    try:
        while True:
            try:
                remote.update()
                status = remote.status
            except Exception as err:  # noqa: BLE001 - a status blip must not cost the queue place
                print(f"GloFAS: status check failed ({type(err).__name__}); polling on")
                status = None
            if status == "successful":
                remote.download(str(out))
                done = True
                return out
            if status in ("failed", "rejected", "dismissed"):
                raise RuntimeError(f"EWDS request {status}")
            if deadline is not None and datetime.now(UTC) >= deadline:
                raise TimeoutError(
                    f"EWDS had not delivered the {issue} issue by {deadline:%H:%M} UTC"
                )
            time.sleep(poll)
    finally:
        if not done:  # never leave a request in the account's one-at-a-time queue
            try:
                remote.delete()
            except Exception as err:  # noqa: BLE001 - best effort
                print(f"GloFAS: could not delete the abandoned request ({type(err).__name__})")


def open_glofas(path: Path) -> xr.DataArray:
    """Discharge as (issue, member, lead_day, lat, lon), lat descending. Control is member 0;
    lead_day n is the step ending n days after the issue's 00 UTC."""
    parts = []
    with zipfile.ZipFile(path) as z, tempfile.TemporaryDirectory() as tmp:
        for name in z.namelist():
            if not name.endswith(".nc"):
                continue
            nc = Path(z.extract(name, tmp))
            with xr.open_dataset(nc) as ds:
                var = next(v for v in ds.data_vars if "dis" in v)
                da = ds[var].load()
            if "number" not in da.dims:
                da = da.expand_dims(number=[0])
            parts.append(da)
    da = xr.concat(parts, dim="number")
    lead = next(d for d in da.dims if d in ("forecast_period", "step", "leadtime"))
    if "forecast_reference_time" not in da.dims:
        da = da.expand_dims("forecast_reference_time")
    da = da.squeeze(
        [
            d
            for d in da.dims
            if d not in ("number", lead, "forecast_reference_time", "latitude", "longitude")
        ]
    )
    days = (pd.to_timedelta(da[lead].values) / pd.Timedelta(days=1)).astype(int)
    issues = pd.to_datetime(da.forecast_reference_time.values).normalize()
    da = da.assign_coords({lead: days, "forecast_reference_time": issues})
    da = da.rename(
        {
            lead: "lead_day",
            "number": "member",
            "forecast_reference_time": "issue",
            "latitude": "lat",
            "longitude": "lon",
        }
    )
    da = da.drop_vars([c for c in da.coords if c not in da.dims])
    return da.sortby("lat", ascending=False).transpose("issue", "member", "lead_day", "lat", "lon")
