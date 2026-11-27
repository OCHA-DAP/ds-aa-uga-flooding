"""Render and send the daily Uganda flood monitoring email (Listmonk, via ocha-relay).

Run modes, as in the team's email-testing convention (strict parsing, safe defaults):

  DRY_RUN=true       (default) render to monitoring/out/ and send nothing
  TEST_EMAIL=true    (default) send to the test list (LISTMONK_TEST_LIST_ID, default 103),
                     subject prefixed [TEST]
  LISTMONK_LIST_ID   the live list; required when TEST_EMAIL=false, refused otherwise

The email states what the data shows: per zone, met or not and the closest reading to its
threshold; the season so far; the dates of the data used and anything missing.
"""

from __future__ import annotations

import os
import time
from html import escape
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

OUT_DIR = Path(__file__).resolve().parent / "out"
ZONE_LABEL = {
    "teso_kyoga": "Teso / Lake Kyoga",
    "elgon": "Mount Elgon",
    "karamoja": "Karamoja",
    "adjumani": "Adjumani / Albert Nile",
}
ZONE_COLOR = {
    "teso_kyoga": "#1f6fb2",
    "elgon": "#c0392b",
    "karamoja": "#d68910",
    "adjumani": "#16a085",
}
# Zones whose trigger belongs to another organisation: (short name, name in full). The email
# shows our reading of it for information, in grey; whether it is met is for them to confirm.
PARTNER_LED = {
    "teso_kyoga": ("URCS", "the Uganda Red Cross Society (URCS)"),
    "elgon": ("FAO", "FAO"),
}


def zones() -> list[str]:
    """Display order: our zones first, the partner-led (grey) zones last."""
    return [z for z in ZONE_LABEL if z not in PARTNER_LED] + [
        z for z in ZONE_LABEL if z in PARTNER_LED
    ]


TRUE = {"true", "1", "yes"}
FALSE = {"false", "0", "no"}


def env_flag(name: str, default: bool) -> bool:
    v = os.getenv(name)
    if v is None or v == "":
        return default
    if v.strip().lower() in TRUE:
        return True
    if v.strip().lower() in FALSE:
        return False
    raise ValueError(f"{name}={v!r}: expected true or false")


# --- numbers -----------------------------------------------------------------------------------


def closeness(day: pd.DataFrame) -> pd.Series:
    """Per row, the reading as a share of its threshold (rain only for T3: the soil condition
    is reported beside it, not folded in). Negative readings count as 0."""
    r = (day.value / day.threshold).clip(lower=0)
    return r.where(day.met.notna())


def season_table(season: pd.DataFrame) -> pd.DataFrame:
    """Per zone: first issue day met this season, issue days evaluated, issue days with gaps."""
    rows = []
    for z in zones():
        g = season[season.zone == z]
        met_days = sorted(g[g.met.eq(True)].issue_date.unique())
        gap_days = sorted(g[g.met.isna()].issue_date.unique())
        rows.append(
            dict(
                zone=z,
                first_met=pd.Timestamp(met_days[0]) if met_days else None,
                days_met=len(met_days),
                days=g.issue_date.nunique(),
                days_evaluated=g[g.met.notna()].issue_date.nunique(),
                days_with_gaps=len(gap_days),
            )
        )
    return pd.DataFrame(rows)


def plural(n: int, word: str) -> str:
    return f"{n} {word}" + ("" if n == 1 else "s")


def season_state(r) -> str:
    """First day met; "not evaluated" when no day had the data; otherwise "not met"."""
    if pd.notna(r.first_met):
        return "first met " + pd.Timestamp(r.first_met).strftime("%d %b")
    return "not met" if r.days_evaluated else "not evaluated"


