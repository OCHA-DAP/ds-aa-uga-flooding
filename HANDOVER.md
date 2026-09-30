# Handover — Uganda flood AA triggers

**From Tristan to Pauline (@PaulineNimo), 30 September 2026.** Start here, then read
`CLAUDE.md` (working notes and conventions, written for Claude as much as for people), then the
restricted `/triggers/` page, which carries every backtest table. Anything that comes from an
unpublished partner document is **not** in this file or anywhere else in the repo — it is in the
gitignored `config/*.local.json` and on the restricted pages (see *Private material*).

The funding window is **1 October to 31 December 2026**, which opens now, and **nothing is
monitored yet** (step 4).

## 1. Where it stands

Four zones, each an independent all-in trigger (`src/constants.py`; rationale on `/coverage/`).
Backtested on the October–December windows of 2000–2024 against a dated impact record: an
activation "catches" a major flood (5+ deaths or 5,000+ affected in one event) if the flood
starts within the trigger's lead window after it, or is already under way.

| zone | trigger | status | backtest, Oct–Dec 2000–2024 |
|---|---|---|---|
| **Teso / Lake Kyoga** | the IFRC/URCS EAP trigger (EAP2021UG01), as the IBF portal computes it | **adopted** after the country-team call (29 Sep); to confirm — step 1 | stand-in: 1-in-4.3; 6 activations, catches Oct 2007 (under way, sub-county level only); misses 2010, 2014, 2021 |
| **Mount Elgon** | draft: CHIRPS-GEFS 5-day forecast, mean of 15 districts, 1-in-5.4 | **likely replaced by a partner's trigger** once the partner confirms how it processes it — step 2 | draft: 5 activations, catches Nov 2024 (Bulambuli landslides, 5 days ahead) |
| **Karamoja** | CHIRPS-GEFS 5-day forecast, any of 9 districts at a common rarity, 1-in-5.2 (frequency-matched) | **draft, to finalise** — step 3 | 5 activations, catches Dec 2006; misses 2007, 2008, 2010, 2012 (at 1-in-4 it also catches Nov 2008) |
| **Adjumani / Albert Nile** | Lake Kyoga 180-day rise OR any district's 5-day rain forecast, 1-in-20 | **draft, to finalise** — step 3; recommended: the lake leg alone at its own frequency, stated as "the Nile is already high" | 2 activations, catches 2020 (lake leg, months into the flood); misses 2004, 2008, 2023 |

Also decided or found this round (details in the sections of `/triggers/`):

- **FloodScan observed-flood fallback** (`analysis/floodscan_fallback.py`): worth adding in
  **Teso only**, where it catches October 2021 for one extra false alarm. In Elgon and Karamoja it
  catches nothing in this window; in Adjumani no district passes the usability check.
- **Karamoja, rain or FloodScan per district**: the rain forecast is the better indicator in 6 of
  the 7 districts with their own record; FloodScan adds nothing in October–December.
- **Independent review (30 Sep)** of the three judgement calls — IFRC reproduction, Adjumani,
  Karamoja — by a separate reasoning model, with its numbers re-checked: section 4. It changed
  three things: the IFRC numbers are labelled a stand-in, the Adjumani compound rule is no longer
  recommended, and a flaw in the threshold-raising rule was fixed (Karamoja back to 1-in-5.2 from
  1-in-10).
- **Maps** of where each trigger is measured: `pipeline/zone_trigger_maps.py` → embedded in
  `/triggers/`.
- **The honest headline**: in an October–December window these triggers catch few major floods.
  October–December holds only 16–29 % of each zone's recorded impact (August is the peak month in
  three zones), and no GloFAS reading has anticipatory skill for Teso in this window — Teso's
  October floods are the tail of a wet August–September. Teso takes the IFRC trigger for alignment
  with URCS, not for skill.

## 2. Next steps

### Step 1 — Confirm the IFRC trigger looks good

