"""Other organisations' flood AA coverage in Uganda, for the coverage map.

District lists by CODAB ADM2_EN. Every entry carries its source; entries
marked `verified=False` are placeholders awaiting confirmation from the
source documents and must not be presented as fact.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ExternalFramework:
    """Another organisation's flood AA framework, mapped to CODAB ADM2 districts."""

    key: str
    org: str
    label: str
    districts: tuple[str, ...]
    trigger: str
    status: str
    source: str
    verified: bool = False
    notes: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class Programme:
    """A national or sub-regional programme with no district list — early-warning
    infrastructure, roadmaps, appeals. Not drawn on the coverage map (nothing to draw),
    but it changes what a trigger can lean on, so it is reported alongside."""

    key: str
    org: str
    label: str
    scope: str
    what: str
    status: str
    source: str
    relevance: str = ""


EXTERNAL: dict[str, ExternalFramework] = {
    "ifrc_eap": ExternalFramework(
        key="ifrc_eap",
        org="IFRC / Uganda Red Cross",
        label="flood EAP (EAP2021UG01) — 14 high-risk districts",
        districts=(
            "Kasese",
            "Ntoroko",  # Rwenzori / Semliki
            "Katakwi",
            "Amuria",
            "Kumi",
            "Ngora",  # Teso / Kyoga
            "Nabilatuk",  # Karamoja (Awoja headwaters)
            "Butaleja",
            "Sironko",
            "Bududa",
            "Manafwa",
            "Bulambuli",  # Elgon
            "Moyo",  # Albert Nile
            "Kampala",
        ),
        trigger=(
            "GloFAS via the 510 IBF portal: >=70% (operationally 60%) probability of a 5-yr RP flood "
            "in high-priority districts (10-yr in lower-priority), >1,000 households, 5-day lead, FAR<=0.5"
        ),
        status=(
            "Approved 27 May 2021, 5-yr EAP nominally expired mid-2026 (GO appeal MDRUG048 open to 2026-11-30); "
            "no second-generation EAP found. One activation: 15 Nov 2023 (Ntoroko, Butaleja, Kikuube)."
        ),
        source="EAP summary https://adore.ifrc.org/Download.aspx?FileId=438600 (p.3 district list); MDRUG048 reports",
        verified=True,
        notes=(
            "The '16 potentially exposed districts' in the Nov 2023 reports are that event's IBF output, not the design list.",
            "No public assignment of districts to the 5-yr vs 10-yr priority tiers.",
            "Nov 2023 lessons: multiple false alarms in the 2023 El Nino season; episodic floods not captured by the portal.",
        ),
    ),
    "wfp_sw": ExternalFramework(
        key="wfp_sw",
        org="WFP",
        label="Southwest Flood AAP (Kasese, Ntoroko, Kisoro, Bundibugyo), Aug 2026-Dec 2028",
        districts=("Kasese", "Ntoroko", "Kisoro", "Bundibugyo"),
        trigger=(
            "Three-tier (mild/moderate/severe). General readiness: monthly SPI-1 forecast over per-district "
            "3-yr (moderate) / 5-yr (severe) RP thresholds, MAM and SOND, 15 days-1 month lead. Readiness: 7-day "
            "'exceptional rainfall' forecast at the 90th/95th/99th percentile OR daily totals above per-district "
            "mm thresholds (e.g. Kasese 14/39/47 mm, Ntoroko 16/27/35 mm for SOND), 7-day lead. Activation: the same "
            "exceeded on 2 consecutive forecast days, 5-day lead."
        ),
        status=(
            "Plan dated 28 Aug 2026, validity Aug 2026-Dec 2028; tier-1 beneficiaries 74,815-103,550 by scenario, "
            "budget USD 2.47-3.42 M. Earlier: 2024 MAM desilting, 2025 anticipatory cash (mainly Ntoroko)."
        ),
        source="Flood Anticipatory Action Plan for Southwestern Uganda, WFP, 28 Aug 2026 (country team share; dev blob raw/external_frameworks/)",
        verified=True,
        notes=(
            (
                "WFP/FAO PRO-ACT in the 9 Karamoja districts + Kaberamaido, Katakwi is a DROUGHT AA plan "
                "(activated May 2026) with multi-hazard bulletins — no flood trigger; not drawn on the flood map."
            ),
            "Rainfall thresholds are in mm/day within a 7-day forecast; the forecast product is not named in the plan summary.",
        ),
    ),
    "crs_elgon": ExternalFramework(
        key="crs_elgon",
        org="CRS / Caritas Tororo",
        label="AA Protocol for floods & landslides, Butaleja + Bududa (validated 7 Jul 2026)",
        districts=("Butaleja", "Bududa"),
        trigger=(
            "Window 1 (1-month lead): DMS/UNMA seasonal forecast 'likely or very likely' above-normal rainfall for "
            "Mt Elgon. Window 2 (7-day lead): DMS forecast of >=70% probability of a 5-yr RP flood via the DMS "
            "emergency dashboard and/or VDMC community indicators (3 days above-average rain, W-E wind, animal "
            "movement, river turning brown) in Buwali sub-county (Bududa) and Butaleja Town Council."
        ),
        status=(
            "Validated V5, 7 Jul 2026; pilot budget USD 218,520 (USD 200,000 CRS internal HRD funding pre-arranged; Start Network a possible top-up) (ECHO-consortium lineage: Oxfam Novib lead, "
            "CRS, Caritas Tororo, URCS in Bududa, Butaleja, Mbale, Namisindwa, Sironko; AA first triggered by the "
            "UNMA OND-2023 El Nino outlook). Sub-county scope: Butaleja TC, Butaleja SC, Himutu, Mazimasa; Bududa "
            "Buwali, Bundesi, Busiriwa, Bubita, Bufuma, Bushiyi, Bukibokolo."
        ),
        source="Anticipatory Action Protocol for Floods and Landslides, Uganda / Butaleja and Bududa, Validated V5 (country team share; dev blob raw/external_frameworks/)",
        verified=True,
        notes=("Threshold set by expert judgement, not a hindcast; MPCA via mobile money.",),
    ),
    "drc_karamoja": ExternalFramework(
        key="drc_karamoja",
        org="DRC",
        label="Karamoja AAP 2026 (drought, conflict, flash flood) — Moroto, Napak, Amudat",
        districts=("Moroto", "Napak", "Amudat"),
        trigger=(
            "Flash-flood ladder: Kospir River at 80-85% and rising; ~150 mm forecast over a short window; "
            "livestock moving to high ground. Drought: SPI <= -1.5, Kobebe dam <50%, body condition <3.0, "
            "price falls >30%. Conflict: herd concentration, raiding, youth grouping."
        ),
        status=(
            "Activated 27 Jul 2026 on the dual drought + conflict trigger (not flood). Cross-border with Kenya "
            "(Loima, Lokiriama, North Pokot). Flood-risk analysis flags Napak floodplains as highest risk; 48,000 "
            "people forecast displaced by flooding in Uganda under DRC's OND 2026 central scenario."
        ),
        source="DRC Karamoja Anticipatory Action Plan AAP2026KS (country team share; dev blob raw/external_frameworks/)",
        verified=True,
    ),
    "fao_2023": ExternalFramework(
        key="fao_2023",
        org="FAO",
        label="OND-2023 El Nino flood AA (one-off, closed)",
        districts=(
            "Mbale",
            "Butaleja",
            "Sironko",
            "Bulambuli",
            "Manafwa",
            "Namisindwa",
            "Bundibugyo",
            "Ntoroko",
            "Kasese",
            "Katakwi",
        ),
        trigger="Seasonal outlook (OND 2023, 40-45% above-normal) — one-off, no standing threshold",
        status=(
            "11 Aug - 31 Dec 2023 only (OSRO/UGA/070/BEL, USD 1M, 78,375 people). Succeeded in 2025-26 by the "
            "Japan-funded OPM/FAO flood early-warning project (see PROGRAMMES), which is infrastructure rather "
            "than a trigger. FAO's standing AA in Uganda remains Karamoja drought/livestock, activated May 2026."
        ),
        source="FAO project report https://openknowledge.fao.org/server/api/core/bitstreams/22e1fbf6-6ae8-436c-9118-12d9d94482f6/content pp.1-2, 7",
        verified=True,
        notes=(
            (
                "Still no FAO flood framework anywhere in Uganda with a published trigger (indicator, threshold, "
                "lead time) as of Sep 2026 — the only documented flood trigger in the country is the URCS/IFRC one."
            ),
        ),
    ),
}


