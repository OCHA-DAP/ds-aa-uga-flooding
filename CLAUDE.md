# ds-aa-uga-flooding — working notes for Claude

Read `README.md` first. Team discipline for this work: the `aa-methods` plugin
(`trigger-design`, `return-periods`) — say "activated" not "fired", validate every
specific trigger against BOTH an impact record and an observed-hazard record, always
report per-trigger and combined return periods.

## Context that is not in the code

- The country team's request (2 Sep 2026): a trigger system split by zone — Teso/Kyoga
  riverine on GloFAS G5196; Mt Elgon and Karamoja flash-flood triggers from rainfall
  forecasts; Adjumani/Albert Nile with an indicator still to be found; an observed-flood
  backstop everywhere; and a coverage map showing our zones next to WFP's and IFRC's.
- Prior work lives in `ds-seas5-skill` (`pages/uganda-flood-trigger/`, `pages/uganda/`,
  `processed/uga/` on the dev blob): GloFAS skill-layer check (only the Akokoro point
  passes both CRPSS lead and hydrology; wet bias 1.7×, so thresholds go in model space),
  FloodScan OND recurrence, EM-DAT event modality split, IOM DTM district counts.
- Country documents shared Aug 2026 (UHF severity note, DTM xlsx, URCS/FAO hotspot maps,
  OPM El Niño retrospective) are internal — reference them, never commit them.
- Unpublished partner material (currently FAO's draft Mt Elgon flood AAP, Sep 2026) never
  goes in committed source or the public pages — this repo and its Pages site are public. It
  lives in gitignored `config/*.local.json`; `pipeline/build_private_page.py` renders it into
  gitignored `site_private/` with images as data URIs, then staticrypt-encrypts it into
  `pages/partner/index.html`, the only committed form. The public pages may say a draft exists
  and link to `/partner/`, nothing more. The script refuses to write if plaintext survives.
- Draft triggers (Sep 2026): `analysis/trigger_draft.py` -> `/triggers/` (restricted, since it
  carries partner triggers). Zones trigger independently: each zone's RP = frequency of its
  own major-impact years, floored at 1-in-3 (the user's call, 22 Sep 2026; a shared overall
  1-in-3 budget was the earlier design and was dropped). Do not pick RPs by maximising backtest
  skill — 25 seasons is noise. Season window is 1 Oct to 31 Dec (user 23 Sep 2026: planning runs into Sep, funding not past
  March). NB Oct-Dec holds only 16-29% of each zone's recorded impact — peak is August in three
  zones — and the indicators peak earlier still (Apr rain, Aug GloFAS); see monthly_profile.csv, and every activation is matched to a DATED event within a lead
  window (30 d rain / 45 d GloFAS / 150 d lake) — never score by calendar year. Zones with legs (Adjumani: lake / rain) split their share equally
  between legs. Existing triggers are reproduced in `analysis/existing_triggers.py` — published
  ones in `PUBLIC_SPECS`, unpublished ones in the gitignored config. `pipeline/encrypt.py` is the
  only path to a restricted page.
- Teso on the GloFAS reforecast (29 Sep 2026): at G5196 the reforecast matches the reanalysis
  within 1 % at leads 1-15 in OND (slow catchment: the forecast mostly persists the current
  state), so reanalysis-fitted thresholds are valid in model space. But in the Oct-Dec window
  every activation is on 1 Oct with the river already high from Aug-Sep: zero lead gained over
  the reanalysis. Rise-through variant: <=1 catch vs 4-5 false alarms. Treat Teso OND as having
  no GloFAS anticipatory skill unless the window changes. GloFAS/IFRC return periods are on
  ANNUAL maxima — the IFRC stand-ins use those.
- Teso = the IFRC/URCS trigger (user decision after the country-team call, 29 Sep 2026;
  `TESO_SOURCE = "ifrc"`, `FIXED_THRESHOLDS` — not calibrated, not raised). The IBF portal
  (rodekruis/IBF-river-flood-pipeline, UGA config: admin levels 2-4, lead <= 5, RP 5, p >= 0.6,
  51 members) judges each area at its ZONAL MAX: max forecast flow over the area (all_touched) vs
  max of the official GloFAS v4 RL5 map over the area; a triggered sub-county triggers its
  district. So Katakwi/Soroti/Ngora read the Lake Bisina-Awoja channel (RL5 ~370-410 m3/s, fed
  from Elgon), Amuria/Kapelebyong the Akokoro, Serere Lake Kyoga — NOT G5196 alone (our first
  stand-in, 1 act in 20). `analysis/ifrc_reproduction.py` (reanalysis as perfect forecast, dated
  5 d early) reproduces 15/16 districts of the portal's 15 Nov 2023 notification. Own Gumbel
  annual-max RL5 at G5196 59.2 vs official 60.9. The 2021 wording (70 %, 10-yr in low-priority
  districts) is not what runs; the 2023 wording is.
- Post-call analyses (29 Sep 2026): FloodScan fallback helps Teso only (Oct 2021); Karamoja rain
  forecast beats FloodScan per district (keep rain; indicator chosen per district, rarity common —
  never tune thresholds per district on 1-3 events); Adjumani compound (Kyoga rise >= 1-in-5 AND
  rain >= 1-in-3 same day) catches 2020+2023 at 1-in-6.5 — found after looking at 2023, pending
  the user's decision. Elgon: the choice waits on a partner confirming its processing (the
  specifics live only in the private config text). Kyoga altimetry is median-filtered (3 passes) before the 180-d rise.