def chart(season: pd.DataFrame, path: Path) -> Path:
    s = season.assign(c=closeness(season))
    daily = s.groupby(["issue_date", "zone"]).c.max().unstack("zone")
    fig, ax = plt.subplots(figsize=(8, 3.6), dpi=150)
    for z in zones():
        label = ZONE_LABEL[z]
        if z in daily:
            partner = z in PARTNER_LED
            ax.plot(
                daily.index,
                daily[z] * 100,
                color=ZONE_COLOR[z],
                alpha=0.4 if partner else 1.0,
                lw=1.2 if partner else 1.8,
                marker="o",
                ms=2.5,
                label=f"{label} ({PARTNER_LED[z][0]})" if partner else label,
            )
            over = daily[z] >= 1
            if partner and over.any():  # a reading at its threshold is never drawn pale
                ax.plot(daily.index[over], daily[z][over] * 100, "o", color=ZONE_COLOR[z], ms=3.5)
    year = pd.Timestamp(season.issue_date.max()).year
    lo, hi = pd.Timestamp(year, 10, 1), pd.Timestamp(year, 12, 31)
    ax.set_xlim(lo, hi)
    ax.xaxis.set_major_locator(mdates.MonthLocator())
    ax.xaxis.set_minor_locator(mdates.WeekdayLocator(byweekday=0))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d %b"))
    ax.axhline(100, color="#222", lw=1, ls="--")
    ax.text(lo, 102, "threshold", fontsize=8, va="bottom", color="#222")
    top = max(110.0, float(np.nanmax(daily.to_numpy()) * 100) * 1.05)
    ax.set_ylim(0, top)
    ax.set_ylabel("closest reading, % of threshold", fontsize=8)
    ax.tick_params(labelsize=8)
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(fontsize=7, frameon=False, ncol=4, loc="upper left", bbox_to_anchor=(0, -0.12))
    ax.set_title(
        "Each zone's closest reading to its threshold, by issue day",
        fontsize=10,
        loc="left",
        fontweight="bold",
    )
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, facecolor="white")
    plt.close(fig)
    return path


# --- text --------------------------------------------------------------------------------------


def _fmt(v: float, unit: str, dp: int = 0) -> str:
    """dp: extra decimals, for a reading that would otherwise round to its threshold."""
    if not np.isfinite(v):
        return "n/a"
    if unit == "households":
        return f"{v:,.0f} households"
    if unit == "share of members":
        return f"{v:.{dp}%} of members"
    if unit == "m":
        return f"{v:+.{2 + dp}f} m"
    if unit.startswith("mm in 72"):
        return f"{v:.{dp}f} mm in 72 h"
    if unit.startswith("mm in 5"):
        return f"{v:.{dp}f} mm in 5 days"
    return f"{v:.{2 + dp}f} {unit}"


def trigger_rows(day: pd.DataFrame) -> list[dict]:
    """One row per (zone, trigger) for the results table: the result, where it was met (or the
    closest place), its reading and threshold, and the detail line."""
    rows = []
    for z in ZONE_LABEL:
        g = day[day.zone == z].assign(c=closeness(day[day.zone == z]))
        for trig, t in g.groupby("trigger", sort=False):
            n_gap = int(t.met.isna().sum())
            if n_gap == len(t):
                rows.append(
                    dict(
                        zone=z,
                        trigger=trig,
                        state="not evaluated",
                        where="",
                        reading="n/a",
                        threshold="",
                        note=t.detail.iloc[0],
                        crossed=False,
                    )
                )
                continue
            met = t[t.met.eq(True)]
            # stable: among equal readings, keep the order evaluate gave (Teso: closest first)
            top = (
                (met if len(met) else t[t.met.notna()])
                .sort_values("c", ascending=False, kind="stable")
                .iloc[0]
            )
            if len(met):
                state = "MET"
            elif n_gap:
                state = f"not met ({n_gap} of {len(t)} places not evaluated)"
            else:
                state = "not met"
            reading, threshold = _fmt(top.value, top.unit), _fmt(top.threshold, top.unit)
            if reading == threshold and top.value != top.threshold:  # 39.7 vs 40.2 -> "40" twice
                reading, threshold = _fmt(top.value, top.unit, 1), _fmt(top.threshold, top.unit, 1)
            rows.append(
                dict(
                    zone=z,
                    trigger=trig,
                    state=state,
                    where=", ".join(met.place) if len(met) else f"{top.place} (closest)",
                    reading=reading,
                    threshold=threshold,
                    note=top.detail,
                    # reading at or over its threshold: true on a met row; on a "not met" row
                    # only when another condition failed (Elgon T3: rain over, soil too dry)
                    crossed=bool(top.value >= top.threshold),
                )
            )
    return rows


def data_dates(day: pd.DataFrame) -> list[str]:
    """Each product with the date of the data actually read (issue, run, file or pass)."""
    ok = day[day.met.notna()]
    out = []
    for label, mask in (
        ("GloFAS issue", ok.source.str.startswith("GloFAS")),
        ("CHIRPS3-GEFS issue", ok.source.str.startswith("CHIRPS3")),
        ("GEFS control run (00 UTC)", ok.source.str.startswith("GEFS control")),
        ("GFS and ICON runs (Open-Meteo)", ok.source.str.contains("Open-Meteo")),
    ):
        if mask.any():
            out.append(f"{label} {ok[mask].source_date.max()}")
    cpc = ok.detail.str.extract(r"CPC (\d{4}-\d{2}-\d{2})")[0].dropna()
    if len(cpc):
        out.append(f"CPC soil moisture {cpc.max()}")
    lake = ok[ok.trigger.str.startswith("Lake")]
    if len(lake):
        out.append(f"Lake Kyoga satellite pass {lake.source_date.iloc[0]}")
    return out


