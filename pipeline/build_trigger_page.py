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
        # side analyses: IFRC reproduction, FloodScan fallback, Karamoja and Adjumani options
        opt = lambda f: pd.read_csv(TRIG / f) if (TRIG / f).exists() else None
        self.ifrc_units = opt("ifrc_units.csv")
        self.ifrc_2023 = opt("ifrc_2023_check.csv")
        self.fallback = opt("fallback_summary.csv")
        self.kar_choice = opt("karamoja_indicator_choice.csv")
        self.kar_variants = opt("karamoja_variants.csv")
        self.adj_options = opt("adjumani_options.csv")
        self.adj_grid = opt("adjumani_compound_grid.csv")
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
    if z == "teso_kyoga" and "IFRC portal" in t.index:
        return (
            "the <strong>IFRC/URCS trigger</strong> shows any Teso district triggered on the IBF portal: at least "
            "60 % of GloFAS members above the official <strong>5-year</strong> flow at a lead of up to 5 days, each "
            "district, county and sub-county judged at its largest river cell",
            "up to 5 days nominally; about <strong>none in practice</strong> in this window \u2014 the river is "
            "usually already high when it opens",
        )
    if z == "teso_kyoga":
        return (
            f"at least 60 % of GloFAS reforecast members put the Akokoro at G5196 above "
            f"<strong>{t.threshold.iloc[0]:,.0f} m\u00b3/s</strong> within days 3\u20137 (model space; the model runs "
            "about 1.7\u00d7 wet, so this is not a gauged flow)",
            "3\u20137 days nominally; <strong>none in practice</strong> \u2014 every activation falls on 1 October with "
            "the river already above the threshold",
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
            + (
                "<span class='fn'>what the IFRC protocol gives; not calibrated</span>"
                if r.get("fixed", False)
                else ""
            )
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


MONTH_NAMES = [
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
]


def timing_grids(inp: Inputs) -> str:
    """Per zone, a year x month grid of when floods happened and when the trigger activated."""
    path = TRIG / "timing_grid.csv"
    if not path.exists():
        return ""
    d = pd.read_csv(path)
    top = max(float(d.affected.max()), 1.0)
    out = []
    for z in ZONE_ORDER:
        g = d[d.zone == z].set_index(["year", "month"])
        cols = "<col class='tg-y'>" + "<col class='tg-m'>" * 12
        head = (
            "<tr><th></th>"
            + "".join(
                f"<th class='{'tg-win' if m in WINDOW_MONTHS else ''}'>{MONTHS[m - 1][0]}</th>"
                for m in range(1, 13)
            )
            + "</tr>"
        )
        rows = []
        for y in sorted({i[0] for i in g.index}, reverse=True):
            cells = []
            for m in range(1, 13):
                r = g.loc[(y, m)]
                cls = ["tg-c"]
                if m in WINDOW_MONTHS:
                    cls.append("tg-win")
                style = ""
                if r.affected > 0 or r.deaths > 0:
                    t = 0.12 + 0.88 * math.log10(max(r.affected, 1) + 1) / math.log10(top + 1)
                    if r.major:
                        t = max(t, 0.45)
                    style = f"background:{ramp(t)}"
                elif r.ongoing:
                    cls.append("tg-on-major" if r.ongoing_major else "tg-on")
                mark = ""
                if r.activated:
                    mark = f"<span class='tg-act' style='background:{bp.ZONE_COL[z]}'></span>"
                elif r.crossing:
                    mark = "<span class='tg-x'></span>"
                cerf = r.cerf if isinstance(r.cerf, str) and r.cerf else ""
                if cerf:
                    role = cerf.split("|")[1]
                    mark += f"<span class='tg-cerf{' tg-cerf2' if role == 'secondary' else ''}'>C</span>"
                tip = [f"{MONTH_NAMES[m - 1]} {y}"]
                if r.n_events:
                    tip.append(
                        f"{int(r.n_events)} event(s) starting: {r.affected:,.0f} affected, {r.deaths:,.0f} deaths"
                    )
                if r.ongoing:
                    tip.append("an earlier flood still under way")
                if r.activated:
                    tip.append("trigger activated")
                if r.crossing:
                    tip.append("indicator over threshold (outside the window)")
                for c in filter(None, cerf.split("; ")):
                    code, role, amt, resp, dists = c.split("|")
                    tip.append(
                        f"CERF {code} approved, {amt} for the {resp}"
                        + (" (this zone secondary)" if role == "secondary" else "")
                        + f" \u2014 {dists}"
                    )
                cells.append(
                    f"<td class='{' '.join(cls)}' style='{style}' title='{bp.e('; '.join(tip))}'>{mark}</td>"
                )
            rows.append(f"<tr><th class='tg-yr'>{y}</th>{''.join(cells)}</tr>")
        out.append(
            f"<h3><span class='sw' style='background:{bp.ZONE_COL[z]}'></span>{bp.e(ZONES[z].label.split(' (')[0])}</h3>"
            f"<div class='tw'><table class='tgrid'><colgroup>{cols}</colgroup><thead>{head}</thead>"
            f"<tbody>{''.join(rows)}</tbody></table></div>"
        )
    legend = (
        "<div class='tg-legend'>"
        f"<span><i class='tg-sw' style='background:{ramp(0.2)}'></i><i class='tg-sw' style='background:{ramp(0.55)}'></i>"
        f"<i class='tg-sw' style='background:{ramp(0.95)}'></i> flood starting that month (darker = more people "
        "affected)</span>"
        "<span><i class='tg-sw tg-on-major'></i> a major flood still under way</span>"
        "<span><i class='tg-sw tg-on'></i> a smaller flood still under way</span>"
        "<span><span class='tg-act' style='background:#555'></span> trigger activated (Oct\u2013Dec only)</span>"
        "<span><span class='tg-x'></span> indicator over its threshold outside the window</span>"
        "<span><span class='tg-cerf'>C</span> CERF flood allocation approved for this zone</span>"
        "<span><span class='tg-cerf tg-cerf2'>C</span> zone covered, not the focus</span>"
        "<span><i class='tg-sw tg-winsw'></i> the Oct\u2013Dec window</span>"
        "</div>"
    )
    return legend + "".join(out)


def teso_exploration() -> str:
    """Side exploration: what drives Teso's Oct-Dec floods, and a decide-on-1-October test."""
    dp, tp = TRIG / "teso_ond_drivers.csv", TRIG / "teso_oct1_trigger.csv"
    if not (dp.exists() and tp.exists()):
        return ""
    d = pd.read_csv(dp)
    rows = "".join(
        f"<tr><td>{bp.e(r.indicator)}</td><td class='num'>{r.auc_any_flood:.2f}</td>"
        f"<td class='num'>{r.auc_major:.2f}</td></tr>"
        for r in d.itertuples()
    )
    t1 = (
        "<div class='tw trig-cmp'><table><thead><tr><th>Indicator (0.5 = no skill)</th>"
        "<th>Any Oct\u2013Dec flood</th><th>Major only</th></tr></thead>"
        f"<tbody>{rows}</tbody></table></div>"
    )
    t = pd.read_csv(tp)
    rows2 = "".join(
        f"<tr><td>{bp.e(r.indicator)}</td><td class='num'>{rp_txt(r.rp)}</td>"
        f"<td class='num'>{r.flood_windows_caught} of {r.flood_windows}</td>"
        f"<td class='num'>{r.majors_caught} of {r.majors}</td><td class='num'>{r.false_alarms}</td>"
        f"<td class='src'>{bp.e(r.seasons)}</td></tr>"
        for r in t.itertuples()
    )
    t2 = (
        "<div class='tw trig-cmp'><table><thead><tr><th>Decide on 1 October from</th><th>Rarity</th>"
        "<th>Flood windows caught</th><th>Major caught</th><th>False alarms</th><th>Activates in</th></tr></thead>"
        f"<tbody>{rows2}</tbody></table></div>"
    )
    return (
        "<h3>Side exploration: what drives Teso\u2019s October floods?</h3>"
        "<p>The October\u2013December flood records in the Teso zone are mostly typed <em>rains</em> or "
        "<em>rainstorm</em> rather than riverine flooding, in the flat Katakwi and Amuria plains, which suggests "
        "pluvial waterlogging with a different driver from the August\u2013September river peak. The data do not "
        "support that. Scoring candidate indicators on how well they separate the seven windows with a recorded "
        "Oct\u2013Dec flood start (three of them major) from the rest, rainfall has no skill at all \u2014 "
        "forecast, observed or antecedent \u2014 while the state of the landscape when the window opens does: how "
        "much of Teso FloodScan shows flooded, and how high the Akokoro is, on 1 October. October floods are mostly "
        "the tail of a wet August\u2013September, not a new rain-driven event. With 25 windows these scores are "
        "noisy; differences under about 0.1 are ties.</p>"
        + t1
        + "<p>That suggests deciding on 1 October from the state at window open. It does better than the level "
        "trigger drafted above \u2014 which is the same GloFAS signal set higher \u2014 catching two of the three "
        "major October windows (2007 and 2021) at about 1-in-4. But it is early action on an already-primed "
        "landscape rather than anticipation: the floods it catches are recorded as starting on 1\u20132 October, "
        "so the lead is days at best. The largest October event, 2014 (66,573 affected, single-source), is caught "
        "by nothing: the land was not wet on 1 October, and October rain did not stand out either.</p>"
        + t2
    )


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
        f"catch count is not an artefact of strict matching. At the 30-day rain window they catch "
        f"{int(g.loc[30].caught)} where random timing would catch about {g.loc[30].chance:.1f}.</p>"
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


def cerf_overview(inp: Inputs, y: int) -> str:
    """The CERF allocation(s) for a season, with the zones each reached."""
    by_label: dict[str, list[str]] = {}
    for z in ZONE_ORDER:
        c = inp.tabs[z].loc[y].cerf if y in inp.tabs[z].index else ""
        for part in filter(None, (c if isinstance(c, str) else "").split("; ")):
            base = part.replace(" (secondary)", "")
            by_label.setdefault(base, []).append(
                SHORT[z] + (" (secondary)" if "secondary" in part else "")
            )
    return "; ".join(f"{bp.e(k)} \u2014 {bp.e(', '.join(v))}" for k, v in by_label.items())


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
        cerf = cerf_overview(inp, y)
        lbl = inp.tabs["teso_kyoga"].loc[y].label
        rows.append(
            f"<tr><td class='yr'>{lbl}</td>{''.join(cells)}"
            f"<td class='any'>{'●' if anyz else ''}</td>"
            f"<td class='src'>{cerf}</td></tr>"
        )
    head = (
        "<tr><th>Season</th>"
        + "".join(f"<th>{SHORT[z]}</th>" for z in ZONE_ORDER)
        + "<th>Any zone</th><th>CERF flood allocation, and the zones it reached</th></tr>"
    )
    return f"<div class='tw trig-over'><table><thead>{head}</thead><tbody>{''.join(rows)}</tbody></table></div>"


def compare_table(z: str, tab: pd.DataFrame, cols, own: str = "Our draft") -> str:
    """Our draft and each existing trigger over the same seasons, against the same events."""
    items = [(own, tab.activated, tab.data, tab.caught, bp.ZONE_COL[z])]
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
                if via in ("GloFAS G5196", "IFRC portal", "zone-mean 5-day forecast")
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
        if r.get("via", "") == "IFRC portal" or (
            z == "teso_kyoga" and inp.s.loc[z].get("fixed", False)
        ):
            # a protocol trigger: show how far the river got relative to its own bar
            pv = r.get("peak_value", float("nan"))
            peak = f"{pv:.2f}× the 5-yr flow" if pd.notna(pv) and r.data else ""
        elif pd.notna(r.peak_rp) and r.data:
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
        f"<tr><th>Season</th><th>{'IFRC trigger (Teso)' if z == 'teso_kyoga' and inp.s.loc[z].get('fixed', False) else 'Our draft'}</th>"
        "<th>Season\u2019s peak</th>"
        + "".join(f"<th>{bp.e(short)}</th>" for short, _, _ in cols)
        + "<th>People affected</th><th>Deaths</th><th>Events recorded</th><th>Impact sources</th>"
        "<th>CERF</th></tr>"
    )
    return f"<div class='tw trig-zone'><table><thead>{head}</thead><tbody>{''.join(rows)}</tbody></table></div>"


