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
        self.tabs = {z: pd.read_csv(TRIG / f"{z}.csv").set_index("season") for z in ZONE_ORDER}
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

    def activated(self, z: str) -> list[str]:
        t = self.tabs[z]
        return list(t[t.activated & t.in_calibration].sort_index(ascending=False).label)


def load_existing(path) -> dict[str, list[tuple[str, str, pd.DataFrame]]]:
    """Existing triggers per zone as (short name, description, per-year frame)."""
    out: dict[str, list[tuple[str, str, pd.DataFrame]]] = {}
    if not Path(path).exists():
        return out
    df = pd.read_csv(path)
    for z, g in df.groupby("zone", sort=False):
        out[z] = [
            (h.short.iloc[0], h.label.iloc[0], h.set_index("season"))
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


def rates(act: pd.Series, dat: pd.Series, caught: pd.Series, tab: pd.DataFrame) -> dict:
    """Scores for any trigger over the calibration seasons, judged on the same events as ours:
    activations, how many caught a major event, false alarms, and major seasons missed."""
    cal = tab[tab.in_calibration]
    a = act.reindex(cal.index).fillna(False).astype(bool)
    d = dat.reindex(cal.index).fillna(False).astype(bool)
    c = caught.reindex(cal.index).fillna(False).astype(bool)
    n = int(d.sum())
    acts, hits = int((a & d).sum()), int((c & d).sum())
    major = cal.major & d
    return dict(
        n=n,
        acts=acts,
        caught=hits,
        false=acts - hits,
        missed=int((major & ~c).sum()),
        major=int(major.sum()),
        rp=(n + 1) / acts if acts else float("nan"),
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
            f"<td class='num'>{int(r.major_seasons)} of {int(r.seasons_with_data)}"
            f"<span class='fn'>{rp_txt(r.major_rp)}</span></td>"
            f"<td class='num'><strong>{rp_txt(r.design_rp)}</strong>"
            + (f"<span class='fn'>raised from {rp_txt(r.frequency_rp)}</span>" if r.raised else "")
            + "</td>"
            f"<td class='num'>{int(r.activations)}<span class='fn'>{bp.e(r.activated_seasons)}</span></td>"
            f"<td class='num'>{int(r.caught)}</td><td class='num'>{int(r.false_alarms)}</td>"
            f"<td class='num'>{int(r.missed)} of {int(r.major_seasons)}</td>"
            f"<td class='num'>{'' if pd.isna(r.median_lead_days) else f'{r.median_lead_days:+.0f} d'}</td>"
            "</tr>"
        )
    head = (
        "<tr><th>Zone</th><th>Activates when</th><th>Lead time</th><th>Major-impact seasons</th>"
        "<th>Design return period</th><th>Activations</th><th>Caught</th><th>False alarms</th>"
        "<th>Missed</th><th>Median lead</th></tr>"
    )
    return f"<div class='tw trig-sum'><table><thead>{head}</thead><tbody>{''.join(rows)}</tbody></table></div>"


MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
WINDOW_MONTHS = (10, 11, 12)


def month_heat(v: float, top: float) -> str:
    if top <= 0 or v <= 0:
        return "<td class='num mo'></td>"
    t = 0.08 + 0.92 * (v / top)
    fg = "#fff" if t > 0.55 else "#1a1a1a"
    return f"<td class='num mo' style='background:{ramp(t)};color:{fg}'>{v / top * 100 * (top / max(top, 1e-9)):.0f}</td>"


def months_table(inp: Inputs) -> str:
    """When floods actually happen in each zone, against when the trigger would fire if it ran
    all year. Each row is a share of its own total, in per cent."""
    path = TRIG / "monthly_profile.csv"
    if not path.exists():
        return ""
    d = pd.read_csv(path)
    rows = []
    for z in ZONE_ORDER:
        g = d[d.zone == z].set_index("month").reindex(range(1, 13)).fillna(0)
        for lbl, col in (
            ("flood events", "events"),
            ("people affected", "affected"),
            ("trigger would fire", "activations_all_year"),
        ):
            tot = g[col].sum()
            share = (g[col] / tot * 100) if tot else g[col] * 0
            cells = "".join(
                f"<td class='num mo{' win' if m in WINDOW_MONTHS else ''}' "
                f"style='background:{ramp(0.08 + 0.92 * (share[m] / max(share.max(), 1e-9)))};"
                f"color:{'#fff' if share[m] / max(share.max(), 1e-9) > 0.55 else '#1a1a1a'}'>"
                f"{share[m]:.0f}</td>"
                if share[m] >= 0.5
                else f"<td class='num mo{' win' if m in WINDOW_MONTHS else ''}'></td>"
                for m in range(1, 13)
            )
            ond = share[list(WINDOW_MONTHS)].sum()
            first = (
                f"<td class='zn' rowspan='3'><span class='sw' style='background:{bp.ZONE_COL[z]}'></span>{SHORT[z]}</td>"
                if col == "events"
                else ""
            )
            rows.append(
                f"<tr>{first}<td class='src'>{lbl}</td>{cells}<td class='num'><strong>{ond:.0f} %</strong></td></tr>"
            )
    head = (
        "<tr><th>Zone</th><th></th>"
        + "".join(
            f"<th class='mo{' win' if i + 1 in WINDOW_MONTHS else ''}'>{m}</th>"
            for i, m in enumerate(MONTHS)
        )
        + "<th>in Oct\u2013Dec</th></tr>"
    )
    return f"<div class='tw trig-months'><table><thead>{head}</thead><tbody>{''.join(rows)}</tbody></table></div>"


def window_table(inp: Inputs) -> str:
    """Catches against matching window, beside what random timing would score."""
    path = TRIG / "window_sensitivity.csv"
    if not path.exists():
        return ""
    d = pd.read_csv(path)
    g = d.groupby("window")[["caught", "chance"]].sum()
    head = "<tr><th></th>" + "".join(f"<th>{int(w)} d</th>" for w in g.index) + "</tr>"
    r1 = "".join(f"<td class='num'>{int(v)}</td>" for v in g.caught)
    r2 = "".join(f"<td class='num'>{v:.1f}</td>" for v in g.chance)
    return (
        "<p><strong>How generous is the matching?</strong> An activation counts as catching a flood if the flood "
        "starts within the trigger\u2019s lead window \u2014 set at 30 days for the rain forecasts, 45 for GloFAS and "
        "150 for the lake leg, deliberately loose, because reported impact dates lag the flood and rain that falls "
        "inside a forecast window can pool for days before it floods. Widening the window further barely finds any "
        "more floods, while it raises what sheer luck would score: below, the major events the four drafts catch at "
        "each window, against the average a trigger activating on random dates in the same seasons would catch.</p>"
        f"<div class='tw trig-alloc'><table><thead>{head}</thead><tbody>"
        f"<tr><td>Caught by the drafts</td>{r1}</tr><tr><td>Caught by random timing</td>{r2}</tr>"
        "</tbody></table></div>"
        "<p class='fn'>So the drafts do beat chance, and the gap does not close as the window widens \u2014 the low "
        "catch count is not an artefact of strict matching. At the chosen windows they catch 5 where random timing "
        "would catch about 2.6.</p>"
    )


def sensitivity_table(inp: Inputs) -> str:
    """Per zone, what each candidate return period would have done, with the chosen one first."""
    d = pd.read_csv(TRIG / "rp_sensitivity.csv")
    rps = sorted(d.rp.unique())
    rows = []
    for z in ZONE_ORDER:
        g = d[d.zone == z].set_index("rp")
        r0 = inp.s.loc[z]
        chosen = (
            f"<strong>{rp_txt(r0.design_rp)}: {int(r0.activations)} \u00b7 {int(r0.caught)} \u00b7 "
            f"{int(r0.missed)}</strong>"
        )
        cells = "".join(
            f"<td class='num'>{int(g.loc[rp].activations)} \u00b7 {int(g.loc[rp].caught)} \u00b7 "
            f"{int(g.loc[rp].missed)}</td>"
            for rp in rps
        )
        rows.append(
            f"<tr><td><span class='sw' style='background:{bp.ZONE_COL[z]}'></span>{SHORT[z]}</td>"
            f"<td class='num'>{chosen}</td>{cells}</tr>"
        )
    head = (
        "<tr><th>Zone</th><th>Chosen</th>"
        + "".join(f"<th>1-in-{rp:g}</th>" for rp in rps)
        + "</tr>"
    )
    return f"<div class='tw trig-alloc'><table><thead>{head}</thead><tbody>{''.join(rows)}</tbody></table></div>"


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
    """One row per season; a cell says "caught" where the activation matched a major event."""
    rows = []
    for y in years:
        cells, anyz = [], False
        for z in ZONE_ORDER:
            r = inp.tabs[z].loc[y]
            if not r.data:
                cells.append("<td class='nodata'>no data</td>")
            elif r.activated:
                anyz = True
                txt = "caught" if r.caught else "activated"
                cells.append(f"<td class='act' style='background:{bp.ZONE_COL[z]}'>{txt}</td>")
            else:
                cells.append("<td></td>")
        cerf = inp.tabs["teso_kyoga"].loc[y].cerf
        lbl = inp.tabs["teso_kyoga"].loc[y].label
        rows.append(
            f"<tr><td class='yr'>{lbl}</td>{''.join(cells)}"
            f"<td class='any'>{'●' if anyz else ''}</td>"
            f"<td class='src'>{bp.e(cerf) if isinstance(cerf, str) else ''}</td></tr>"
        )
    head = (
        "<tr><th>Season</th>"
        + "".join(f"<th>{SHORT[z]}</th>" for z in ZONE_ORDER)
        + "<th>Any zone</th><th>CERF flood allocation (national)</th></tr>"
    )
    return f"<div class='tw trig-over'><table><thead>{head}</thead><tbody>{''.join(rows)}</tbody></table></div>"


def compare_table(z: str, tab: pd.DataFrame, cols) -> str:
    """Our draft and each existing trigger over the same seasons, against the same events."""
    items = [("Our draft", tab.activated, tab.data, tab.caught, bp.ZONE_COL[z])]
    items += [(short, h.activated, h.data, h.caught, EXT_COL) for short, _, h in cols]
    rows = []
    for name, act, dat, caught, col in items:
        r = rates(act, dat, caught, tab)
        rp = rp_txt(r["rp"]) if r["acts"] else "never"
        rows.append(
            f"<tr><td><span class='sw' style='background:{col}'></span>{bp.e(name)}</td>"
            f"<td class='num'>{r['acts']} of {r['n']}</td><td class='num'><strong>{rp}</strong></td>"
            f"<td class='num'>{r['caught']}</td><td class='num'>{r['false']}</td>"
            f"<td class='num'>{r['missed']} of {r['major']}</td></tr>"
        )
    head = (
        "<tr><th>Trigger</th><th>Activations</th><th>Return period</th><th>Caught a major event</th>"
        "<th>False alarms</th><th>Major events missed</th></tr>"
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
        mark = (
            f"caught +{int(r.lead_days)} d"
            if r.caught and r.lead_days >= 0
            else ("caught, during" if r.caught else "no event")
        )
        return (
            f"<td class='act' style='background:{EXT_COL}'>activated"
            f"<span class='d'>{r.first_date} \u00b7 {mark}</span></td>"
        )
    return "<td></td>"


def zone_table(z: str, inp: Inputs, cols=()) -> str:
    tab = inp.tabs[z]
    rows = []
    for y, r in tab.sort_index(ascending=False).iterrows():
        if not r.data:
            act = "<td class='nodata'>no forecast data</td>"
        elif r.activated:
            via = r.via if isinstance(r.via, str) else ""
            via = (
                ""
                if via in ("GloFAS G5196", "zone-mean 5-day forecast")
                else f" \u00b7 {bp.e(via)}"
            )
            if r.caught:
                mark = (
                    f"caught +{int(r.lead_days)} d"
                    if r.lead_days >= 0
                    else f"caught, {abs(int(r.lead_days))} d into the flood"
                )
            elif isinstance(r.later_catch, str) and r.later_catch:
                mark = f"no event; a later activation ({r.later_catch[5:]}) would have caught +{int(r.later_lead)} d"
            else:
                mark = f"no major event within {int(r.window_days)} d"
            act = (
                f"<td class='act' style='background:{bp.ZONE_COL[z]}'>activated"
                f"<span class='d'>{r.first_date}{via}<br>{mark}</span></td>"
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
        lbl = f"{r.label}" + (
            "" if r.in_calibration else "<span class='fn'>not in calibration</span>"
        )
        rows.append(
            f"<tr><td class='yr'>{lbl}</td>{act}<td class='num'>{peak}</td>"
            + "".join(existing_cell(h, y) for _, _, h in cols)
            + f"{impact_cell(r.affected, inp.top_aff, 500)}{impact_cell(r.deaths, inp.top_d, 1)}"
            f"<td class='num'>{int(r.n_events) if r.n_events else ''}</td>"
            f"<td class='src'>{bp.e(source_labels(src))}</td>"
            f"<td class='src'>{bp.e(r.cerf) if isinstance(r.cerf, str) else ''}</td></tr>"
        )
    head = (
        "<tr><th>Season</th><th>Our draft</th><th>Season\u2019s peak</th>"
        + "".join(f"<th>{bp.e(short)}</th>" for short, _, _ in cols)
        + "<th>People affected</th><th>Deaths</th><th>Events recorded</th><th>Impact sources</th>"
        "<th>CERF</th></tr>"
    )
    return f"<div class='tw trig-zone'><table><thead>{head}</thead><tbody>{''.join(rows)}</tbody></table></div>"


# --- narrative -----------------------------------------------------------------------------


def season_2007(inp: Inputs) -> str:
    """What happened in the October-December window of 2007, the largest flood year on record."""
    bits = []
    for z in ZONE_ORDER:
        r = inp.tabs[z].loc[2007]
        if r.activated and r.caught:
            bits.append(f"{SHORT[z]} activated and caught it")
        elif r.activated:
            bits.append(f"{SHORT[z]} activated but matched no major event")
        else:
            leg = (
                "lake"
                if (z == "adjumani" and r.peak_where == "Kyoga rise")
                else ("rain" if z == "adjumani" else None)
            )
            bits.append(
                f"{SHORT[z]} did not activate ({rp_txt(r.peak_rp)} against a {rp_txt(inp.series_rp(z, leg))} bar)"
            )
    return (
        "<p><strong>October\u2013December 2007</strong>, the largest flood year on record and a CERF year: "
        + "; ".join(bits)
        + ". The 2007 floods ran from August to October \u2014 a long wet season rather than one extreme week, which "
        "is what a 5-day forecast peak can see. A longer accumulation window is the obvious thing to test.</p>"
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
    r = inp.s.loc[z]
    act, caught, missed = int(r.activations), int(r.caught), int(r.missed)
    rp, freq = rp_txt(r.design_rp), rp_txt(r.frequency_rp)
    raised = f" \u2014 raised from {freq} to shed false alarms" if r.raised else ""
    if z == "teso_kyoga":
        return (
            "Aligned with the IFRC/URCS early action protocol\u2019s instrument \u2014 GloFAS at a reporting point \u2014 "
            "on the one point in the sub-region that passes both skill checks, as the country team asked. The "
            "reanalysis stands in for the forecast until the reforecast download finishes, so this is an upper bound. "
            f"At {rp}{raised} it activates in {act} of the {int(r.seasons_with_data)} windows and catches {caught}: "
            "October 2007, the largest flood in the record, on the day. The other activation is October 2020, a "
            f"season with nothing recorded, and it misses {missed} of {int(r.major_seasons)} major windows. Teso\u2019s "
            "floods peak in August and September, so the October\u2013December window sees less than a third of its "
            "recorded impact, and the model\u2019s own peak is in August \u2014 before the window opens."
            + teso_ifrc_sentence(inp)
        )
    if z == "elgon":
        return (
            "One zone-wide trigger: every lowland flood year in the record is also a slope flood year, and the "
            "forecast moves together across the 15 districts. Elgon carries nearly half the recorded people affected "
            "and three quarters of the deaths, and it is the one zone whose trigger peaks inside the window. At "
            f"{rp}{raised} it activates in {act} windows, catches {caught} \u2014 November 2024, eight days before "
            f"the Bulambuli landslides \u2014 and misses {missed}. It cannot be raised further without losing that "
            "catch. Elgon\u2019s impact is concentrated in April to September, though, so the window holds only about "
            "a sixth of its recorded people affected: the Bududa landslides of 2010 and 2012 and the September 2011 "
            "floods are all outside it."
        )
    if z == "karamoja":
        return (
            "Per district: each of the nine districts is held to the same rarity, and the zone activates when any "
            f"one reaches it \u2014 about a {rp_txt(inp.series_rp(z))}-year level per district to keep the zone at "
            f"{rp}{raised}. It activates in {act} windows, catches {caught} and misses {missed}. Karamoja is the "
            "worst fit for this window of the four: its floods peak in May and August, its rain forecast peaks in "
            "April, and only a sixth of its recorded impact falls in October to December. Whether an activation in "
            "one district releases the whole Karamoja envelope or that district\u2019s share is a funding decision; "
            "this draft assumes all-in."
        )
    return (
        "Two legs, because the record shows two flood regimes. Nile high-stand floods \u2014 2020 above all, when the "
        "Albert Nile rose from June and displaced 123,000 people across Pakwach, Obongi and Adjumani \u2014 are "
        "covered by Lake Kyoga\u2019s rise over six months: Kyoga tracks Lake Albert at r = 0.96 month to month and "
        "has a record from 1992, where Albert\u2019s starts in 2016. A threshold on the lake level itself would not "
        "work: the lakes rose about 3 m in 2020 and have stayed up, so it would activate every year since. Tributary "
        "and settlement flash floods, most of the record, are covered by the rain forecast per district, each leg "
        f"taking half the zone\u2019s rate. At {rp}{raised} it activates in {act} windows and catches {caught}: 2020, "
        "where the lake leg was already over its threshold when the window opened, four months into the flood. That "
        "is the honest reading of a slow-onset leg in a window that starts in October \u2014 the signal was there in "
        f"June. It misses {missed}, and November is the zone\u2019s deadliest month, so this is the one zone whose "
        "impact the window fits at all well."
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
        cell = lambda x: x
        rows.append(
            f"<tr><td>{cell(SHORT[z])}</td><td class='num'>{cell(rp_txt(r.needed_rp))}</td>"
            f"<td class='num'>{cell(rp_txt(r.overall_rp))}</td><td class='num'>{cell(int(r.worst5_caught))} of 20</td></tr>"
        )
    head = (
        "<tr><th>Catch 2007 with</th><th>That zone at least</th><th>Overall return period</th>"
        "<th>Zone-worst years caught, all zones</th></tr>"
    )
    return (
        "<p><strong>Tried and not chosen: requiring 2007.</strong> 2007 \u2014 the largest flood year on record and a "
        "CERF year \u2014 activates in no zone (see below). One way to force it is to write it in as a must-catch year: "
        "for each zone, find the smallest share that would make that zone activate in 2007, re-scale the others to "
        "hold the overall return period, and keep the option that catches the most of the zones\u2019 worst years. "
        "Teso would be the cheapest, at about 1-in-6, but the others would then have to be much rarer \u2014 "
        "Karamoja about 1-in-34, Adjumani about 1-in-25 \u2014 which is too steep a price for one year. Elgon could "
        "only catch 2007 by activating nearly every year.</p>"
        f"<div class='tw trig-alloc'><table><thead>{head}</thead><tbody>{''.join(rows)}</tbody></table></div>"
    )


def key_points(inp: Inputs) -> str:
    s_ = inp.s
    cal = s_.calibration.iloc[0]
    tot_a, tot_c, tot_m, tot_major = (
        int(s_.activations.sum()),
        int(s_.caught.sum()),
        int(s_.missed.sum()),
        int(s_.major_seasons.sum()),
    )
    catches = []
    for z in ZONE_ORDER:
        t = inp.tabs[z]
        for _y, r in t[t.in_calibration & t.caught].sort_index(ascending=False).iterrows():
            catches.append(f"{SHORT[z]} {r.label.replace('OND ', '')}")
    items = [
        "Four triggers, one per zone, each all-in and independent of the others. They can activate only in "
        f"<strong>October, November and December</strong> \u2014 planning runs into September, so October is the "
        f"earliest month that can be acted on this year. Calibrated and backtested on {cal}.",
        "Each zone\u2019s return period starts from how often that zone has a major-impact window (at least 5 deaths "
        "or 5,000 people affected in one recorded event), then is <strong>raised as far as it can go without losing "
        "a big flood it already catches</strong>: "
        + ", ".join(f"{SHORT[z]} {rp_txt(s_.loc[z].design_rp)}" for z in ZONE_ORDER)
        + ". That trades activations for precision; it cannot add catches.",
        f"<strong>Every activation is matched to a dated flood.</strong> The drafts activate {tot_a} times across "
        f"the four zones, catch <strong>{tot_c}</strong> major events \u2014 {', '.join(catches)} \u2014 and miss "
        f"<strong>{tot_m} of {tot_major}</strong>.",
        "<strong>The window is the binding problem.</strong> October to December holds 29 % of the people affected "
        "on record in Teso, 24 % in Adjumani and 16 % in Elgon and Karamoja; the peak impact month is August in "
        "three of the four zones. The indicators peak earlier still \u2014 April for the rain forecasts in Karamoja "
        "and Adjumani, August for Teso\u2019s GloFAS \u2014 so for three zones the window sits after the signal and "
        "beside the floods.",
        "Existing triggers are reproduced alongside ours, on the same windows and the same events.",
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
            sub="One independent trigger per zone, each as frequent as the zone\u2019s major-impact years (never more often than 1-in-3), backtested year by year against the "
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
        "<p class='fn'>Major-impact season: a season in which one recorded event in the zone reached 5 deaths or "
        "5,000 people affected (the zone\u2019s share of events naming several districts). Activations, catches and "
        "misses count only the October\u2013December window. An activation catches an event when the event "
        "starts within the trigger\u2019s lead window after it \u2014 30 days for the rain forecasts, 45 for GloFAS, "
        "150 for Adjumani\u2019s lake leg \u2014 or is already under way when it comes (negative lead).</p>",
        "<h2>When floods actually happen</h2>",
        "<p>Each row is a share of its own total, per cent, across the calendar year; the October to December "
        "window is boxed. The third row per zone is when the trigger would have fired if the window were lifted, "
        "which is the honest test of whether the indicator peaks when the floods do.</p>",
        months_table(inp),
        "<p><strong>Two things to face.</strong> First, the window holds a minority of the record: 29 % of the "
        "people affected in Teso, 24 % in Adjumani, 16 % in Elgon and Karamoja. The peak impact month is August in "
        "Teso, Elgon and Karamoja, and April in Adjumani. An October to December trigger cannot be judged on, or "
        "expected to catch, the floods of the long rains. Second, the indicators peak earlier still: the rain "
        "forecasts crest in April in Karamoja and Adjumani, and Teso\u2019s GloFAS in August. Only Elgon\u2019s peak "
        "sits inside the window \u2014 the same thing as the early activations noticed in the last draft: the "
        "signal arrives before the window opens.</p>",
        "<h2>How each zone\u2019s return period is set</h2>",
        "<p>Each zone has its own envelope and triggers on its own, so there is no shared budget to divide. A zone\u2019s "
        "return period is set to <strong>how often that zone has a major-impact season</strong>, so the trigger "
        "activates about as often as there is something to respond to, with a floor: <strong>never more often than "
        "1-in-3</strong>. Elgon and Karamoja have major seasons often enough to sit on the floor; Teso and Adjumani "
        "sit a little above it.</p>",
        "<p>Frequency-matching rather than picking the return period that scores best in the backtest: with 25 "
        "seasons the best score is noise. Matching frequency never looks at which seasons were hit, so it cannot be "
        "tuned to them. The table shows what each return period would have done: <em>activations \u00b7 major events "
        "caught \u00b7 major seasons missed</em>, with each zone\u2019s chosen return period first. Going rarer buys "
        "fewer false alarms and almost no extra catches; going more frequent than 1-in-3 buys activations, not "
        "<p><strong>Then raised to shed false alarms.</strong> Starting from that frequency-matched level, each "
        "zone\u2019s threshold is stepped rarer for as long as it still catches every big flood it caught before \u2014 "
        "big meaning thousands of people affected, not a hundred \u2014 and still activates at least once. The step "
        "stops just before a big catch would be lost. Raising a threshold can only remove activations, never add "
        "catches, so what it buys is precision: Teso goes from 1-in-8.7 to 1-in-17 and sheds two false alarms, "
        "Adjumani from 1-in-5.2 to 1-in-17, Karamoja from 1-in-5.2 to 1-in-10. Elgon barely moves, to 1-in-5.4, "
        "because the next step up would lose the November 2024 landslides. The risk is the usual one of tuning on a "
        "short record: a big flood sitting just under the final threshold here might be missed in another 25 "
        "years.</p>",
        "catches.</p>",
        sensitivity_table(inp),
        "<p class='fn'>Impact frequencies use the dated event record described under Data and methods, so they "
        "inherit its gaps: West Nile is thinly recorded before 2004, and seasons after 2021 rest on EM-DAT, press "
        "reports and IOM DTM rounds once DesInventar stops.</p>",
        "<h2>All zones, season by season</h2>",
        overview_table(inp, years),
        "<p class='fn'>A cell says \u201ccaught\u201d where that season\u2019s first activation matched a major "
        "event. \u201cNo data\u201d: CHIRPS-GEFS has no forecasts from 1 January to 4 October 2020, so the "
        "rain-based triggers cannot be judged in the seasons that gap touches; Adjumani\u2019s lake leg can.</p>",
        window_table(inp),
        season_2007(inp),
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
        "<li><strong>Season</strong> \u201cOND 2019\u201d means 1 October to 31 December 2019. Only activations and impact "
        "inside that window count.</li>"
        "<li><strong>Our draft</strong> shows the first activation of the season \u2014 the one that releases an "
        "all-in envelope \u2014 with the district or leg that triggered it, and whether it matched a major event and "
        "with how much lead. Where the first activation missed but a later one in the same season would have "
        "matched, the cell says so: that is what the all-in rule costs.</li>"
        "<li><strong>Season\u2019s peak</strong> is the rarest value the indicator reached in the window, as a return "
        "period on its own record, so near-misses are visible.</li>"
        "<li><strong>Existing triggers</strong> (grey) are other organisations\u2019 triggers for the zone, reproduced "
        "as closely as the data allows and judged on the same seasons, events and lead windows. They were designed "
        "for their own coverage and budgets, so this is about which floods each would have caught, not a ranking.</li>"
        "<li><strong>Impact</strong> is shaded by magnitude on one scale for every zone, and is what was recorded, "
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
        "<li><strong>Season and matching</strong>: the window is 1 October to 31 December \u2014 planning runs into "
        "September, so October is the earliest month that can be acted on, and the funding does not run past March. Thresholds are calibrated on in-window maxima only. An activation catches an event when "
        "the event starts within the trigger\u2019s lead window after it (30 days rain, 45 GloFAS, 150 the lake leg) "
        "or is already under way; three days of tolerance allow for reporting dates.</li>"
        "<li><strong>Impact events</strong> are dated: EM-DAT, press and IOM DTM events keep their start and end "
        "dates and are split evenly across the districts they name, with only the zone\u2019s share counted; "
        "DesInventar cards are summed per day. Cards whose day is unknown in the export (a quarter of them, and most "
        "of the recorded deaths) span their whole month rather than being pinned to the 1st \u2014 an earlier version "
        "of the loader treated them as day-precise, which this analysis corrects.</li>"
        "<li><strong>Calibration</strong>: each series’ annual maxima get a Gumbel fit; a zone’s statistic for a "
        "year is the rarest value any of its series reached on its own fit, so districts with wet and dry climates "
        "are held to the same rarity. Thresholds are set on that statistic to meet the zone’s share (above), and "
        "reported back as return levels per series. Return periods quoted for the backtest are Weibull, (n + 1) / "
        "activations.</li>"
        "</ul>",
        "<h2>Open questions and next steps</h2>",
        "<ul>"
        "<li><strong>The honest headline:</strong> matched to dated floods, these triggers catch few major events. "
        "Any of them would need the observational backstop behind it before it could be proposed as a mechanism.</li>"
        "<li><strong>Teso:</strong> run on the GloFAS reforecast (download nearly complete), and decide whether a "
        "river already above the threshold on 1 October counts as an activation. Then the third opinion on the "
        "post-2013 divergence \u2014 a DWRM gauge or Google Flood Hub.</li>"
        "<li><strong>Longer windows:</strong> test a 15- or 30-day accumulation for prolonged seasons such as "
        "2007.</li>"
        "<li><strong>Staging:</strong> an all-in envelope is released by the first activation. A readiness/action "
        "split would let a later activation in the same season still act \u2014 which is exactly what late 2019 in "
        "Elgon needed.</li>"
        "<li><strong>Karamoja funding:</strong> all-in for the zone, or per district.</li>"
        "<li><strong>Adjumani:</strong> the lake leg gives months of warning, so a window opening on 1 October "
        "truncates it; consider reading Lake Albert directly and allowing an earlier readiness decision.</li>"
        "<li><strong>Return periods:</strong> frequency-matching with a 1-in-3 floor is a judgement; the sensitivity "
        "table shows the trade-off.</li>"
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
