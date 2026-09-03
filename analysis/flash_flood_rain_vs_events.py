"""Elgon and Karamoja: how much rain fell before the recorded flash floods / landslides?

Link 2 of the skill chain (observed rain -> impact), run per zone on IMERG daily
district rainfall (1998-) against every day-dated impact record for the zone's
districts: DesInventar datacards (flood, flash flood, landslide, mudslide,
rainstorm; 1998-2021), curated events (2007-2025) and EM-DAT events with a day.

For each event day: the max 1-, 3- and 5-day rainfall (zone mean over districts,
and the wettest district's mean) in a window from 3 days before to 1 day after
the event, expressed as a percentile of the whole daily climatology of that
accumulation. The complementary question — how often do days above the 2-yr
rain level have an event within +/-3 days — gives the false-alarm side.

Writes outputs/flash_rain_vs_events_{zone}.csv, outputs/flash_rain_vs_events.png,
and prints the summary. Run:  uv run python analysis/flash_flood_rain_vs_events.py
"""

import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import ocha_stratus as stratus
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.constants import PROJECT_PREFIX, ZONES  # noqa: E402
from src.datasources import desinventar as di  # noqa: E402
from src.datasources import impact  # noqa: E402
from src.skill_chain import annual_max, rolling_sum, weibull_threshold  # noqa: E402
from src.zones import load_adm2  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "outputs"
ZONE_KEYS = ["elgon", "karamoja"]
WINDOWS = (1, 3, 5)
LEAD_DAYS, LAG_DAYS = 3, 1


def zone_rain(imerg: pd.DataFrame, pcodes: list[str]) -> tuple[pd.Series, pd.Series]:
    sub = imerg[imerg.pcode.isin(pcodes)]
    g = sub.groupby("date")["mean"]
    return g.mean().asfreq("D"), g.max().asfreq("D")


def zone_events(zone_key: str) -> pd.DataFrame:
    z = ZONES[zone_key]
    d = di.load_datacards()
    d = d[d.district.isin(z.core) & (d.date_precision == "day") & (d.date >= "1998-01-01")]
    des = d.groupby(d.date.dt.normalize()).agg(
        n=("serial", "size"),
        deaths=("deaths", "sum"),
        affected=("affected", "sum"),
        districts=("district", lambda s: ",".join(sorted(set(s)))),
        types=("event_type", lambda s: ",".join(sorted(set(s)))),
    )
    des["source"] = "DesInventar"
    ev = impact.events_by_district(include_dtm=False)
    ev = ev[
        ev.zone.eq(zone_key)
        & ev.membership.eq("core")
        & ((ev.end - ev.start).dt.days <= 7)
        & (ev.start >= "1998-01-01")
    ]
    other = ev.groupby(ev.start.dt.normalize()).agg(
        n=("event_id", "nunique"),
        deaths=("deaths", "max"),
        affected=("affected", "max"),
        districts=("district", lambda s: ",".join(sorted(set(s)))),
        types=("subtype", lambda s: ",".join(sorted(set(s)))),
    )
    other["source"] = ev.groupby(ev.start.dt.normalize()).source.first().str[:20]
    allev = pd.concat([des, other])
    allev = allev[
        ~allev.index.duplicated(keep="last")
    ].sort_index()  # curated/EM-DAT wins on same day
    allev.index.name = "event_day"
    return allev


def rain_before(events: pd.DataFrame, mean_s: pd.Series, max_s: pd.Series) -> pd.DataFrame:
    sums = {("mean", w): rolling_sum(mean_s, w) for w in WINDOWS} | {
        ("max", w): rolling_sum(max_s, w) for w in WINDOWS
    }
    rows = []
    for day, r in events.iterrows():
        lo, hi = day - pd.Timedelta(days=LEAD_DAYS), day + pd.Timedelta(days=LAG_DAYS)
        row = dict(event_day=day, **r.to_dict())
        for (kind, w), s in sums.items():
            win = s.loc[lo:hi].dropna()
            if win.empty:
                continue
            v = float(win.max())
            row[f"{kind}{w}d_mm"] = v
            row[f"{kind}{w}d_pctl"] = float((s.dropna() < v).mean() * 100)
        rows.append(row)
    return pd.DataFrame(rows)