# --- side analyses -------------------------------------------------------------------------

# EAP2021UG01 trigger statements, verbatim. Approved EAP summary (IFRC, 27 May 2021) and the
# EAP activation document for operation MDRUG048 (IFRC, 15 Nov 2023). Both are published by IFRC.
IFRC_2021 = (
    "URCS will activate this EAP when GloFAS issues a forecast of at least 70% probability of a 5-year "
    "return period flood occurring in high priority flood prone districts, and 10 year return period in "
    "lower priority flood prone districts, which will be anticipated to affect more than 1,000hh. The EAP "
    "will be triggered with a lead time of 5 days and in locations where the FAR is not more than 0.5."
)
IFRC_2023 = (
    "URCS will activate this EAP when GloFAS issues a forecast of at least 60% probability (based on the "
    "different ensemble runs) of a 5-year return period flood occurring in flood prone districts, which will "
    "be anticipated to affect more than 1,000hh. The EAP will be triggered with a lead time of 5 days and a "
    "FAR of not more than 0.5."
)
IFRC_HIGH_RISK = (
    "Kasese, Katakwi, Amuria, Kampala, Butaleja, Sironko, Bududa, Manafwa, Kumi, Ntoroko, Bulambuli, Moyo, "
    "Nabilatuk and Ngora"
)


