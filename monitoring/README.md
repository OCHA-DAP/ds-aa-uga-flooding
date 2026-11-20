# Uganda flood trigger monitor

Daily check of the four zone triggers in the October to December window, on the live products.

| zone | trigger | live product | published |
|---|---|---|---|
| Teso / Lake Kyoga | IFRC/URCS EAP as the IBF portal computes it: per admin area (levels 2 to 4), 60 % of 51 members over the zonal max of the official 5-year map | GloFAS operational forecast (EWDS `cems-glofas-forecast`) | daily; EWDS queue from minutes to hours |
| Mount Elgon | the partner's draft triggers, as backtested in `analysis/elgon_exposure_trigger.py` and `analysis/existing_triggers.py` | read from the private config | |
| Karamoja | CHIRPS3-GEFS 5-day district mean against each district's v3 threshold, any of nine | CHIRPS3-GEFS (CHC) | about 09:20 UTC |
| Adjumani / Albert Nile | Lake Kyoga 180-day rise OR CHIRPS3-GEFS 5-day district mean, v3 thresholds | NASA Global Water Monitor; CHIRPS3-GEFS | lake passes every 10 days, about a week behind |

Code: `feeds.py` (one reader per product), `evaluate.py` (the rules), `run.py` (one issue, or a
replay), `notify.py` (email), `daily.py` (the job), `static.py` (fixed inputs, built once).

The Elgon partner's parameters, districts and labels are read at run time from the private
config on the dev blob, never from this folder. Outputs that carry them are written under
`private/`. The Karamoja and Adjumani thresholds are read from `monitoring/config/thresholds.csv`
on the dev blob.

## Run

```bash
uv run python monitoring/static.py                          # once, or after a threshold change
uv run python monitoring/run.py 2026-10-01 2026-11-18       # replay a range (archived feeds)
uv run python monitoring/daily.py                           # today; DRY_RUN=true by default
```

`daily.py` flags: `DRY_RUN` (default true: render to `monitoring/out/`, send and write nothing),
`TEST_EMAIL` (default true: list 103, `[TEST]` subject), `LISTMONK_LIST_ID` (live list, required
when `TEST_EMAIL=false`), `MONITORING_DATE`, `WAIT_UNTIL_UTC` (default 15:45).

## Blob (dev, `ds-aa-uga-flooding/`)

- `private/monitoring/daily/{issue}.parquet`: one row per zone, trigger and place
- `private/monitoring/season/{year}.parquet`, `{year}_zones.parquet`: the season so far
- `private/monitoring/sent/{issue}.json`: a live email went out for that issue
- `private/monitoring/replay/`: replays (`run.py`), kept apart from the operational record
- `monitoring/static/teso_units.parquet`, `monitoring/config/thresholds.csv`,
  `private/monitoring/elgon_t2_cells.parquet`: fixed inputs

## Databricks

`databricks.yml` defines `uga_flood_monitoring` (10:00 UTC, Oct to Dec, waits for GloFAS until
15:45 UTC). Defaults are safe: `dry_run` true, `test_email` true. No live list exists yet.
