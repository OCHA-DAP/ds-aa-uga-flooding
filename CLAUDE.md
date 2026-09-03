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
- Severity 3+ scope decision on Teso/Kyoga districts is the working group's, not ours.
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
- `analysis/impact_coverage.py` is the accounting of recorded impact by coverage class
  (zone core / tier 2 / partner-only / uncovered) — rerun it after any zone change.
- Blob paths use `PROJECT_PREFIX`; everything derived goes to `processed/<source>/`.
- Pipelines checkpoint per year in `pipeline/.checkpoint_*` (gitignored) and are re-runnable.
- CHIRPS-GEFS v12 archive on CHC stops 2026-07-04 — fine for hindcast skill, not for live
  monitoring; the operational feed has to be re-sourced before go-live.
- GloFAS: EWDS (not CDS) host; v4 reanalysis pinned to match the v4 reforecast archive.