def img_uri(path: Path) -> str:
    import base64

    return "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode()


def zone_map(z: str) -> str:
    """The per-zone map (pipeline/zone_trigger_maps.py), embedded so the encrypted page is whole.
    The Elgon map can name unpublished partner triggers: it only ever goes into this page."""
    path = TRIG / f"map_{z}.png"
    if not path.exists():
        return ""
    return (
        f"<figure><img src='{img_uri(path)}' alt='Where the {SHORT[z]} trigger is measured'>"
        "<figcaption class='fn'>Where the trigger is measured: the zone, the cells, points or areas each "
        "indicator is read at, and the partner points nearby.</figcaption></figure>"
    )


def ifrc_section(inp: Inputs) -> str:
    """The IFRC/URCS trigger word for word, what the portal computes, and our check of both."""
    u = inp.ifrc_units
    rows = ""
    if u is not None:
        teso = list(ZONES["teso_kyoga"].all_districts)
        elg = ["Butaleja", "Sironko", "Bududa", "Manafwa", "Bulambuli", "Kumi"]
        d2 = u[(u.level == 2) & u.district.isin(teso + elg)].copy()
        d2["zone"] = d2.district.map(lambda d: "Teso" if d in teso else "Elgon")
        d2["order"] = d2.district.map(lambda d: (teso + elg).index(d))
        river = {
            "Amuria": "Akokoro, next cell downstream of G5196",
            "Kapelebyong": "Akokoro, upstream of G5196",
            "Katakwi": "Lake Bisina–Awoja channel",
            "Soroti": "Lake Bisina–Awoja channel",
            "Ngora": "Awoja, above Lake Kyoga",
            "Serere": "Lake Kyoga",
            "Kumi": "Lake Bisina–Awoja channel",
            "Butaleja": "Mpologoma",
            "Manafwa": "Manafwa",
        }
        for r in d2.sort_values("order").itertuples():
            rows += (
                f"<tr><td>{r.zone}</td><td>{bp.e(r.district)}</td><td class='num'>{r.thr_lat:.3f}°N "
                f"{r.thr_lon:.3f}°E</td><td class='num'>{r.threshold:,.0f}</td>"
                f"<td class='num'>{r.mean_flow_thr_cell:,.0f}</td><td>{bp.e(river.get(r.district, ''))}</td></tr>"
            )
    cells = (
        "<div class='tw trig-cmp'><table><thead><tr><th>Zone</th><th>District</th><th>Read at (cell centre)</th>"
        "<th>Official 5-yr flow, m³/s</th><th>Mean flow there, m³/s</th><th>River</th></tr></thead>"
        f"<tbody>{rows}</tbody></table></div>"
        "<p class='fn'>The district-level cell only. Each county and sub-county is judged at its own largest "
        "cell too, and triggers the district if it exceeds — so smaller rivers inside a district count. "
        "Because cells touching the boundary are included, a district’s cell can sit just over the line: "
        "Katakwi’s is on the Soroti side. Flows are the model’s, not gauged.</p>"
        if rows
        else ""
    )
    chk = inp.ifrc_2023
    check = ""
    if chk is not None:
        chk = chk.assign(first_day=pd.to_datetime(chk.first_day))
        on_list = chk[chk.portal_2023]
        by22 = int((on_list.first_day <= "2023-11-22").sum())
        by30 = int(on_list.exceeds_15_30_nov.sum())
        missing = ", ".join(on_list[~on_list.exceeds_15_30_nov].district)
        check = (
            f"<li><strong>Checked against the portal itself.</strong> On 15 November 2023 the portal triggered "
            f"the EAP and listed {len(on_list)} potentially exposed districts. The reproduction has {by22} of them "
            f"over the 5-year flow within that forecast’s 8 days (15–22 November) and {by30} by the "
            f"end of the month; it misses only {missing}. But it also has <strong>other districts over the "
            "level that the portal did not list</strong> \u2014 seven Elgon slope districts on 15 November, and in "
            "Teso Katakwi (7\u201314 November, then the 22nd) and Serere (from the 21st). Some of that may be "
            "the notification listing only districts with mapped exposure; some is the stand-in over-triggering. "
            "Katakwi\u2019s exceedances are marginal (1.02\u20131.03\u00d7 the level), and at G5196 the reforecast "
            "shows that when the reanalysis is 0\u20132 % over the level, 60 % of members agree only about a third "
            "of the time. <strong>So the reproduction has the portal\u2019s mechanics, not necessarily its "
            "decisions</strong>: read it as a stand-in until it is checked against the portal\u2019s own trigger "
            "log (did Katakwi or Serere trigger in November 2023?).</li>"
        )
    return (
        "<h3>The IFRC/URCS trigger, word for word</h3>"
        "<p>The approved Early Action Protocol (EAP2021UG01, approved 27 May 2021; IFRC EAP summary):</p>"
        f"<blockquote class='wording'>“{IFRC_2021}”</blockquote>"
        "<p>As stated when it was activated (operation MDRUG048, trigger notification 15 November 2023; IFRC EAP "
        "activation document):</p>"
        f"<blockquote class='wording'>“{IFRC_2023}”</blockquote>"
        f"<p>The EAP names 14 high-risk districts: {IFRC_HIGH_RISK}. Four are in Teso (Katakwi, Amuria, Ngora, "
        "and Kumi, which this analysis places in the Elgon lowlands), five on Elgon, plus Moyo on the Albert Nile "
        "and Nabilatuk in Karamoja.</p>"
        "<p><strong>What the portal computes.</strong> The 510 IBF river-flood pipeline that raises the "
        "notification (<code>rodekruis/IBF-river-flood-pipeline</code>, Uganda settings, read September 2026):</p>"
        "<ul>"
        "<li>admin levels 2, 3 and 4 — districts, counties and sub-counties;</li>"
        "<li>threshold: the <strong>zonal maximum</strong> of the official GloFAS v4 5-year return-level map over "
        "each area (cells touching the area count);</li>"
        "<li>forecast: for each of the 51 ensemble members and each lead day 0–7, the zonal maximum of "
        "forecast discharge over the same area;</li>"
        "<li>triggered when at least <strong>60 %</strong> of members exceed the threshold at any lead of "
        "<strong>5 days or less</strong>; a triggered county or sub-county also triggers its district.</li>"
        "</ul>"
        "<p>So in practice the 2023 wording is what runs, not the 2021 one: a single 60 %, 5-year bar in every "
        "district, no 10-year bar for lower-priority districts. The “more than 1,000 households” and "
        "“FAR not more than 0.5” conditions are not part of the computation: the first is judged from "
        "the exposure the portal displays, the second was a condition on where the EAP applies.</p>"
        "<p><strong>Did we have it right?</strong></p>"
        "<ul>"
        "<li><strong>The level — yes.</strong> Our own 5-year level at G5196 (Gumbel on annual maxima, "
        "2000–2024) is 59 m³/s; the official map has 61 m³/s there.</li>"
        "<li><strong>Probability and lead — yes.</strong> 60 % of members, up to 5 days.</li>"
        "<li><strong>Where it is read — no.</strong> We read G5196, the Akokoro reporting point, alone. The "
        "portal judges each area at its largest river cell. For Amuria and Kapelebyong that is the Akokoro, next "
        "to G5196; for Katakwi, Soroti and Ngora it is the Lake Bisina–Awoja channel, whose 5-year flow is six "
        "times the Akokoro’s; for Serere it is Lake Kyoga. Read at G5196 alone the trigger would have "
        "activated once in 20 October–December windows; as the portal runs it, it activates in about one in "
        "four.</li>"
        f"{check}"
        "</ul>"
        f"{cells}"
        "<p class='fn'>Reproduction: <code>analysis/ifrc_reproduction.py</code>, on the GloFAS v4 reanalysis "
        "(1999–2025) against the official 5-year map (<code>flood_threshold_glofas_v4_rl_5.0.nc</code>, "
        "GloFAS), with CODAB boundaries at levels 2–4 (the portal uses its own, of similar size). The "
        "reanalysis stands in for the ensemble — as if the forecast came true — and an exceedance is "
        "dated 5 days early, when a forecast would first have shown it.</p>"
    )


