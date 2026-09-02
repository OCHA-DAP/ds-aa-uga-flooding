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


EXTERNAL: dict[str, ExternalFramework] = {}