- Google Flood Hub has NO gauges in Uganda (API: regionCode UG and a box around the country
  both return 0; KE 3, SO 7, SS 4 — checked 29 Sep 2026). No third opinion from Google.
- Teso Oct-Dec floods (analysis/teso_ond_drivers.py): rain (forecast, observed, antecedent) has
  no skill (AUC ~0.5); the landscape state on 1 Oct does (FloodScan extent 0.70/0.76, GloFAS
  level 0.66/0.80). October floods are the tail of a wet Aug-Sep, not a separate pluvial
  mechanism despite being typed RAINS. A decide-on-1-October trigger at ~1-in-3.7 catches 2 of
  the 3 major windows (2007, 2021) but with 0-1 days of lead; 2014 is caught by nothing.
- Severity 3+ scope decision on Teso/Kyoga districts is the working group's, not ours.
- GloFAS G5196 vs FloodScan in Teso is NOT stationary (found 4 Sep 2026 once the reanalysis
  reached 2024): Katakwi anomaly corr by era 0.25 / 0.83 / 0.57 / 0.15 / 0.06 for 1999-2005,
  2006-11, 2012-13, 2014-19, 2020-24; same swing in every zone district. 2020 is the model's
  record year with an ordinary satellite season; modelled daily variance rises 5.2 -> 17.3
  m3/s with no satellite counterpart. Get a third opinion (DWRM gauge, Google Flood Hub)
  and report any backtest era by era. `era_split()` in src/glofas_coverage.py.
- Design notes from the user (3 Sep 2026), for when trigger design starts: (1) the Teso
  GloFAS trigger should align as far as possible with the IFRC/URCS EAP formulation
  (ensemble probability of exceeding a return-period flow at a reporting point, 5-day lead),
  calibrated on our own G5196 reforecast; (2) for Elgon, still test GloFAS points (Manafwa
  at Butaleja and any upstream cells) against the impact record even though the skill
  layers look bad — cheap to check, settles it.

## Conventions

- Zones are district-name lists in `src/constants.py`; resolve to geometry via
  `src/zones.py`. Core = what the zone is for; tier 2 = same driver, different flood regime
  and therefore a different indicator (Elgon lowlands, Teso downstream wetlands, Lake Albert
  shore); candidate = to be ruled in/out by analysis. Teso was settled by
  `analysis/teso_glofas_coverage.py` (3 core + 3 tier 2, 13 ruled out in `TESO_EXCLUDED`).
- FloodScan usability is judged on RANK-BASED evidence only (share of events reaching the
  district's own 80th percentile; AUC; a flat-series check). Never gate on absolute extent:
  thresholds are percentiles of each district's own record, so a tiny-but-informative series
  is fine. An earlier absolute gate ("2-yr extent < 1 % = blind") wrongly wrote off Kapchorwa,
  Manafwa, Mbale and most of Karamoja — see docs/research-notes.md section 6.
- DesInventar encodes an unknown day as 0; the loader used to date those to the 1st and call
  them day-precise (a quarter of cards, most of the deaths). Fixed 22 Sep 2026 — they are now
  month-precision. Analyses that use dated events (floodscan_vs_impact, exposure_vs_impact,
  backstop_options, flash_flood_*) predate the fix and should be rerun.
- Event percentiles use midrank; with many tied zeros, "share strictly below" understates.
- `analysis/impact_coverage.py` is the accounting of recorded impact by coverage class
  (zone core / tier 2 / partner-only / uncovered) — rerun it after any zone change.
- Blob paths use `PROJECT_PREFIX`; everything derived goes to `processed/<source>/`.
- Pipelines checkpoint per year in `pipeline/.checkpoint_*` (gitignored) and are re-runnable.
- CHIRPS-GEFS v12 archive on CHC stops 2026-07-04 — fine for hindcast skill, not for live
  monitoring; the operational feed has to be re-sourced before go-live.
- GloFAS: EWDS (not CDS) host; v4 reanalysis pinned to match the v4 reforecast archive.