# Inline styles only: the email is read in Outlook, which ignores <style> blocks.
_TABLE = "border-collapse:collapse;font-size:13px;width:100%;max-width:760px"
_TH = (
    "text-align:left;padding:6px 8px;background:#eef2f6;border-bottom:1px solid #c9d1da;"
    "font-weight:bold"
)
_TD = "padding:6px 8px;border-bottom:1px solid #e3e6ea;vertical-align:top"
# Result cells: red = met, green = not met, yellow = not (fully) evaluated.
_MET = "background-color:#c62828;color:#ffffff;font-weight:bold"
_NOT_MET = "background-color:#c8e6c9;color:#1b5e20"
_GAP = "background-color:#ffe08a;color:#5c4300;font-weight:bold"
_THRESHOLD = "font-style:italic;color:#555555"
# Rows of a partner-led zone are grey, except the result and reading cells, which keep their
# colour so that a met trigger still shows.
_PARTNER = "background-color:#f1f2f4;color:#5f6368;border-bottom-color:#d0d5db"


def _state_style(state: str) -> str:
    """Background for a result cell. "not met" with some places not evaluated is a gap, not a
    clean "not met", so it is yellow."""
    if state == "MET" or state.startswith("first met"):
        return _MET
    if "not evaluated" in state:
        return _GAP
    return _NOT_MET if state == "not met" else ""


def _grey(z: str) -> str:
    """Style to append to a cell of zone z: grey if the zone is partner-led."""
    return f";{_PARTNER}" if z in PARTNER_LED else ""


def _zone_cell(z: str, style: str = "", attrs: str = "") -> str:
    """The zone's name; for a partner-led zone, in grey and with who confirms its trigger."""
    label = ZONE_LABEL[z]
    if z in PARTNER_LED:
        label += (
            "<br><span style='font-size:11px;font-weight:normal'>for information; confirm "
            f"with {PARTNER_LED[z][0]}</span>"
        )
    return f"<td{attrs} style='{_TD}{style}{_grey(z)}'>{label}</td>"


def _and(items: list[str]) -> str:
    return ", ".join(items[:-1]) + " and " + items[-1] if len(items) > 1 else "".join(items)


def partner_note() -> str:
    """Which zones are in grey, and who confirms their triggers. A one-cell table: Outlook
    ignores padding and borders on a paragraph."""
    if not PARTNER_LED:
        return ""
    names = _and([ZONE_LABEL[z] for z in PARTNER_LED])
    whose = _and([f"{full} for {ZONE_LABEL[z]}" for z, (_, full) in PARTNER_LED.items()])
    return (
        f"<table cellpadding='0' cellspacing='0' style='{_TABLE};margin:0 0 12px'><tr>"
        "<td style='background-color:#f1f2f4;color:#333333;padding:8px 10px;"
        f"border-left:4px solid #9aa0a6;font-size:14px'>{names} are in grey because other "
        f"organisations are responsible for their triggers: {whose}. Our readings for these "
        "zones are for information only. Whether a trigger there is met or not met should be "
        "confirmed with that zone's organisation.</td></tr></table>"
    )


def _table(head: list[str], body: str) -> str:
    th = "".join(f"<th style='{_TH}'>{h}</th>" for h in head)
    return f"<table cellpadding='0' cellspacing='0' style='{_TABLE}'><tr>{th}</tr>{body}</table>"


def season_html(season: pd.DataFrame) -> str:
    rows = ""
    for r in season_table(season).itertuples():
        state = season_state(r)
        # "not met" is green only if every day was fully evaluated: a day with missing data
        # could have been a day the trigger was met
        style = _GAP if state == "not met" and r.days_with_gaps else _state_style(state)
        why = (
            "<br><span style='font-size:11px;font-weight:normal'>data missing on "
            f"{plural(r.days_with_gaps, 'day')}</span>"
            if style == _GAP and state == "not met"
            else ""
        )
        g = _grey(r.zone)
        rows += (
            f"<tr>{_zone_cell(r.zone)}"
            f"<td style='{_TD};{style}'>{state}{why}</td>"
            f"<td style='{_TD}{g}'>{r.days_met}</td>"
            f"<td style='{_TD}{g}'>{r.days}</td>"
            f"<td style='{_TD}{g}'>{r.days_with_gaps}</td></tr>"
        )
    return _table(["Zone", "Season so far", "Days met", "Days run", "Days with missing data"], rows)


