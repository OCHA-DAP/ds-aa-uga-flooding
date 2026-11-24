"""Evaluate all four zones for one issue day (used by monitoring/daily.py), or replay past days.

  uv run python monitoring/run.py 2026-11-18            replay one past issue day
  uv run python monitoring/run.py 2026-10-01 2026-11-18 replay a range

A replay reads the same products as the daily job, except: CPC soil moisture is the day before the issue
(live: the latest file, ~2 days behind); Lake Kyoga uses every pass up to the issue day, not only
those NASA had published by then (~1 week behind). So a replay is kept apart from the operational
record: it writes under private/monitoring/replay/, never the files daily.py reads.

The results carry the Elgon partner thresholds, so everything is written under private/ on the
dev blob. GloFAS files are cached under data/glofas/raw/forecast_monitoring/ (gitignored).
"""

from __future__ import annotations

import io
import os
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import numpy as np
import ocha_stratus as stratus
import pandas as pd
import xarray as xr

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from monitoring import evaluate as ev
from monitoring import feeds
from monitoring.static import CONFIG, PRIVATE_STATIC, STATIC, forecast_grid
from pipeline.build_openmeteo_runs_adm2 import daily_frame, district_points, fetch
from src.constants import PROJECT_PREFIX, ZONES
from src.frameworks import read_private_config
from src.zones import load_adm2

GLOFAS_CACHE = ROOT / "data" / "glofas" / "raw" / "forecast_monitoring"
OUT = f"{PROJECT_PREFIX}/private/monitoring"  # operational record, written by daily.py
REPLAY = f"{OUT}/replay"
SEASON_MONTHS = (10, 11, 12)
ZONE_ORDER = ("teso_kyoga", "elgon", "karamoja", "adjumani")


class Inputs:
    """Everything fixed for a run: static tables, thresholds, the partner config, boundaries."""

    def __init__(self):
        self.units = stratus.load_parquet_from_blob(f"{STATIC}/teso_units.parquet", stage="dev")
        self.cells = stratus.load_parquet_from_blob(
            f"{PRIVATE_STATIC}/elgon_t2_cells.parquet", stage="dev"
        )
        self.thr = pd.read_csv(
            io.BytesIO(stratus.load_blob_data(f"{CONFIG}/thresholds.csv", stage="dev"))
        )
        self.cfg = read_private_config("partner_triggers.local.json")
        if self.cfg is None:
            raise SystemExit("partner config unavailable: the Elgon trigger cannot be evaluated")
        self.adm = load_adm2()
        self.name_of = dict(zip(self.adm.ADM2_PCODE, self.adm.ADM2_EN, strict=True))
        need = (
            set(ZONES["karamoja"].core)
            | set(ZONES["adjumani"].core + ZONES["adjumani"].tier2)
            | set(self.cfg["districts"])
        )
        self.polys = self.adm[self.adm.ADM2_EN.isin(need)][["ADM2_PCODE", "geometry"]]
        self.elgon_adm = self.adm[self.adm.ADM2_EN.isin(self.cfg["districts"])]
        sh = stratus.load_parquet_from_blob(
            f"{PROJECT_PREFIX}/processed/cpc_soil/cpc_soil_adm2_daily.parquet", stage="dev"
        )
        self.soil_hist = sh[sh.pcode.isin(self.elgon_adm.ADM2_PCODE)]
        self._passes = None

    @property
    def passes(self) -> pd.DataFrame:
        if self._passes is None:
            self._passes = feeds.kyoga_levels()
        return self._passes


# --- GloFAS ------------------------------------------------------------------------------------


_OPENED: dict[Path, object] = {}


def _cached(issue: date):
    """`issue` from the cache, steps from every file that holds it, joined (a backfill can hold
    some steps in one file and the rest in another). Names: glofas_fc<tag>_<first>_<last day>.zip.
    May hold fewer steps than Teso reads; the caller decides what it can evaluate."""
    parts = []
    for f in sorted(GLOFAS_CACHE.glob("glofas_fc*.zip")):
        first, last_day = f.stem.split("_")[-2:]
        first = date.fromisoformat(first)
        if first <= issue <= first.replace(day=int(last_day)):
            if f not in _OPENED:
                _OPENED[f] = feeds.open_glofas(f)
            parts.append(_OPENED[f].sel(issue=pd.Timestamp(issue)))
    if not parts:
        return None
    da = xr.concat(parts, dim="lead_day").sortby("lead_day")
    da = da.isel(lead_day=~pd.Index(da.lead_day.values).duplicated())
    return da


