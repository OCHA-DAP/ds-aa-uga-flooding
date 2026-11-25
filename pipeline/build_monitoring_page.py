"""Build pages/monitoring/index.html: the season monitor, replayed issue day by issue day, restricted.

What it shows, per zone: whether the trigger was met on each issue day, how close it came, and
checks on the inputs: the Elgon rain forecasts against the rain observed afterwards (IMERG
late), the Karamoja and Adjumani rain forecasts against their own 2001-2025 hindcast, and the
Lake Kyoga reading as the monitor takes it and as the backtest smoothing would.

The Mount Elgon triggers are a partner's unpublished draft, so this page is built in plaintext
into the gitignored site_private/ and only an encrypted copy is written to pages/monitoring/
(pipeline/encrypt.py). Every sentence about the Elgon triggers comes from the private
monitoring_page.local.json (dev blob, private/config/; a local config/ copy overrides), filled
with numbers computed here; nothing partner-specific is written in this file.

Inputs (dev blob, ds-aa-uga-flooding/):
  private/monitoring/replay/season/{year}.parquet   monitoring/run.py replay of the season
  processed/chirps_gefs/chirps3_gefs_5day_adm2.parquet   the v3 hindcast
  IMERG late daily (prod blob, raster/imerg/daily/late/v7/), Lake Kyoga passes (NASA GWM)

  uv run python monitoring/run.py 2026-10-01 2026-11-18
  uv run python pipeline/build_monitoring_page.py [2026]

The plaintext page is written to site_private/, the encrypted one to pages/monitoring/ (password: pipeline/encrypt.py).
"""

from __future__ import annotations

import html as html_mod
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import ocha_stratus as stratus
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import build_pages as bp

from monitoring import evaluate as ev
from monitoring import feeds
from src.constants import PROJECT_PREFIX
from src.frameworks import read_private_config
from src.zonal import read_windowed, zonal_stats
from src.zones import load_adm2

PRIVATE = ROOT / "site_private"
CSS_V = "1"


def e(x) -> str:
    return html_mod.escape(str(x))


def ordinal(x: float) -> str:
    n = round(x)
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def day(ts) -> str:
    ts = pd.Timestamp(ts)
    return f"{ts.day} {ts:%b}"


def pct(x: float) -> str:
    return f"{round(x * 100)} %"


def clean(xs) -> list:
    return [None if x is None or not np.isfinite(x) else round(float(x), 4) for x in xs]


# --- data -------------------------------------------------------------------------------------


class Season:
    def __init__(self, year: int):
        blob = f"{PROJECT_PREFIX}/private/monitoring/replay/season/{year}.parquet"
        s = stratus.load_parquet_from_blob(blob, stage="dev")
        s["issue_date"] = pd.to_datetime(s.issue_date)
        self.s = s
        self.days = sorted(s.issue_date.unique())
        self.iso = [pd.Timestamp(d).strftime("%Y-%m-%d") for d in self.days]

    def per_day(self, df: pd.DataFrame, col: str = "value", how: str = "max") -> list:
        return clean(df.groupby("issue_date")[col].agg(how).reindex(self.days))

    def argmax_place(self, df: pd.DataFrame, col: str = "value") -> list:
        out = []
        for d in self.days:
            g = df[(df.issue_date == d) & df[col].notna()]
            out.append(None if g.empty else str(g.loc[g[col].idxmax(), "place"]))
        return out


