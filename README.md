# ds-aa-uga-flooding

Trigger design for **anticipatory action (AA) for flooding in Uganda** — a multi-zone
mechanism for the OCHA/CERF framework under development (started Sep 2026).

Builds on the exploratory work in
[`ds-seas5-skill`](https://github.com/OCHA-DAP/ds-seas5-skill) (Uganda drought & flood
analysis, OND 2026 flood-trigger design options, FloodScan recurrence layers, GloFAS
skill verification) — that repo keeps the country-team readouts; this one holds the
trigger analysis proper.

**Site:** <https://ocha-dap.github.io/ds-aa-uga-flooding/>

| page | what | access |
|---|---|---|
| `/coverage/` | the zones and tiers, district lists, other organisations' flood AA coverage, harmonisation by area | public |
| `/results/` | the analysis behind the zones: GloFAS coverage, FloodScan and exposure vs impact, rainfall chain, backstop options, CEMS, impact maps | public |
| `/triggers/` | **the draft triggers**: one per zone, budget shared by historical impact, year-by-year backtest, existing partner triggers alongside | restricted |
| `/partner/` | the substance of unpublished partner plans (FAO's draft Mt Elgon AAP) and the coverage map including them | restricted |

Restricted pages use the team review password (ask Tristan). See *Private material* below.

## Handover — state of play (Sep 2026)

**Where it stands.** Zones are settled (`src/constants.py`, rationale on `/coverage/`). A first
draft of all four triggers exists, calibrated and backtested on 2000–2025 (`/triggers/`):

| zone | draft trigger | design RP | notes |
|---|---|---|---|
| Teso / Lake Kyoga | GloFAS G5196 discharge (reanalysis stand-in) | ~1-in-6 | carries the must-catch 2007; same years as the IFRC stand-in; model and satellite diverge after 2013 |
| Mount Elgon | CHIRPS-GEFS 5-day forecast, zone mean of 15 districts | ~1-in-8 | largest weight (about half the recorded people affected); catches 2019 and 2018 |
| Karamoja | CHIRPS-GEFS 5-day forecast, any district at a common rarity | ~1-in-34 | weak; funding per district vs all-in undecided |
| Adjumani / Albert Nile | Lake Kyoga 180-day rise OR per-district rain forecast | ~1-in-25 | two legs for two flood regimes; lake leg catches 2020 |

The overall return period (any zone activating) is 1-in-3 by design (9 of 26 years,
2000–2025). The budget is shared in proportion to each zone's recorded people affected, with
2007 — the largest flood year and a CERF year — required as a must-catch event, met by the
zone where it costs least (Teso). `ALLOCATION` and `MUST_CATCH` in `analysis/trigger_draft.py`;
alternatives are tabulated on the page.

**Open questions** (also at the foot of `/triggers/`): run Teso on the reforecast and get a
third opinion (DWRM gauge / Flood Hub) on the post-2013 divergence; test longer rainfall
windows (the rain zones miss 2007; only Teso catches it); decide whether rain-forecast triggers sit behind the
FloodScan backstop; Karamoja funding; agree spatial scale and rainfall product with FAO and
DRC for their rain triggers; the country team's call on the Severity 3+ scope in Teso.

**In flight.**
- GloFAS reforecast for G5196 (`pipeline/download_glofas.py`, EWDS, slow queue; resumes from
  what is on disk). When complete, replace the reanalysis stand-in for Teso.
- ERA5-Land soil moisture download stalled on CDS timeouts; the antecedent precipitation index
  (IMERG) is the proxy meanwhile.

**Things learned the hard way** (details in `CLAUDE.md` and `docs/research-notes.md`):
- Judge an indicator in an area on evidence relative to *that area's own record* (percentiles,
  AUC), not absolute magnitude; judge GloFAS points on correlation and skill, not KGE.
- When scoring events on the maximum of a window, measure the chance rate — it is not 20 %.
- CHIRPS-GEFS: the builder retries (transient errors once silently dropped Mar–Dec 2013);
  Jan–Sep 2020 is a genuine gap in the product.
- Unpublished partner material never goes in committed source or public pages.

## Rebuilding everything

```bash
uv sync
# data (each writes to the dev blob; all resumable)
uv run python pipeline/build_daily_adm2.py floodscan
uv run python pipeline/build_daily_adm2.py imerg
uv run python pipeline/build_chirps_gefs_adm2.py
uv run python pipeline/download_glofas.py            # or pull the mirror, below
# analyses
uv run python analysis/<script>.py                   # each is standalone; see Layout
# triggers
uv run python analysis/trigger_draft.py
uv run python analysis/existing_triggers.py
# pages
uv run python pipeline/zones_map.py
uv run python pipeline/build_pages.py                # /coverage/ and /results/
uv run python pipeline/build_trigger_page.py         # /triggers/ (encrypted)
uv run python pipeline/build_private_page.py         # /partner/ (encrypted)
```

`pages/` is committed and published as-is by `.github/workflows/deploy-pages.yml` on push.
Bump `ASSET_VERSION` in `pipeline/build_pages.py` when `pages/assets/*.css` changes.

## Private material

This repository and its Pages site are **public**. Material from partner documents that
are not published (FAO's draft Mt Elgon AAP; the CRS/Caritas Tororo protocol, DRC Karamoja
AAP and WFP southwest plan shared through the country team) must not appear in committed
source or on public pages.