def fallback_section(inp: Inputs) -> str:
    """FloodScan observed-flood fallback, per zone, alone and over the zone trigger."""
    f = inp.fallback
    if f is None:
        return ""
    rows = []
    for z in ZONE_ORDER:
        r = f.set_index("zone").loc[z]
        if not isinstance(r.districts, str) or not r.districts:
            rows.append(
                f"<tr><td class='zn'><span class='sw' style='background:{bp.ZONE_COL[z]}'></span>{SHORT[z]}</td>"
                "<td colspan='6'>no zone district where FloodScan tracks recorded floods — no fallback</td></tr>"
            )
            continue
        n_d = len(r.districts.split(";"))
        rows.append(
            f"<tr><td class='zn'><span class='sw' style='background:{bp.ZONE_COL[z]}'></span>{SHORT[z]}</td>"
            f"<td>{n_d}<span class='fn'>{bp.e(r.districts.replace(';', ', '))}</span></td>"
            f"<td class='num'>{rp_txt(r.design_rp)}</td>"
            f"<td class='num'>{int(r.fs_activations)}<span class='fn'>{bp.e(r.fs_activated)}</span></td>"
            f"<td class='num'>{int(r.fs_caught)}</td>"
            f"<td>{bp.e(r.added_catches) if isinstance(r.added_catches, str) else 'none'}</td>"
            f"<td>{bp.e(r.added_false_alarms) if isinstance(r.added_false_alarms, str) else 'none'}"
            f"<span class='fn'>zone then activates {rp_txt(r.combined_rp)}</span></td></tr>"
        )
    head = (
        "<tr><th>Zone</th><th>Districts it reads</th><th>Return period</th><th>Activations</th>"
        "<th>Caught</th><th>Catches it adds to the zone trigger</th><th>False alarms it adds</th></tr>"
    )
    return (
        "<h2>The FloodScan fallback, zone by zone</h2>"
        "<p>The country team asked for an observed-flood backstop everywhere, so that a forecast miss can still "
        "release money. Each zone’s fallback reads FloodScan flood extent in the zone districts where it "
        "tracks recorded floods (rank-based evidence: a district’s dated events reach its own top fifth more "
        "often than an arbitrary window does, by at least 0.10), holds every district to the same rarity on its "
        "own record, and is set by the same rule as the zone triggers: as frequent as the zone’s major "
        "seasons, floored at 1-in-3, then raised while it keeps every big catch. An observed-flood activation "
        "counts as catching a flood it sees while the flood is on or up to 10 days after it.</p>"
        f"<div class='tw trig-cmp'><table><thead>{head}</thead><tbody>{''.join(rows)}</tbody></table></div>"
        "<p><strong>It earns its place in Teso only.</strong> There it catches October 2021, which the IFRC "
        "trigger misses, for one extra false alarm. In Elgon and Karamoja it catches nothing in this window: "
        "their October–December majors are landslides and flash floods that satellite extent does not see "
        "at the right time, and every activation it adds is a false alarm. In Adjumani no district passes the "
        "check — on the Albert Nile FloodScan does not track the recorded floods. Outside October–"
        "December the picture is different (FloodScan tracks the long-rains floods in Elgon’s lowlands well), "
        "so this is a verdict on this window, not on FloodScan.</p>"
        "<p class='fn'><code>analysis/floodscan_fallback.py</code>. Districts whose evidence is too thin "
        "(created after 2018, or fewer than three dated events) are left out rather than guessed.</p>"
    )


