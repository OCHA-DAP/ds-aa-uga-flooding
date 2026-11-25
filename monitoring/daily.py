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
    return {s for s in gaps.source if s in ("GloFAS", "CHIRPS3-GEFS", "GEFS control")}


def past(cutoff: str) -> bool:
    h, m = map(int, cutoff.split(":"))
    now = datetime.now(UTC)
    return (now.hour, now.minute) >= (h, m)


def keep_fuller(day: pd.DataFrame, blob: str) -> pd.DataFrame:
    """Per (zone, trigger): keep the stored rows of this issue where the new run could not
    evaluate the trigger at all and the stored run could (a late re-run must not replace a
    met / not-met reading with "not evaluated"); otherwise the new rows."""
    if not R.blob_exists(blob):
        return day
    old = stratus.load_parquet_from_blob(blob, stage="dev")
    parts = []
    for key, new in day.groupby(["zone", "trigger"], sort=False):
        stored = old[(old.zone == key[0]) & (old.trigger == key[1])]
        if new.met.isna().all() and stored.met.notna().any():
            print(f"{key[0]} / {key[1]}: not evaluated now; keeping the stored reading")
            parts.append(stored)
        else:
            parts.append(new)
    return pd.concat(parts, ignore_index=True)


def mark_sent(record: dict, blob: str, attempts: int = 3) -> None:
    for i in range(attempts):
        try:
            stratus.upload_blob_data(json.dumps(record, default=str).encode(), blob, stage="dev")
            return
        except Exception:
            if i == attempts - 1:
                raise
            time.sleep(10)


def main() -> None:
    issue = date.fromisoformat(os.getenv("MONITORING_DATE") or datetime.now(UTC).date().isoformat())
    if issue.month not in R.SEASON_MONTHS:
        print(f"{issue}: outside the October-December window, nothing to do")
        return
    dry, test = notify.check_config()  # fail now, not after hours of waiting
    sent_blob = f"{R.OUT}/sent/{issue:%Y-%m-%d}.json"
    if not dry and not test and R.blob_exists(sent_blob):
        print(f"already sent for {issue}; not evaluating or sending again")
        return
    cutoff = os.getenv("WAIT_UNTIL_UTC", "15:45")
    rerun = issue < datetime.now(UTC).date()  # a past issue: everything is out, no waiting
    inp = R.Inputs()
    while True:
        day = R.evaluate_issue(issue, inp, live=True)
        missing = waiting_for(day)
        if not missing or rerun or past(cutoff):
            break
        print(
            f"waiting for {sorted(missing)}; next try in {RETRY_MINUTES} min (until {cutoff} UTC)"
        )
        time.sleep(RETRY_MINUTES * 60)

    if not dry:
        day = keep_fuller(day, f"{R.OUT}/daily/{issue:%Y-%m-%d}.parquet")
        R.write(day)
        R.append(day, f"{R.OUT}/season/{issue.year}.parquet")
        R.append(R.zone_summary(day), f"{R.OUT}/season/{issue.year}_zones.parquet")
    season_blob = f"{R.OUT}/season/{issue.year}.parquet"
    season = day
    if R.blob_exists(season_blob):
        old = stratus.load_parquet_from_blob(season_blob, stage="dev")
        season = pd.concat([old[old.issue_date != pd.Timestamp(issue)], day])
    print(R.zone_summary(day).to_string(index=False))

    # A live send is recorded as soon as Listmonk accepts it, before the delivery check, so a
    # failure after that cannot make a re-run send it twice.
    def first_mark(record: dict) -> None:
        try:
            mark_sent(record, sent_blob)
        except Exception as err:  # noqa: BLE001 - written again below; raised only if both fail
            print(f"WARNING: sent marker not written yet ({type(err).__name__}); retrying")

    result = notify.send(
        day,
        season.sort_values("issue_date"),
        on_live_send=first_mark,
        version_note=R.glofas_version_status() + ".",
    )
    if result.get("sent") and not result.get("delivered"):
        # Listmonk's sent count is not reliable either way (19 Nov 2026: 0/1 reported, email
        # received), so this is a warning in the log and the record, not a failure.
        print(f"WARNING: Listmonk did not confirm delivery of campaign {result.get('campaign')}")
    if result.get("sent") and not result.get("test"):
        mark_sent(result, sent_blob)  # the full record, with the delivery check
    if retired := R.glofas_v4_retired():
        # the email has gone out with the GloFAS triggers not evaluated; fail so the job's
        # failure mail reaches whoever must refit the GloFAS thresholds
        raise SystemExit(
            f"GloFAS operational is no longer v4 (EWDS legacy: {retired}): Teso and the Elgon "
            "GloFAS trigger were not evaluated. Refit their thresholds on the new version."
        )


if __name__ == "__main__":
    main()
