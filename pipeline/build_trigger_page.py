"""Build pages/triggers/index.html — the draft trigger mechanisms and their year-by-year backtest.

Reads outputs/triggers/ (written by analysis/trigger_draft.py) and the zone definitions.
Public: everything here is our own analysis of public data.

  uv run python analysis/trigger_draft.py && uv run python pipeline/build_trigger_page.py
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import build_pages as bp

from src.constants import ZONES

TRIG = bp.OUT / "triggers"
ZONE_ORDER = ["teso_kyoga", "elgon", "karamoja", "adjumani"]
EXT_COL = "#5b5b5b"  # existing (other organisations') triggers: one neutral colour
SHORT = {"teso_kyoga": "Teso", "elgon": "Elgon", "karamoja": "Karamoja", "adjumani": "Adjumani"}


def ramp(t: float, lo=(253, 236, 230), hi=(165, 15, 21)) -> str:
    """Sequential light-to-dark red for impact magnitude, t in [0, 1]."""
    t = max(0.0, min(1.0, t))
    return "#" + "".join(f"{round(a + (b - a) * t):02x}" for a, b in zip(lo, hi, strict=True))


def impact_cell(v: float, top: float, floor: float) -> str:
    """Log shading from `floor` (palest) to the largest value in any zone (darkest), so a few
    thousand people affected reads light and a hundred thousand reads dark."""
    # EM-DAT figures are split evenly across the districts an event names, so values can be
    # fractional; anything that rounds to zero is shown as nothing recorded
    if pd.isna(v) or round(v) <= 0:
        return "<td class='num'></td>"
    t = (math.log10(max(v, floor)) - math.log10(floor)) / (math.log10(top) - math.log10(floor))
    t = 0.08 + 0.92 * t  # keep even the smallest recorded value visibly tinted
    fg = "#fff" if t > 0.55 else "#1a1a1a"
    return f"<td class='num' style='background:{ramp(t)};color:{fg}'>{v:,.0f}</td>"


def trigger_text(zone: str, thr: pd.DataFrame) -> tuple[str, str]:
    """Plain description of the trigger and its lead time."""
    t = thr[thr.zone == zone].set_index("series")
    rp = float(t.series_rp.iloc[0])
    if zone == "teso_kyoga":
        v = t.threshold.iloc[0]
        return (
            f"GloFAS daily discharge at G5196 (Akokoro) reaches <strong>{v:,.0f} m³/s</strong>, in model space "
            f"(the model runs about 1.7× wet, so this is not a gauged flow)",
            "3–14 days once run on the forecast; <strong>none in this backtest</strong>, which uses the reanalysis",
        )
    if zone == "elgon":
        v = t.threshold.iloc[0]
        return (
            f"The 5-day forecast rainfall, averaged over all 15 districts, reaches <strong>{v:,.0f} mm</strong>",
            "1–5 days",
        )
    rain = t.drop(index="Kyoga rise", errors="ignore").threshold
    rain_txt = (
        f"the 5-day forecast rainfall in any one district reaches that district’s own 1-in-{rp:.0f}-year level "
        f"(<strong>{rain.min():,.0f}–{rain.max():,.0f} mm</strong> depending on the district)"
    )
    if zone == "karamoja":
        return rain_txt[0].upper() + rain_txt[1:], "1–5 days"
    lake = t.loc["Kyoga rise", "threshold"]
    return (
        f"<em>Either</em> Lake Kyoga rises <strong>{lake:.2f} m</strong> over 180 days — the Nile high-stand "
        f"leg — <em>or</em> {rain_txt}",
        "months for the lake leg; 1–5 days for the rain leg",
    )


def summary_table(s: pd.DataFrame, thr: pd.DataFrame) -> str:
    rows = []
    for z in ZONE_ORDER:
        r = s.set_index("zone").loc[z]
        what, lead = trigger_text(z, thr)
        rows.append(
            "<tr>"
            f"<td class='zn'><span class='sw' style='background:{bp.ZONE_COL[z]}'></span><strong>{SHORT[z]}</strong></td>"
            f"<td>{what}</td><td>{lead}</td>"
            f"<td class='num'>{int(r.activation_years)} of {int(r.years_with_data)}</td>"
            f"<td class='num'><strong>1-in-{r.individual_rp:.1f}</strong></td>"
            f"<td class='num'>{int(r.worst5_caught)} of 5</td>"
            f"<td class='num'>{int(r.activations_in_major_years)} of {int(r.activation_years)}"
            f"<span class='fn'>base rate {r.base_rate_major:.0%}</span></td>"
            "</tr>"
        )
    head = (
        "<tr><th>Zone</th><th>Activates when</th><th>Lead time</th><th>Activation years</th>"
        "<th>Individual RP</th><th>Five worst years caught</th><th>Activations in a major-impact year</th></tr>"
    )
    return f"<div class='tw trig-sum'><table><thead>{head}</thead><tbody>{''.join(rows)}</tbody></table></div>"


def overview_table(tabs: dict[str, pd.DataFrame], years: list[int]) -> str:
    rows = []
    for y in years:
        cells, anyz = [], False
        for z in ZONE_ORDER:
            r = tabs[z].loc[y]
            if not r.data:
                cells.append("<td class='nodata'>no data</td>")
            elif r.activated:
                anyz = True
                cells.append(f"<td class='act' style='background:{bp.ZONE_COL[z]}'>activated</td>")
            else:
                cells.append("<td></td>")
        cerf = tabs["teso_kyoga"].loc[y].cerf
        rows.append(
            f"<tr><td class='yr'>{y}</td>{''.join(cells)}"
            f"<td class='any'>{'●' if anyz else ''}</td>"
            f"<td class='fn'>{bp.e(cerf) if isinstance(cerf, str) else ''}</td></tr>"
        )
    head = (
        "<tr><th>Year</th>"
        + "".join(f"<th>{SHORT[z]}</th>" for z in ZONE_ORDER)
        + "<th>Any zone</th><th>CERF flood allocation (national)</th></tr>"
    )
    return f"<div class='tw trig-over'><table><thead>{head}</thead><tbody>{''.join(rows)}</tbody></table></div>"


def source_labels(raw: str) -> str:
    """The impact table keeps the first ten characters of each source; name them properly."""
    out = []
    for x in filter(None, raw.split("|")):
        lab = (
            "EM-DAT"
            if x.startswith("EM-DAT")
            else "IOM DTM"
            if x.startswith("IOM")
            else "DesInventar"
            if x.startswith("DesInvent")
            else "press / ReliefWeb"
        )
        if lab not in out:
            out.append(lab)
    return ", ".join(out)


def load_existing(path) -> dict[str, list[tuple[str, str, pd.DataFrame]]]:
    """Existing triggers per zone as (short name, description, per-year frame)."""
    out: dict[str, list[tuple[str, str, pd.DataFrame]]] = {}
    if not Path(path).exists():
        return out
    df = pd.read_csv(path)
    for z, g in df.groupby("zone", sort=False):
        out[z] = [
            (h.short.iloc[0], h.label.iloc[0], h.set_index("year"))
            for _, h in g.groupby("key", sort=False)
        ]
    return out


def merge_existing(*dicts) -> dict[str, list[tuple[str, str, pd.DataFrame]]]:
    """Combine sets of existing triggers. Triggers whose year-by-year activations are identical
    in the backtest (several organisations' GloFAS 5-year triggers reduce to the same stand-in
    at the same point) become one column with their names joined, not duplicate columns."""
    out: dict[str, list[tuple[str, str, pd.DataFrame]]] = {}
    for d in dicts:
        for z, cols in d.items():
            cur = out.setdefault(z, [])
            for short, label, h in cols:
                sig = tuple(h.activated & h.data)
                for i, (s0, l0, p0) in enumerate(cur):
                    if tuple(p0.activated & p0.data) == sig:
                        cur[i] = (f"{s0} · {short}", f"{l0}<br>{label}", p0)
                        break
                else:
                    cur.append((short, label, h))
    return out


def rates(activated: pd.Series, data: pd.Series, tab: pd.DataFrame) -> dict:
    cal = tab[tab.in_calibration]
    a = activated.reindex(cal.index).fillna(False).astype(bool)
    d = data.reindex(cal.index).fillna(False).astype(bool)
    act_years = set(a[a & d].index)
    n = int(d.sum())
    worst = set(cal.affected.nlargest(5).index)
    major = set(cal[cal.major].index)
    return dict(
        n=len(act_years),
        years=n,
        rp=(n + 1) / len(act_years) if act_years else float("nan"),
        worst=len(worst & act_years),
        major=len(major & act_years),
    )


def compare_table(z: str, tab: pd.DataFrame, cols) -> str:
    """Our draft and each existing trigger over the same calibration years."""
    items = [("Our draft", tab.activated, tab.data, bp.ZONE_COL[z])]
    items += [(short, h.activated, h.data, EXT_COL) for short, _, h in cols]
    base = tab[tab.in_calibration].major.mean()
    rows = []
    for name, act, dat, col in items:
        r = rates(act, dat, tab)
        rp = f"1-in-{r['rp']:.1f}" if r["n"] else "never"
        rows.append(
            f"<tr><td><span class='sw' style='background:{col}'></span>{bp.e(name)}</td>"
            f"<td class='num'>{r['n']} of {r['years']}</td><td class='num'><strong>{rp}</strong></td>"
            f"<td class='num'>{r['worst']} of 5</td><td class='num'>{r['major']} of {r['n']}</td></tr>"
        )
    head = (
        "<tr><th>Trigger</th><th>Activation years</th><th>Return period</th><th>Five worst years caught</th>"
        f"<th>Activations in a major-impact year (base rate {base:.0%})</th></tr>"
    )
    return f"<div class='tw trig-cmp'><table><thead>{head}</thead><tbody>{''.join(rows)}</tbody></table></div>"


def existing_notes(cols) -> str:
    if not cols:
        return ""
    items = "".join(f"<li><strong>{bp.e(short)}</strong>: {label}</li>" for short, label, _ in cols)
    return f"<ul class='ext-notes'>{items}</ul>"


def existing_cell(h: pd.DataFrame, y: int) -> str:
    if y not in h.index or not h.loc[y].data:
        return "<td class='nodata'>no data</td>"
    r = h.loc[y]
    if r.activated:
        return f"<td class='act' style='background:{EXT_COL}'>activated<span class='d'>{r.first_date}</span></td>"
    return "<td></td>"


def zone_table(z: str, tab: pd.DataFrame, top_aff: float, top_d: float, cols=()) -> str:
    rows = []
    for y, r in tab.sort_index(ascending=False).iterrows():
        if not r.data:
            act = "<td class='nodata'>no forecast data</td>"
        elif r.activated:
            via = r.via if isinstance(r.via, str) else ""
            via = "" if via in ("GloFAS G5196", "zone-mean 5-day forecast") else f" · {bp.e(via)}"
            act = (
                f"<td class='act' style='background:{bp.ZONE_COL[z]}'>activated"
                f"<span class='d'>{r.first_date}{via}</span></td>"
            )
        else:
            act = "<td></td>"
        if pd.notna(r.peak_rp) and r.data:
            peak = f"1-in-{r.peak_rp:.0f}" if r.peak_rp >= 2 else "below 1-in-2"
            if isinstance(r.peak_where, str) and z in ("karamoja", "adjumani"):
                peak += f"<span class='fn'>{bp.e(r.peak_where)}</span>"
        else:
            peak = ""
        src = r.sources if isinstance(r.sources, str) else ""
        yr = f"{y}" + ("" if r.in_calibration else "<span class='fn'>not in calibration</span>")
        rows.append(
            f"<tr><td class='yr'>{yr}</td>{act}<td class='num'>{peak}</td>"
            + "".join(existing_cell(h, y) for _, _, h in cols)
            + f"{impact_cell(r.affected, top_aff, 500)}{impact_cell(r.deaths, top_d, 1)}"
            f"<td class='num'>{int(r.districts) if r.districts else ''}</td>"
            f"<td class='src'>{bp.e(source_labels(src))}</td>"
            f"<td class='src'>{bp.e(r.cerf) if isinstance(r.cerf, str) else ''}</td></tr>"
        )
    head = (
        "<tr><th>Year</th><th>Our draft</th><th>Year’s peak</th>"
        + "".join(f"<th>{bp.e(short)}</th>" for short, _, _ in cols)
        + "<th>People affected</th><th>Deaths</th><th>Districts reporting</th><th>Impact sources</th>"
        "<th>CERF</th></tr>"
    )
    return f"<div class='tw trig-zone'><table><thead>{head}</thead><tbody>{''.join(rows)}</tbody></table></div>"


ZONE_NOTE = {
    "teso_kyoga": (
        "Aligned with the IFRC/URCS early action protocol’s instrument (GloFAS at a reporting point), on the one "
        "point in the sub-region that passes both skill checks. The reanalysis is a stand-in until the reforecast "
        "download finishes: it has no forecast error in it, so this is an upper bound. Two known weaknesses show "
        "in the table. The biggest recorded years — 2007, 2010, 2012, 2014 — are not the model’s biggest "
        "years; and 2020, the model’s record by far, was an ordinary season on the satellite record. That is "
        "the non-stationarity found in the coverage work (G5196 tracks observed flooding well in 2006–2013 and "
        "poorly since), and it needs a third opinion — a DWRM gauge or Flood Hub — before this is proposed."
    ),
    "elgon": (
        "One zone-wide trigger: every lowland flood year in the record is also a slope flood year, and the forecast "
        "moves together across the 15 districts (median rank correlation of annual peaks 0.74). Elgon has some "
        "recorded impact every year, so the useful test is whether activations land in the worst years: "
        "2019 and 2018 do, and 2019 is a CERF year. At year level the forecast does not rank Elgon’s years "
        "well overall (AUC about 0.5 against the worst third), which is the same limit the event-level work found."
    ),
    "karamoja": (
        "Per district, as suggested: each of the nine districts is held to the same rarity, and the zone activates "
        "when any one reaches it. To keep the zone at 1-in-8.7, each district has to be much rarer — about "
        "1-in-22 — because nine districts give nine chances. The first-activation date and the district that "
        "activated are shown in the trigger cell. Whether an activation in one district releases the whole Karamoja "
        "envelope or that district’s share is a funding decision; this draft assumes all-in."
    ),
    "adjumani": (
        "Two legs, because the record shows two regimes. The lake leg covers Nile high-stand floods — 2020 above "
        "all, when the Albert Nile rose from June and displaced 123,000 people across Pakwach, Obongi and "
        "Adjumani — using Lake Kyoga’s rise over six months: Kyoga tracks Lake Albert at r = 0.96 month to "
        "month and has a record from 1992, where Albert’s starts in 2016. A threshold on the lake level itself "
        "would not work: the lakes rose about 3 m in 2020 and have stayed up, so it would activate every year since. "
        "The rain leg covers the tributary and settlement flash floods that make up most of the record. Both legs "
        "sit at the same rarity, about 1-in-{rp} each on a fitted Gumbel, so that the zone as a whole lands on its "
        "share. The rain leg activates in 2011, the September floods in Obongi and Moyo (about 4,000 people, below the "
        "major bar), and in 2000 in Moyo with nothing recorded \u2014 the West Nile record is thin before 2004, so "
        "treat that one as unverified rather than a false alarm. The lake leg does not reach 2023 or 2024: 2024 was "
        "a 1-in-10 rise, short of the threshold, and 2023\u2019s floods were rain-driven in a year the lake fell."
    ),
}


# Where an existing trigger operates in the zone but is not shown on this public page
EXISTING_NOTE = {
    "elgon": (
        "Two partner plans also trigger here \u2014 a draft FAO plan and the CRS/Caritas Tororo protocol. Neither is "
        'published, so their backtests sit on the <a href="../partner/">restricted partner page</a>.'
    ),
    "karamoja": (
        "The IFRC EAP lists Nabilatuk, but there is no GloFAS reporting point in Karamoja to reproduce it with. DRC\u2019s "
        "Karamoja plan covers Moroto, Napak and Amudat; it is not published, so its backtest sits on the "
        '<a href="../partner/">restricted partner page</a>.'
    ),
    "adjumani": (
        "The IFRC EAP lists Moyo, but there is no GloFAS reporting point on the Albert Nile to reproduce it with. No "
        "other organisation has a flood trigger in the zone."
    ),
}


def page() -> str:
    s = pd.read_csv(TRIG / "summary.csv")
    thr = pd.read_csv(TRIG / "thresholds.csv")
    tabs = {z: pd.read_csv(TRIG / f"{z}.csv").set_index("year") for z in ZONE_ORDER}
    existing = merge_existing(load_existing(TRIG / "existing_public.csv"))
    years = sorted(tabs["teso_kyoga"].index, reverse=True)
    top_aff = max(float(t.affected.max()) for t in tabs.values())
    top_d = max(float(t.deaths.max()) for t in tabs.values())
    r0 = s.iloc[0]
    parts = [
        bp.HEAD.format(
            v=bp.ASSET_VERSION,
            title="Draft triggers",
            sub="One trigger per zone, balanced to an overall return period of about three years. First draft for discussion.",
        ),
        "<p class='callout'><strong>Status: first draft.</strong> Thresholds are calibrated on "
        f"{r0.calibration} and will move as data is added. Teso runs on the GloFAS reanalysis until the reforecast "
        "download completes. Nothing here is endorsed.</p>",
        "<h2>How the four triggers are balanced</h2>",
        f"<p>Each zone has one all-in trigger: any activation releases that zone’s whole envelope. The budget is set "
        f"on the <strong>overall</strong> return period — the years in which at least one zone activates — and "
        f"shared equally, so every zone gets the same number of activation years. Three each gives "
        f"<strong>{int(r0.overall_years)} years out of 25 with at least one activation, an overall return period of "
        f"1-in-{r0.overall_rp:.2f}</strong>. That is the closest achievable to 3: four each gives 12 years and 1-in-2.2. "
        "Each zone on its own therefore activates about once in nine years. Zones mostly activate in different "
        "years, so the individual rarity has to be close to four times the overall one.</p>",
        summary_table(s, thr),
        "<p class='fn'>Return periods are Weibull, (n + 1) / activations, over the calibration years with data for "
        "that zone. “Major-impact year”: at least 5 deaths or 5,000 people affected recorded in the zone "
        "that year; the base rate beside it is how often that happens anyway, which is the bar an activation has "
        "to beat. “Five worst years”: by people affected in the calibration period.</p>",
        "<h2>All zones, year by year</h2>",
        overview_table(tabs, years),
        "<p class='fn'>“No data”: CHIRPS-GEFS has no forecasts from 1 January to 4 October 2020, the gap between "
        "the GEFS v12 reforecast and the operational feed, so the rain-based triggers cannot be judged that year. "
        "Adjumani’s lake leg can, and activated. 2025 is shown but was not used to calibrate.</p>",
        "<p><strong>2007 activates nowhere,</strong> although it is the largest flood year in the record and a CERF "
        "year. Two zones came close — Karamoja’s Nakapiripirit reached a 1-in-32 level against its 1-in-35 bar, and "
        "the Teso gauge 1-in-8 against about 1-in-11 — while Adjumani reached 1-in-14 against 1-in-48 and Elgon’s "
        "forecast saw nothing unusual at all. 2007 was a long wet season, August to October, rather than one extreme "
        "week, which is what a 5-day peak cannot see. A longer accumulation window, alongside the 5-day one, is the "
        "obvious thing to test next.</p>",
    ]
    for z in ZONE_ORDER:
        what, lead = trigger_text(z, thr)
        zl = ZONES[z].label.split(" (")[0]
        parts += [
            f"<h2><span class='sw' style='background:{bp.ZONE_COL[z]}'></span>{bp.e(zl)}</h2>",
            f"<p><strong>Activates when</strong> {what}. <strong>Lead time:</strong> {lead}.</p>",
            f"<p>{ZONE_NOTE[z].format(rp=round(float(thr[thr.zone == z].series_rp.iloc[0])))}</p>",
        ]
        cols = existing.get(z, [])
        if cols:
            parts += [
                "<p><strong>Alongside existing triggers.</strong></p>",
                compare_table(z, tabs[z], cols),
                existing_notes(cols),
            ]
        if EXISTING_NOTE.get(z):
            parts.append(f"<p class='fn'>{EXISTING_NOTE[z]}</p>")
        parts.append(zone_table(z, tabs[z], top_aff, top_d, cols))
    parts += [
        "<h2>Reading the tables</h2>",
        "<ul>"
        "<li><strong>Year’s peak</strong> is the rarest value the trigger indicator reached that year, as a return "
        "period on that indicator’s own record, so near-misses are visible: a 1-in-7 year sat just under a "
        "1-in-8.7 threshold.</li>"
        "<li><strong>Impact</strong> is shaded by magnitude on one scale for every zone. It is what was recorded, "
        "which is not the same as what happened: DesInventar ends in 2021, so later years rest on EM-DAT, press "
        "reports and IOM DTM rounds, and quiet recent years are partly quiet reporting. EM-DAT events spanning many "
        "districts are split evenly across them.</li>"
        "<li><strong>Existing triggers</strong> (grey columns) are other organisations’ triggers for the same "
        "zone, reproduced as closely as public data allows over the same years; each is described under its zone’s "
        "comparison table. They were designed for their own coverage and return periods, not for this budget, so "
        "the comparison is about which years each would have picked, not a ranking.</li>"
        "<li><strong>CERF</strong> marks the national flood allocations of October 2007 and January 2020 (for the "
        "late-2019 floods); they are not zone-specific.</li>"
        "</ul>",
        "<h2>What this draft does not settle</h2>",
        "<ul>"
        "<li>Teso needs the reforecast, and a third opinion on why the model and the satellite parted ways after 2013.</li>"
        "<li>Prolonged wet seasons such as 2007 need a longer accumulation window than 5 days.</li>"
        "<li>The rain-based triggers are weak at year level in every zone they are used in. They carry the lead time; "
        "whether they should sit behind an observational confirmation (the FloodScan backstop where it works) is the "
        "next design question.</li>"
        "<li>Karamoja per-district activations raise a funding question: all-in for the zone, or per district.</li>"
        "<li>Adjumani’s lake leg is calibrated on Lake Kyoga as a stand-in for Lake Albert; the operational trigger "
        "would read Albert directly.</li>"
        "</ul>",
        bp.FOOT.format(today=bp.TODAY).replace(
            "<code>pipeline/build_pages.py</code>",
            "<code>analysis/trigger_draft.py</code> and <code>pipeline/build_trigger_page.py</code>",
        ),
    ]
    return bp.add_heading_anchors("\n".join(parts))


def main() -> None:
    out = bp.PAGES / "triggers" / "index.html"
    out.parent.mkdir(exist_ok=True)
    out.write_text(page())
    print(f"wrote {out.relative_to(bp.ROOT)}")


if __name__ == "__main__":
    main()
