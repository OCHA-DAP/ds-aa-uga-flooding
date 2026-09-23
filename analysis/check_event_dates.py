"""Check the researched date corrections in src/data/event_dates.csv.

Every correction must match at least one (event, district) row, and every date it sets must be
inside the impact record's plausible range. Run after editing the file:

  uv run python analysis/check_event_dates.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.datasources import impact as imp


def main() -> None:
    v = imp.load_verified_dates()
    raw = (
        imp.events_by_district.__wrapped__()
        if hasattr(imp.events_by_district, "__wrapped__")
        else None
    )
    ev = imp.events_by_district()
    print(f"{len(v)} corrections; {len(ev)} (event, district) rows")
    unmatched = []
    for _, c in v.iterrows():
        m = pd.Series(True, index=ev.index)
        if isinstance(c.event_id, str) and c.event_id:
            m &= ev.event_id.astype(str) == c.event_id
        if isinstance(c.source, str) and c.source:
            m &= ev.source.astype(str).str.startswith(c.source)
        if c.districts:
            m &= ev.district.isin(c.districts)
        n = int((m & (ev.start == c.start)).sum())
        if n == 0:
            unmatched.append((c.event_id, c.source, c.districts, c.start))
        print(
            f"  {str(c.event_id or c.source)[:28]:30s} {str(c.start)[:10]} -> {n:3d} rows  {str(c.evidence)[:60]}"
        )
    if unmatched:
        print("\nUNMATCHED corrections (nothing changed by these):")
        for u in unmatched:
            print("   ", u)
        raise SystemExit(1)
    print("\nall corrections matched")
    if raw is not None:
        print(raw.head())


if __name__ == "__main__":
    main()
