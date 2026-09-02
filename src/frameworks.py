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
}
