"""Daily job: evaluate today's issue for all four zones, store it, send the email.

Waits for the two forecasts that publish during the day (CHIRPS3-GEFS ~09:20 UTC; GloFAS on
EWDS, whose queue can take hours) and retries every RETRY_MINUTES until WAIT_UNTIL_UTC; after
that it evaluates with what it has and the email names what is missing.

Environment:
  MONITORING_DATE   issue day (YYYY-MM-DD); default today (UTC)
  WAIT_UNTIL_UTC    HH:MM, default 15:45
  DRY_RUN, TEST_EMAIL, LISTMONK_LIST_ID, LISTMONK_TEST_LIST_ID   see monitoring/notify.py

A live send (TEST_EMAIL=false, DRY_RUN=false) is recorded in private/monitoring/sent/{issue}.json on the
dev blob (under private/) and not repeated for that issue.

Run:  uv run python monitoring/daily.py
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import UTC, date, datetime
from pathlib import Path

import ocha_stratus as stratus
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from monitoring import notify
from monitoring import run as R

RETRY_MINUTES = 15


def waiting_for(day: pd.DataFrame) -> set[str]:
    """Same-day forecasts still missing (the slow sources are reported, not waited for)."""
    gaps = day[day.met.isna()]
    return {s for s in gaps.source if s in ("GloFAS", "CHIRPS3-GEFS")}


def past(cutoff: str) -> bool:
    h, m = map(int, cutoff.split(":"))
    now = datetime.now(UTC)
    return (now.hour, now.minute) >= (h, m)


def main() -> None:
    issue = date.fromisoformat(os.getenv("MONITORING_DATE") or datetime.now(UTC).date().isoformat())
    if issue.month not in R.SEASON_MONTHS:
        print(f"{issue}: outside the October-December window, nothing to do")
        return
    cutoff = os.getenv("WAIT_UNTIL_UTC", "15:45")
    inp = R.Inputs()
    while True:
        day = R.evaluate_issue(issue, inp, live=True)
        missing = waiting_for(day)
        if not missing or past(cutoff):
            break
        print(
            f"waiting for {sorted(missing)}; next try in {RETRY_MINUTES} min (until {cutoff} UTC)"
        )
        time.sleep(RETRY_MINUTES * 60)

    if not notify.env_flag("DRY_RUN", True):
        R.write(day)
        R.append(day, f"{R.OUT}/season/{issue.year}.parquet")
        R.append(R.zone_summary(day), f"{R.OUT}/season/{issue.year}_zones.parquet")
    season_blob = f"{R.OUT}/season/{issue.year}.parquet"
    season = day
    if R.blob_exists(season_blob):
        old = stratus.load_parquet_from_blob(season_blob, stage="dev")
        season = pd.concat([old[old.issue_date != pd.Timestamp(issue)], day])
    print(R.zone_summary(day).to_string(index=False))

    sent_blob = f"{R.OUT}/sent/{issue:%Y-%m-%d}.json"
    live_send = not notify.env_flag("DRY_RUN", True) and not notify.env_flag("TEST_EMAIL", True)
    if live_send and R.blob_exists(sent_blob):
        print(f"already sent for {issue}; not sending again")
        return
    result = notify.send(day, season.sort_values("issue_date"))
    if result.get("sent") and not result.get("delivered"):
        # Listmonk's sent count is not reliable either way (19 Nov 2026: 0/1 reported, email
        # received), so this is a warning in the log and the record, not a failure: failing would
        # make a re-run send the trigger email twice.
        print(f"WARNING: Listmonk did not confirm delivery of campaign {result.get('campaign')}")
    if result.get("sent") and not result.get("test"):
        stratus.upload_blob_data(json.dumps(result, default=str).encode(), sent_blob, stage="dev")


if __name__ == "__main__":
    main()
