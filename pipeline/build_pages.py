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
from src.frameworks import EXTERNAL, PROGRAMMES

ZONE_COL = {
    "teso_kyoga": "#2a78d6",
    "elgon": "#e34948",
    "karamoja": "#eda100",
    "adjumani": "#4a3aa7",
}

ROOT = Path(__file__).resolve().parent.parent
PAGES, OUT = ROOT / "pages", ROOT / "outputs"
TODAY = date.today().isoformat()

ASSET_VERSION = "4"  # bump when assets/*.css change so browsers refetch

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


# Rating vocabulary for the "proposed forecast" column (status colours, never reused for series)
RATING = {
    "good": ("good", "rate-good"),
    "promising": ("promising, unvalidated", "rate-mid"),
    "weak": ("weak", "rate-weak"),
}

# One row per zone tier: regime, the forecast we propose, its rating, and whether the
# satellite backstop applies. Numbers come from the results page analyses.
ZONE_STATUS = [
    (
        "teso_kyoga",
        "tier 1",
        "Riverine — Akokoro river (Katakwi, Amuria, Kapelebyong)",
        "GloFAS G5196 ensemble probability of exceeding a return-period flow, 3–14 day lead; aligned with the IFRC EAP form",
        "good",
        "Yes — FloodScan registers 87 % of events (AUC 0.75)",
        "Discharge–extent relationship drifted after 2013; needs a third opinion (DWRM gauge or Google Flood Hub) before it carries an action trigger.",
    ),
    (
        "teso_kyoga",
        "tier 2",
        "Wetland fill downstream — Awoja / Lake Bisina (Soroti, Ngora, Serere)",
        "Same G5196 signal read 3–4 weeks later, or the observed extent itself",
        "promising",
        "Yes — every dated event registers (AUC 0.69)",
        "Lagged relationship is weaker than upstream; may end up observation-led.",
    ),
    (
        "elgon",
        "tier 1",
        "Flash floods and landslides on the slopes (9 districts)",
        "Rainfall forecast (CHIRPS-GEFS / ECMWF) with an antecedent-wetness condition, 1–5 day lead",
        "weak",
        "No — 5 of 9 districts satellite-blind, 13 % of events register. Backstop must be gauge- or report-based (FAO/OPM stations, DTM, OPM)",
        "Precision stays under 15 % at any threshold; readiness-tier signal only.",
    ),
    (
        "elgon",
        "tier 2",
        "Lowland riverine and wetland — Manafwa / Mpologoma / Awoja (Butaleja, Pallisa, Kumi, Bukedea, Budaka, Kibuku)",
        "Elgon rainfall with a lag, or none — trigger on observed extent; GloFAS Manafwa point fails hydrology",
        "promising",
        "Yes — 72 % of events register (AUC 0.65; Butaleja 0.86)",
        "Forecast leg untested; the observational leg is the strong one here.",
    ),
    (
        "karamoja",
        "tier 1",
        "Flash floods (9 districts)",
        "Rainfall forecast with antecedent wetness, 1–5 day lead; sub-zoning by basin likely",
        "weak",
        "Partial — 3 of 9 districts blind, 11 % of events register; mostly report-based",
        "Same limits as the Elgon slopes; DRC covers Moroto, Napak, Amudat.",
    ),
    (
        "adjumani",
        "tier 1",
        "Albert Nile bank — two regimes: lake backwater and local tributary flash floods (Adjumani, Moyo, Obongi)",
        "Lake Victoria → Kyoga → Albert level chain for the slow regime (months of lead); rainfall for the flash regime",
        "promising",
        "No — none of 36 events register. Backstop must be a river gauge (Pakwach, Laropi) or reports",
        "Lake-driven floods of 2020, 2021, 2024 all sat above the 90th percentile of lake level, but that is three events and the Albert altimetry starts in 2016.",
    ),
    (
        "adjumani",
        "tier 2",
        "Lake Albert shore and upper Albert Nile backwater (Pakwach, Nebbi, Madi Okollo)",
        "Lake Albert level with the same upstream chain",
        "promising",
        "No — none of 39 events register; CEMS confirms lakeshore flooding is invisible to FloodScan",
        "Cleanest lake-level case (Pakwach 2020), still few events to validate on.",
    ),
]