What we built: `analysis/ifrc_reproduction.py` rebuilds the trigger from the IBF pipeline's own
code (`rodekruis/IBF-river-flood-pipeline`, Uganda settings), not from the EAP's wording. Every
district, county and sub-county (admin 2/3/4) is judged at its **zonal maximum**: the largest
forecast flow anywhere in the area against the largest value of the official GloFAS v4 5-year
return-level map in the area. It triggers when at least 60 % of the 51 members exceed that level
at a lead of 5 days or less, and a triggered sub-area triggers its district. Consequences:

- It is **not** read at G5196, the Akokoro reporting point we first used. Katakwi, Soroti and
  Ngora are read on the Lake Bisina–Awoja channel (5-year flow ~370–410 m³/s, fed from Mt Elgon);
  Amuria and Kapelebyong on the Akokoro; Serere on Lake Kyoga. The level, probability and lead we
  had were right (our 5-year level at G5196: 59 m³/s; official map: 61).
- Stand-in: the GloFAS **reanalysis** as a perfect forecast, against the official map, on CODAB
  boundaries; an exceedance is dated 5 days early.
- Check against the portal: it notified on 15 Nov 2023 with 16 "potentially exposed" districts;
  the reproduction has 12 of them over the level within that forecast's 8 days and 15 by the end
  of the month (not Namayingo), plus other districts the notification would not list (it lists
  districts with mapped exposure, ranked by it).

To confirm:

1. **Ask URCS / 510 for the portal's own trigger history** (which admin areas triggered, on
   which dates, since 2021) and their boundary file. Compare with
   `outputs/triggers/ifrc_district_days.csv`. This is the one test that settles fidelity.
2. **Ask URCS whether EAP2021UG01 is live for October–December 2026.** The 2023 activation
   document gives the EAP's timeframe as 27 May 2021 – 27 May 2026; IFRC GO shows operation
   MDRUG048 open to 30 Nov 2026. If a renewed EAP changes districts, probability or return period,
   the Teso trigger follows it (edit `analysis/ifrc_reproduction.py` / `trigger_draft.py`).
3. Decide the **districts that count** for us: currently any of the six Teso-zone districts
   (Katakwi, Amuria, Kapelebyong, Soroti, Ngora, Serere); the EAP's own high-risk list has
   Katakwi, Amuria, Ngora (and Kumi, which we place in the Elgon lowlands). Same backtest either way.
4. Read the reproduction as a **stand-in** until step 1.1 is done: it has the portal's
   mechanics, not necessarily its decisions (section 4).

The exact trigger wording (2021 approved, 2023 as activated) is quoted on `/triggers/`.

### Step 2 — Put in the partner's processing for Elgon once they reply

The Elgon trigger is expected to become a partner's trigger. The plan is unpublished, so its
name, thresholds and the questions put to the partner are in the **private handover notes**
(`config/private_frameworks.local.json`, key `handover_notes`, also rendered on `/partner/`).

How to put it in:

1. Edit its entry in `trigger_specs` in `config/private_frameworks.local.json`. Supported types
   (`analysis/existing_triggers.py`, `activation_days`): `rain_forecast` (CHIRPS-GEFS 5-day,
   `stat` = `mean` for the district mean or `max` for the wettest pixel, `mm`) and `rain_observed`
   (IMERG `window`-day sum, `stat`, `mm`, optional `antecedent_pctl` using the IMERG antecedent
   precipitation index as a soil-moisture proxy). If the partner uses a product we do not have
   (a station network, a soil-moisture product), add a type there.
2. `uv run python analysis/existing_triggers.py` — the backtest appears beside our draft on
   `/triggers/`.
3. To make it **the** Elgon trigger, follow the Teso pattern in `analysis/trigger_draft.py`:
   a series whose value is a margin over the partner's rule (≥ 1 = met) and a fixed threshold in
   `FIXED_THRESHOLDS`, so it is backtested but not recalibrated. Keep the partner's numbers in the
   config, never in code or labels (see *Rules*).