- Their parameters live in `config/private_frameworks.local.json` and
  `config/partner_triggers.local.json` — **gitignored**. The source documents are on the dev
  blob under `raw/external_frameworks/` and `raw/country_team/`.
- Restricted pages are built in plaintext into the gitignored `site_private/`, then encrypted
  by `pipeline/encrypt.py` (staticrypt, needs `npx`), which refuses to write if plaintext
  survives. Only the encrypted `index.html` is committed.
- To pick this up on a new machine, copy the two config files from the dev blob:

```bash
uv run python -c "
import ocha_stratus as s, pathlib
c = s.get_container_client(stage='dev')
for n in ('private_frameworks.local.json', 'partner_triggers.local.json'):
    pathlib.Path('config', n).write_bytes(c.download_blob(f'ds-aa-uga-flooding/private/config/{n}').readall())
"
```

## The zones

Four zones, three with a second tier (same driver, different flood regime, different
indicator). District lists and the rationale for each tier are on `/coverage/`.

| zone | regime | draft indicator |
|---|---|---|
| **Teso / Lake Kyoga** — Akokoro river | riverine; tier 2 wetlands lag 3–4 weeks | GloFAS G5196 |
| **Mount Elgon** | flash floods and landslides on the slopes; tier 2 lowland riverine | rainfall forecast |
| **Karamoja** | flash floods | rainfall forecast, per district |
| **Adjumani / Albert Nile** | Nile high stand (lake backwater) and tributary flash floods | Lake Kyoga rise, or rainfall forecast |

## Layout

- `src/constants.py` — blob prefix, zones and tiers, GloFAS point
- `src/zones.py` — CODAB resolution of zones; `src/zonal.py` — windowed COG reads + exactextract
- `src/frameworks.py` — other organisations' flood AA (public registry) and `load_private()`
- `src/datasources/` — `glofas.py` (EWDS reanalysis/reforecast), `chirps_gefs.py` (CHC rainfall
  forecasts), `impact.py` (EM-DAT + curated events → districts), `desinventar.py`, `dtm.py`,
  `lake_levels.py`, `era5_land.py`
- `src/data/events_curated.csv` — hand-curated impact events (press, DTM, OPM, URCS) with sources
- `docs/research-notes.md` — sourced notes on other frameworks, GloFAS points, Adjumani
  hydrology, event history, and the corrections made along the way
- `pipeline/` — data builders (write to the dev blob under `ds-aa-uga-flooding/`) and page builders:
  - `build_daily_adm2.py {floodscan|imerg}` — daily per-district mean/max, 1998–present
  - `build_exposure_weights.py` + `build_floodscan_exposure.py` — daily flood-exposed population per
    district (WorldPop 2020 × SFED); Uganda is not in the team's flood-exposure pipeline
  - `build_chirps_gefs_adm2.py` — daily-issued 5-day rainfall forecast per district, 2000–2026
  - `download_glofas.py` — GloFAS v4 reanalysis (Uganda box) and per-point reforecast
  - `zones_map.py`, `build_pages.py`, `build_trigger_page.py`, `build_private_page.py`, `encrypt.py`
- `analysis/`
  - triggers: `trigger_draft.py` (our drafts, calibration, budget allocation),
    `existing_triggers.py` (other organisations' triggers reproduced), `fao_elgon_triggers.py`
  - zones and indicators: `teso_glofas_coverage.py`, `adjumani_lake_levels.py`,
    `flash_flood_rain_vs_events.py`, `flash_flood_antecedent.py`
  - observation: `floodscan_vs_impact.py`, `exposure_vs_impact.py`, `backstop_options.py`, `cems_pass.py`
  - impact: `impact_maps.py`, `impact_coverage.py`
- `data/` — local caches (gitignored); `outputs/` — figures (tracked) and tables (gitignored);
  `config/*.local.json`, `site_private/` — private, gitignored

## Data (dev blob, container `projects`)

```
ds-aa-uga-flooding/processed/floodscan/floodscan_adm2_daily.parquet     date, pcode, mean, max (SFED)
ds-aa-uga-flooding/processed/exposure/floodscan_exposure_adm2_daily.parquet  date, pcode, exposure, exposure_floor (people)
ds-aa-uga-flooding/processed/exposure/pop_weights.npz                   population per district × FloodScan cell
ds-aa-uga-flooding/processed/imerg/imerg_adm2_daily.parquet             date, pcode, mean, max (mm/day)
ds-aa-uga-flooding/processed/chirps_gefs/chirps_gefs_5day_adm2.parquet  issue_date, valid_end, pcode, mean, max (mm/5 days)
ds-aa-uga-flooding/processed/desinventar/datacards.parquet             DesInventar datacards, district-matched
ds-aa-uga-flooding/processed/gwm/lake_levels.parquet                    Victoria/Kyoga/Albert altimetry
ds-aa-uga-flooding/raw/glofas/                                          mirror of data/glofas/raw (reanalysis box, point reforecasts)
ds-aa-uga-flooding/raw/country_team/, raw/external_frameworks/          documents shared by the country team (internal)
ds-aa-uga-flooding/private/config/                                      the gitignored config/*.local.json files
```

Uganda is capped at ADM1 in the team rasterstats DB, so district series are computed here
from the processed COGs on the prod raster blob. Blob access via `ocha-stratus` (env vars per
its README). GloFAS needs an EWDS key (`~/.cdsapirc` or `CDSAPI_KEY`).
