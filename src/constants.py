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

# GloFAS reporting point for the riverine zone — verified 2026-09-02 against the
# public GloFAS OWS HydrologicalModelPerformance layer (src/data/glofas_calibration_stations_uga_bbox.csv):
#   G5196 "Akokorio At Uganda Gauge", river Akokoro; station 1.80N 33.90E; LISFLOOD v4
#   pixel centre 33.875E 1.775N; calibrated, 22.5-yr record; KGE 0.11, corr 0.65, bias 1.68.
#   Model RP thresholds (Qsim): 2-yr 33, 5-yr 62, 20-yr 100 m3/s.
#   The OWS layer quotes 13,218 km2 (LDD) vs 1,410 km2 (provider) upstream; the v4
#   reanalysis mean at the pixel is ~7 m3/s (annual maxima 4-97 m3/s) while the E-W Awoja
#   main stem one row south (lat 1.675) runs ~140 m3/s, so the pixel IS the local Akokoro
#   above the Awoja confluence, not the Karamoja-fed main stem.
# A second, unnamed fixed reporting point sits ~44 km upstream at ~33.805E 2.17N (Kapelebyong).
# There are NO GloFAS points of any kind on the Albert Nile (Pakwach to Laropi).
GLOFAS_STATION_ID = "G5196"
GLOFAS_STATION_NAME = "Akokorio at Uganda gauge (Akokoro river)"
GLOFAS_STATION_LATLON = (1.80, 33.90)  # gauge
GLOFAS_PIXEL_LONLAT = (33.875, 1.775)  # LISFLOOD v4 cell centre used for reanalysis/reforecast
GLOFAS_UPSTREAM_KM2_MODEL = 13_218
GLOFAS_MODEL_RP_THRESHOLDS = {2: 33.0, 5: 62.0, 20: 100.0}
GLOFAS_KAPELEBYONG_LONLAT = (33.805, 2.17)  # unnamed fixed point, pixel-derived (+/-0.01 deg)


@dataclass(frozen=True)
class Zone:
    key: str
    label: str
    regime: str  # riverine | flash-landslide | flash | riverine-lake
    core: tuple[str, ...]
    # Second tier: same driver, different flood regime and therefore a different
    # indicator (e.g. the lowlands below a massif, the wetlands downstream of a gauge).
    tier2: tuple[str, ...] = field(default_factory=tuple)
    tier2_label: str = ""
    tier2_regime: str = ""
    candidate: tuple[str, ...] = field(default_factory=tuple)
    note: str = ""

    @property
    def all_districts(self) -> tuple[str, ...]:
        return self.core + self.tier2 + self.candidate


ZONES: dict[str, Zone] = {
    "teso_kyoga": Zone(
        key="teso_kyoga",
        label="Teso / Lake Kyoga (Akokoro river, GloFAS G5196)",
        regime="riverine",
        # Core = districts whose FloodScan flood extent co-varies with G5196 discharge
        # (analysis/teso_glofas_coverage.py, 1999-2019): Amuria and Katakwi directly
        # (anomaly corr 0.6, lag 0-7 d), Soroti, Ngora and Serere as the downstream Awoja/Bisina
        # wetlands (corr ~0.5 at 19-30 d lag, P(Q>2yr | max extent>2yr) 0.6). Kapelebyong holds the
        # point and its catchment: extent there is too small for FloodScan (corr 0.36)
        # but when it does flood the discharge is high (P 0.73), so it stays in.
        core=("Katakwi", "Amuria", "Kapelebyong"),
        # Tier 2: the Awoja / Lake Bisina wetlands the Akokoro drains into — extent tracks the
        # point with a 19-30 day lag (Serere passes only on the max-pixel extent), so the trigger
        # there is the same discharge signal read later, or the observed extent itself.
        # No candidates left — the check ruled the rest out (TESO_EXCLUDED).
        tier2=("Soroti", "Ngora", "Serere"),
        tier2_label="downstream wetlands (Awoja / Bisina)",
        tier2_regime="wetland fill, 3-4 weeks behind the gauge",
        candidate=(),
        note=(
            "Ruled OUT by the coverage check (corr < 0.45 or P < 0.25): Kumi, Bukedea, Pallisa, "
            "Butaleja, Kibuku, Budaka, Butebo (Mpologoma system), Kaberamaido, Kalaki, Amolatar, "
            "Dokolo, Otuke, Alebtong (Kyoga north shore). Their flooding is not what G5196 sees."
        ),
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
        # Tier 2: the Manafwa / Mpologoma / Awoja lowlands at the foot of the massif. Same
        # rain, different regime — slow riverine and wetland flooding a few days later,
        # which FloodScan does see (Butaleja 24 %, Pallisa 32 %, Kumi 30 % of OND seasons).
        # Every impact year in these districts is also an Elgon-slope impact year.
        tier2=("Butaleja", "Budaka", "Kibuku", "Pallisa", "Bukedea", "Kumi"),
        tier2_label="lowlands below the massif (Manafwa / Mpologoma / Awoja)",
        tier2_regime="riverine + wetland, lagged behind the slope rainfall",
        note=(
            "Slopes: rainfall-forecast trigger; FloodScan cannot see the hazard, impact record must "
            "be report-based. Lowlands: observed extent, river level, or Elgon rainfall with a lag."
        ),
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
        # Tier 2: the Lake Albert shore and the Nile bank just below the lake, where the
        # lake-level regime dominates outright (Pakwach ~100,000 affected in 2020).
        tier2=("Pakwach", "Nebbi", "Madi Okollo"),
        tier2_label="Lake Albert shore and upper Albert Nile",
        tier2_regime="lake backwater (months of lead from Lake Victoria)",
        note=(
            "Two regimes in the record: lake backwater (2020, 2021, 2024 at >90th pctl Kyoga/Albert level) "
            "and local tributary flash floods at ordinary lake levels. Needs a lake-level leg and a rainfall leg."
        ),
    ),
}

# Teso/Kyoga districts evaluated for G5196 coverage and ruled out (kept so the coverage
# analysis keeps showing why): Mpologoma system and Kyoga north shore.
TESO_EXCLUDED = (
    "Kumi",
    "Bukedea",
    "Pallisa",
    "Butaleja",
    "Kibuku",
    "Budaka",
    "Butebo",
    "Kaberamaido",
    "Kalaki",
    "Amolatar",
    "Dokolo",
    "Otuke",
    "Alebtong",
)

# Uganda's two rainy seasons (bimodal south/east; Karamoja and West Nile are
# effectively unimodal Apr–Oct). Kept for season-splitting of statistics.
SEASONS = {"MAM": (3, 4, 5), "OND": (10, 11, 12), "JJAS": (6, 7, 8, 9)}

# FloodScan SFED noise floor used across the team (ds-floodexposure-monitoring)
SFED_NOISE_FLOOR = 0.05
