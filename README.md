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

**Where it stands.** Zones are settled (`src/constants.py`, rationale on `/coverage/`). Second
draft of the four triggers, backtested on Oct–Dec 2000–2024 (`/triggers/`), revised after the
country-team call of 29 Sep 2026:

| zone | trigger | return period | activations / caught / missed |
|---|---|---|---|
| Teso / Lake Kyoga | **the IFRC/URCS EAP trigger as the IBF portal runs it** (reproduced, below) | 1-in-4.3 (the protocol's own) | 6 / 1 / 3 of 4 — catches Oct 2007 |
| Mount Elgon | CHIRPS-GEFS 5-day forecast, zone mean of 15 districts | 1-in-5.4 | 5 / 1 / 4 of 5 — catches Nov 2024, five days ahead |
| Karamoja | CHIRPS-GEFS 5-day forecast, any district at a common rarity | 1-in-10 (from 1-in-5.2) | 3 / 1 / 4 of 5 |
| Adjumani / Albert Nile | Lake Kyoga 180-day rise OR per-district rain forecast | 1-in-20 (from 1-in-6.5) | 2 / 1 / 3 of 4 — lake leg catches 2020 |

- **Teso = IFRC.** The portal (rodekruis/IBF-river-flood-pipeline, UGA config) judges each
  district, county and sub-county at its largest river cell — zonal max of each member's flow
  against the zonal max of the official GloFAS v4 5-year map, >= 60 % of 51 members, lead <= 5 d,
  and a triggered sub-area triggers its district. It is **not** read at G5196: Katakwi, Soroti
  and Ngora are read on the Lake Bisina–Awoja channel (fed from Elgon). `analysis/ifrc_reproduction.py`
  rebuilds it on the reanalysis and reproduces 15 of the 16 districts the portal listed on
  15 Nov 2023. No GloFAS reading has anticipatory skill for Teso in Oct–Dec; the choice is for
  alignment with URCS. Check with URCS that the EAP is live for Oct–Dec 2026 (its stated
  timeframe ended 27 May 2026; the GO operation runs to 30 Nov 2026).
- **Elgon**: the final choice waits on a partner's confirmation of how its trigger is processed
  (restricted page).
- **Karamoja**: district-by-district, the rain forecast beats FloodScan in 6 of the 7 districts
  with their own record (`analysis/floodscan_fallback.py`); swapping or adding FloodScan catches
  nothing more in Oct–Dec. Thresholds deliberately not tuned per district (1–3 events each).
- **Adjumani**: a compound option — Kyoga rise >= 1-in-5 AND any district rain >= 1-in-3, same
  day — activates at 1-in-6.5 and catches 2020 and 2023 (the current draft misses 2023) for two
  false alarms (`analysis/adjumani_options.py`). Found after looking at 2023: decision pending.
- **FloodScan fallback** (`analysis/floodscan_fallback.py`): worth adding in Teso only (catches
  Oct 2021); catches nothing in Elgon or Karamoja in this window; no usable district in Adjumani.
- Maps of where each trigger is measured: `pipeline/zone_trigger_maps.py` (the Elgon map names
  partner triggers from the gitignored config; it only goes into the encrypted page).

Zones trigger **independently**. Triggers may activate only in **October, November and
December** (planning runs into September; the funding does not run past March). Each zone's
return period starts from how often it has a major-impact window (one event with 5+ deaths or
5,000+ affected), floored at 1-in-3, and is then **raised as far as it can go without losing a
big flood it already catches** (`raise_threshold`, `BIG_AFFECTED`); Teso takes the IFRC
protocol's own rate. Every activation is **matched to a dated flood** (30 days for rain
forecasts, 45 for GloFAS, 150 for the lake leg, during or up to 10 days after for FloodScan).

**The window is the binding constraint**: Oct–Dec holds only 16–29 % of each zone's recorded
people affected, and the peak impact month is August in three of the four zones. The
indicators peak earlier still (April for the rain forecasts in Karamoja and Adjumani, August
for Teso's GloFAS). `outputs/triggers/monthly_profile.csv` and the page's month table show it.

**Open questions** (also at the foot of `/triggers/`): URCS on the EAP's status for 2026; the
Elgon partner's processing; Adjumani compound rule yes/no; test longer rainfall windows (2007
was a long wet season); Karamoja funding; agree spatial scale and rainfall product with partners
for their rain triggers; the country team's call on the Severity 3+ scope in Teso.

**In flight.**
- ERA5-Land soil moisture download stalled on CDS timeouts; the antecedent precipitation index
  (IMERG) is the proxy meanwhile.

**Things learned the hard way** (details in `CLAUDE.md` and `docs/research-notes.md`):
- Judge an indicator in an area on evidence relative to *that area's own record* (percentiles,
  AUC), not absolute magnitude; judge GloFAS points on correlation and skill, not KGE.
- When scoring events on the maximum of a window, measure the chance rate — it is not 20 %.
- CHIRPS-GEFS: the builder retries (transient errors once silently dropped Mar–Dec 2013);
  Jan–Sep 2020 is a genuine gap in the product.
- Unpublished partner material never goes in committed source or public pages.
- Reproduce a partner's trigger from its code, not its prose: the IFRC wording says "5-year
  flood in flood-prone districts"; the portal reads each area at its largest river cell.
- Lake altimetry has single-pass outliers (~0.5 m); a running median over three passes before
  differencing, or a 180-day "rise" appears half a year later.

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
# triggers (ifrc_reproduction needs the official GloFAS v4 RL5 map in data/glofas/thresholds/)
uv run python analysis/ifrc_reproduction.py
uv run python analysis/trigger_draft.py
uv run python analysis/existing_triggers.py
uv run python analysis/floodscan_vs_impact.py
uv run python analysis/floodscan_fallback.py
uv run python analysis/adjumani_options.py
uv run python pipeline/zone_trigger_maps.py
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