def results_html(day: pd.DataFrame) -> str:
    rows = trigger_rows(day)
    body = ""
    for z in zones():
        zr = [r for r in rows if r["zone"] == z]
        g = _grey(z)
        for i, r in enumerate(zr):
            zone_cell = (
                _zone_cell(z, ";font-weight:bold", f" rowspan='{2 * len(zr)}'") if i == 0 else ""
            )
            last = i == len(zr) - 1
            sep = "" if last else ";border-bottom:none"
            # the reading takes the result's colour; the threshold is italic and grey, so the
            # two are told apart at a glance. A reading over its threshold on a row that is not
            # met (another condition failed, given in the note) is left unfilled, not green.
            st = _state_style(r["state"])
            rst = g.lstrip(";") if r.pop("crossed") and r["state"] != "MET" else st
            r = {k: escape(str(v)) for k, v in r.items()}
            nw = "border-bottom:none;white-space:nowrap"
            body += (
                f"<tr>{zone_cell}"
                f"<td style='{_TD};border-bottom:none{g}'>{r['trigger']}</td>"
                f"<td style='{_TD};border-bottom:none;{st}'>{r['state']}</td>"
                f"<td style='{_TD};border-bottom:none{g}'>{r['where']}</td>"
                f"<td style='{_TD};{nw};{rst}'>{r['reading']}</td>"
                f"<td style='{_TD};{nw};{_THRESHOLD}{g}'>{r['threshold']}</td></tr>"
                f"<tr><td colspan='5' style='{_TD}{sep};padding-top:0;font-size:11px;"
                f"color:#666{g}'>{r['note']}</td></tr>"
            )
    return _table(["Zone", "Trigger", "Result", "Where", "Reading", "Threshold"], body)


def render(
    day: pd.DataFrame, season: pd.DataFrame, chart_url: str, version_note: str = ""
) -> tuple[str, str]:
    issue = pd.Timestamp(day.issue_date.iloc[0])
    zmet = [z for z in zones() if day[day.zone == z].met.eq(True).any()]
    zgap = [z for z in zones() if z not in zmet and day[day.zone == z].met.isna().any()]
    if zmet:
        head = "Trigger met: " + ", ".join(ZONE_LABEL[z] for z in zmet)
    elif zgap:
        head = "No trigger met; not fully evaluated: " + ", ".join(ZONE_LABEL[z] for z in zgap)
    else:
        head = "No zone trigger met"
    subject = f"Uganda floods | {issue:%d %b %Y} | {head}"

    first_run, n_runs = pd.Timestamp(season.issue_date.min()), season.issue_date.nunique()
    sources = data_dates(day)
    h = "style='font-size:15px;margin:20px 0 6px'"
    paler = " The paler lines are the zones shown for information." if PARTNER_LED else ""
    body = f"""
<p style='font-size:16px'><b>{head}</b> for the forecasts issued on {issue.day} {issue:%B %Y}.</p>
{partner_note()}
<h3 {h}>Season so far</h3>
<p style='font-size:12px;color:#666;margin:0 0 6px'>{plural(n_runs, "daily run")} since
{first_run.day} {first_run:%B}; the window is 1 October to 31 December.</p>
{season_html(season)}
<p style='margin:12px 0 0'><img src='{chart_url}' alt='closest reading to threshold by zone'
style='max-width:100%'></p>
<p style='font-size:12px;color:#666;margin-top:0'>For a trigger with two conditions, the chart
shows the first; the second is in the table below.{paler}</p>
<h3 {h}>Today's results</h3>
{results_html(day)}
<p style='font-size:12px;color:#666;margin-top:16px'>Data used: {" | ".join(sources)}.<br>
Teso: the IBF portal's rule reproduced on the GloFAS forecast, not the portal's own state.
Mount Elgon: FAO's draft triggers as rebuilt by us, read on the data our backtest used.
Karamoja and Adjumani rain: draft thresholds calibrated on the CHIRPS3-GEFS hindcast. Adjumani
lake: draft threshold on the Lake Kyoga altimetry record. The GloFAS thresholds are v4.
{escape(version_note)}</p>
"""
    return subject, body


# --- send --------------------------------------------------------------------------------------


