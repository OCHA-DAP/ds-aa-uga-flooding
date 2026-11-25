"""Download GloFAS forecast issues for a date range into data/glofas/raw/forecast_monitoring/
(gitignored), in chunks of consecutive days within a month, halving a chunk when EWDS refuses it
on cost. Used to backfill the season; the daily job fetches one issue at a time through
monitoring.feeds.download_glofas.

Run:  uv run python monitoring/fetch_glofas_range.py 2026-10-01 2026-11-18 [chunk_days] [hours]

`hours` (comma-separated, e.g. 144) fetches only those steps, into files tagged with them;
monitoring/run.py joins the steps of every cached file that holds an issue.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from monitoring.feeds import glofas_request
from src.datasources.glofas import _client

OUT = ROOT / "data" / "glofas" / "raw" / "forecast_monitoring"


def get(c, days: pd.DatetimeIndex, hours: list[int] | None) -> None:
    tag = "".join(str(h) for h in hours) if hours else ""
    out = OUT / f"glofas_fc{tag}_{days[0]:%Y-%m-%d}_{days[-1]:%d}.zip"
    if out.exists():
        print("have", out.name)
        return
    req = glofas_request(days[0].date(), hours=hours) | {"day": [f"{d:%d}" for d in days]}
    try:
        c.retrieve("cems-glofas-forecast", req, str(out))
        print("got", out.name, out.stat().st_size, "bytes", flush=True)
    except requests.HTTPError as err:
        if "cost limits" not in str(err) or len(days) == 1:
            raise
        h = len(days) // 2
        print(f"{len(days)} days too large, splitting", flush=True)
        get(c, days[:h], hours)
        get(c, days[h:], hours)


def main(start: str, end: str, chunk: str = "7", hours: str = "") -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    days = pd.date_range(start, end, freq="D")
    hrs = [int(h) for h in hours.split(",")] if hours else None
    c = _client()
    for _, grp in days.to_series().groupby([days.year, days.month]):
        idx = grp.index
        for i in range(0, len(idx), int(chunk)):
            get(c, idx[i : i + int(chunk)], hrs)


if __name__ == "__main__":
    main(*sys.argv[1:5])
