"""Assemble the GitHub Pages product pages from the repo's own outputs.

The landing page (pages/index.html) is hand-edited. This script (re)generates:

  pages/coverage/index.html  — the zones + external-coverage map, the zone
                               district lists and the other organisations' frameworks
                               (from src/constants.py and src/frameworks.py)
  pages/results/index.html   — results so far: G5196 coverage table + figure,
                               Adjumani lake-level figure + percentile table, data inventory

and copies the figures from outputs/ into the page directories. Every figure or
table shown is produced by a script in analysis/ or pipeline/; this file only
lays them out. Run after re-running any analysis:

  uv run python pipeline/build_pages.py
"""

import html
import shutil
import sys
from datetime import date
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.constants import GLOFAS_PIXEL_LONLAT, ZONES
from src.frameworks import EXTERNAL

ROOT = Path(__file__).resolve().parent.parent
PAGES, OUT = ROOT / "pages", ROOT / "outputs"
TODAY = date.today().isoformat()

ASSET_VERSION = "3"  # bump when assets/*.css change so browsers refetch

HEAD = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} — Uganda flood AA</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Merriweather:wght@700&family=Roboto:wght@400;500;700&display=swap" rel="stylesheet">
<link rel="stylesheet" href="../assets/site.css?v={v}"><link rel="stylesheet" href="../assets/page.css?v={v}">
</head><body><div class="wrap page">
<a class="home" href="../">&larr; Uganda flood anticipatory action</a>
<h1>{title}</h1><p class="sub">{sub}</p>
"""
FOOT = """<div class="note"><p>Generated {today} by <code>pipeline/build_pages.py</code> in
<a href="https://github.com/OCHA-DAP/ds-aa-uga-flooding">OCHA-DAP/ds-aa-uga-flooding</a>. Work in progress — not a trigger.</p></div>
</div></body></html>"""


def e(x) -> str:
    return html.escape(str(x))


def table(df: pd.DataFrame, fmt: dict | None = None) -> str:
    fmt = fmt or {}
    cols = "".join(f"<th>{e(c)}</th>" for c in df.columns)
    rows = []
    for _, r in df.iterrows():
        cells = "".join(f"<td>{e(fmt[c](r[c]) if c in fmt else r[c])}</td>" for c in df.columns)
        rows.append(f"<tr>{cells}</tr>")
    return f'<div class="tw"><table><thead><tr>{cols}</tr></thead><tbody>{"".join(rows)}</tbody></table></div>'


def coverage_page() -> str:
    shutil.copy(OUT / "zones_coverage_map.png", PAGES / "coverage" / "zones_coverage_map.png")
    parts = [
        HEAD.format(
            v=ASSET_VERSION,
            title="Trigger zones and existing coverage",
            sub="The four OCHA/CERF zones under design, the GloFAS point, and where other organisations' flood anticipatory action already operates.",
        ),
        '<figure><img src="zones_coverage_map.png" alt="Map of Uganda with the four trigger zones and other organisations\' flood AA coverage">'
        "<figcaption>Backdrop: share of Oct–Dec seasons 1998–2025 with FloodScan flooding (SFED ≥ 0.05), clipped to Uganda. "
        "Zones: solid = core districts, dashed = second tier (same driver, different flood regime, different indicator). Hatched: other organisations' "
        "flood AA districts. Triangles: GloFAS reporting points (filled = G5196, calibrated).</figcaption></figure>",
        "<h2>The zones</h2>",
    ]
    for z in ZONES.values():
        parts.append(
            f"<h3>{e(z.label)}</h3><p><strong>Regime:</strong> {e(z.regime)}. <strong>Core:</strong> {e(', '.join(z.core))}."
            + (f" <strong>Candidates:</strong> {e(', '.join(z.candidate))}." if z.candidate else "")
            + (f"<br><em>{e(z.note)}</em>" if z.note else "")
            + "</p>"
        )
    parts.append(
        f"<p>GloFAS G5196 (Akokorio at Uganda gauge, river Akokoro) — LISFLOOD v4 pixel {GLOFAS_PIXEL_LONLAT[1]:.3f}°N "
        f"{GLOFAS_PIXEL_LONLAT[0]:.3f}°E, calibrated on a 22-year record. The pixel is the local Akokoro above the Awoja "
        "confluence (mean ~7 m³/s), not the Karamoja-fed main stem. There are no GloFAS points on the Albert Nile.</p>"
    )
    parts.append(
        "<h2>Other organisations' flood anticipatory action</h2>"
        "<p>What each covers and how it triggers, from the source documents named in each row. "
        "Karamoja drought plans (WFP/FAO PRO-ACT) are not flood frameworks and are not drawn.</p>"
    )
    for fw in EXTERNAL.values():
        parts.append(
            f"<h3>{e(fw.org)} — {e(fw.label)}</h3>"
            f"<p><strong>Districts:</strong> {e(', '.join(fw.districts))}<br>"
            f"<strong>Trigger:</strong> {e(fw.trigger)}<br>"
            f"<strong>Status:</strong> {e(fw.status)}<br>"
            f"<strong>Source:</strong> {e(fw.source)}</p>"
            + ("".join(f"<p class='fn'>{e(n)}</p>" for n in fw.notes) if fw.notes else "")
        )
    parts.append(
        "<h2>Coverage against our zones</h2><ul>"
        "<li><strong>Teso / Kyoga:</strong> IFRC EAP (Katakwi, Amuria, Kumi, Ngora), FAO 2023 (Katakwi). No standing riverine trigger on the Akokoro/Awoja system.</li>"
        "<li><strong>Mount Elgon:</strong> IFRC EAP (Butaleja, Sironko, Bududa, Manafwa, Bulambuli); CRS/Caritas protocol at sub-county level in Butaleja and Bududa; FAO 2023. Kapchorwa, Kween, Bukwo, Namisindwa, Mbale have no trigger.</li>"
        "<li><strong>Karamoja:</strong> DRC (Moroto, Napak, Amudat — flash-flood ladder inside a drought/conflict plan); Nabilatuk in the IFRC list. Kaabong, Karenga, Kotido, Abim, Nakapiripirit uncovered.</li>"
        "<li><strong>Adjumani / Albert Nile:</strong> nothing except Moyo in the IFRC list.</li>"
        "<li><strong>Rwenzori (outside our zones):</strong> WFP's four-district plan plus IFRC (Kasese, Ntoroko).</li></ul>"
    )
    parts.append(FOOT.format(today=TODAY))
    return "".join(parts)


def impact_coverage_table() -> str:
    cov = pd.read_csv(OUT / "impact_coverage.csv").rename(columns={"cls": "class"})
    cov = cov[
        [
            "class",
            "districts",
            "affected",
            "pct_affected",
            "deaths",
            "pct_deaths",
            "years",
            "pct_years",
        ]
    ].rename(
        columns={
            "affected": "people affected",
            "pct_affected": "% affected",
            "deaths": "deaths",
            "pct_deaths": "% deaths",
            "years": "district-years with a record",
            "pct_years": "% district-years",
        }
    )
    return table(
        cov,
        {
            "people affected": lambda v: f"{v:,.0f}",
            "deaths": lambda v: f"{v:,.0f}",
            "district-years with a record": lambda v: f"{v:,.0f}",
        },
    )


def floodscan_impact_table() -> str:
    d = pd.read_csv(OUT / "floodscan_vs_impact_district.csv")
    ev = pd.read_csv(OUT / "floodscan_vs_impact_events.csv")
    d["zone"] = d.zone.fillna("outside the zones")
    ev["zone"] = ev.zone.replace({"outside": "outside the zones"})
    ok = d[(d.n_impact_years >= 3) & ~d.blind]
    rows = []
    for z in [*ZONES, "outside the zones"]:
        dz, ez = d[d.zone == z], ev[ev.zone == z]
        rows.append(
            {
                "area": ZONES[z].label.split(" (")[0] if z in ZONES else z,
                "districts": len(dz),
                "FloodScan-blind": int(dz.blind.sum()),
                "median AUC (non-blind, ≥3 impact years)": round(ok[ok.zone == z].auc.median(), 2)
                if (ok.zone == z).any()
                else float("nan"),
                "dated events": len(ez),
                "median FloodScan percentile in the event window": round(ez.sfed_pctl.median())
                if len(ez)
                else float("nan"),
                "share of events with any FloodScan flooding": round(
                    (ez.sfed_max >= 0.01).mean(), 2
                )
                if len(ez)
                else float("nan"),
            }
        )
    return table(pd.DataFrame(rows))


def results_page() -> str:
    for f in (
        "teso_glofas_coverage.png",
        "adjumani_lake_levels.png",
        "flash_rain_vs_events.png",
        "flash_antecedent.png",
        "impact_by_year.png",
        "impact_summary.png",
        "floodscan_vs_impact.png",
    ):
        shutil.copy(OUT / f, PAGES / "results" / f)
    cov = pd.read_csv(OUT / "teso_glofas_coverage.csv")
    cov_show = cov[
        [
            "district",
            "membership",
            "best_lag",
            "best_corr",
            "p_dis_given_sfed",
            "p_sfed_given_dis",
            "covered",
        ]
    ].rename(
        columns={
            "best_lag": "best lag (d)",
            "best_corr": "best corr",
            "p_dis_given_sfed": "P(Q>2yr | extent>2yr)",
            "p_sfed_given_dis": "P(extent>2yr | Q>2yr)",
        }
    )
    parts = [
        HEAD.format(
            v=ASSET_VERSION,
            title="Results so far",
            sub="Interim analysis outputs. Each figure and table is produced by a script in the repo; nothing here is a trigger yet.",
        ),
        "<h2>Teso / Kyoga — what does GloFAS G5196 cover?</h2>",
        f"<p>GloFAS v4 reanalysis discharge at the G5196 pixel against each candidate district's FloodScan flood-extent daily mean, {e(cov.record.iloc[0])}: "
        "best lagged correlation of daily anomalies in the Aug–Dec flood season (the shared seasonal cycle removed), and the conditional probability "
        "that discharge is over its 2-year level when the district's extent (mean, or wettest pixel for small wetlands) is over its own 2-year level. "
        "Covered = anomaly correlation ≥ 0.45 and P ≥ 0.5 (red outline); dashed = the point's own catchment.</p>",
        '<figure><img src="teso_glofas_coverage.png" alt="Two maps of Teso districts coloured by correlation and conditional probability"></figure>',
        table(
            cov_show,
            {
                "best corr": lambda v: f"{v:.2f}",
                "P(Q>2yr | extent>2yr)": lambda v: f"{v:.2f}",
                "P(extent>2yr | Q>2yr)": lambda v: f"{v:.2f}",
            },
        ),
        "<p><strong>Reading, and what it changed:</strong> the point speaks for Amuria and Katakwi at 0–7 days, and for Soroti, Ngora and Serere with a "
        "19–30 day lag as the Awoja–Bisina wetlands fill; Kapelebyong holds the point and its headwaters (too little extent for a correlation, but "
        "its rare floods coincide with high discharge, P 0.73). Nothing further out passes: Kumi, Bukedea, Pallisa, Butaleja and the Mpologoma "
        "districts, and the whole Kyoga north shore (Kaberamaido, Kalaki, Amolatar, Dokolo, Otuke, Alebtong) have correlations below 0.45 and no "
        "threshold agreement. The zone was redrawn accordingly: six core districts, no candidates. Reforecast-based thresholds and the backtest follow "
        "once the EWDS download completes.</p>",
        "<h2>Adjumani / Albert Nile — are the floods lake-level events?</h2>",
        "<p>Monthly altimetry levels of Lakes Victoria, Kyoga and Albert (NASA Global Water Monitor) against every dated flood record we hold for Adjumani, "
        "Moyo, Obongi, Nebbi and Pakwach (DesInventar datacards 1992–2021, EM-DAT, and curated 2019–2024 events).</p>",
        '<figure><img src="adjumani_lake_levels.png" alt="Three lake level time series with flood months marked"></figure>',
        "<p><strong>Reading:</strong> two regimes. The large, well-documented backwater floods (Pakwach and Obongi 2020, 2021, Obongi/Palorinya Oct–Nov 2024) "
        "sit above the 90th percentile of Kyoga and Albert levels, with the Victoria → Kyoga → Albert chain giving months of lead. Most smaller DesInventar "
        "records (Moyo 2008, 2011, 2014; Nebbi 2007–2014) occurred at ordinary lake levels and are local-rain / tributary events. The zone therefore needs "
        "a lake-level leg and a rainfall leg.</p>",
        "<h2>Mount Elgon and Karamoja — how much rain falls before the recorded events?</h2>",
        "<p>Link 2 of the flash-flood chain (observed rain → impact), on IMERG daily rainfall averaged over each zone's core districts, "
        "1998–2026: for every day-dated impact record in the zone (DesInventar datacards, EM-DAT, curated events) the 3-day rainfall in "
        "the three days before the event, as a percentile of all days.</p>",
        '<figure><img src="flash_rain_vs_events.png" alt="Histograms of pre-event rainfall percentile for Elgon and Karamoja"></figure>',
        "<p><strong>Reading:</strong> events do happen on wet days — the median pre-event 3-day rainfall sits at the 86th percentile on Elgon and the "
        "83rd in Karamoja, and the deadly events (≥5 deaths) at the 88th — but almost never on <em>extreme</em> days: only 2 % of events follow "
        "3-day zone-mean rainfall above its 2-year level, and of the 17 zone-wide episodes above that level since 1998 only one coincided with a "
        "recorded event. A zone-mean rainfall return-period threshold of the usual kind would therefore miss nearly everything and mostly "
        "activate on non-events. The trigger needs a lower rainfall bar combined with antecedent wetness (the landslide literature's "
        "'prolonged low-intensity rain'), finer spatial resolution (district or slope-unit rather than zone mean), and an explicit statement "
        "of the false-alarm ratio that comes with it. The forecast leg (CHIRPS-GEFS vs IMERG) follows when its table lands.</p>",
        "<h2>Does antecedent wetness help?</h2>",
        "<p>Soil moisture is the missing variable in the previous result: landslides and flash floods follow moderate rain on saturated "
        "ground. Until the ERA5-Land soil-moisture download lands, an antecedent precipitation index from IMERG stands in for it "
        "(API<sub>t</sub> = 0.9·API<sub>t−1</sub> + P<sub>t</sub>, an e-folding time of about ten days, lagged so it describes the ground "
        "before the 3-day rain window). Grey: all days since 1998; points: event days; circles: events with five or more deaths.</p>",
        '<figure><img src="flash_antecedent.png" alt="Rain percentile vs antecedent index percentile for all days and event days"></figure>',
        "<p><strong>Reading:</strong> events cluster in the wet–wet corner, and the deadly ones more so (median antecedent percentile "
        "78 on Elgon, 89 in Karamoja). A trigger grid over rain and antecedent thresholds (tables <code>outputs/flash_trigger_grid_*.csv</code>, "
        "zone-level and any-district variants) shows what that buys: at a fixed rain threshold, requiring the antecedent index above its "
        "85th percentile roughly doubles the share of activations that have a recorded event within two days (for example on Elgon, "
        "any-district 3-day rain ≥ 95th percentile: 8 % → 14 %), while keeping about half of the deadly events. But no combination gets "
        "precision above about 15 %, and catching most deadly events costs 10–25 activations a year. Two things follow. First, a daily "
        "rainfall trigger at zone scale is a readiness-tier signal at best, not an action trigger; the action decision needs something "
        "sharper — slope-unit susceptibility, a landslide-model layer, community gauges, or the forecast's own probability. Second, the "
        "impact record is incomplete (DesInventar stops in 2021 and misses minor events), so true precision is somewhat higher than "
        "measured — but not by the factor needed. ERA5-Land soil moisture will replace the proxy and be re-tested here.</p>",
        "<h2>Where impact has been recorded</h2>",
        "<p>All four impact sources merged to district-years (EM-DAT, DesInventar to 2021, IOM DTM 2023–25, curated events). "
        "First the whole record on one map: how many years each district has a recorded flood or landslide impact, cumulative deaths "
        "as circles, the 14 largest cumulative caseloads labelled, and the zones outlined.</p>",
        '<figure><img src="impact_summary.png" alt="Uganda districts coloured by number of years with recorded impact"></figure>',
        "<p>Then one map per year. Districts are coloured by people affected that year (log scale; pale pink = a record without a count), "
        "circles mark five or more deaths. Panels are framed for the two CERF rapid-response allocations (gold: USD 4.8 M in Oct 2007, USD 4.0 M in Jan 2020 for the Nov–Dec 2019 floods) and for El Niño Oct–Dec seasons (orange, ONI ≥ 0.5), with a tag for positive-IOD seasons. The 2007 Teso floods, the 2010 to 2013 run, 2018, 2020 and the 2024 to 2025 El Niño years stand out; "
        "2019 and 2022 are under-recorded because DesInventar has no 2019 cards and stops in 2021.</p>",
        '<figure><img src="impact_by_year.png" alt="Grid of 28 yearly maps of Uganda districts coloured by recorded impact"></figure>',
        "<p class='fn'>Two corrections to the raw sources: a few DesInventar datacards carry national totals against one district (Agago "
        "3,000,000 in July 2007; Bududa 300,000 in March 2010 against EM-DAT's 12,795), so counts of 100,000 or more per card are dropped "
        "while the record is kept; and DesInventar double-counts deaths across cards, so EM-DAT or curated death tolls take precedence where "
        "they exist. Table: <code>outputs/impact_district_year.csv</code>.</p>",
        "<h2>Does FloodScan see the recorded impact?</h2>",
        "<p>The observational backstop leans on FloodScan, so this asks, district by district, whether the satellite registers the "
        "floods people actually reported. Two tests: at year level, the AUC — the probability that a random impact year has a higher "
        "FloodScan annual maximum than a random non-impact year (0.5 = no relation); and at event level, where each dated event's "
        "window (3 days before to 7 days after) sits in the district's own FloodScan distribution. A district is called blind when "
        "its 2-year annual-maximum extent is below 1 percent — FloodScan essentially never registers flooding there.</p>",
        '<figure><img src="floodscan_vs_impact.png" alt="Map of AUC per district and a histogram of event percentiles by zone"></figure>',
        floodscan_impact_table(),
        "<p><strong>Reading:</strong> FloodScan is a good witness exactly where the riverine and wetland zones are — Butaleja, Bulambuli, "
        "Amuria, Katakwi and Soroti have AUCs of 0.7 to 0.86, and Teso events sit at the 94th percentile of the district record — and it is "
        "blind across most of the rest of the country: 60 of the 100 districts with three or more impact years never reach 1 percent "
        "extent, including the Elgon slopes (Bududa, Sironko, Kapchorwa, Bukwo, Namisindwa), the Karamoja north (Kaabong, Karenga, Amudat) "
        "and, notably, Adjumani, Moyo and Nebbi, where the Albert Nile floods are narrow riverbank events a 9-km product does not resolve. "
        "So the satellite backstop is sound for the Teso zone and the Elgon and Teso lowland tiers, partial for Karamoja, and cannot "
        "serve the Elgon slopes or the Albert Nile bank, where the backstop has to be report-based (DTM, OPM) or gauge-based.</p>",
        "<h2>How much of the recorded impact do the zones cover?</h2>",
        "<p>Every district classified as zone core, zone tier 2, partner-only (in a standing flood AA of IFRC, WFP, CRS/Caritas or DRC "
        "but not in our zones) or uncovered, with the 1998–2025 record summed per class.</p>",
        impact_coverage_table(),
        "<p><strong>Reading:</strong> the four zones with their second tiers hold just over half of all recorded people affected and "
        "about two thirds of recorded deaths; the partner-only districts (Kasese, Kisoro, Ntoroko, Bundibugyo under WFP; Kampala under "
        "the IFRC EAP) add another sixth of affected. The uncovered remainder is spread thinly over about ninety districts with no single "
        "large gap: the biggest are Masaka, Amuru, Kabale, Otuke and Zombo, each under 100,000 cumulative affected and mostly single-source "
        "DesInventar records.</p>",
        "<h2>Impact record assembled</h2><ul>"
        "<li><strong>EM-DAT</strong> — 47 flood and wet mass-movement events 2001–2024, exploded to districts.</li>"
        "<li><strong>DesInventar Uganda</strong> — about 1,500 flood, 370 landslide and 130 rainstorm datacards, day-dated and district-matched, 1933–2021 (no 2019 records; ends 2021).</li>"
        "<li><strong>IOM DTM</strong> — affected people by district and reporting round, Oct 2023 – Oct 2025 (country-team compilation).</li>"
        "<li><strong>Curated events</strong> — dated Elgon and Karamoja flash floods / landslides and West Nile floods 2007–2025, each with a source.</li></ul>",
        "<h2>Data built for the analysis</h2><ul>"
        "<li>FloodScan SFED and IMERG rainfall, daily per district (mean and max), 1998–present.</li>"
        "<li>CHIRPS-GEFS 5-day rainfall forecast per district, daily issues 2000 – Jul 2026 (the forecast leg of the flash-flood skill chain).</li>"
        "<li>GloFAS v4 reanalysis 1999–2024 (Uganda box) and G5196 reforecast 2003–2023 (leads 1–15 days).</li>"
        "<li>Lake Victoria, Kyoga and Albert altimetry levels.</li></ul>"
        "<p>Uganda is capped at admin 1 in the team rasterstats database, so the district series are computed from the processed rasters directly.</p>",
        "<h2>Next</h2><ul>"
        "<li>Flash-flood skill chain for Elgon and Karamoja: CHIRPS-GEFS 5-day forecast vs IMERG, then observed rain vs the DesInventar / DTM / curated events.</li>"
        "<li>G5196: model-space return-period thresholds from the reforecast climatology; backtest of readiness (10–14 d) and action (3–7 d) windows against the 2007, 2011–2013, 2018 and 2025 Teso floods.</li>"
        "<li>Adjumani: lake-level leg (Kyoga/Albert percentile) plus rainfall leg; extend the Albert record back to 2002 via DAHITI/Hydroweb.</li></ul>",
        FOOT.format(today=TODAY),
    ]
    return "".join(parts)


def main() -> None:
    (PAGES / "coverage" / "index.html").write_text(coverage_page())
    (PAGES / "results" / "index.html").write_text(results_page())
    print("wrote pages/coverage/index.html and pages/results/index.html")


if __name__ == "__main__":
    main()