def on_grid(da):
    """Onto the static grid the Teso cell indices refer to (a nudged request can add a column)."""
    lat, lon = forecast_grid()
    return da.sel(lat=lat, lon=lon, method="nearest", tolerance=1e-3)


_STARTED = datetime.now(UTC)
PAST_ISSUE_WAIT = timedelta(hours=3)


def glofas_deadline(issue: date) -> datetime:
    """When the daily job stops waiting for EWDS (GLOFAS_DEADLINE_UTC, HH:MM on the issue day,
    default 17:30): the email then goes out with the GloFAS triggers marked not evaluated, rather
    than the job timing out with no email at all. For a past issue (a manual re-run) the
    issue-day deadline has already gone, so the wait is PAST_ISSUE_WAIT from the job's start."""
    if issue < _STARTED.date():
        return _STARTED + PAST_ISSUE_WAIT
    h, m = map(int, os.getenv("GLOFAS_DEADLINE_UTC", "17:30").split(":"))
    return datetime(issue.year, issue.month, issue.day, h, m, tzinfo=UTC)


_V4_LEGACY: list[str] | None = None


def glofas_v4_retired() -> list[str]:
    """The v4 entries EWDS lists as legacy for the GloFAS forecast: empty while v4 is the
    operational version (the one every GloFAS threshold here was fitted on). Checked once per
    process. A failed check is a warning, not a version change."""
    global _V4_LEGACY
    if _V4_LEGACY is None:
        try:
            legacy = feeds.glofas_legacy_versions()
            print(f"EWDS GloFAS legacy versions: {legacy}")
        except Exception as err:  # noqa: BLE001 - catalogue down: carry on, say so
            print(f"WARNING: GloFAS version check failed ({type(err).__name__}); assuming v4")
            legacy = []
        _V4_LEGACY = [v for v in legacy if v.startswith("version_4")]
    return _V4_LEGACY


_NUDGE: dict[date, int] = {}  # per issue, kept across daily.py waits: never re-ask an area


def glofas_issue(issue: date, attempts: int = 1):
    """The forecast for one issue: from a cached file if there is one, else from EWDS. A partial
    issue (fewer than 51 members) is deleted and requested again with a newly nudged area; the
    nudge keeps counting across calls, since EWDS serves a cached partial product back to any
    area it has already seen. One request per call by default: daily.py calls again every
    RETRY_MINUTES, and the account's EWDS queue is shared with other live monitors."""
    da = _cached(issue)
    offline = os.getenv("GLOFAS_OFFLINE", "").lower() == "true"  # replay from the cache only
    if da is not None and (offline or int(da.lead_day.max()) >= ev.TESO_STEPS):
        return on_grid(da)
    if offline:
        return None
    if datetime.now(UTC) >= glofas_deadline(issue):
        raise TimeoutError(f"past the GloFAS deadline ({glofas_deadline(issue):%d %b %H:%M} UTC)")
    path = GLOFAS_CACHE / f"glofas_fc_{issue:%Y-%m-%d}_{issue:%d}.zip"
    q = None
    for _ in range(attempts):
        k = _NUDGE.get(issue, 0)
        _NUDGE[issue] = k + 1
        try:
            feeds.download_glofas(issue, path, nudge=k, deadline=glofas_deadline(issue))
        except TimeoutError:
            raise  # reported as "GloFAS failed (TimeoutError)": no point asking again today
        except Exception as err:  # noqa: BLE001 - not published yet, or EWDS down: reported
            print(f"GloFAS {issue}: not available ({type(err).__name__}: {str(err)[:120]})")
            return None
        q = on_grid(feeds.open_glofas(path).sel(issue=pd.Timestamp(issue)))
        if (n := ev.members_present(q)) >= ev.N_MEMBERS:
            return q
        print(f"GloFAS {issue}: {n} of {ev.N_MEMBERS} members, asking again")
        path.unlink()
    return q


# --- GFS / ICON 72-hour rain -------------------------------------------------------------------