def karamoja_section(inp: Inputs) -> str:
    ch, v = inp.kar_choice, inp.kar_variants
    if ch is None or v is None:
        return ""
    f = lambda x: "" if pd.isna(x) else f"{x:+.2f}"
    crow = "".join(
        f"<tr><td>{bp.e(r.district)}</td><td class='num'>{int(r.n_events)}</td>"
        f"<td class='num'>{f(r.rain_lift)}</td><td class='num'>{f(r.fs_lift)}</td>"
        f"<td>{bp.e(r.choice)}</td></tr>"
        for r in ch.itertuples()
    )
    vrow = "".join(
        f"<tr><td>{bp.e(r.variant)}</td><td class='num'>{rp_txt(r.design_rp)}</td>"
        f"<td class='num'>{int(r.activations)}<span class='fn'>{bp.e(r.activated)}</span></td>"
        f"<td class='num'>{int(r.caught)}</td><td class='num'>{int(r.false_alarms)}</td>"
        f"<td class='num'>{int(r.missed)} of {int(r.major_seasons)}</td></tr>"
        for r in v.itertuples()
    )
    n_rain = int(ch.choice.eq("rain").sum())
    n_rec = int((ch.n_events > 0).sum())
    fs_only = ", ".join(ch[ch.choice == "floodscan"].district) or "none"
    return (
        "<h3>Rain forecast or FloodScan, district by district</h3>"
        "<p>For each district, the same rank-based test for both indicators on every dated event in the district "
        "(all months, for enough events): how much more often than an arbitrary window of the same length the "
        "indicator reaches the district’s own top fifth around an event. Positive and at least 0.10 counts as "
        "informative. The better-evidenced indicator is the district’s choice; with no evidence either way, "
        "rain (it gives lead time).</p>"
        "<div class='tw trig-cmp'><table><thead><tr><th>District</th><th>Dated events</th><th>Rain forecast, lift "
        "over chance</th><th>FloodScan, lift over chance</th><th>Choice</th></tr></thead>"
        f"<tbody>{crow}</tbody></table></div>"
        f"<p>The rain forecast is the better indicator in {n_rain} of the {n_rec} districts with a record of their "
        f"own; FloodScan only in {fs_only}. "
        "Karenga and Nabilatuk were carved out in 2018–19 and their events are still recorded under Kaabong "
        "and Nakapiripirit, so they have no record of their own. Each design below then gets the zone rule "
        "(frequency, floor 1-in-3, raised while it keeps its big catches):</p>"
        "<div class='tw trig-cmp'><table><thead><tr><th>Design</th><th>Return period</th><th>Activations</th>"
        "<th>Caught</th><th>False alarms</th><th>Missed</th></tr></thead>"
        f"<tbody>{vrow}</tbody></table></div>"
        "<p><strong>Keep the rain forecast.</strong> Swapping in FloodScan where it is better, or adding it "
        "everywhere it is usable, catches nothing more in October–December and adds false alarms. Thresholds "
        "are deliberately not tuned district by district: each district has one to three dated October–"
        "December events, so a per-district optimum would fit the record rather than the hazard. What is chosen "
        "per district is the indicator; the rarity stays common.</p>"
        + (
            f"<p><strong>The near miss is November 2008</strong> ({kar08.affected:,.0f} affected on record, the zone\u2019s "
            f"largest October\u2013December flood), when {kar08.peak_where}\u2019s forecast reached "
            f"1-in-{kar08.peak_rp:.1f} against a per-district bar of 1-in-{inp.series_rp('karamoja'):.1f}. A zone return "
            "period of 1-in-4 would catch it, at six activations in 25 windows (sensitivity table above); the "
            "record cannot tell 1-in-4 from 1-in-5.2 apart, so that is a preference for 2008, not a finding. An "
            "earlier draft sat at 1-in-10: the raise had parked the bar 0.03 mm under a 140-affected December 2006 "
            "card, which the rule should not do when there is no big flood to protect (fixed 30 September). A "
            "wettest-pixel reading of the forecast is worth one run (the district tables already carry it).</p>"
            if (kar08 := inp.tabs["karamoja"].loc[2008]) is not None
            else ""
        )
    )


