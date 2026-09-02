"""Project constants: blob prefix, the four trigger zones, the GloFAS point, seasons.

Zone membership is by CODAB ADM2_EN district name (FieldMaps vintage with 135
districts, loaded via ocha_stratus.codab). Each zone has a `core` list (the
districts the zone is *for*) and a `candidate` list (neighbours the analysis
must rule in or out — e.g. everything the Akokoro GloFAS point might cover).
Resolve to pcodes with `src.zones.zone_districts()`; never hardcode pcodes here.
"""

from dataclasses import dataclass, field

PROJECT_PREFIX = "ds-aa-uga-flooding"
BLOB_STAGE = "dev"

ISO3 = "UGA"
UGA_BOX = (29.0, -2.0, 35.5, 4.7)  # W, S, E, N — windowing box for country rasters

# GloFAS reporting point for the riverine zone. ID and name as given by the
# country team (2026-09-02); coordinates/upstream area are filled by
# pipeline/glofas_points.py from the reporting-point layer and verified in
# analysis — do not trust the placeholder below until that has run.
GLOFAS_STATION_ID = "G5196"
GLOFAS_STATION_NAME = "Akokoro at Uganda gauge"


@dataclass(frozen=True)
class Zone:
    key: str
    label: str
    regime: str  # riverine | flash-landslide | flash | riverine-lake
    core: tuple[str, ...]
    candidate: tuple[str, ...] = field(default_factory=tuple)
    note: str = ""

    @property
    def all_districts(self) -> tuple[str, ...]:
        return self.core + self.candidate


ZONES: dict[str, Zone] = {
    "teso_kyoga": Zone(
        key="teso_kyoga",
        label="Teso / Lake Kyoga (Akokoro river, GloFAS G5196)",
        regime="riverine",
        core=("Katakwi", "Amuria", "Kapelebyong"),
        candidate=(
            # rest of Teso sub-region
            "Soroti",
            "Serere",
            "Ngora",
            "Kumi",
            "Bukedea",
            "Kaberamaido",
            "Kalaki",
            # Lango shore of Lake Kyoga
            "Amolatar",
            "Dokolo",
            "Otuke",
            "Alebtong",
            # Bukedi / Mpologoma wetlands
            "Pallisa",
            "Butaleja",
            "Kibuku",
            "Budaka",
            "Butebo",
        ),
        note="Which candidates the G5196 point actually covers is the first analysis task.",
    ),
    "elgon": Zone(
        key="elgon",
        label="Mount Elgon (flash floods & landslides)",
        regime="flash-landslide",
        core=(
            "Bududa",
            "Bulambuli",
            "Sironko",
            "Manafwa",
            "Namisindwa",
            "Mbale",
            "Kapchorwa",
            "Kween",
            "Bukwo",
        ),
        note="Rainfall-forecast trigger; FloodScan cannot see the hazard, impact record must be report-based.",
    ),
    "karamoja": Zone(
        key="karamoja",
        label="Karamoja (flash floods)",
        regime="flash",
        core=(
            "Kaabong",
            "Karenga",
            "Kotido",
            "Abim",
            "Moroto",
            "Napak",
            "Nabilatuk",
            "Nakapiripirit",
            "Amudat",
        ),
        note="Rainfall-forecast trigger over a very large area; sub-zoning by river basin likely needed.",
    ),
    "adjumani": Zone(
        key="adjumani",
        label="Adjumani / Albert Nile",
        regime="riverine-lake",
        core=("Adjumani", "Moyo", "Obongi"),
        candidate=("Madi Okollo", "Pakwach", "Nebbi"),
        note="Indicator undecided: GloFAS Albert Nile points, Lake Albert level, or rainfall.",
    ),
}

# Uganda's two rainy seasons (bimodal south/east; Karamoja and West Nile are
# effectively unimodal Apr–Oct). Kept for season-splitting of statistics.
SEASONS = {"MAM": (3, 4, 5), "OND": (10, 11, 12), "JJAS": (6, 7, 8, 9)}

# FloodScan SFED noise floor used across the team (ds-floodexposure-monitoring)
SFED_NOISE_FLOOR = 0.05