def openmeteo_archive(start: date, end: date, adm) -> pd.DataFrame:
    """72-hour forecasts for issue days start..end from the Open-Meteo archive of past runs:
    the forecast issued on D is lead 0 at D + lead 1 at D+1 + lead 2 at D+2 (as in
    pipeline/build_openmeteo_runs_adm2.py). Returns (issue_date, pcode, district, model, mm_72h)."""
    parts = []
    for _, r in adm.iterrows():
        pts = district_points(r.geometry)
        resp = fetch(pts, start.isoformat(), (end + timedelta(days=2)).isoformat())
        d = (
            pd.concat([daily_frame(x) for x in resp])
            .groupby(["date", "model", "lead_day"], as_index=False)
            .precip_mm.mean()
        )
        d["issue_date"] = d.date - pd.to_timedelta(d.lead_day, unit="D")
        s = d.groupby(["issue_date", "model"]).precip_mm.agg(["sum", "count"]).reset_index()
        s = s[s["count"] == 3]  # all three days present
        parts.append(
            s.rename(columns={"sum": "mm_72h"}).assign(pcode=r.ADM2_PCODE, district=r.ADM2_EN)
        )
    out = pd.concat(parts, ignore_index=True)
    lo, hi = pd.Timestamp(start), pd.Timestamp(end)
    return out[(out.issue_date >= lo) & (out.issue_date <= hi)].drop(columns="count")


# --- one issue ---------------------------------------------------------------------------------


def missing(zone: str, trigger: str, source: str, issue: date, why: str) -> pd.DataFrame:
    return ev.frame(
        [
            dict(
                zone=zone,
                trigger=trigger,
                place="",
                value=np.nan,
                threshold=np.nan,
                unit="",
                met=None,
                detail=why,
                source=source,
                source_date="",
            )
        ]
    )


def _try(what: str, fn):
    """Run one source; an outage of one product must not stop the other zones."""
    try:
        return fn(), None
    except Exception as err:  # noqa: BLE001 - reported as a gap in the output and the email
        print(f"{what}: failed ({type(err).__name__}: {str(err)[:160]})")
        why = str(err) if isinstance(err, TimeoutError) else type(err).__name__
        return None, f"{what} failed ({why[:120]})"


def evaluate_issue(
    issue: date,
    inp: Inputs,
    live: bool,
    rain72: pd.DataFrame | None = None,
) -> pd.DataFrame:
    ts = pd.Timestamp(issue)
    parts = []
    t2_label = inp.cfg["t2"].get("short", "partner T2")
    t3_label = inp.cfg.get("t3", {}).get("short", "partner T3")

    retired = glofas_v4_retired() if live else []
    gl_source = "GloFAS"
    if retired:  # nothing is requested: the thresholds do not apply to the new version
        q, gl_source = None, "GloFAS version"
        gl_why = (
            f"the operational GloFAS is no longer v4 (EWDS lists {', '.join(retired)} as a "
            "legacy version); the GloFAS thresholds are v4 and must be refitted"
        )
    else:
        q, err = _try("GloFAS", lambda: glofas_issue(issue))
        gl_why = err or "GloFAS issue not available"
    if q is not None and (n := ev.members_present(q)) < ev.N_MEMBERS:
        q, gl_why = None, f"GloFAS issue incomplete ({n} of {ev.N_MEMBERS} members)"
    steps = int(q.lead_day.max()) if q is not None else 0
    short = f"GloFAS forecast has steps to {24 * steps} h only"
    if steps >= ev.TESO_STEPS:
        parts.append(ev.teso(q, inp.units, ts))
    else:
        why = gl_why if q is None else short
        parts.append(missing("teso_kyoga", "IFRC/URCS EAP (GloFAS)", gl_source, issue, why))
    if steps >= ev.T2_STEPS:
        parts.append(ev.elgon_t2(q, inp.cells, inp.cfg, ts))
    else:
        why = gl_why if q is None else short
        parts.append(missing("elgon", t2_label, gl_source, issue, why))

    # T3 rain: the GEFS control run, the series the backtest was calibrated on
    err = None
    if rain72 is None:
        rain72, err = _try("GEFS control", lambda: feeds.gefs_c00_72h(issue, inp.elgon_adm))
    soil, soil_err = _try(
        "CPC soil moisture",
        lambda: (
            feeds.cpc_soil_latest(issue, inp.polys)
            if live
            else feeds.cpc_soil(issue - timedelta(days=1), inp.polys)
        ),
    )
    soil = soil[soil.pcode.isin(inp.elgon_adm.ADM2_PCODE)] if soil is not None else None
    if rain72 is None or rain72.empty:
        why = err or "the 00 UTC GEFS control run is not published yet"
        parts.append(missing("elgon", t3_label, "GEFS control", issue, why))
    else:
        if soil is None:
            print(f"CPC soil moisture: {soil_err or 'no file in the last 7 days'}")
        parts.append(ev.elgon_t3(rain72, soil, inp.soil_hist, inp.cfg, ts))

    cg, err = _try("CHIRPS3-GEFS", lambda: feeds.chirps3_gefs(issue, inp.polys))
    for z in ("karamoja", "adjumani"):
        if cg is not None:
            parts.append(ev.rain_zone(z, cg, inp.thr, inp.name_of, ts))
        else:
            why = err or "issue not published"
            parts.append(missing(z, "CHIRPS3-GEFS 5-day rain", "CHIRPS3-GEFS", issue, why))
    lake, err = _try("Lake Kyoga (NASA GWM)", lambda: ev.adjumani_lake(inp.passes, inp.thr, ts))
    if lake is not None:
        parts.append(lake)
    else:
        parts.append(missing("adjumani", "Lake Kyoga 180-day rise", "NASA GWM", issue, err))

    out = pd.concat([p for p in parts if len(p)], ignore_index=True)
    out.insert(0, "issue_date", ts)
    return out


