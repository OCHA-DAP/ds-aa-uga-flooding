"""Check the researched date corrections in src/data/event_dates.csv.

Corrections reach the record by two paths — DesInventar cards through
`desinventar.load_datacards()`, and EM-DAT / curated / DTM events through
`impact.events_by_district()` — so both are checked here. A correction that matches nothing
is a silent no-op, which is the failure mode worth catching: run this after editing the file.

  uv run python analysis/check_event_dates.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.datasources import desinventar as di
from src.datasources import impact as imp


def main() -> None:
    v = imp.load_verified_dates()
    ev = imp.events_by_district()
    cards = di.load_datacards()
    raw_cards = di.load_datacards(verified=False)
    print(f"{len(v)} corrections | {len(ev)} event-district rows | {len(cards)} DesInventar cards")
    unmatched = []
    for _, c in v.iterrows():
        is_di = isinstance(c.source, str) and c.source.startswith("DesInventar")
        if is_di:
            m = raw_cards.date.dt.normalize() == c.match_start.normalize()
            if c.districts:
                m &= raw_cards.district.isin(c.districts)
            n, what = int(m.sum()), "cards"
        else:
            m = pd.Series(True, index=ev.index)
            if isinstance(c.event_id, str) and c.event_id:
                m &= ev.event_id.astype(str) == c.event_id
            if isinstance(c.source, str) and c.source:
                m &= ev.source.astype(str).str.startswith(c.source)
            n, what = int(m.sum()), "event rows"
        label = str(c.event_id if isinstance(c.event_id, str) and c.event_id else c.source)
        print(
            f"  {label[:24]:26s} {str(c.match_start)[:10]} -> {str(c.start)[:10]}..{str(c.end)[:10]}"
            f"  {n:4d} {what:11s} {str(c.evidence)[:52]}"
        )
        if n == 0:
            unmatched.append((label, str(c.match_start)[:10], c.districts))
    if unmatched:
        print("\nUNMATCHED (these corrections change nothing):")
        for u in unmatched:
            print("   ", u)
        raise SystemExit(1)
    # and confirm the corrections actually moved the dates that reach the analyses
    moved = int((cards.date != raw_cards.date).sum())
    print(f"\nall corrections matched; {moved} DesInventar cards re-dated")


if __name__ == "__main__":
    main()
