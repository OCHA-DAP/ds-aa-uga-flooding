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
    for z in ZONE_LABEL:
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
    for z, label in ZONE_LABEL.items():
        if z in daily:
            ax.plot(
                daily.index,
                daily[z] * 100,
                color=ZONE_COLOR[z],
                lw=1.8,
                marker="o",
                ms=2.5,
                label=label,
            )
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


def _fmt(v: float, unit: str) -> str:
    if not np.isfinite(v):
        return "n/a"
    if unit == "households":
        return f"{v:,.0f} households"
    if unit == "share of members":
        return f"{v:.0%} of members"
    if unit == "m":
        return f"{v:+.2f} m"
    if unit.startswith("mm in 72"):
        return f"{v:.0f} mm in 72 h"
    if unit.startswith("mm in 5"):
        return f"{v:.0f} mm in 5 days"
    return f"{v:.2f} {unit}"


def trigger_lines(day: pd.DataFrame) -> dict[str, list[str]]:
    """Per zone, one line per trigger: met or not, the closest place, its reading and threshold."""
    out: dict[str, list[str]] = {}
    for z in ZONE_LABEL:
        lines = []
        g = day[day.zone == z].assign(c=closeness(day[day.zone == z]))
        for trig, t in g.groupby("trigger", sort=False):
            if t.met.isna().all():
                lines.append(f"<b>{trig}</b>: not evaluated | {t.detail.iloc[0]}")
                continue
            met = t[t.met.eq(True)]
            top = (met if len(met) else t).sort_values("c", ascending=False).iloc[0]
            state = "MET" if len(met) else "not met"
            where = ", ".join(met.place) if len(met) else top.place
            lines.append(
                f"<b>{trig}</b>: {state} | {'met in' if len(met) else 'closest'} {where}: "
                f"{_fmt(top.value, top.unit)} against {_fmt(top.threshold, top.unit)} "
                f"| {top.detail}"
            )
        out[z] = lines
    return out


def data_dates(day: pd.DataFrame) -> list[str]:
    """Each product with the date of the data actually read (issue, run, file or pass)."""
    ok = day[day.met.notna()]
    out = []
    for label, mask in (
        ("GloFAS issue", ok.source.str.startswith("GloFAS")),
        ("CHIRPS3-GEFS issue", ok.source.str.startswith("CHIRPS3")),
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


def render(day: pd.DataFrame, season: pd.DataFrame, chart_url: str) -> tuple[str, str]:
    issue = pd.Timestamp(day.issue_date.iloc[0])
    zmet = [z for z in ZONE_LABEL if day[day.zone == z].met.eq(True).any()]
    zgap = [z for z in ZONE_LABEL if z not in zmet and day[day.zone == z].met.isna().any()]
    gaps = day[day.met.isna()]
    if zmet:
        head = "Trigger met: " + ", ".join(ZONE_LABEL[z] for z in zmet)
    elif zgap:
        head = "No trigger met; not fully evaluated: " + ", ".join(ZONE_LABEL[z] for z in zgap)
    else:
        head = "No zone trigger met"
    subject = f"Uganda floods | {issue:%d %b %Y} | {head}"

    st = season_table(season)
    first_run, n_runs = pd.Timestamp(season.issue_date.min()), season.issue_date.nunique()
    srows = "".join(
        f"<tr><td style='padding:2px 10px 2px 0'>{ZONE_LABEL[r.zone]}</td>"
        f"<td style='padding:2px 10px 2px 0'>"
        f"{season_state(r)}"
        f"</td><td style='padding:2px 0;color:#666'>{plural(r.days, 'issue day')}"
        f"{f', {r.days_with_gaps} with missing data' if r.days_with_gaps else ''}</td></tr>"
        for r in st.itertuples()
    )
    lines = trigger_lines(day)
    blocks = "".join(
        f"<h3 style='margin:16px 0 4px;font-size:15px'>{ZONE_LABEL[z]}</h3>"
        + "".join(f"<p style='margin:2px 0;font-size:13px'>{x}</p>" for x in lines[z])
        for z in ZONE_LABEL
    )
    sources = data_dates(day)
    gap_html = (
        "<p style='font-size:13px'><b>Missing today:</b> "
        + "; ".join(sorted({f"{r.trigger} ({r.detail})" for r in gaps.itertuples()}))
        + "</p>"
        if len(gaps)
        else ""
    )
    body = f"""
<p style='font-size:16px'><b>{head}</b> for the forecasts issued on {issue:%d %B %Y}.</p>
{gap_html}
<p style='font-size:13px;margin-bottom:2px'><b>Season so far</b>: {plural(n_runs, "daily run")} since {first_run:%d %B} (window 1 October to 31 December):</p>
<table style='font-size:13px;border-collapse:collapse'>{srows}</table>
<p><img src='{chart_url}' alt='closest reading to threshold by zone' style='max-width:100%'></p>
<p style='font-size:12px;color:#666;margin-top:0'>Where a trigger has two conditions, the
line shows the first only; the second is in the zone's lines below.</p>
{blocks}
<p style='font-size:12px;color:#666;margin-top:16px'>Data used: {" | ".join(sources)}.<br>
Teso: the IBF portal's rule reproduced on the GloFAS forecast, not the portal's own state.
Mount Elgon: the partner's draft triggers as rebuilt by us. Karamoja and Adjumani rain: draft
thresholds calibrated on the CHIRPS3-GEFS hindcast. Adjumani lake: draft threshold on the
Lake Kyoga altimetry record.</p>
"""
    return subject, body


# --- send --------------------------------------------------------------------------------------


def send(day: pd.DataFrame, season: pd.DataFrame) -> dict:
    dry = env_flag("DRY_RUN", True)
    test = env_flag("TEST_EMAIL", True)
    issue = pd.Timestamp(day.issue_date.iloc[0])
    print(f"email mode: DRY_RUN={dry} TEST_EMAIL={test}")
    png = chart(season, OUT_DIR / f"uga_floods_{issue:%Y-%m-%d}.png")
    if dry:
        subject, body = render(day, season, png.name)
        html = OUT_DIR / f"uga_floods_{issue:%Y-%m-%d}.html"
        html.write_text(f"<h2>{subject}</h2>{body}", encoding="utf-8")
        print(f"dry run: wrote {html}")
        return {"sent": False, "subject": subject, "html": str(html)}

    from ocha_relay.listmonk import ListmonkClient

    if test:
        list_id = int(os.getenv("LISTMONK_TEST_LIST_ID", "103"))
        live = os.getenv("LISTMONK_LIST_ID")
        if live and int(live) == list_id:
            raise SystemExit("LISTMONK_TEST_LIST_ID is the live list: refusing a test send")
    else:
        if not os.getenv("LISTMONK_LIST_ID"):
            raise SystemExit("TEST_EMAIL=false needs LISTMONK_LIST_ID (no live list is set)")
        list_id = int(os.environ["LISTMONK_LIST_ID"])
    client = ListmonkClient.from_env()
    url = client.upload_media(png.read_bytes(), png.name)
    subject, body = render(day, season, url)
    name = f"uga-floods-{issue:%Y-%m-%d}"
    if test:
        subject, name = f"[TEST] {subject}", f"[test] {name}"
    cid = client.create_campaign(name=name, subject=subject, body=body, list_ids=[list_id])
    client.send_campaign(cid, skip_confirmation=True)
    print(f"sent campaign {cid} to list {list_id}: {subject}")
    out = {"sent": True, "campaign": cid, "list": list_id, "subject": subject, "test": test}
    return out | verify_delivery(client, cid)


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
