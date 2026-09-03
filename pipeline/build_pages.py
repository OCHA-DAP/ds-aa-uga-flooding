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
from src.constants import GLOFAS_PIXEL_LONLAT, ZONES  # noqa: E402
from src.frameworks import EXTERNAL  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
PAGES, OUT = ROOT / "pages", ROOT / "outputs"
TODAY = date.today().isoformat()

HEAD = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} — Uganda flood AA</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Merriweather:wght@700&family=Roboto:wght@400;500;700&display=swap" rel="stylesheet">
<link rel="stylesheet" href="../assets/site.css"><link rel="stylesheet" href="../assets/page.css">
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
            title="Trigger zones and existing coverage",
            sub="The four OCHA/CERF zones under design, the GloFAS point, and where other organisations' flood anticipatory action already operates.",
        ),
        '<figure><img src="zones_coverage_map.png" alt="Map of Uganda with the four trigger zones and other organisations\' flood AA coverage">'
        "<figcaption>Backdrop: share of Oct–Dec seasons 1998–2025 with FloodScan flooding (SFED ≥ 0.05), clipped to Uganda. "
        "Zones: solid = core districts, lighter = candidates to be ruled in or out by the analysis. Hatched: other organisations' "
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


def results_page() -> str:
    for f in ("teso_glofas_coverage.png", "adjumani_lake_levels.png"):
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
            title="Results so far",
            sub="Interim analysis outputs. Each figure and table is produced by a script in the repo; nothing here is a trigger yet.",
        ),
        "<h2>Teso / Kyoga — what does GloFAS G5196 cover?</h2>",
        f"<p>GloFAS v4 reanalysis discharge at the G5196 pixel against each candidate district's FloodScan flood-extent daily mean, {e(cov.record.iloc[0])}: "
        "best lagged correlation in the Aug–Dec flood season, and the conditional probability that discharge is over its 2-year level when the district's "
        "extent is over its own 2-year level. Red outline = covered (corr ≥ 0.5 and P ≥ 0.4).</p>",
        '<figure><img src="teso_glofas_coverage.png" alt="Two maps of Teso districts coloured by correlation and conditional probability"></figure>',
        table(
            cov_show,
            {
                "best corr": lambda v: f"{v:.2f}",
                "P(Q>2yr | extent>2yr)": lambda v: f"{v:.2f}",
                "P(extent>2yr | Q>2yr)": lambda v: f"{v:.2f}",
            },
        ),
        "<p><strong>Reading:</strong> the point speaks for Amuria and Katakwi (lag 0–7 days), weakly for the Soroti–Ngora–Serere wetlands downstream "
        "(long lags, the wetland fill), and not at all for Pallisa, Butaleja or the Kyoga north shore. Kapelebyong, upstream, is barely visible to FloodScan. "
        "Reforecast-based thresholds and the backtest follow once the EWDS download completes.</p>",
        "<h2>Adjumani / Albert Nile — are the floods lake-level events?</h2>",
        "<p>Monthly altimetry levels of Lakes Victoria, Kyoga and Albert (NASA Global Water Monitor) against every dated flood record we hold for Adjumani, "
        "Moyo, Obongi, Nebbi and Pakwach (DesInventar datacards 1992–2021, EM-DAT, and curated 2019–2024 events).</p>",
        '<figure><img src="adjumani_lake_levels.png" alt="Three lake level time series with flood months marked"></figure>',
        "<p><strong>Reading:</strong> two regimes. The large, well-documented backwater floods (Pakwach and Obongi 2020, 2021, Obongi/Palorinya Oct–Nov 2024) "
        "sit above the 90th percentile of Kyoga and Albert levels, with the Victoria → Kyoga → Albert chain giving months of lead. Most smaller DesInventar "
        "records (Moyo 2008, 2011, 2014; Nebbi 2007–2014) occurred at ordinary lake levels and are local-rain / tributary events. The zone therefore needs "
        "a lake-level leg and a rainfall leg.</p>",
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
