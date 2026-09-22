"""Build pages/triggers/index.html — the draft trigger mechanisms, restricted.

One page holds the whole trigger analysis: our four draft triggers, how the budget is shared
between zones, the year-by-year backtest per zone, and other organisations' existing
triggers reproduced alongside ours. Some of those come from partner documents that are not
published, so the page is built in plaintext into the gitignored site_private/ and only an
encrypted copy (staticrypt, team review password) is written to pages/triggers/.

Inputs:
  outputs/triggers/            analysis/trigger_draft.py      our drafts, per-zone years, allocations
  outputs/triggers/existing_public.csv   analysis/existing_triggers.py  published triggers (IFRC EAP)
  site_private/existing_private.csv      analysis/existing_triggers.py  unpublished partner triggers

  uv run python analysis/trigger_draft.py
  uv run python analysis/existing_triggers.py
  uv run python pipeline/build_trigger_page.py
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import build_pages as bp
from encrypt import encrypt_page

from src.constants import ZONES
from src.frameworks import load_private

TRIG = bp.OUT / "triggers"
PRIVATE = bp.ROOT / "site_private"
ZONE_ORDER = ["teso_kyoga", "elgon", "karamoja", "adjumani"]
EXT_COL = "#5b5b5b"  # existing (other organisations') triggers: one neutral colour
SHORT = {"teso_kyoga": "Teso", "elgon": "Elgon", "karamoja": "Karamoja", "adjumani": "Adjumani"}


# --- small formatting helpers --------------------------------------------------------------


def ramp(t: float, lo=(253, 236, 230), hi=(165, 15, 21)) -> str:
    """Sequential light-to-dark red for impact magnitude, t in [0, 1]."""
    t = max(0.0, min(1.0, t))
    return "#" + "".join(f"{round(a + (b - a) * t):02x}" for a, b in zip(lo, hi, strict=True))


def impact_cell(v: float, top: float, floor: float) -> str:
    """Log shading from `floor` (palest) to the largest value in any zone (darkest). EM-DAT
    figures are split evenly across the districts an event names, so values can be fractional;
    anything that rounds to zero is shown as nothing recorded."""
    if pd.isna(v) or round(v) <= 0:
        return "<td class='num'></td>"
    t = (math.log10(max(v, floor)) - math.log10(floor)) / (math.log10(top) - math.log10(floor))
    t = 0.08 + 0.92 * t
    fg = "#fff" if t > 0.55 else "#1a1a1a"
    return f"<td class='num' style='background:{ramp(t)};color:{fg}'>{v:,.0f}</td>"


def rp_txt(rp: float) -> str:
    return f"1-in-{rp:.0f}" if rp >= 10 else f"1-in-{rp:.1f}"


def years_txt(years) -> str:
    ys = sorted(years, reverse=True)
    if not ys:
        return "no year"
    return ", ".join(str(y) for y in ys[:-1]) + (" and " if len(ys) > 1 else "") + str(ys[-1])


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


# --- inputs --------------------------------------------------------------------------------


class Inputs:
    def __init__(self):
        self.s = pd.read_csv(TRIG / "summary.csv").set_index("zone")
        self.thr = pd.read_csv(TRIG / "thresholds.csv")
        self.alloc = pd.read_csv(TRIG / "allocations.csv")
        self.tabs = {z: pd.read_csv(TRIG / f"{z}.csv").set_index("year") for z in ZONE_ORDER}
        self.existing = merge_existing(
            load_existing(TRIG / "existing_public.csv"),
            load_existing(PRIVATE / "existing_private.csv"),
        )
        self.top_aff = max(float(t.affected.max()) for t in self.tabs.values())
        self.top_d = max(float(t.deaths.max()) for t in self.tabs.values())
        # narrative about unpublished partner triggers: gitignored config, never this source
        self.ptext = load_private().get("trigger_page_text", {})

    def series_rp(self, z: str, leg: str | None = None) -> float:
        t = self.thr[self.thr.zone == z]
        if leg:
            t = t[t.leg == leg]
        return float(t.series_rp.iloc[0])

    def activated(self, z: str) -> list[int]:
        t = self.tabs[z]
        return sorted(t[t.activated & t.in_calibration].index, reverse=True)


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


# --- tables --------------------------------------------------------------------------------


def trigger_text(z: str, inp: Inputs) -> tuple[str, str]:
    """Plain description of the trigger and its lead time."""
    t = inp.thr[inp.thr.zone == z].set_index("series")
    if z == "teso_kyoga":
        return (
            f"GloFAS daily discharge at G5196 (Akokoro) reaches <strong>{t.threshold.iloc[0]:,.0f} m³/s</strong>, "
            "in model space (the model runs about 1.7× wet, so this is not a gauged flow)",
            "3–14 days once run on the forecast; <strong>none in this backtest</strong>, which uses the reanalysis",
        )
    if z == "elgon":
        return (
            f"the 5-day forecast rainfall, averaged over all 15 districts, reaches <strong>{t.threshold.iloc[0]:,.0f} mm</strong>",
            "1–5 days",
        )
    rain = t[t.leg != "lake"] if "leg" in t else t
    rain = rain.drop(index="Kyoga rise", errors="ignore")
    rain_rp = float(rain.series_rp.iloc[0])
    rain_txt = (
        f"the 5-day forecast rainfall in any one district reaches that district’s own {rp_txt(rain_rp)}-year "
        f"level (<strong>{rain.threshold.min():,.0f}–{rain.threshold.max():,.0f} mm</strong> depending on the district)"
    )
    if z == "karamoja":
        return rain_txt, "1–5 days"
    lake = t.loc["Kyoga rise"]
    return (
        f"<em>either</em> Lake Kyoga rises <strong>{lake.threshold:.2f} m</strong> over 180 days (a {rp_txt(lake.series_rp)}-"
        f"year rise; the Nile high-stand leg) <em>or</em> {rain_txt}",
        "months for the lake leg; 1–5 days for the rain leg",
    )


def summary_table(inp: Inputs) -> str:
    rows = []
    for z in ZONE_ORDER:
        r = inp.s.loc[z]
        what, lead = trigger_text(z, inp)
        rows.append(
            "<tr>"
            f"<td class='zn'><span class='sw' style='background:{bp.ZONE_COL[z]}'></span><strong>{SHORT[z]}</strong></td>"
            f"<td>{what[0].upper() + what[1:]}</td><td>{lead}</td>"
            f"<td class='num'>{r.weight:.0%}</td>"
            f"<td class='num'><strong>{rp_txt(r.design_rp)}</strong></td>"
            f"<td class='num'>{int(r.activation_years)} of {int(r.years_with_data)}"
            f"<span class='fn'>{years_txt(inp.activated(z))}</span></td>"
            f"<td class='num'>{int(r.worst5_caught)} of 5</td>"
            f"<td class='num'>{int(r.activations_in_major_years)} of {int(r.activation_years)}"
            f"<span class='fn'>base rate {r.base_rate_major:.0%}</span></td>"
            "</tr>"
        )
    head = (
        "<tr><th>Zone</th><th>Activates when</th><th>Lead time</th><th>Share of people affected</th>"
        "<th>Design return period</th><th>Activation years in the backtest</th><th>Five worst years caught</th>"
        "<th>Activations in a major-impact year</th></tr>"
    )
    return f"<div class='tw trig-sum'><table><thead>{head}</thead><tbody>{''.join(rows)}</tbody></table></div>"


def allocation_table(inp: Inputs) -> str:
    a = inp.alloc
    order = [
        "equal shares",
        "people affected",
        "people affected, 2007 required",
        "half equal, half people affected",
        "deaths",
    ]
    rows = []
    for z in ZONE_ORDER:
        cells = []
        for name in order:
            r = a[(a.allocation == name) & (a.zone == z)].iloc[0]
            bold = name == inp.s.allocation.iloc[0]
            txt = f"{r.weight:.0%} · {rp_txt(r.design_rp)} · {int(r.activation_years)} yr"
            cells.append(f"<td class='num'>{'<strong>' + txt + '</strong>' if bold else txt}</td>")
        rows.append(
            f"<tr><td><span class='sw' style='background:{bp.ZONE_COL[z]}'></span>{SHORT[z]}</td>{''.join(cells)}</tr>"
        )
    over = "".join(
        f"<td class='num'>{int(a[a.allocation == n].overall_years.iloc[0])} yr · "
        f"{rp_txt(a[a.allocation == n].overall_rp.iloc[0])}</td>"
        for n in order
    )
    rows.append(f"<tr class='tot'><td>Any zone</td>{over}</tr>")
    head = "<tr><th>Zone</th>" + "".join(f"<th>Shared by {n}</th>" for n in order) + "</tr>"
    return f"<div class='tw trig-alloc'><table><thead>{head}</thead><tbody>{''.join(rows)}</tbody></table></div>"


def overview_table(inp: Inputs, years: list[int]) -> str:
    rows = []
    for y in years:
        cells, anyz = [], False
        for z in ZONE_ORDER:
            r = inp.tabs[z].loc[y]
            if not r.data:
                cells.append("<td class='nodata'>no data</td>")
            elif r.activated:
                anyz = True
                cells.append(f"<td class='act' style='background:{bp.ZONE_COL[z]}'>activated</td>")
            else:
                cells.append("<td></td>")
        cerf = inp.tabs["teso_kyoga"].loc[y].cerf
        rows.append(
            f"<tr><td class='yr'>{y}</td>{''.join(cells)}"
            f"<td class='any'>{'●' if anyz else ''}</td>"
            f"<td class='src'>{bp.e(cerf) if isinstance(cerf, str) else ''}</td></tr>"
        )
    head = (
        "<tr><th>Year</th>"
        + "".join(f"<th>{SHORT[z]}</th>" for z in ZONE_ORDER)
        + "<th>Any zone</th><th>CERF flood allocation (national)</th></tr>"
    )
    return f"<div class='tw trig-over'><table><thead>{head}</thead><tbody>{''.join(rows)}</tbody></table></div>"


def compare_table(z: str, tab: pd.DataFrame, cols) -> str:
    """Our draft and each existing trigger over the same calibration years."""
    items = [("Our draft", tab.activated, tab.data, bp.ZONE_COL[z])]
    items += [(short, h.activated, h.data, EXT_COL) for short, _, h in cols]
    base = tab[tab.in_calibration].major.mean()
    rows = []
    for name, act, dat, col in items:
        r = rates(act, dat, tab)
        rp = rp_txt(r["rp"]) if r["n"] else "never"
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


def zone_table(z: str, inp: Inputs, cols=()) -> str:
    tab = inp.tabs[z]
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
            peak = rp_txt(r.peak_rp) if r.peak_rp >= 2 else "below 1-in-2"
            if isinstance(r.peak_where, str) and z in ("karamoja", "adjumani"):
                peak += f"<span class='fn'>{bp.e(r.peak_where)}</span>"
        else:
            peak = ""
        src = r.sources if isinstance(r.sources, str) else ""
        yr = f"{y}" + ("" if r.in_calibration else "<span class='fn'>not in calibration</span>")
        rows.append(
            f"<tr><td class='yr'>{yr}</td>{act}<td class='num'>{peak}</td>"
            + "".join(existing_cell(h, y) for _, _, h in cols)
            + f"{impact_cell(r.affected, inp.top_aff, 500)}{impact_cell(r.deaths, inp.top_d, 1)}"
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


# --- narrative -----------------------------------------------------------------------------


def near_miss_2007(inp: Inputs) -> str:
    """Where each zone stood in 2007 against its own threshold rarity, written from the data."""
    bits, fired = [], []
    for z in ZONE_ORDER:
        r = inp.tabs[z].loc[2007]
        if r.activated:
            fired.append(SHORT[z])
            continue
        leg = (
            "lake"
            if (z == "adjumani" and r.peak_where == "Kyoga rise")
            else ("rain" if z == "adjumani" else None)
        )
        bar = inp.series_rp(z, leg)
        where = f" ({r.peak_where})" if z in ("karamoja", "adjumani") else ""
        bits.append(f"{SHORT[z]} reached {rp_txt(r.peak_rp)}{where} against a {rp_txt(bar)} bar")
    if fired:
        return f"<p><strong>2007</strong>, the largest flood year on record and a CERF year, activates in {', '.join(fired)}.</p>"
    return (
        "<p><strong>2007 activates nowhere,</strong> although it is the largest flood year in the record and a CERF "
        f"year: {'; '.join(bits)}. 2007 was a long wet season, August to October, rather than one extreme week, which "
        "a 5-day peak cannot see. A longer accumulation window alongside the 5-day one is the obvious thing to test.</p>"
    )


def zone_note(z: str, inp: Inputs) -> str:
    """The zone's narrative. Sentences about unpublished partner triggers are not kept in this
    (public) source: they come from the gitignored config and are appended when present."""
    base = _zone_note(z, inp)
    extra = inp.ptext.get(z, "")
    return f"{base} {extra}".strip()


def teso_ifrc_sentence(inp: Inputs) -> str:
    """Whether our Teso draft and the IFRC stand-in at the same point pick the same years."""
    ours = set(inp.activated("teso_kyoga"))
    for short, _, h in inp.existing.get("teso_kyoga", []):
        if short.startswith("IFRC"):
            cal = h[
                h.index.isin(inp.tabs["teso_kyoga"][inp.tabs["teso_kyoga"].in_calibration].index)
            ]
            if set(cal[cal.activated & cal.data].index) == ours:
                return (
                    " At this share it activates in exactly the same years as the IFRC stand-in at the same point "
                    "— in effect the IFRC/URCS trigger, as the country team asked for alignment."
                )
    return ""


def _zone_note(z: str, inp: Inputs) -> str:
    act = inp.activated(z)
    if z == "teso_kyoga":
        return (
            "Aligned with the IFRC/URCS early action protocol’s instrument — GloFAS at a reporting point — on "
            "the one point in the sub-region that passes both skill checks, as the country team asked. The reanalysis "
            f"stands in for the forecast until the reforecast download finishes, so this is an upper bound. Teso "
            f"carries the requirement to catch 2007 (see How the budget is shared), which sets it at "
            f"{rp_txt(inp.s.loc[z].design_rp)}; it activates in {years_txt(act)}, "
            f"{int(inp.s.loc[z].worst5_caught)} of them among Teso’s five worst years. The two that are not, 2020 and "
            "2013, are the known weakness: they are the model’s biggest years but ordinary ones on the satellite "
            "record, because G5196 tracks observed flooding well in 2006–2013 and poorly since. That needs a third "
            "opinion — a DWRM gauge or Google Flood Hub — before a Teso trigger is proposed."
            + teso_ifrc_sentence(inp)
        )
    if z == "elgon":
        return (
            "One zone-wide trigger: every lowland flood year in the record is also a slope flood year, and the forecast "
            "moves together across the 15 districts (median rank correlation of annual peaks 0.74). Elgon carries "
            "nearly half the recorded people affected and three quarters of the deaths, so it has the largest weight; "
            f"after Teso takes on 2007 it sits at {rp_txt(inp.s.loc[z].design_rp)} and activates in {years_txt(act)}. "
            "Some impact is recorded in Elgon every year, so the "
            "useful test is whether activations land in the worst years: 2019 (a CERF year) and 2018 do; 2022, 2011 and "
            "2007 are missed."
        )
    if z == "karamoja":
        return (
            "Per district: each of the nine districts is held to the same rarity, and the zone activates when any one "
            f"reaches it. Karamoja’s share of recorded people affected is the smallest of the four, and nine "
            f"districts give nine chances, so each district is held to about a {rp_txt(inp.series_rp(z))}-year level "
            f"and the zone activates in {years_txt(act)} only. Whether an activation in one district releases the whole "
            "Karamoja envelope or that district’s share is a funding decision; this draft assumes all-in."
        )
    return (
        "Two legs, because the record shows two flood regimes. Nile high-stand floods — 2020 above all, when "
        "the Albert Nile rose from June and displaced 123,000 people across Pakwach, Obongi and Adjumani, and "
        "earlier 2002, 2004, late 2019 and 2024 — are covered by Lake Kyoga’s rise over six months: Kyoga "
        "tracks Lake Albert at r = 0.96 month to month and has a record from 1992, where Albert’s starts in 2016. "
        "A threshold on the lake level itself would not work: the lakes rose about 3 m in 2020 and have stayed up, "
        "so it would activate every year since. Tributary and settlement flash floods, most of the record, are "
        "covered by the rain forecast per district. Each leg gets half the zone’s share and is calibrated on "
        "its own, so the single lake series is not outvoted by six rain series (an earlier version did that and lost "
        f"2020). The zone activates in {years_txt(act)}. The rain-leg year, 2000, has nothing recorded; the West "
        "Nile record is thin before 2004, so treat it as unverified rather than a false alarm. The IFRC EAP lists "
        "Moyo, but there is no GloFAS reporting point on the Albert Nile to reproduce it with."
    )


def must_catch_text(inp: Inputs) -> str:
    """The must-catch requirement and what each zone would have cost, from the options table."""
    path = TRIG / "must_catch_2007.csv"
    if not path.exists():
        return ""
    o = pd.read_csv(path).set_index("zone")
    rows = []
    for z in ZONE_ORDER:
        r = o.loc[z]
        if not r.can_catch:
            rows.append(
                f"<tr><td>{SHORT[z]}</td><td colspan='3'>cannot catch 2007 at any level</td></tr>"
            )
            continue
        chosen = abs(inp.s.loc[z].design_rp - r.needed_rp) < 0.05
        cell = lambda x, c=chosen: f"<strong>{x}</strong>" if c else x
        rows.append(
            f"<tr><td>{cell(SHORT[z])}</td><td class='num'>{cell(rp_txt(r.needed_rp))}</td>"
            f"<td class='num'>{cell(rp_txt(r.overall_rp))}</td><td class='num'>{cell(int(r.worst5_caught))} of 20</td></tr>"
        )
    head = (
        "<tr><th>Catch 2007 with</th><th>That zone at least</th><th>Overall return period</th>"
        "<th>Zone-worst years caught, all zones</th></tr>"
    )
    return (
        "<p><strong>A must-catch year.</strong> Shared by people affected alone, the mechanism missed 2007 in every "
        "zone \u2014 the largest flood year on record and a CERF year. The design therefore requires it, as a "
        "trigger specification would: for each zone, the smallest share that would make that zone activate in "
        "2007 is found, the other zones are re-scaled to keep the overall return period on target, and the "
        "option that catches the most of the zones\u2019 five worst years overall is kept. Teso wins clearly; "
        "Elgon could only catch 2007 by activating nearly every year, and Adjumani would starve every other zone.</p>"
        f"<div class='tw trig-alloc'><table><thead>{head}</thead><tbody>{''.join(rows)}</tbody></table></div>"
    )


def key_points(inp: Inputs) -> str:
    s = inp.s
    over_rp = float(s.overall_rp.iloc[0])
    over_n = int(s.overall_years.iloc[0])
    cal = s.calibration.iloc[0]
    items = [
        f"Four triggers, one per zone, each all-in. Across the four, <strong>{over_n} of the {cal} years would have "
        f"seen at least one activation — an overall return period of {rp_txt(over_rp)}</strong>, the closest the "
        "backtest allows to the 1-in-3 target.",
        "The budget is shared in proportion to each zone\u2019s recorded <strong>people affected</strong>, with one "
        "requirement on top: the mechanism must catch <strong>2007</strong>, the largest flood year on record and a "
        "CERF year, which the plain tilt missed everywhere. Teso is the cheapest zone to catch it with, so it runs at "
        f"{rp_txt(s.loc['teso_kyoga'].design_rp)}, Elgon at {rp_txt(s.loc['elgon'].design_rp)}, Adjumani at "
        f"{rp_txt(s.loc['adjumani'].design_rp)} and Karamoja at {rp_txt(s.loc['karamoja'].design_rp)}. Other ways "
        "of sharing the budget are compared below.",
        f"Across the four, {int(s.worst5_caught.sum())} of the zones\u2019 20 worst years are caught (Teso "
        f"{int(s.loc['teso_kyoga'].worst5_caught)}, Elgon {int(s.loc['elgon'].worst5_caught)}, Adjumani "
        f"{int(s.loc['adjumani'].worst5_caught)}, Karamoja {int(s.loc['karamoja'].worst5_caught)}), against 3 "
        "without the 2007 requirement. None of the four separates bad years from ordinary ones convincingly; "
        "Teso\u2019s two false years, 2020 and 2013, are the model\u2019s big years since its record and the "
        "satellite\u2019s parted ways after 2013.",
        "Tuning to one year is a choice made in the open: 2007 is written into the design as a must-catch event, "
        "the way a trigger specification would list it, and the table below shows what each zone would have cost.",
        "Existing triggers are reproduced alongside ours, where the data allows.",
    ]
    if inp.ptext.get("key_point"):
        items[-1] = inp.ptext["key_point"]
    return "<ul class='keypts'>" + "".join(f"<li>{x}</li>" for x in items) + "</ul>"


def page(inp: Inputs) -> str:
    years = sorted(inp.tabs["teso_kyoga"].index, reverse=True)
    cal = inp.s.calibration.iloc[0]
    parts = [
        bp.HEAD.format(
            v=bp.ASSET_VERSION,
            title="Draft triggers",
            sub="One trigger per zone, the budget shared by historical impact, backtested year by year against the "
            "recorded impact and alongside the triggers other organisations already run. First draft for discussion.",
        ),
        "<p class='callout'><strong>Restricted.</strong> This page includes material from partner plans that are not "
        "published (FAO’s draft Mt Elgon plan, the CRS/Caritas Tororo protocol, DRC’s Karamoja plan). Please "
        f"do not forward it outside the team. <strong>Status:</strong> first draft, calibrated on {cal}; Teso runs on "
        "the GloFAS reanalysis until the reforecast is complete. Nothing here is endorsed.</p>",
        "<h2>In brief</h2>",
        key_points(inp),
        "<h2>The four triggers</h2>",
        summary_table(inp),
        "<p class='fn'>Design return period: the rarity each zone’s threshold is set to. Activation years: what the "
        "threshold would have done over the calibration years with data for that zone. “Major-impact year”: "
        "at least 5 deaths or 5,000 people affected recorded in the zone that year; the base rate beside it is how "
        "often that happens anyway, which is the bar an activation has to beat. “Five worst years”: by "
        "people affected in the calibration period.</p>",
        "<h2>How the budget is shared</h2>",
        "<p>The target is set on the <strong>overall</strong> return period — the years in which at least one "
        "zone activates — at about 1-in-3. That budget is then shared between the zones in proportion to the "
        "people affected recorded in each over the calibration years, so a zone with more historical impact is more "
        "likely to activate. Concretely, each zone’s annual activation probability is set proportional to its "
        "share, and the shares are scaled together until the backtest’s overall return period is as close to 3 "
        f"as whole years allow: {int(inp.s.overall_years.iloc[0])} activation years out of "
        f"{int(inp.s.years_with_data.max())} is {rp_txt(float(inp.s.overall_rp.iloc[0]))}. Thresholds for "
        "fractional targets are interpolated between the backtest’s order statistics, so they do not jump in "
        "whole-year steps.</p>",
        "<p>People affected was chosen over deaths because it is what an anticipatory envelope is sized on, and "
        "because a deaths weighting is dominated by the Elgon landslides — three quarters of all recorded deaths "
        "— and would leave Adjumani, with almost none, effectively never activating. The table shows the "
        "alternatives: each cell is the zone’s share, its design return period and its activation years in "
        "the backtest.</p>",
        must_catch_text(inp),
        allocation_table(inp),
        "<p class='fn'>Shares use the zone-year impact record described under Data and methods. They are recorded "
        "impact, so they inherit its gaps: West Nile is thinly recorded before 2004, and years after 2021 rest on "
        "EM-DAT, press and IOM DTM once DesInventar stops.</p>",
        "<h2>All zones, year by year</h2>",
        overview_table(inp, years),
        "<p class='fn'>“No data”: CHIRPS-GEFS has no forecasts from 1 January to 4 October 2020, the gap between "
        "the GEFS v12 reforecast and the operational feed, so the rain-based triggers cannot be judged that year; "
        "Adjumani’s lake leg can.</p>",
        near_miss_2007(inp),
    ]
    for z in ZONE_ORDER:
        what, lead = trigger_text(z, inp)
        cols = inp.existing.get(z, [])
        parts += [
            f"<h2><span class='sw' style='background:{bp.ZONE_COL[z]}'></span>{bp.e(ZONES[z].label.split(' (')[0])}</h2>",
            f"<p><strong>Activates when</strong> {what}. <strong>Lead time:</strong> {lead}. "
            f"<strong>Design return period:</strong> {rp_txt(inp.s.loc[z].design_rp)}.</p>",
            f"<p>{zone_note(z, inp)}</p>",
        ]
        if cols:
            parts += [
                "<p><strong>Alongside existing triggers</strong> (grey), over the same years:</p>",
                compare_table(z, inp.tabs[z], cols),
                existing_notes(cols),
            ]
        parts.append(zone_table(z, inp, cols))
    parts += [
        "<h2>Reading the tables</h2>",
        "<ul>"
        "<li><strong>Our draft</strong> is shaded in the zone’s colour with the first activation date, and the "
        "district or leg that activated where a zone has several.</li>"
        "<li><strong>Year’s peak</strong> is the rarest value the trigger indicator reached that year, as a return "
        "period on that indicator’s own record, so near-misses are visible.</li>"
        "<li><strong>Existing triggers</strong> (grey) are other organisations’ triggers for the zone, reproduced as "
        "closely as the data allows over the same years; each is described under its zone’s comparison table, "
        "including what could not be reproduced. They were designed for their own coverage and budgets, so the "
        "comparison is about which years each would have picked, not a ranking.</li>"
        "<li><strong>Impact</strong> is shaded by magnitude on one scale for every zone. It is what was recorded, "
        "which is not the same as what happened.</li>"
        "<li><strong>CERF</strong> marks the national flood allocations of October 2007 and January 2020 (for the "
        "late-2019 floods); they are not zone-specific.</li>"
        "</ul>",
        "<h2>Data and methods</h2>",
        "<ul>"
        "<li><strong>GloFAS v4</strong> river discharge, reanalysis 1999–2024 for the Uganda box (EWDS), at G5196 "
        "“Akokorio at Uganda” (the local Akokoro river, 33.875°E 1.775°N) and G5220 Manafwa at Butaleja. "
        "Thresholds are in model space: the model runs about 1.7× wet at G5196.</li>"
        "<li><strong>CHIRPS-GEFS v12</strong> 5-day rainfall forecasts, 2000 to July 2026, as district means (and "
        "the wettest pixel where stated). The CHC archive has no issues for January–September 2020.</li>"
        "<li><strong>IMERG</strong> daily rainfall for the observed-rain partner triggers, with an antecedent "
        "precipitation index (k = 0.9) standing in for soil moisture.</li>"
        "<li><strong>Lake Kyoga</strong> altimetry (NASA Global Water Monitor, 10-day since 1992), as a stand-in for "
        "Lake Albert (from 2016 only).</li>"
        "<li><strong>Impact</strong>: EM-DAT, DesInventar (to 2021), press and ReliefWeb reports curated in the repo, "
        "and IOM DTM rounds from the country team, matched to districts and summed per zone and year. Events naming "
        "several districts are split evenly across them.</li>"
        "<li><strong>Calibration</strong>: each series’ annual maxima get a Gumbel fit; a zone’s statistic for a "
        "year is the rarest value any of its series reached on its own fit, so districts with wet and dry climates "
        "are held to the same rarity. Thresholds are set on that statistic to meet the zone’s share (above), and "
        "reported back as return levels per series. Return periods quoted for the backtest are Weibull, (n + 1) / "
        "activations.</li>"
        "</ul>",
        "<h2>Open questions and next steps</h2>",
        "<ul>"
        "<li><strong>Teso:</strong> run on the GloFAS reforecast (download in progress), and get a third opinion — "
        "a DWRM gauge or Flood Hub — on why the model and the satellite record parted ways after 2013.</li>"
        "<li><strong>Longer windows:</strong> test a 15- or 30-day accumulation alongside the 5-day one for prolonged "
        "seasons such as 2007.</li>"
        "<li><strong>Observational confirmation:</strong> whether the rain-forecast triggers should sit behind the "
        "FloodScan backstop where it works (Teso, the Elgon lowlands, four Elgon slope districts, four in Karamoja).</li>"
        "<li><strong>Karamoja funding:</strong> all-in for the zone, or per district.</li>"
        "<li><strong>Adjumani:</strong> read Lake Albert directly once its record is long enough; ask FAO/OPM about the "
        "new station data on the Nile.</li>"
        + inp.ptext.get("next_step", "")
        + "<li><strong>Budget sharing:</strong> people affected is a choice; the allocation table shows the alternatives.</li>"
        "</ul>",
        "<h2>Reproducing this page</h2>",
        "<p>In <code>OCHA-DAP/ds-aa-uga-flooding</code>, with the partner config in place (see the README):</p>"
        "<pre>uv run python analysis/trigger_draft.py\nuv run python analysis/existing_triggers.py\n"
        "uv run python pipeline/build_trigger_page.py</pre>",
        bp.FOOT.format(today=bp.TODAY).replace(
            "<code>pipeline/build_pages.py</code>",
            "<code>analysis/trigger_draft.py</code>, <code>analysis/existing_triggers.py</code> and "
            "<code>pipeline/build_trigger_page.py</code>",
        ),
    ]
    return bp.add_heading_anchors("\n".join(parts))


def main() -> None:
    inp = Inputs()
    plain = PRIVATE / "triggers.html"
    plain.parent.mkdir(exist_ok=True)
    plain.write_text(page(inp))
    encrypt_page(
        plain,
        bp.PAGES / "triggers" / "index.html",
        title="Uganda flood AA — draft triggers",
        instructions="Restricted: includes unpublished partner material. Password shared internally.",
        probes=[v[:40] for v in inp.ptext.values()]
        + ["How the budget is shared", "Alongside existing triggers"],
    )


if __name__ == "__main__":
    main()
