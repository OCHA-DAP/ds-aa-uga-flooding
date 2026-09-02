"""Other organisations' flood AA coverage in Uganda, for the coverage map.

District lists by CODAB ADM2_EN. Every entry carries its source; entries
marked `verified=False` are placeholders awaiting confirmation from the
source documents and must not be presented as fact.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ExternalFramework:
    key: str
    org: str
    label: str
    districts: tuple[str, ...]
    trigger: str
    status: str
    source: str
    verified: bool = False
    notes: tuple[str, ...] = field(default_factory=tuple)


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
        label="district flood AA plans, South-West (Kasese, Kisoro, Ntoroko)",
        districts=("Kasese", "Kisoro", "Ntoroko"),
        trigger=(
            "Flood triggers 'finalised' by MWE/DWRM in 2025 (Semliki river trigger in the Ntoroko contingency plan); "
            "indicator, threshold and lead time not published"
        ),
        status=(
            "2024: MAM flood forecast -> desilting; 2025: anticipatory cash to 2,135 people (mainly Ntoroko). "
            "Anticipation Hub lists the WFP flood framework as 'under development'."
        ),
        source="WFP Uganda Annual Country Report 2025 (WFP-0000172882) p.22; ACR 2024; Anticipation Hub Uganda page",
        verified=True,
        notes=(
            "WFP/FAO PRO-ACT in the 9 Karamoja districts + Kaberamaido, Katakwi is a DROUGHT AA plan "
            "(activated May 2026) with multi-hazard bulletins — no flood trigger; not drawn on the flood map.",
        ),
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
        status="11 Aug - 31 Dec 2023 only (OSRO/UGA/070/BEL, USD 1M, 78,375 people). FAO's standing AA in Uganda is Karamoja drought/livestock.",
        source="FAO project report https://openknowledge.fao.org/server/api/core/bitstreams/22e1fbf6-6ae8-436c-9118-12d9d94482f6/content pp.1-2, 7",
        verified=True,
    ),
}