def _list_id(name: str, default: str | None = None) -> int | None:
    v = (os.getenv(name) or default or "").strip()
    if not v:
        return None
    if not v.isdigit():
        raise SystemExit(f"{name}={v!r}: expected a Listmonk list id")
    return int(v)


def target_list(test: bool) -> int:
    """The list this run sends to; refuses the unsafe combinations."""
    if test:
        list_id = _list_id("LISTMONK_TEST_LIST_ID", "103")
        if list_id == _list_id("LISTMONK_LIST_ID"):
            raise SystemExit("LISTMONK_TEST_LIST_ID is the live list: refusing a test send")
        return list_id
    list_id = _list_id("LISTMONK_LIST_ID")
    if list_id is None:
        raise SystemExit("TEST_EMAIL=false needs LISTMONK_LIST_ID (no live list is set)")
    return list_id


def check_config() -> tuple[bool, bool]:
    """Parse the run mode and check the send settings before any waiting or writing, so a
    mistake fails the run at the start, not hours later with nothing sent. (DRY_RUN, TEST_EMAIL)"""
    dry = env_flag("DRY_RUN", True)
    test = env_flag("TEST_EMAIL", True)
    if not dry:
        target_list(test)
        from ocha_relay.listmonk import ListmonkClient

        ListmonkClient.from_env()  # missing Listmonk credentials fail here
    return dry, test


def send(
    day: pd.DataFrame, season: pd.DataFrame, on_live_send=None, version_note: str = ""
) -> dict:
    """on_live_send(record) is called as soon as Listmonk accepts a live send, before the
    delivery check, so the caller can record it: a failure after that point must not lead a
    re-run to send the live email again."""
    dry = env_flag("DRY_RUN", True)
    test = env_flag("TEST_EMAIL", True)
    issue = pd.Timestamp(day.issue_date.iloc[0])
    print(f"email mode: DRY_RUN={dry} TEST_EMAIL={test}")
    png = chart(season, OUT_DIR / f"uga_floods_{issue:%Y-%m-%d}.png")
    if dry:
        subject, body = render(day, season, png.name, version_note)
        html = OUT_DIR / f"uga_floods_{issue:%Y-%m-%d}.html"
        html.write_text(f"<h2>{subject}</h2>{body}", encoding="utf-8")
        print(f"dry run: wrote {html}")
        return {"sent": False, "subject": subject, "html": str(html)}

    from ocha_relay.listmonk import ListmonkClient

    list_id = target_list(test)
    client = ListmonkClient.from_env()
    url = client.upload_media(png.read_bytes(), png.name)
    subject, body = render(day, season, url, version_note)
    name = f"uga-floods-{issue:%Y-%m-%d}"
    if test:
        subject, name = f"[TEST] {subject}", f"[test] {name}"
    cid = client.create_campaign(name=name, subject=subject, body=body, list_ids=[list_id])
    client.send_campaign(cid, skip_confirmation=True)
    print(f"sent campaign {cid} to list {list_id}: {subject}")
    out = {"sent": True, "campaign": cid, "list": list_id, "subject": subject, "test": test}
    if not test and on_live_send is not None:
        on_live_send(out)
    try:
        return out | verify_delivery(client, cid)
    except Exception as err:  # noqa: BLE001 - the email is out; the check only adds to the record
        print(f"WARNING campaign {cid}: delivery check failed ({type(err).__name__}: {err})")
        return out | {"delivered": False, "status": f"check failed: {type(err).__name__}"}


def verify_delivery(client, cid: int, attempts: int = 12, delay: float = 5.0) -> dict:
    """Poll the campaign until Listmonk reports every message sent. The shared instance has
    marked campaigns finished with nothing sent and no email received (Aug 2026), and also
    reported 0 sent for an email that did arrive (19 Nov 2026): the result is logged and kept
    with the send record, as a prompt to check, not as proof either way."""
    sent = to_send = 0
    status = ""
    for _ in range(attempts):
        time.sleep(delay)
        c = client.get_campaign(cid)
        c = c.get("data", c)
        sent, to_send, status = c.get("sent", 0), c.get("to_send", 0), c.get("status", "")
        if to_send and sent >= to_send:
            print(f"campaign {cid}: delivered to {sent}/{to_send}")
            return {"delivered": True, "delivered_to": sent, "to_send": to_send}
    print(
        f"WARNING campaign {cid}: {sent}/{to_send} delivered after {attempts * delay:.0f} s (status {status})"
    )
    return {"delivered": False, "delivered_to": sent, "to_send": to_send, "status": status}
