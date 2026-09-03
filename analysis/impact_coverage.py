"""How much of the recorded impact do the zones (and the partners) cover?

Classifies every district into: OCHA zone core, OCHA zone tier 2, partner-only
(a district in another organisation's standing flood AA but not in our zones —
WFP South-West, IFRC EAP, CRS/Caritas, DRC; FAO 2023 excluded as closed), or
uncovered. Sums recorded impact 1998-2025 (people affected, deaths, district-years
with a record) per class, and lists the largest uncovered districts.

Writes outputs/impact_coverage.csv (per class) and outputs/impact_uncovered.csv.
Run:  uv run python analysis/impact_coverage.py
"""

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.constants import ZONES
from src.frameworks import EXTERNAL
from src.zones import load_adm2

OUT = Path(__file__).resolve().parent.parent / "outputs"
STANDING = ("ifrc_eap", "wfp_sw", "crs_elgon", "drc_karamoja")


def classify() -> pd.DataFrame:
    adm = load_adm2()[["ADM2_EN"]].rename(columns={"ADM2_EN": "district"})
    cls, zone = {}, {}
    for k, z in ZONES.items():
        for d in z.core:
            cls[d], zone[d] = "zone core", k
        for d in z.tier2:
            cls[d], zone[d] = "zone tier 2", k
    partner = {d for key in STANDING for d in EXTERNAL[key].districts}
    adm["zone"] = adm.district.map(zone)
    adm["cls"] = adm.district.map(cls)
    adm.loc[adm.cls.isna() & adm.district.isin(partner), "cls"] = "partner only"
    adm["cls"] = adm.cls.fillna("uncovered")
    adm["partner"] = adm.district.isin(partner)
    return adm


def main() -> None:
    t = pd.read_csv(OUT / "impact_district_year.csv")
    per = t.groupby("district").agg(
        years=("any_record", "sum"), affected=("affected_any", "sum"), deaths=("deaths_any", "sum")
    )
    c = (
        classify()
        .merge(per, on="district", how="left")
        .fillna({"years": 0, "affected": 0, "deaths": 0})
    )
    tot = c[["years", "affected", "deaths"]].sum()
    by = c.groupby("cls")[["years", "affected", "deaths"]].sum()
    by["districts"] = c.groupby("cls").size()
    share = (
        (by[["years", "affected", "deaths"]] / tot * 100).round(0).astype(int).add_prefix("pct_")
    )
    out = by.join(share).loc[["zone core", "zone tier 2", "partner only", "uncovered"]]
    out.to_csv(OUT / "impact_coverage.csv")
    pd.set_option("display.width", 200)
    print(out.to_string())
    zones = c[c.cls.str.startswith("zone")].groupby("zone")[["years", "affected", "deaths"]].sum()
    print("\nby zone (core + tier 2):")
    print((zones.join((zones / tot * 100).round(0).astype(int).add_prefix("pct_"))).to_string())
    unc = c[c.cls == "uncovered"].sort_values("affected", ascending=False).head(15)
    unc[["district", "years", "affected", "deaths"]].to_csv(
        OUT / "impact_uncovered.csv", index=False
    )
    print("\nlargest uncovered districts:")
    print(unc[["district", "years", "affected", "deaths"]].round(0).to_string(index=False))
    po = c[c.cls == "partner only"].sort_values("affected", ascending=False)
    print("\npartner-only districts:")
    print(po[["district", "years", "affected", "deaths"]].round(0).to_string(index=False))


if __name__ == "__main__":
    main()