def imerg_72h(districts: pd.DataFrame, start, end) -> pd.DataFrame:
    """IMERG late daily district means, summed over D, D+1, D+2 (the days a 72-hour forecast
    issued on D covers). Columns: district names; index: D."""

    def one(d):
        try:
            arr, b, w = read_windowed(
                f"imerg/daily/late/v7/processed/imerg-daily-late-{d:%Y-%m-%d}.tif"
            )
        except Exception:  # noqa: BLE001 - not published yet
            return None
        z = zonal_stats(arr, b, w, districts[["ADM2_PCODE", "geometry"]])
        z["date"] = d
        return z

    dates = pd.date_range(start, pd.Timestamp(end) + pd.Timedelta(days=2))
    with ThreadPoolExecutor(6) as ex:
        parts = [p for p in ex.map(one, dates) if p is not None]
    df = pd.concat(parts)
    df["district"] = df.pcode.map(dict(zip(districts.ADM2_PCODE, districts.ADM2_EN, strict=True)))
    daily = df.pivot_table(index="date", columns="district", values="mean").reindex(dates)
    return daily.rolling(3).sum().shift(-2)


def collect(year: int) -> dict:
    S = Season(year)
    s, days = S.s, S.days
    D: dict = {"days": S.iso}

    t = s[s.zone == "teso_kyoga"].copy()
    t["median"] = t.detail.str.extract(r"median ([\d.]+) x")[0].astype(float)
    D["teso"] = {
        "share": S.per_day(t),
        "median": S.per_day(t, "median"),
        "where": S.argmax_place(t, "median"),
        "met": [bool(t[t.issue_date == d].met.eq(True).any()) for d in days],
        "missing": [bool(t[t.issue_date == d].met.isna().all()) for d in days],
    }

    e_ = s[s.zone == "elgon"]
    rain = e_[e_.unit == "mm in 72 h"]
    t2 = e_[e_.unit == "households"]
    # the district charted: where the rain trigger was met most often, else the wettest forecast
    met_rows = rain[rain.met.eq(True)]
    focus = (
        met_rows.place.value_counts().idxmax()
        if len(met_rows)
        else rain.loc[rain.value.idxmax(), "place"]
    )
    models = {}
    for m in ("GFS", "ICON"):
        g = rain[rain.trigger.str.endswith(f"({m})")]
        models[m] = {
            "focus": S.per_day(g[g.place == focus]),
            "focus_met": [
                bool(g[(g.issue_date == d) & (g.place == focus)].met.eq(True).any()) for d in days
            ],
            "met_at": [
                [
                    {"place": r.place, "mm": float(r.value)}
                    for r in g[(g.issue_date == d) & g.met.eq(True)].itertuples()
                ]
                for d in days
            ],
        }
    adm = load_adm2()
    places = sorted(rain.place.unique())
    obs = imerg_72h(adm[adm.ADM2_EN.isin(places)], days[0], days[-1])
    soil = {
        p: clean(
            rain[rain.place == p]
            .groupby("issue_date")
            .detail.first()
            .reindex(days)
            .str.extract(r"soil moisture (\d+)")[0]
            .astype(float)
        )
        for p in places
    }
    D["elgon"] = {
        "models": models,
        "obs72": {p: clean(obs[p].reindex(days)) for p in places},
        "soil": soil,
        "focus": focus,
        "rain_thr": float(rain.threshold.dropna().iloc[0]),
        "t2": S.per_day(t2),
        "t2_missing": [bool(t2[t2.issue_date == d].met.isna().all()) for d in days],
    }

    hc = stratus.load_parquet_from_blob(
        f"{PROJECT_PREFIX}/processed/chirps_gefs/chirps3_gefs_5day_adm2.parquet", stage="dev"
    )
    pc = dict(zip(adm.ADM2_EN, adm.ADM2_PCODE, strict=True))
    hist = {p: hc[hc.pcode == p]["mean"].dropna().to_numpy() for p in hc.pcode.unique()}
    D["hindcast_seasons"] = int(pd.to_datetime(hc.issue_date).dt.year.nunique())
    for z in ("karamoja", "adjumani"):
        r = s[(s.zone == z) & s.unit.str.startswith("mm in 5") & s.value.notna()].copy()
        r["share"] = r.value / r.threshold
        # rank of each reading among that district's own Oct-Dec hindcast issue days
        r["rank"] = [
            float((hist[pc[p]] < v).mean() * 100) for p, v in zip(r.place, r.value, strict=True)
        ]
        top = r.loc[r.groupby("issue_date").share.idxmax()].set_index("issue_date").reindex(days)
        best = r.loc[r["rank"].idxmax()]
        peak = r.loc[r.share.idxmax()]
        D[z] = {
            "share": clean(top.share),
            "where": [None if pd.isna(x) else str(x) for x in top.place],
            "rank_top": clean(top["rank"]),  # rank of the reading closest to its threshold
            "met": [bool(s[(s.zone == z) & (s.issue_date == d)].met.eq(True).any()) for d in days],
            "missing": [
                bool(
                    s[(s.zone == z) & (s.issue_date == d) & s.unit.str.startswith("mm in 5")]
                    .met.isna()
                    .all()
                )
                for d in days
            ],
            "peak": {
                "place": peak.place,
                "day": str(peak.issue_date.date()),
                "value": float(peak.value),
                "thr": float(peak.threshold),
                "share": float(peak.share),
                "rank": float(peak["rank"]),
            },
            "best_rank": {
                "place": best.place,
                "day": str(best.issue_date.date()),
                "rank": float(best["rank"]),
            },
        }

    lake = s[(s.zone == "adjumani") & (s.unit == "m")]
    passes = feeds.kyoga_levels()
    full = ev.kyoga_rise(passes, pd.Timestamp("2100-01-01"))
    asof = [
        lake[lake.issue_date == d].source_date.iloc[0] if len(lake[lake.issue_date == d]) else None
        for d in days
    ]
    recent = passes[passes.date >= pd.Timestamp(days[0]) - pd.Timedelta(days=60)]
    D["lake"] = {
        "rise": S.per_day(lake),
        "rise_full": [
            None if a is None else round(float(full.loc[pd.Timestamp(a)]), 3) for a in asof
        ],
        "asof": asof,
        "threshold": float(lake.threshold.dropna().iloc[0]),
        "passes": [
            {"date": r.date.strftime("%Y-%m-%d"), "h": round(float(r.height_m), 2)}
            for r in recent.itertuples()
        ],
    }
    gaps = s[s.met.isna()][["issue_date", "zone", "trigger", "detail"]].drop_duplicates()
    D["gaps"] = [
        {
            "day": pd.Timestamp(r.issue_date).strftime("%Y-%m-%d"),
            "zone": r.zone,
            "trigger": r.trigger,
            "why": r.detail,
        }
        for r in gaps.itertuples()
    ]
    return D