# National / sub-regional programmes: no district list, so not on the map, but they change
# what our triggers can lean on (gauges to read, warning centres to route through).
PROGRAMMES: dict[str, Programme] = {
    "fao_opm_flood_ews": Programme(
        key="fao_opm_flood_ews",
        org="FAO + Office of the Prime Minister (Government of Japan funded)",
        label="Enhancing Flood Management in Uganda with Integrated Early Warning Systems",
        scope="Rwenzori and Mount Elgon sub-regions (district list not published)",
        what=(
            "USD 1.13 M. Installed 10 hydro-climatic stations and 2 flood early-warning centres, issued 72 "
            "bulletins, reached 100,000+ people, trained 540, and delivered anticipatory actions to ~5,000 "
            "households. No trigger: this is early-warning infrastructure and community preparedness."
        ),
        status="Mar 2025 - Mar 2026, closed; results dialogue at OPM Jun 2026",
        source="allAfrica, 5 Jun 2026 https://allafrica.com/stories/202606050689.html",
        relevance=(
            "The 10 stations sit in the two sub-regions where our Elgon tier 1 has no satellite signal and needs a "
            "gauge- or report-based backstop. Ask FAO/OPM whether the readings are accessible and at what latency."
        ),
    ),
    "gou_aa_roadmap": Programme(
        key="gou_aa_roadmap",
        org="Government of Uganda / OPM, with WFP, FAO and IGAD",
        label="National AA Roadmap 2026-2031 and the U-MHIEWS multi-hazard early-warning system",
        scope=(
            "National, with sub-national multi-hazard early-warning centres in Karamoja, Teso, Mount Elgon and "
            "Rwenzori, plus 2 regional centres"
        ),
        what=(
            "Commits to 'establish clear disaster triggers'; none published yet. Reports 1.6 M families reached "
            "with early warning and 400,000+ households with anticipatory action since 2021."
        ),
        status="Launched Jul 2026",
        source="https://reliefweb.int/report/uganda/uganda-roadmap-anticipatory-action-2026-2031",
        relevance=(
            "Three of our four zones (Teso, Mount Elgon, Karamoja) will have a government early-warning centre; "
            "West Nile will not. Those centres are the natural route for dissemination and for co-owning triggers."
        ),
    ),
    "fao_wfp_elnino_appeal": Programme(
        key="fao_wfp_elnino_appeal",
        org="FAO and WFP",
        label="Joint El Nino anticipatory action appeal",
        scope="22 countries including Uganda; no sub-national detail published",
        what="USD 202 M for 8.8 M people",
        status="Open, Jun 2026 - Mar 2027",
        source="FAO newsroom, 18 Jun 2026",
        relevance="A possible co-financing route for an OND 2026 activation; Uganda's share is not public.",
    ),
    "opm_fao_refugee_ews_assessment": Programme(
        key="opm_fao_refugee_ews_assessment",
        org="OPM with FAO, DRC and UNHCR",
        label="EWS, anticipatory action and ecosystem-based DRR needs assessment, refugee-hosting districts",
        scope="13 refugee-hosting districts incl. Adjumani, Obongi, Madi Okollo, Yumbe, Terego",
        what=(
            "92 responses, surveyed Dec 2025. Adjumani and Obongi report both riverine and flash flood exposure. "
            "Early-warning coverage is thin (Obongi ~20% institutional, Adjumani no institutional data) and the "
            "report states no comprehensive multi-hazard EWS is formally established in most of these districts."
        ),
        status="Preliminary report 7 Jan 2026; not published online (shared by the country team)",
        source="Needs Assessment preliminary data analysis report, Jan 2026 (dev blob raw/country_team/uga/)",
        relevance=(
            "Independent support for the two-regime split in the Adjumani zone, and a warning that the last mile "
            "there is weak — lead time must be budgeted for slow dissemination, favouring the long-lead lake-level leg."
        ),
    ),
}