def zone_summary(day: pd.DataFrame) -> pd.DataFrame:
    """Per zone for one issue: met / not met / incomplete, and which triggers were met where."""
    rows = []
    for z in ZONE_ORDER:
        g = day[day.zone == z]
        met = g[g.met.eq(True)]
        gaps = g[g.met.isna()]
        status = "met" if len(met) else ("incomplete" if len(gaps) else "not met")
        rows.append(
            dict(
                issue_date=day.issue_date.iloc[0],
                zone=z,
                status=status,
                met_by="; ".join(sorted({f"{r.trigger}: {r.place}" for r in met.itertuples()})),
                gaps="; ".join(sorted(set(gaps.detail))),
            )
        )
    return pd.DataFrame(rows)


def write(day: pd.DataFrame, prefix: str = OUT) -> None:
    issue = day.issue_date.iloc[0]
    d = day.copy()
    d["met"] = d.met.astype("object")
    stratus.upload_parquet_to_blob(d, f"{prefix}/daily/{issue:%Y-%m-%d}.parquet", stage="dev")


def main(start: str, end: str | None = None) -> None:
    """Replay past issue days; results go under REPLAY, apart from the operational record."""
    d0 = date.fromisoformat(start)
    d1 = date.fromisoformat(end) if end else d0
    inp = Inputs()
    days, summaries = [], []
    for k in range((d1 - d0).days + 1):
        issue = d0 + timedelta(days=k)
        if issue.month not in SEASON_MONTHS:
            continue
        day = evaluate_issue(issue, inp, live=False)  # GEFS runs stay on NOAA's archive
        write(day, REPLAY)
        s = zone_summary(day)
        print(f"{issue}: " + ", ".join(f"{r.zone} {r.status}" for r in s.itertuples()))
        days.append(day)
        summaries.append(s)
    if not days:
        print("no issue day in the October-December window")
        return
    for new, name in (
        (pd.concat(days, ignore_index=True), f"{d0.year}.parquet"),
        (pd.concat(summaries, ignore_index=True), f"{d0.year}_zones.parquet"),
    ):
        append(new, f"{REPLAY}/season/{name}")


def blob_exists(blob: str) -> bool:
    return stratus.get_container_client(stage="dev").get_blob_client(blob).exists()


def append(new: pd.DataFrame, blob: str) -> None:
    """Replace the issue days in `new` within the season file, keep the rest."""
    if blob_exists(blob):
        old = stratus.load_parquet_from_blob(blob, stage="dev")
        new = pd.concat([old[~old.issue_date.isin(new.issue_date.unique())], new])
    if "met" in new:
        new["met"] = new.met.astype("object")
    out = new.sort_values("issue_date").reset_index(drop=True)
    stratus.upload_parquet_to_blob(out, blob, stage="dev")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit("usage: run.py START [END]  (the daily job is monitoring/daily.py)")
    main(*sys.argv[1:3])