4. Push the updated config to the blob mirror (command under *Private material*).

### Step 3 — Finalise Karamoja and Adjumani

Both are working drafts under the zone rule: return period = how often the zone has a major
season (never more often than 1-in-3), then raised while every big catch survives.

- **Karamoja** (`outputs/triggers/karamoja*.csv`, `rp_sensitivity.csv`). Now at the
  frequency-matched 1-in-5.2 (per-district bar 1-in-12.4): 5 activations, catches December 2006.
  Decisions: (a) 1-in-5.2 by rule, or 1-in-4 by a stated preference for catching November 2008
  (Kaabong 1-in-11.7, one rank short; the zone's largest October–December flood, 25,000 affected)
  — the record cannot tell them apart; (b) district mean or wettest pixel: one run, since
  `processed/chirps_gefs/chirps_gefs_5day_adm2.parquet` already has a `max` column (swap
  `values="mean"` for `"max"` in `chirps_gefs_wide`, keep a common rarity — never tune per
  district); a partner's wettest-pixel trigger catches November 2008 (private notes); (c) all-in
  for the zone or per district — a funding question for the country team. Be honest that the
  zone has one or two catchable October–December seasons in 25: 2007, 2010 and 2012 peaked at
  1-in-1 to 1-in-3.
- **Adjumani** (`analysis/adjumani_options.py`, `outputs/triggers/adjumani_options.csv`).
  **Recommended: the lake leg alone at 1-in-5 to 1-in-6.5**, said plainly as "activate when the
  Nile is already high" — no anticipatory lead in this window — with the rain leg at its own
  rarity if wanted. It catches 2020 and 2023 on 1 October (both floods already under way) for
  three to four false alarms. The compound lake-AND-rain rule looked better (4 activations, same
  two catches) but is close to a lake gate and was chosen after seeing 2023 (section 4). Check the
  September 2023 onset and whether the 2004 and 2008 "major" events are really this zone's.
- Then rerun `analysis/trigger_draft.py` with the chosen design. For Adjumani's lake leg alone,
  drop the rain series from `zone_series()["adjumani"]` and the entry in `LEGS`, or use the
  `FIXED_THRESHOLDS` pattern with the chosen lake level.

### Step 4 — Set up monitoring

Nothing runs operationally yet. What each trigger needs:

| zone | indicator | live source | cadence / latency | gap to close |
|---|---|---|---|---|
| Teso | IFRC portal trigger state | IBF portal (URCS / 510) | daily | access: ask URCS/510 for an account or an API feed; the portal's state *is* the trigger |
| Teso (check) | own reproduction on the forecast | GloFAS v4 forecast, EWDS `cems-glofas-forecast`, 51 members | daily, 00 UTC | adapt `ifrc_reproduction.py` from reanalysis to per-member forecasts |
| Teso | FloodScan fallback | team blob `raster/floodscan/daily/v5/` | daily, ~2 days behind | daily district extraction (`pipeline/build_daily_adm2.py floodscan` logic) |
| Elgon, Karamoja, Adjumani rain | CHIRPS-GEFS 5-day forecast | **CHIRPS3-GEFS** `https://data.chc.ucsb.edu/products/CHIRPS-GEFS/v3/05_day/africa/data/YYYY/c3g_YYYY.MM.DD.tif` | daily, same day | **v2 (what every rain threshold was calibrated on) was discontinued 1 Jul 2026.** Recalibrate on the v3 hindcast (2001–2019, 2021–) or at least compare v2 and v3 district distributions before monitoring |
| Elgon (partner trigger) | per the partner's processing | IMERG late (team blob `raster/imerg/daily/late/v7/`) if observed rain | daily, ~1 day behind | depends on step 2 |
| Adjumani lake leg | Lake Kyoga 180-day rise | NASA Global Water Monitor text files (`src/datasources/lake_levels.py`) | 10-day passes, weeks of publication lag (our table ends 25 Aug) | scheduled refresh; keep the 3-pass median filter |

How: the team's other flood monitors are the templates — Databricks jobs from a bundle, writing
through `ocha-stratus`, emailing through Listmonk (see `ds-aa-nga-flooding` and
`pa-aa-tcd-flooding`, both moved from GitHub Actions to Databricks in Sep 2026, and the KB's email-testing notes: `TEST_EMAIL`,
`SIMULATE_TRIGGER`, `DRY_RUN`). Until that runs, a manual weekly check through October — the IBF
portal for Teso, the CHIRPS3-GEFS 5-day district values against the thresholds in
`outputs/triggers/thresholds.csv` (after the v3 check) — is better than nothing.

## 3. Outstanding points

| point | owner / who to ask |
|---|---|
| Is EAP2021UG01 live for Oct–Dec 2026? Portal trigger history and boundaries | URCS / 510 |
| How the Elgon partner processes its trigger | the partner (private notes) |
| Adjumani compound rule: adopt or not | Pauline + Tristan |
| Karamoja: return period; district mean vs wettest pixel; all-in vs per district | Pauline; funding question for the country team |
| Recalibrate rain thresholds on CHIRPS3-GEFS | Pauline (before monitoring) |
| Severity 3+ scope in Teso | country team / working group |
| Whether the CRS, DRC and WFP thresholds should stay on the public `/coverage/` page or move behind the password | Tristan |
| Feedback on the UHF-funded joint South-West plan (outside our zones; questions in private notes) | Tristan / country team |
| Third opinion on GloFAS drift after 2013 (DWRM gauge); Google Flood Hub has no Uganda gauges | low priority now Teso follows IFRC |
| IOM DTM workbooks on HDX have day-precision events — wiring them in would upgrade 2022+ dates | Pauline, optional |
| Older results-page analyses (`exposure_vs_impact`, `backstop_options`, `flash_flood_*`) predate the DesInventar date fix — rerun | Pauline, optional |
| Longer rainfall windows (2007 was a long wet season); readiness/action staging | later design round |
| ERA5-Land soil moisture download stalled on CDS timeouts; IMERG antecedent index is the proxy | optional |
| KB PR #624 (methods: choosing the area a threshold is calibrated on) awaits review | team |

## 4. Review notes (second opinion)

An independent review (a separate reasoning model, 30 Sep 2026) of the three judgement calls,
with the key numbers re-checked against the data before they went in here.

**IFRC reproduction — adopt, with a caveat.** The mechanics match the IBF code (zonal max,
`all_touched`, `nodata=0`, child-to-parent propagation). But:

- The reanalysis stand-in **over-triggers at marginal exceedances**. At G5196, when the
  reanalysis is 0–2 % over the 5-year level, 60 % of reforecast members agree only about a third
  of the time; at 2 % or more, 77–100 % of the time. Katakwi's whole November 2023 exceedance is
  1.02–1.03×; the Teso 2023 activation rests on it (and on Serere, 1.23×, which reads Lake Kyoga).
- November 2023: 15 of the portal's 16 districts match, but the reproduction also has about 23
  districts the portal did not list. Whether the notification lists every triggered area or only
  those with mapped exposure decides whether that is over-triggering. Ask 510.
- The 2007 "catch" exists only through one Katakwi sub-county at 1.045×; at district level Teso
  stays below the level that season, and the flood had been under way for five weeks.
- The reanalysis ≈ forecast finding rests on G5196 alone (17 exceedance days, all in 2020); it
  need not hold on the Bisina or Kyoga cells.
- Because a district takes the largest of many areas, some Teso district passes the "5-year"
  level in about 15 of 26 years. Fine as mechanics; do not describe the trigger as 1-in-5.
- First checks: the portal's trigger log 2021–25, its boundary file and its per-area threshold
  table (the single question "did Katakwi or Serere trigger in November 2023?" settles most of it);
  whether notifications list all triggered areas.

**Adjumani compound rule — do not adopt as calibrated.** Both catches are floods already under
way (2020 since mid-year; 2023 from 20 Sep, before the window). The rain condition does little
work: some district reaches 1-in-3 in 17 of 25 seasons. The lake leg alone at 1-in-5 catches the
same two seasons, on 1 October. With four major seasons, a random four-activation rule catches at
least two of them about one time in ten, and the grid of nearby settings is not independent
evidence. The physics is half-supported (the OND 2019 rise preceded the 2020 flood; the 2011 rise
had no flood). 2004 and 2008 look like national EM-DAT totals apportioned to districts.

**Karamoja — do not keep 1-in-10 (fixed).** The raise had protected no big catch: with none, the
rule raised until the last small catch would be lost, parking the Kotido bar 0.03 mm under a
140-affected, month-precision December 2006 card. `raise_threshold` now stays at the
frequency-matched level when there is no catch of 5,000+ affected (Elgon and Adjumani, which do
protect big catches, are unchanged). Note the same construction gives thin margins where the
raise is legitimate: Adjumani's lake bar sits at 1.548 m against 2020's 1.614 m rise, Elgon's
just under November 2024. That is the known cost of "raise until you would lose it" on 25
seasons.

## 5. Where everything is

- **Pages**: https://ocha-dap.github.io/ds-aa-uga-flooding/ — `/coverage/` and `/results/`
  public; `/triggers/` and `/partner/` restricted (team review password: ask Tristan).
- **Knowledge base**: `frameworks/uga-flooding/development.md` in `ds-knowledge-base`.
- **Private material** (gitignored, never commit): `config/private_frameworks.local.json` (partner
  frameworks, partner trigger specs, restricted page text, handover notes) and
  `config/partner_triggers.local.json`. Mirrored on the dev blob; to pull:

  ```bash
  uv run python -c "import ocha_stratus as s; cc = s.get_container_client(stage='dev'); \
  [open(f'config/{f}', 'wb').write(cc.download_blob(f'ds-aa-uga-flooding/private/config/{f}').readall()) \
   for f in ('private_frameworks.local.json', 'partner_triggers.local.json')]"
  ```

  After editing, push back with `get_container_client(stage='dev', write=True)` and
  `upload_blob(..., overwrite=True)`. Country-team and partner documents are on the dev blob under
  `ds-aa-uga-flooding/raw/external_frameworks/` — reference them, never commit them.
- **Local data**: GloFAS reanalysis, reforecast and the official return-level map live in
  `data/glofas/` (gitignored); mirrors on the dev blob under `ds-aa-uga-flooding/raw/glofas/`.
  Everything processed is on the dev blob under `ds-aa-uga-flooding/processed/`.
- **Code**: `analysis/trigger_draft.py` (the zone triggers), `analysis/existing_triggers.py`
  (IFRC and partner triggers beside ours), `analysis/ifrc_reproduction.py`,
  `analysis/floodscan_fallback.py`, `analysis/adjumani_options.py`,
  `pipeline/build_trigger_page.py` (the restricted page), `pipeline/encrypt.py` (the only way to
  write a restricted page). Rebuild order is in `README.md`.

## 6. Rules that bit us

- **Unpublished partner material never goes in committed source, labels, figures or public pages.**
  Numbers come from the config at run time; figures made from them go to `site_private/`
  (gitignored) — `outputs/*.png` is committed. A figure with a partner threshold sat on the public
  site for three weeks because a title string hard-coded it (fixed 30 Sep).
- **Reproduce a partner's trigger from its code, not its prose** (the IFRC lesson).
- **Judge FloodScan per district on rank-based evidence**, never on absolute extent; measure the
  chance rate of a window maximum, it is not 20 %.
- **Match activations to dated floods**, never score by calendar year; DesInventar's unknown day
  is month precision, not the 1st.
- **Percentile thresholds on monthly or daily values are not rare seasons**: a monthly 1-in-3
  level checked over four months and four districts is met almost every season.
- Lake altimetry has single-pass outliers (~0.5 m): median-filter before differencing.