def zone_status_table() -> str:
    rows = []
    for key, tier, regime, forecast, rating, backstop, note in ZONE_STATUS:
        z = ZONES[key]
        col = ZONE_COL[key]
        swatch = (
            f'<span class="sw sw-t1" style="background:{col}"></span>'
            if tier == "tier 1"
            else f'<span class="sw sw-t2" style="border-color:{col};background:{col}22"></span>'
        )
        label, cls = RATING[rating]
        rows.append(
            "<tr>"
            f"<td class='zn'>{swatch}<strong>{e(z.label.split(' (')[0])}</strong><br><span class='tier'>{e(tier)}</span></td>"
            f"<td>{e(regime)}</td>"
            f"<td class='{cls}'><span class='pill'>{e(label)}</span> {e(forecast)}<br><span class='fn'>{e(note)}</span></td>"
            f"<td>{e(backstop)}</td>"
            "</tr>"
        )
    head = "<tr><th>Zone</th><th>Flooding regime</th><th>Proposed forecast</th><th>Observational backstop (FloodScan) applicable?</th></tr>"
    legend = (
        "<p class='fn'>Forecast rating: <span class='pill rate-good'>good</span> a validated signal with usable lead time · "
        "<span class='pill rate-mid'>promising, unvalidated</span> a real signal with too few events or too short a record to calibrate on · "
        "<span class='pill rate-weak'>weak</span> readiness-tier at best, high false-alarm rate. "
        "Backstop = whether FloodScan flood extent sees the events that were recorded there (results page).</p>"
    )
    return f'<div class="tw status"><table><thead>{head}</thead><tbody>{"".join(rows)}</tbody></table></div>{legend}'


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
        "<h2>At a glance</h2>",
        "<p>What each zone is for, what would trigger it, and whether the satellite backstop can be trusted there.</p>",
        zone_status_table(),
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
        "<h2>National and sub-regional programmes</h2>"
        "<p>These carry no district list, so they are not on the map, but they change what a trigger can lean on — "
        "gauges to read, warning centres to route through, money to draw on.</p>"
    )
    for pr in PROGRAMMES.values():
        parts.append(
            f"<h3>{e(pr.org)} — {e(pr.label)}</h3>"
            f"<p><strong>Scope:</strong> {e(pr.scope)}<br>"
            f"<strong>What it is:</strong> {e(pr.what)}<br>"
            f"<strong>Status:</strong> {e(pr.status)}<br>"
            f"<strong>Source:</strong> {e(pr.source)}</p>"
            + (
                f"<p class='fn'><strong>Why it matters here:</strong> {e(pr.relevance)}</p>"
                if pr.relevance
                else ""
            )
        )
    parts.append(
        "<h2>Coverage against our zones</h2><ul>"
        "<li><strong>Teso / Kyoga:</strong> IFRC EAP (Katakwi, Amuria, Kumi, Ngora), FAO 2023 (Katakwi). No standing riverine trigger on the "
        "Akokoro/Awoja system. A government multi-hazard early-warning centre for Teso is coming under the national roadmap.</li>"
        "<li><strong>Mount Elgon:</strong> IFRC EAP (Butaleja, Sironko, Bududa, Manafwa, Bulambuli); CRS/Caritas protocol at sub-county level in "
        "Butaleja and Bududa; FAO 2023. Kapchorwa, Kween, Bukwo, Namisindwa and Mbale have no trigger. Since 2025 the FAO/OPM project has put "
        "hydro-climatic stations and a flood early-warning centre in the sub-region — the most promising backstop for the slopes, where no "
        "satellite works.</li>"
        "<li><strong>Karamoja:</strong> DRC (Moroto, Napak, Amudat — a flash-flood ladder inside a drought and conflict plan, activated Jul 2026 "
        "on the drought and conflict legs); Nabilatuk in the IFRC list. Kaabong, Karenga, Kotido, Abim and Nakapiripirit have no flood trigger. "
        "The FAO/WFP Karamoja drought plan activated separately in May 2026.</li>"
        "<li><strong>Adjumani / Albert Nile:</strong> nothing except Moyo in the IFRC list — and no early-warning centre is planned for West Nile "
        "under the national roadmap. The OPM/FAO/UNHCR/DRC assessment finds early-warning coverage there among the thinnest in the country.</li>"
        "<li><strong>Rwenzori (outside our zones):</strong> WFP's four-district plan, IFRC (Kasese, Ntoroko), and the other half of the FAO/OPM "
        "station network.</li></ul>"
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
    """One row per zone tier (and one for outside the zones): FloodScan visibility of the impact record."""
    d = pd.read_csv(OUT / "floodscan_vs_impact_district.csv")
    ev = pd.read_csv(OUT / "floodscan_vs_impact_events.csv")
    tier_of = {dd: "tier 1" for z in ZONES.values() for dd in z.core} | {
        dd: "tier 2" for z in ZONES.values() for dd in z.tier2
    }
    d["tier"] = d.district.map(tier_of)
    ev["tier"] = ev.district.map(tier_of)
    ok = d[(d.n_impact_years >= 3) & ~d.blind]
    rows = []
    groups = [
        (z, t) for z in ZONES for t in ("tier 1", "tier 2") if t == "tier 1" or ZONES[z].tier2
    ] + [("outside", None)]
    for z, t in groups:
        if z == "outside":
            dz, ez, okz = d[d.zone.isna()], ev[ev.zone == "outside"], ok[ok.zone.isna()]
            name = "outside the zones"
        else:
            dz, ez, okz = (
                d[(d.zone == z) & (d.tier == t)],
                ev[(ev.zone == z) & (ev.tier == t)],
                ok[(ok.zone == z) & (ok.tier == t)],
            )
            name = f"{ZONES[z].label.split(' (')[0]} — {t}" + (
                f" ({ZONES[z].tier2_label.split(' (')[0]})" if t == "tier 2" else ""
            )
        rows.append(
            {
                "area": name,
                "districts": len(dz),
                "FloodScan-blind": int(dz.blind.sum()),
                "median AUC (non-blind, ≥3 impact years)": round(okz.auc.median(), 2)
                if len(okz)
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
        "cems_pass.png",
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
        "<p><strong>Reading, and what it changed:</strong> the point speaks for Amuria and Katakwi at lag 0, and for Soroti, Ngora and Serere with a "
        "19–30 day lag as the Awoja–Bisina wetlands fill; Kapelebyong holds the point and its headwaters (too little extent for a correlation, but "
        "its rare floods coincide with high discharge). Nothing further out passes: Kumi, Bukedea, Pallisa, Butaleja and the Mpologoma "
        "districts, and the whole Kyoga north shore (Kaberamaido, Kalaki, Amolatar, Dokolo, Otuke, Alebtong) have weak correlations and no "
        "threshold agreement. The zone was redrawn accordingly: three core districts plus a downstream-wetland tier.</p>",
        "<p><strong>The caveat that matters most — the relationship is not stable in time.</strong> Now that the reanalysis covers 1999–2024, splitting "
        "by era shows the Katakwi correlation running 0.25 (1999–2005), 0.83 (2006–2011), 0.57 (2012–13), 0.15 (2014–19) and 0.06 (2020–24), with every "
        "other district in the zone swinging the same way. The full-record figure is therefore an average over periods that behave very differently, and "
        "the recent decade — the one that matters operationally — is the weakest. Two direct contradictions: 2020 is the model's record year "
        "(125 m³/s, three times its 2-year level) while the satellite saw an ordinary season, and 2022 is Amuria's wettest year in the satellite record "
        "on near-minimum discharge. Modelled daily variability also rises steadily across the eras (standard deviation 5.2 → 17.3 m³/s) with no matching "
        "change in the satellite, which points at the model rather than the river. Before this point carries an action trigger it needs a third opinion "
        "independent of both — the Directorate of Water Resources Management gauge record if it can be obtained, or Google Flood Hub — and the backtest "
        "must be reported era by era rather than as a single number.</p>",
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
        "extent. The tiers split cleanly on this. Elgon tier 1 (the slopes) is blind in five of nine districts, its events sit at the "
        "37th percentile and only 13 percent register at all; Elgon tier 2 (the lowlands) has no blind district, an AUC of 0.65, events "
        "at the 91st percentile and 72 percent registering. Both Teso tiers are fully visible. Both Adjumani tiers are invisible: none "
        "of the 75 Albert Nile and Lake Albert events registered, because they are narrow riverbank and lakeshore floods a 9-km product "
        "does not resolve. So the satellite backstop is sound for the Teso zone and the two lowland tiers, partial for Karamoja, and "
        "cannot serve the Elgon slopes or the Adjumani zone, where the backstop has to be report-based (DTM, OPM), gauge-based, or the "
        "lake level itself.</p>",
        "<h2>A second witness: Copernicus EMS rapid mapping</h2>",
        "<p>The team's CEMS flood archive holds every Copernicus EMS rapid-mapping flood activation since 2012 as harmonised polygons "
        "with acquisition dates. Uganda has three: EMSR438 (May 2020, the East Africa rains; three areas of interest with observed "
        "flooding, six acquisition dates), EMSR446 (June to September 2020, the Ministry of Water's request on rising lake levels; "
        "eleven dates) and EMSR662 (May 2023, the Katonga river at Nkozi). Each district-day of CEMS flooding is compared with the "
        "FloodScan district-mean extent on the same day.</p>",
        '<figure><img src="cems_pass.png" alt="Three maps of Uganda with CEMS flood polygons and the trigger zones"></figure>',
        "<p><strong>Reading:</strong> all three activations mapped ground outside the zones — the Lake Kyoga south shore (Nakasongola, "
        "Buyende, Kayunga), Kampala and the Katonga — so they cannot validate the zones directly. What they do test is FloodScan on "
        "lake-driven flooding, and the answer is blunt: across 75 district-days with at least 5 km² of CEMS-mapped water, FloodScan "
        "showed essentially nothing on 93 percent of them and was above its 90th percentile on 11 percent; the rank correlation between "
        "the two is zero. The 2020 lake-rise flooding of Kyoga's shore, the same mechanism as the Albert Nile and Lake Albert shore floods "
        "in the Adjumani zone, is invisible to the 9-km product. That is consistent with the Adjumani result above and settles that the "
        "observational leg for lake-driven floods has to be lake level or gauges, not satellite extent. Global Flood Monitoring "
        "(Sentinel-1) has no Uganda coverage in the team's store and was not pulled for this pass.</p>",
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