def adjumani_section(inp: Inputs) -> str:
    o = inp.adj_options
    if o is None:
        return ""
    rows = "".join(
        f"<tr><td>{bp.e(r.option)}</td><td class='num'>{int(r.activations)}<span class='fn'>"
        f"{rp_txt(r.rp)}</span></td><td class='num'>{int(r.caught)}<span class='fn'>"
        f"{bp.e(r.caught_seasons) if isinstance(r.caught_seasons, str) else ''}</span></td>"
        f"<td class='num'>{int(r.false_alarms)}<span class='fn'>"
        f"{bp.e(r.false_alarm_seasons) if isinstance(r.false_alarm_seasons, str) else ''}</span></td>"
        f"<td>{'yes, ' + r.first_2023[5:] if r.catches_2023 else 'no'}</td></tr>"
        for r in o.itertuples()
    )
    return (
        "<h3>Could Adjumani have caught 2023?</h3>"
        "<p>October–December 2023 was a major season on the Albert Nile (Adjumani 2–7 November, "
        "Madi Okollo from 5 November, IOM DTM counts in Moyo and Obongi through October and November) and the "
        "draft stayed quiet. Nothing was extreme: the districts’ 5-day forecasts peaked at 1-in-3 to "
        "1-in-9 (Obongi) and Lake Kyoga’s six-month rise at about 1-in-8, against draft bars near 1-in-30 "
        "per series. Options, on the same seasons and events:</p>"
        "<div class='tw trig-cmp'><table><thead><tr><th>Option</th><th>Activations</th><th>Caught</th>"
        "<th>False alarms</th><th>Catches 2023</th></tr></thead>"
        f"<tbody>{rows}</tbody></table></div>"
        "<p><strong>Not with anticipation, and not with the compound rule as calibrated.</strong> The compound "
        "rule \u2014 Lake Kyoga\u2019s rise at 1-in-5 <em>and</em> any district\u2019s rain forecast at 1-in-3 on the "
        "same day \u2014 does activate in 2023, at the zone\u2019s own frequency (1-in-6.5). But an independent "
        "review (30 September) found both of its catches are floods already under way: the 2020 Nile flood had run "
        "since mid-year, and 2023\u2019s began before the window (over 4,000 refugees hit in Adjumani on "
        "20\u201327 September; DTM counts from 1 October). The rain condition does little work \u2014 some "
        "district reaches 1-in-3 in most seasons \u2014 so the rule is close to a lake gate: the lake leg alone, at "
        "the same rate, catches the same two seasons, on 1 October. With four major seasons and a rule chosen after "
        "seeing 2023, a random rule of this size would do as well about one time in eight, and the grid of nearby "
        "settings is not independent evidence (every cell scores the same two seasons). The honest option is the "
        "<strong>lake leg at 1-in-5 to 1-in-6.5, stated plainly as \u201cactivate when the Nile is already "
        "high\u201d</strong> \u2014 no anticipatory lead in this window \u2014 with the rain leg at its own rarity "
        "if wanted. 2004 and 2008 are missed by every option; their impact figures look like national EM-DAT "
        "totals split across districts, so the zone\u2019s major-season count is itself soft.</p>"
        "<p class='fn'><code>analysis/adjumani_options.py</code>. The lake series is now smoothed with a "
        "three-pass running median: single altimetry passes ~0.5 m low had been turning into fake six-month "
        "“rises” half a year later (October 2024 read as a 1-in-18 rise).</p>"
    )


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
        + ". The 2007 floods ran from mid-August to the end of October, so most of them fell before the window "
        "opened, and as a long wet season rather than one extreme week they are not what a 5-day forecast peak "
        "sees.</p>"
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
    if z == "teso_kyoga" and r.get("fixed", False):
        t = inp.tabs[z]
        c = t[t.in_calibration & t.data]
        fa = [x.replace("OND ", "") for x in c[c.activated & ~c.caught].label]
        miss = [x.replace("OND ", "") for x in c[c.major & ~c.caught].label]
        hit = [x.replace("OND ", "") for x in c[c.caught].label]
        return (
            "<strong>Teso uses the IFRC/URCS trigger</strong>, as the country team proposed after its call on "
            "29 September: when the IBF portal shows any Teso district triggered, the zone activates, so the "
            "money moves on the same signal as URCS\u2019s own early action. The exact wording and how the portal "
            "turns it into an activation are set out in the next section, with our check of both. Backtested on "
            "the GloFAS reanalysis against the official 5-year map \u2014 a perfect-forecast stand-in, so read "
            "these numbers as the IBF trigger\u2019s likely behaviour, not its record \u2014 it "
            f"activates in {act} of the {int(r.seasons_with_data)} windows ({rp}), catches {caught} "
            f"({years_txt(hit)}, a flood five weeks under way, and only through one Katakwi sub-county at 1.05\u00d7 "
            "the level \u2014 at district level Teso stays below it that season) and misses "
            f"{missed} of {int(r.major_seasons)} major seasons ({years_txt(miss)}). Because the district takes the "
            "largest of many areas, some Teso district passes the \u201c5-year\u201d level in most years: do not "
            f"describe this trigger as 1-in-5. Its false alarms ({years_txt(fa)}) mostly come through the Lake "
            "Bisina\u2013Awoja channel that the portal reads Katakwi, Soroti and Ngora on: it drains Mt Elgon\u2019s "
            "northern slopes and runs high in Elgon\u2019s wet years, which were not Teso flood windows. Our own "
            "G5196 draft did no better (1-in-8; activations 2007, 2012 and 2020, both catches floods already under "
            "way): <strong>in an October\u2013December window GloFAS has no anticipatory skill for Teso, whoever "
            "reads it</strong> \u2014 Teso\u2019s floods peak in August and September and October floods are their "
            "tail. The FloodScan fallback below is what adds a catch here (October 2021)."
        )
    if z == "teso_kyoga":
        return (
            "Built in the IFRC/URCS protocol\u2019s own form, as the country team asked: on the GloFAS reforecast "
            "(2003\u20132022, 11 members, issued about four times a week), at least 60 % of members above a "
            "model-space threshold within days 3\u20137. At G5196 the reforecast agrees with the reanalysis to "
            "within 1 % at every lead in October\u2013December, so thresholds fitted on the reanalysis hold. "
            f"At {rp}{raised} it activates in {act} of the {int(r.seasons_with_data)} windows. <strong>Every "
            "activation falls on 1 October</strong>, the day the window opens, with the Akokoro already above the "
            "threshold from its August\u2013September peak \u2014 in the forecast and the reanalysis alike, so the "
            "forecast buys no lead at all. The catches are floods already under way (2007, 39 days in) or an edge "
            "of the matching tolerance (2012, one day after the event\u2019s recorded end); October 2014, October "
            "2021 and the 2010 season are missed. Requiring the river to rise through the threshold after the "
            "window opens does not rescue it: at any threshold it catches at most one flood, at 1\u20133 days, "
            "against four or five false alarms. <strong>At this point and in this window, GloFAS has no "
            "anticipatory skill for Teso.</strong> Teso\u2019s floods peak in August and September, before the "
            "window, and the model\u2019s own peak is in August." + teso_ifrc_sentence(inp)
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


def raise_text(inp: Inputs) -> str:
    """How far each calibrated zone's threshold was raised, from the summary (not hand-typed)."""
    bits, flat = [], []
    for z in ZONE_ORDER:
        r = inp.s.loc[z]
        if r.get("fixed", False):
            continue
        if r.raised:
            bits.append(f"{SHORT[z]} from {rp_txt(r.frequency_rp)} to {rp_txt(r.design_rp)}")
        else:
            flat.append(SHORT[z])
    teso = inp.s.loc["teso_kyoga"]
    return (
        "<p><strong>Then raised to shed false alarms.</strong> Starting from that frequency-matched level, each "
        "zone\u2019s threshold is stepped rarer for as long as it still catches every big flood it caught before "
        "\u2014 big meaning thousands of people affected, not a hundred \u2014 and still activates at least once. "
        "The step stops just before a big catch would be lost. Raising a threshold can only remove activations, "
        "never add catches, so what it buys is precision: "
        + "; ".join(bits)
        + (f"; {', '.join(flat)} not at all" if flat else "")
        + ". "
        + (
            f"Teso is not calibrated: it takes the IFRC trigger as it is, which activates at "
            f"{rp_txt(teso.design_rp)} in this window. "
            if teso.get("fixed", False)
            else ""
        )
        + "The risk is the usual one of tuning on a short record: a big flood sitting just under the final "
        "threshold here might be missed in another 25 years.</p>"
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
        "<strong>Since the country-team call (29 September):</strong> Teso adopts the <strong>IFRC/URCS "
        "trigger</strong>, now reproduced the way the IBF portal actually computes it (it is not read at G5196 "
        "alone \u2014 see the Teso section for the wording and the check); Elgon\u2019s choice waits on FAO (see the Elgon "
        "section); Karamoja keeps the rain forecast after a district-by-district test against FloodScan, back "
        "at its frequency-matched rate; Adjumani\u2019s 2023 flood can only be met once under way, and the honest "
        "option is the lake leg stated as such; and every zone has a FloodScan fallback test and a map of where "
        "it is measured. An independent review of the three judgement calls (30 September) is folded in.",
        "Four triggers, one per zone, each all-in and independent of the others. They can activate only in "
        f"<strong>October, November and December</strong> \u2014 planning runs into September, so October is the "
        f"earliest month that can be acted on this year. Calibrated and backtested on {cal}.",
        "Each zone\u2019s return period starts from how often that zone has a major-impact window (at least 5 deaths "
        "or 5,000 people affected in one recorded event), then is <strong>raised as far as it can go without losing "
        "a big flood it already catches</strong>: "
        + ", ".join(
            f"{SHORT[z]} {rp_txt(s_.loc[z].design_rp)}"
            for z in ZONE_ORDER
            if not s_.loc[z].get("fixed", False)
        )
        + ". That trades activations for precision; it cannot add catches. Teso is the exception: it takes the "
        "IFRC trigger as it is.",
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
        f"do not forward it outside the team. <strong>Status:</strong> second draft, calibrated on {cal}. Teso now "
        "uses the IFRC/URCS trigger as the IBF portal runs it (reproduced on the GloFAS reanalysis); Elgon\u2019s "
        "likely choice waits on FAO. Nothing here is endorsed. <strong>Handed over to Pauline on 30 September "
        "2026</strong> \u2014 the next steps are at the foot of the page, and <code>HANDOVER.md</code> in the repo "
        "is the full write-up.</p>",
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
        "<h2>Timing, year by month</h2>",
        "<p>When floods happened in each zone and when its trigger activated, month by month. Hover a cell for the "
        "detail. The hollow dots are the point: they show the indicator crossing its threshold in months the "
        "October\u2013December window cannot act on.</p>",
        timing_grids(inp),
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
        "catches.</p>",
        raise_text(inp),
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
        fixed = bool(inp.s.loc[z].get("fixed", False))
        rp_lab = "Return period (the protocol\u2019s own)" if fixed else "Design return period"
        parts += [
            f"<h2><span class='sw' style='background:{bp.ZONE_COL[z]}'></span>{bp.e(ZONES[z].label.split(' (')[0])}</h2>",
            f"<p><strong>Activates when</strong> {what}. <strong>Lead time:</strong> {lead}. "
            f"<strong>{rp_lab}:</strong> {rp_txt(inp.s.loc[z].design_rp)}.</p>",
            zone_map(z),
            f"<p>{zone_note(z, inp)}</p>",
        ]
        if z == "teso_kyoga":
            parts.append(ifrc_section(inp))
        if cols:
            parts += [
                "<p><strong>Alongside existing triggers</strong> (grey), over the same years:</p>",
                compare_table(
                    z, inp.tabs[z], cols, "IFRC trigger (Teso\u2019s)" if fixed else "Our draft"
                ),
                existing_notes(cols),
            ]
        parts.append(zone_table(z, inp, cols))
        if z == "teso_kyoga":
            parts.append(teso_exploration())
        if z == "karamoja":
            parts.append(karamoja_section(inp))
        if z == "adjumani":
            parts.append(adjumani_section(inp))
    parts.append(fallback_section(inp))
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
        "<li><strong>CERF</strong> marks Uganda\u2019s two CERF flood allocations \u2014 07-RR-UGA-11920 (approved 4 "
        "October 2007, $6.0M) and 20-RR-UGA-40553 (approved 17 January 2020, $3.95M, for the September\u2013December "
        "2019 floods) \u2014 only in the zones they reached, per the Resident Coordinator\u2019s report on each. 2007 "
        "targeted Teso and Karamoja, with the Elgon districts covered but not the focus; 2020 targeted Elgon, "
        "including the Kumi and Pallisa lowlands, alongside Rwenzori outside the zones. Neither reached West Nile. "
        "Attribution and evidence are in <code>src/data/cerf_allocations.csv</code>.</li>"
        "</ul>",
        "<h2>Data and methods</h2>",
        "<ul>"
        "<li><strong>GloFAS v4</strong> river discharge, reanalysis 1999–2024 for the Uganda box (EWDS), at G5196 "
        "“Akokorio at Uganda” (the local Akokoro river, 33.875°E 1.775°N) and G5220 Manafwa at Butaleja. "
        "Thresholds are in model space: the model runs about 1.7× wet at G5196. For the IFRC trigger, the "
        "official GloFAS v4 5-year return-level map, read per district, county and sub-county as the IBF portal "
        "does.</li>"
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
        "<h2>Next steps (handover, 30 September 2026)</h2>",
        "<ol>"
        "<li><strong>Confirm the IFRC trigger looks good.</strong> Ask URCS/510 for the portal\u2019s own trigger "
        "history and boundaries and compare with the reproduction; confirm the EAP is live for October\u2013December "
        "2026; settle which Teso districts count.</li>"
        "<li><strong>Put in FAO\u2019s processing</strong> for the Elgon trigger once they reply, and make it the "
        "Elgon trigger (the questions are in the handover notes on the partner page).</li>"
        "<li><strong>Finalise Karamoja and Adjumani:</strong> Karamoja\u2019s return period and rainfall reading "
        "(district mean or wettest pixel); whether Adjumani takes the compound lake-and-rain rule.</li>"
        "<li><strong>Set up monitoring</strong> for all four zones. Nothing runs yet. The rain thresholds were set on "
        "CHIRPS-GEFS v2, which CHC discontinued on 1 July 2026: recalibrate on CHIRPS3-GEFS before monitoring. Teso "
        "needs access to the IBF portal\u2019s trigger state.</li>"
        "</ol>",
        "<h2>Open questions</h2>",
        "<ul>"
        "<li><strong>The honest headline:</strong> matched to dated floods, these triggers catch few major events. "
        "Any of them would need the observational backstop behind it before it could be proposed as a mechanism.</li>"
        "<li><strong>Teso:</strong> the IFRC trigger is adopted for alignment, not skill \u2014 in this window "
        "no GloFAS reading has anticipatory skill for Teso. Add the FloodScan fallback (it catches October 2021). "
        "Confirm with URCS that EAP2021UG01 is live for October\u2013December 2026: the 2023 activation document "
        "gives the EAP\u2019s timeframe as 27 May 2021 to 27 May 2026, while IFRC GO lists operation MDRUG048 to "
        "30 November 2026. If a renewed EAP changes the districts, probability or return period, the Teso trigger "
        "follows it.</li>"
        "<li><strong>Adjumani:</strong> decide whether to adopt the compound lake-and-rain rule, which catches "
        "2023 at the zone\u2019s own frequency.</li>"
        "<li><strong>FloodScan fallback:</strong> Teso only in this window; none for Elgon, Karamoja or "
        "Adjumani.</li>"
        "<li><strong>Longer windows:</strong> test a 15- or 30-day accumulation for prolonged seasons such as "
        "2007.</li>"
        "<li><strong>Staging:</strong> an all-in envelope is released by the first activation. A readiness/action "
        "split would let a later activation in the same season still act \u2014 which is exactly what late 2019 in "
        "Elgon needed.</li>"
        "<li><strong>Karamoja funding:</strong> all-in for the zone, or per district.</li>"
        "<li><strong>Adjumani:</strong> the lake leg gives months of warning, so a window opening on 1 October "
        "truncates it; consider reading Lake Albert directly and allowing an earlier readiness decision.</li>"
        "<li><strong>Return periods:</strong> frequency-matching with a 1-in-3 floor is a judgement; the sensitivity "
        "table shows the trade-off.</li>" + inp.ptext.get("next_step", "") + "</ul>",
        # partner-specific next steps come from the gitignored config, never this source
        "<h2>Reproducing this page</h2>",
        "<p>In <code>OCHA-DAP/ds-aa-uga-flooding</code>, with the partner config in place (see the README):</p>"
        "<pre>uv run python analysis/ifrc_reproduction.py     # needs the official RL5 map in data/glofas/thresholds/\n"
        "uv run python analysis/trigger_draft.py\nuv run python analysis/existing_triggers.py\n"
        "uv run python analysis/floodscan_vs_impact.py\nuv run python analysis/floodscan_fallback.py\n"
        "uv run python analysis/adjumani_options.py\nuv run python pipeline/zone_trigger_maps.py\n"
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