# --- text ---------------------------------------------------------------------------------------


def hp(x: float) -> str:
    """A share as a whole percent, rounded half up once from the full value."""
    return f"{int(x * 100 + 0.5)} %"


def mm(x: float) -> str:
    return f"{int(x + 0.5)} mm"


def ranges(days_iso: list[str], flags: list[bool]) -> str:
    """'8 to 17 Nov, 19 Nov' for the days whose flag is set."""
    picked = [pd.Timestamp(d) for d, f in zip(days_iso, flags, strict=True) if f]
    if not picked:
        return ""
    out, start, prev = [], picked[0], picked[0]
    for d in [*picked[1:], None]:
        if d is not None and (d - prev).days == 1:
            prev = d
            continue
        out.append(day(start) if start == prev else f"{day(start)} to {day(prev)}")
        if d is not None:
            start = prev = d
    return ", ".join(out)


def reliefweb(start: str) -> list[dict]:
    """Uganda reports on ReliefWeb since `start` matching flood terms (API v2; the app name comes
    from RELIEFWEB_APPNAME, and the section is left out without it)."""
    app = os.getenv("RELIEFWEB_APPNAME")
    if not app:
        return []
    import urllib.request

    body = {
        "filter": {
            "operator": "AND",
            "conditions": [
                {"field": "country.iso3", "value": "uga"},
                {"field": "date.created", "value": {"from": f"{start}T00:00:00+00:00"}},
            ],
        },
        "query": {"value": "flood OR floods OR flooding OR landslide", "operator": "OR"},
        "fields": {"include": ["title", "date.created", "source.shortname", "url_alias"]},
        "sort": ["date.created:asc"],
        "limit": 50,
    }
    req = urllib.request.Request(
        f"https://api.reliefweb.int/v2/reports?appname={app}",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        data = json.load(r)["data"]
    return [
        {
            "date": f["fields"]["date"]["created"][:10],
            "title": f["fields"]["title"],
            "source": ", ".join(s["shortname"] for s in f["fields"].get("source", [])),
            "url": f["fields"].get("url_alias", ""),
        }
        for f in data
    ]


def card(name: str, cls: str, state: str, fact: str) -> str:
    return (
        f"<div class='zone {cls}'><div class='name'>{e(name)}</div>"
        f"<span class='state {cls}'>{e(state)}</span><div class='fact'>{e(fact)}</div></div>"
    )


def elgon(D: dict, txt: dict, cfg: dict) -> dict:
    E, days = D["elgon"], D["days"]
    G, I = E["models"]["GFS"], E["models"]["ICON"]
    entries = []  # (index, model, district, forecast, observed, soil)
    for i in range(len(days)):
        for m, mod in (("GFS", G), ("ICON", I)):
            for p in mod["met_at"][i]:
                entries.append(
                    (i, m, p["place"], p["mm"], E["obs72"][p["place"]][i], E["soil"][p["place"]][i])
                )
    met_days = sorted({x[0] for x in entries})
    both = [
        i
        for i in met_days
        if {p["place"] for p in G["met_at"][i]} & {p["place"] for p in I["met_at"][i]}
    ]
    obs_b = E["obs72"].get(E["focus"], [None] * len(days))
    rat = {
        m: [o / f for o, f in zip(obs_b, mod["focus"], strict=True) if o is not None and f]
        for m, mod in (("GFS", G), ("ICON", I))
    }
    soils = [v for col in E["soil"].values() for v in col if v is not None]
    t2_vals = [v for v in E["t2"] if v is not None]
    f = dict(
        n_days=len(met_days),
        focus=E["focus"],
        first_day=day(days[met_days[0]]) if met_days else "",
        places=" and ".join(sorted({x[2] for x in entries})),
        ratio_lo=min(
            (int(o / fc * 100 + 0.5) for *_, fc, o, _s in entries if o is not None), default=0
        ),
        ratio_hi=max(
            (int(o / fc * 100 + 0.5) for *_, fc, o, _s in entries if o is not None), default=0
        ),
        rain_thr=f"{E['rain_thr']:g}",
        soil_thr=ordinal(float(cfg["antecedent_pctl"])),
        n_districts=len(cfg["districts"]),
        soil_all_lo=ordinal(min(soils)) if soils else "n/a",
        n_obs=len(rat["GFS"]),
        med_gfs=int(np.median(rat["GFS"]) * 100 + 0.5) if rat["GFS"] else "n/a",
        med_icon=int(np.median(rat["ICON"]) * 100 + 0.5) if rat["ICON"] else "n/a",
        obs_max=int(max(v for v in obs_b if v is not None) + 0.5)
        if any(v is not None for v in obs_b)
        else "n/a",
        both_n=len(both),
        both_days=f" ({', '.join(day(days[i]) for i in both)})" if both else "",
        t2_share=int(float(cfg["t2"].get("share", ev.IFRC_SHARE)) * 100 + 0.5),
        t2_thr=f"{float(cfg['t2']['households']):,.0f}",
        t2_days=len(t2_vals),
        t2_max=f"{max(t2_vals):,.0f}" if t2_vals else "n/a",
    )
    t = {
        k: (
            v.format(**f)
            if isinstance(v, str)
            else [x.format(**f) for x in v]
            if isinstance(v, list) and all(isinstance(x, str) for x in v)
            else v
        )
        for k, v in txt.items()
    }
    rows = "".join(
        f"<tr><td>{day(days[i])}</td><td>{e(m)}</td><td>{e(pl)}</td><td class='n'>{mm(fc)}</td>"
        f"<td class='n'>{mm(o) if o is not None else 'not yet'}</td>"
        f"<td class='n'>{hp(o / fc) if o is not None else ''}</td>"
        f"<td class='n'>{ordinal(s_) if s_ is not None else ''}</td></tr>"
        for i, m, pl, fc, o, s_ in entries
    )
    head = "".join(f"<th>{e(h)}</th>" for h in t["table_head"])
    met_idx, met_val = [], []
    for mod in (G, I):
        for i, flag in enumerate(mod["focus_met"]):
            if flag:
                met_idx.append(i)
                met_val.append(mod["focus"][i])
    spec = dict(
        id="c-elgon",
        title=t["chart_title"],
        unit="mm",
        series=[
            dict(name=t["series"]["GFS"], values=G["focus"], color="--s1"),
            dict(name=t["series"]["ICON"], values=I["focus"], color="--s2"),
            dict(name=t["series"]["obs"], values=obs_b, color="--s3"),
        ],
        lines=[dict(y=E["rain_thr"], label=t["threshold_label"].format(**f))],
        met=met_idx,
        metValues=met_val,
        metLabel=t["met_label"],
        extra=[
            dict(
                label=f"{E['focus']} soil moisture, percentile",
                values=E["soil"].get(E["focus"]),
                unit="raw",
            )
        ],
    )
    html = (
        f"<h2>{e(t['h_met'] if met_days else t['h_not'])}</h2><p>{e(t['p'])}</p>"
        "<div class='chart' id='c-elgon'></div>"
        + (
            f"<p>{e(t['chart_note'])}</p><div class='tw'><table><thead><tr>{head}</tr></thead>"
            f"<tbody>{rows}</tbody></table></div>"
            if entries
            else ""
        )
        + f"<p>{e(t['t2'])}</p>"
    )
    return dict(
        met=bool(met_days),
        card=card(
            "Mount Elgon",
            "met" if met_days else "not",
            "Met" if met_days else "Not met",
            t["card_met"] if met_days else t["card_not"],
        ),
        html=html,
        spec=spec,
        open=t["open"],
        probes=[t["h_met"][:40], t["p"][:40], t["t2"][:40]],
    )


def teso(D: dict) -> dict:
    T, days = D["teso"], D["days"]
    have = [not m for m in T["missing"]]
    k, n = sum(have), len(days)
    share = [(v, i) for i, v in enumerate(T["share"]) if v is not None]
    med = [(v, i) for i, v in enumerate(T["median"]) if v is not None]
    met = any(T["met"])
    smax, si = max(share) if share else (None, None)
    mmax, mi = max(med) if med else (None, None)
    gap = ranges(days, T["missing"])
    h = (
        f"Teso: the trigger was met on {sum(T['met'])} issue days"
        if met
        else f"Teso: no admin area reached 60 % of members on any of the {k} issue days with a full forecast"
    )
    p = (
        "The IBF portal's rule for the IFRC/URCS EAP, on the GloFAS forecast to 144 h. "
        + (
            f"Not evaluated: {gap}, for want of a forecast to 144 h when this page was built (reasons at the end). "
            if gap
            else ""
        )
        + (
            f"The highest share of members over an area's 5-year level was {hp(smax)} ({day(days[si])}). "
            if share
            else ""
        )
        + (
            f"The highest member median was {hp(mmax)} of an area's level ({T['where'][mi]}, {day(days[mi])})."
            if med
            else ""
        )
    )
    spec = dict(
        id="c-teso",
        title="Teso, by issue day: highest share of the 51 GloFAS members over an area's 5-year level, and highest member median as a share of that level",
        unit="pct",
        series=[
            dict(name="share of members over the level", values=T["share"], color="--s1"),
            dict(
                name="member median, share of the level",
                values=T["median"],
                color="--s2",
                note=[f"highest member median in {w}" if w else "" for w in T["where"]],
            ),
        ],
        lines=[dict(y=0.6, label="trigger, 60 % of members")],
        yMin=0,
        yMax=1,
        ticks=[0, 0.2, 0.4, 0.6, 0.8, 1],
    )
    fact = (
        f"Met on {sum(T['met'])} issue days."
        if met
        else f"Not met on any of the {k} issue days with a full forecast"
        + (f"; {n - k} still downloading." if n - k else ".")
    )
    return dict(
        met=met,
        card=card(
            "Teso / Lake Kyoga",
            "met" if met else ("gap" if n - k else "not"),
            "Met" if met else ("Partly evaluated" if n - k else "Not met"),
            fact,
        ),
        html=f"<h2>{e(h)}</h2><p>{e(p)}</p><div class='chart' id='c-teso'></div>",
        spec=spec,
    )


def rain_zone(z: str, label: str, D: dict) -> tuple[str, str, dict]:
    R, pk, br = D[z], D[z]["peak"], D[z]["best_rank"]
    seasons = D["hindcast_seasons"]
    h = f"{label}: the highest 5-day rain forecast reached {hp(pk['share'])} of its district's threshold"
    p = (
        f"{pk['place']} on {day(pk['day'])}: {mm(pk['value'])} against {mm(pk['thr'])}. That reading ranks at the "
        f"{ordinal(pk['rank'])} percentile of {pk['place']}'s October to December issue days in the "
        f"CHIRPS3-GEFS hindcast ({seasons} seasons, 2001-2025 without 2020). "
        + (
            f"The highest rank of any district reading this season was the {ordinal(br['rank'])} percentile "
            f"({br['place']}, {day(br['day'])})."
            if (br["place"], br["day"]) != (pk["place"], pk["day"])
            else ""
        )
    )
    spec = dict(
        id=f"c-{z}",
        title=f"{label}, by issue day: highest 5-day rain forecast as a share of its district's threshold",
        unit="pct",
        series=[
            dict(
                name="share of threshold",
                values=R["share"],
                color="--s1",
                note=[f"{w}" if w else "" for w in R["where"]],
            )
        ],
        lines=[dict(y=1, label="threshold")],
        yMin=0,
        yMax=1.1,
        ticks=[0, 0.25, 0.5, 0.75, 1],
        extra=[dict(label="that reading's hindcast percentile", values=R["rank_top"], unit="raw")],
    )
    return h, p, spec


def lake(D: dict) -> tuple[str, list[dict]]:
    L, days = D["lake"], D["days"]
    rise = [(v, i) for i, v in enumerate(L["rise"]) if v is not None]
    last_v, last_i = rise[-1]
    hi_v, hi_i = max(rise)
    txt = (
        f"Lake leg: Lake Kyoga's 180-day rise was {last_v:+.2f} m at the pass of {day(L['asof'][last_i])}, "
        f"against {L['threshold']:+.2f} m. Its highest this season was {hi_v:+.2f} m ({day(L['asof'][hi_i])} pass). "
    )
    diffs = [
        (abs(a - b), i)
        for i, (a, b) in enumerate(zip(L["rise"], L["rise_full"], strict=True))
        if a is not None and b is not None
    ]
    big, bi = max(diffs)
    if big >= 0.05:
        same = [i for _, i in diffs if L["asof"][i] == L["asof"][bi]]
        ps = L["passes"]
        k = next(j for j, x in enumerate(ps) if x["date"] == L["asof"][bi])
        nb = (
            f", between passes at {ps[k - 1]['h']:.2f} and {ps[k + 1]['h']:.2f} m"
            if 0 < k < len(ps) - 1
            else ""
        )
        span = (
            day(days[same[0]])
            if len(same) == 1
            else f"{day(days[same[0]])} to {day(days[same[-1]])}"
        )
        txt += (
            f"The two lines differ most on the issues of {span}, which read the pass of "
            f"{day(L['asof'][bi])} ({ps[k]['h']:.2f} m{nb}): the monitor read {L['rise'][bi]:+.2f} m, "
            f"the backtest smoothing gives {L['rise_full'][bi]:+.2f} m."
        )
    spec = dict(
        id="c-lake",
        title="Adjumani lake leg, by issue day: Lake Kyoga's rise over 180 days (m), at the latest pass on or before the issue day",
        unit="m",
        series=[
            dict(
                name="as the monitor reads it (newest pass smoothed with the one before only)",
                values=L["rise"],
                color="--s1",
                note=[f"pass of {a}" if a else "" for a in L["asof"]],
            ),
            dict(
                name="every pass smoothed with both neighbours (the backtest method)",
                values=L["rise_full"],
                color="--s2",
            ),
        ],
        lines=[dict(y=L["threshold"], label=f"threshold, {L['threshold']:+.2f} m")],
        yMin=-1,
        yMax=1.8,
        ticks=[-1, -0.5, 0, 0.5, 1, 1.5],
        height=220,
    )
    return txt, [spec]


def page(D: dict, year: int) -> tuple[str, list[str]]:
    txt = read_private_config("monitoring_page.local.json")
    cfg = read_private_config("partner_triggers.local.json")
    if txt is None or cfg is None:
        raise SystemExit("private text or partner config unavailable: the page cannot be built")
    days = D["days"]
    el, te = elgon(D, txt["elgon"], cfg), teso(D)
    kh, kp, kspec = rain_zone("karamoja", "Karamoja", D)
    ah, ap, aspec = rain_zone("adjumani", "Adjumani / Albert Nile rain leg", D)
    ltxt, lspecs = lake(D)
    A = D["adjumani"]
    lake_met = any(v is not None and v >= D["lake"]["threshold"] for v in D["lake"]["rise"])
    cards = (
        te["card"]
        + el["card"]
        + card(
            "Karamoja",
            "met" if any(D["karamoja"]["met"]) else "not",
            "Met" if any(D["karamoja"]["met"]) else "Not met",
            f"Highest: {hp(D['karamoja']['peak']['share'])} of a district threshold "
            f"({D['karamoja']['peak']['place']}, {day(D['karamoja']['peak']['day'])}).",
        )
        + card(
            "Adjumani / Albert Nile",
            "met" if any(A["met"]) or lake_met else "not",
            "Met" if any(A["met"]) or lake_met else "Not met",
            f"Rain: highest {hp(A['peak']['share'])} of a threshold. Lake Kyoga: "
            f"{[v for v in D['lake']['rise'] if v is not None][-1]:+.2f} m against "
            f"{D['lake']['threshold']:+.2f} m.",
        )
    )
    sections = {
        "elgon": (el["met"], el["html"]),
        "teso": (te["met"], te["html"]),
        "karamoja": (
            any(D["karamoja"]["met"]),
            f"<h2>{e(kh)}</h2><p>{e(kp)}</p><div class='chart' id='c-karamoja'></div>",
        ),
        "adjumani": (
            any(A["met"]) or lake_met,
            f"<h2>{e(ah)}</h2><p>{e(ap)}</p><div class='chart' id='c-adjumani'></div>"
            f"<p>{e(ltxt)}</p><div class='chart' id='c-lake'></div>",
        ),
    }
    order = [z for z in ("teso", "elgon", "karamoja", "adjumani") if sections[z][0]] + [
        z for z in ("teso", "elgon", "karamoja", "adjumani") if not sections[z][0]
    ]
    rw = reliefweb(days[0])
    rw_html = (
        "<h2>Reported on ReliefWeb</h2><p>Uganda reports since "
        f"{day(days[0])} that mention floods, flooding or landslides:</p><ul>"
        + "".join(
            f"<li>{day(r['date'])} | {e(r['source'])} | <a href='{e(r['url'])}'>{e(r['title'])}</a></li>"
            for r in rw
        )
        + "</ul>"
        if rw
        else ""
    )
    gaps = pd.DataFrame(D["gaps"])
    gap_items = []
    if len(gaps):
        for (trig, why), g in gaps.groupby(["trigger", "why"]):
            flags = [d in set(g.day) for d in days]
            gap_items.append(f"{e(trig)}: {e(why)} | {ranges(days, flags)}")
    diffs = [
        "GFS and ICON come from the archive of past runs, the run issued that day; the daily job reads the current run.",
        "CPC soil moisture is the day before the issue; live, the newest file is about two days old.",
        "Lake Kyoga uses every satellite pass up to the issue day; live, NASA publishes a pass about a week later.",
        "Teso is the IBF portal's rule reproduced on the GloFAS forecast, not the portal's own state.",
    ]
    open_items = el["open"] + [
        "Lake Kyoga: the newest pass is smoothed with the one before it only, until the next pass arrives.",
        "GloFAS version: the request does not pin v4, and a switch to v5 would not show in the files.",
    ]
    built = pd.Timestamp.now(tz="UTC").strftime("%d %b %Y %H:%M UTC")
    sub = (
        f"The daily monitor replayed over the forecasts issued from {day(days[0])} to {day(days[-1])} {year}: "
        f"{len(days)} issue days, built {built}. Each zone's trigger, thresholds and products are the ones the "
        "daily job uses; how the replay differs from a live run is listed at the end."
    )
    head = bp.HEAD.format(title="Season monitoring", sub=e(sub), v=bp.ASSET_VERSION).replace(
        "</head>", f'<link rel="stylesheet" href="../assets/monitoring.css?v={CSS_V}"></head>'
    )
    specs = [te["spec"], el["spec"], kspec, aspec, *lspecs]
    body = (
        f"<div class='mon'><div class='zones'>{cards}</div>"
        + "".join(f"<section>{sections[z][1]}</section>" for z in order)
        + rw_html
        + "<h2>How this replay differs from the daily run</h2><ul>"
        + "".join(f"<li>{e(x)}</li>" for x in diffs)
        + "</ul>"
        + (
            "<h3>Not evaluated</h3><ul>" + "".join(f"<li>{x}</li>" for x in gap_items) + "</ul>"
            if gap_items
            else ""
        )
        + "<h3>Not decided yet</h3><ul>"
        + "".join(f"<li>{e(x)}</li>" for x in open_items)
        + "</ul></div>"
    )
    script = (
        f'<script src="../assets/monitoring.js?v={CSS_V}"></script>'
        f"<script>MonCharts.draw({json.dumps(days)}, {json.dumps(specs)});</script>"
    )
    foot = (
        f"<div class='note'><p class='fn'>Built {built} by <code>pipeline/build_monitoring_page.py</code> from "
        "the season replay (<code>monitoring/run.py</code>). Restricted: includes a partner's unpublished draft.</p></div>"
        "</div></body></html>"
    )
    return head + body + script + foot, el["probes"]


def main(year: str = "2026") -> None:
    D = collect(int(year))
    html, probes = page(D, int(year))
    plain = PRIVATE / "monitoring.html"
    PRIVATE.mkdir(exist_ok=True)
    plain.write_text(html, encoding="utf-8")
    print(f"wrote {plain.relative_to(ROOT)} (plaintext, gitignored)")
    from encrypt import encrypt_page

    encrypt_page(
        plain,
        bp.PAGES / "monitoring" / "index.html",
        title="Uganda flood AA: season monitoring",
        instructions="Restricted: includes unpublished partner material. Password shared internally.",
        probes=[*probes, "How this replay differs"],
    )


if __name__ == "__main__":
    main(*sys.argv[1:2])