def false_alarm_side(events: pd.DataFrame, mean_s: pd.Series, w: int = 3, rp: float = 2.0) -> dict:
    s = rolling_sum(mean_s, w)
    thr = weibull_threshold(annual_max(s), rp)
    hot = s[s >= thr]
    # collapse runs of consecutive hot days into episodes
    episodes = (hot.index.to_series().diff() > pd.Timedelta(days=1)).cumsum()
    starts = hot.groupby(episodes).apply(lambda x: x.index.min())
    ev_days = events.index
    hit = [any(abs((ev_days - t).days) <= 3) for t in starts]
    return dict(
        window_days=w,
        rp_years=rp,
        thresh_mm=thr,
        n_episodes=len(starts),
        n_with_event=int(sum(hit)),
        share_with_event=float(np.mean(hit)) if len(hit) else np.nan,
    )


def main() -> None:
    imerg = stratus.load_parquet_from_blob(
        f"{PROJECT_PREFIX}/processed/imerg/imerg_adm2_daily.parquet", stage="dev"
    )
    adm = load_adm2()
    fig, axes = plt.subplots(1, len(ZONE_KEYS), figsize=(13, 5), sharey=True)
    for ax, zk in zip(axes, ZONE_KEYS, strict=True):
        z = ZONES[zk]
        pcodes = adm[adm.ADM2_EN.isin(z.core)].ADM2_PCODE.tolist()
        mean_s, max_s = zone_rain(imerg, pcodes)
        events = zone_events(zk)
        tab = rain_before(events, mean_s, max_s)
        tab.to_csv(OUT / f"flash_rain_vs_events_{zk}.csv", index=False)
        fa = {w: false_alarm_side(events, mean_s, w) for w in WINDOWS}
        pd.set_option("display.width", 220)
        print(
            f"\n=== {z.label}: {len(events)} event days ({events.source.value_counts().to_dict()})"
        )
        print(
            "median percentile of pre-event rain:",
            {c: round(tab[c].median(), 0) for c in tab.columns if c.endswith("_pctl")},
        )
        print(
            "share of events with 3-day zone-mean rain above its 90th pctl:",
            round((tab["mean3d_pctl"] > 90).mean(), 2),
            "| above 2-yr level:",
            round((tab["mean3d_mm"] >= fa[3]["thresh_mm"]).mean(), 2),
        )
        print(
            "false-alarm side (zone-mean rain episodes over the 2-yr level, event within +/-3 d):"
        )
        print(pd.DataFrame(fa).T.round(2).to_string())
        deadly = tab[tab.deaths.fillna(0) >= 5]
        print(
            f"events with >=5 deaths ({len(deadly)}): 3-day zone-mean pctl median {deadly['mean3d_pctl'].median():.0f}, "
            f"5-day {deadly['mean5d_pctl'].median():.0f}"
        )

        bins = np.arange(0, 101, 10)
        ax.hist(
            tab["mean3d_pctl"].dropna(),
            bins=bins,
            color="#b2182b" if zk == "elgon" else "#e08214",
            alpha=0.8,
            label="3-day zone-mean rain, all events",
        )
        ax.hist(
            deadly["mean3d_pctl"].dropna(), bins=bins, color="black", alpha=0.6, label=">=5 deaths"
        )
        ax.axhline(len(tab) / 10, color="grey", ls="--", lw=1, label="uniform (no relation)")
        ax.set_title(
            f"{z.label}\n{len(tab)} event days, {tab.event_day.min():%Y}–{tab.event_day.max():%Y}",
            fontsize=10,
        )
        ax.set_xlabel("percentile of the 3-day rainfall in the 3 days before the event")
        ax.legend(fontsize=8)
    axes[0].set_ylabel("number of event days")
    fig.suptitle(
        "Observed IMERG rainfall before recorded flash floods / landslides (DesInventar, EM-DAT, curated)",
        fontsize=11,
    )
    fig.tight_layout()
    fig.savefig(OUT / "flash_rain_vs_events.png", dpi=150)
    print("wrote", OUT / "flash_rain_vs_events.png")


if __name__ == "__main__":
    main()
