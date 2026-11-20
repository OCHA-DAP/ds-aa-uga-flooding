"""Tests for the daily trigger monitor (monitoring/), on synthetic data: no network, no blob.

Each rule is checked for met, not met, the edge of its window and missing data (which must read
as "not evaluated", never as "not met"); the email modes are checked against the real
ocha-relay API with a fake client, so nothing is sent.

Run:  uv run pytest tests/test_monitoring.py -q
"""

from __future__ import annotations

import inspect
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import ClassVar

import numpy as np
import pandas as pd
import pytest
import rasterio
import xarray as xr

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from monitoring import daily, feeds, notify
from monitoring import evaluate as ev
from monitoring import run as R

ISSUE = pd.Timestamp("2026-11-19")


def state(x):
    """True / False / None from a `met` cell (numpy booleans included)."""
    return None if x is None or (isinstance(x, float) and np.isnan(x)) else bool(x)


# --- helpers ------------------------------------------------------------------------------------


def forecast(values_by_step: dict[int, np.ndarray], steps: int = 6, shape=(3, 3)) -> xr.DataArray:
    """(member, lead_day, lat, lon) with 51 members; values_by_step[step] is a (51,) array put
    in cell (1, 1); every other value is 1.0."""
    data = np.ones((ev.N_MEMBERS, steps, *shape))
    for k, v in values_by_step.items():
        data[:, k - 1, 1, 1] = v
    lat = np.array([2.025, 1.975, 1.925])
    lon = np.array([33.925, 33.975, 34.025])
    return xr.DataArray(
        data,
        dims=("member", "lead_day", "lat", "lon"),
        coords={
            "member": np.arange(51),
            "lead_day": np.arange(1, steps + 1),
            "lat": lat,
            "lon": lon,
        },
    )


def members_over(n: int, level: float, above: float = 2.0, below: float = 0.5) -> np.ndarray:
    """n of 51 members at `level * above`, the rest at `level * below`."""
    v = np.full(ev.N_MEMBERS, level * below)
    v[:n] = level * above
    return v


UNITS = pd.DataFrame(
    [
        dict(level=2, pcode="UG1", name="District A", district="A", threshold=10.0, cells=[4]),
        dict(level=4, pcode="UG1a", name="Sub A1", district="A", threshold=10.0, cells=[4, 5]),
        dict(level=2, pcode="UG2", name="District B", district="B", threshold=10.0, cells=[0]),
    ]
)


# --- Teso: the IBF portal rule -----------------------------------------------------------------


def test_teso_met_at_60_percent_on_the_last_step():
    q = forecast({6: members_over(31, 10.0)})  # 31/51 = 61 %, at the 144 h step
    t = ev.teso(q, UNITS, ISSUE).set_index("place")
    assert t.loc["A", "met"] and t.loc["A", "value"] == pytest.approx(31 / 51)
    assert not t.loc["B", "met"]


def test_teso_not_met_below_60_percent():
    q = forecast({3: members_over(30, 10.0)})  # 30/51 = 59 %
    assert not ev.teso(q, UNITS, ISSUE).met.any()


def test_teso_counts_members_strictly_above_the_level():
    q = forecast({2: np.full(ev.N_MEMBERS, 10.0)})  # every member exactly at the level
    assert ev.teso(q, UNITS, ISSUE).set_index("place").loc["A", "value"] == 0


def test_teso_ignores_steps_after_144_h():
    q = forecast({7: members_over(51, 10.0)}, steps=7)
    assert not ev.teso(q, UNITS, ISSUE).met.any()


def test_teso_refuses_a_forecast_short_of_144_h():
    with pytest.raises(ValueError):
        ev.teso(forecast({}, steps=5), UNITS, ISSUE)


# --- Elgon T2: households in cells over their level ----------------------------------------------

CELLS = pd.DataFrame(
    [
        dict(district="D1", lat=1.975, lon=33.975, households=700.0, level=10.0),
        dict(district="D1", lat=1.975, lon=34.025, households=500.0, level=10.0),
    ]
)
CFG = {  # made-up parameters: the real ones live only in the private config
    "districts": ["D1", "D2"],
    "rain_mm": 60.0,
    "antecedent_pctl": 70.0,
    "t2": {"households": 800},
}


def test_t2_met_when_enough_households_are_in_cells_over_their_level():
    data = forecast({}).values.copy()
    data[:40, 2, 1, 1] = 20.0  # 40/51 members over the level at step 3, both cells
    data[:40, 2, 1, 2] = 20.0
    q = forecast({}).copy(data=data)
    t = ev.elgon_t2(q, CELLS, CFG, ISSUE).set_index("place")
    assert t.loc["D1", "met"] and t.loc["D1", "value"] == 1200
    assert t.loc["D2", "detail"] == "no households in the mapped extent"


def test_t2_cells_must_exceed_at_the_same_step():
    data = forecast({}).values.copy()
    data[:40, 1, 1, 1] = 20.0  # first cell at step 2 only
    data[:40, 3, 1, 2] = 20.0  # second cell at step 4 only
    q = forecast({}).copy(data=data)
    assert not ev.elgon_t2(q, CELLS, CFG, ISSUE).met.any()


def test_t2_ignores_the_144_h_step():
    data = forecast({}).values.copy()
    data[:, 5, 1, 1:3] = 20.0  # every member, both cells, but only at 144 h
    assert not ev.elgon_t2(forecast({}).copy(data=data), CELLS, CFG, ISSUE).met.any()


# --- Elgon T3: 72-hour rain and soil moisture -----------------------------------------------------

HIST = pd.DataFrame({"pcode": "P1", "mean": np.arange(100.0)})  # value v sits at percentile v+1


def rain(mm: float) -> pd.DataFrame:
    return pd.DataFrame([dict(pcode="P1", district="D1", model="gfs_seamless", mm_72h=mm)])


def soil(v: float) -> pd.DataFrame:
    return pd.DataFrame([dict(pcode="P1", mean=v, date=ISSUE - pd.Timedelta(days=1))])


def test_t3_met_needs_both_rain_and_wet_soil():
    assert state(ev.elgon_t3(rain(60.0), soil(90.0), HIST, CFG, ISSUE).met.iloc[0]) is True
    assert state(ev.elgon_t3(rain(59.9), soil(90.0), HIST, CFG, ISSUE).met.iloc[0]) is False
    assert state(ev.elgon_t3(rain(150.0), soil(50.0), HIST, CFG, ISSUE).met.iloc[0]) is False


def test_t3_missing_soil_or_rain_is_not_evaluated():
    assert state(ev.elgon_t3(rain(150.0), None, HIST, CFG, ISSUE).met.iloc[0]) is None
    assert state(ev.elgon_t3(rain(np.nan), soil(90.0), HIST, CFG, ISSUE).met.iloc[0]) is None


# --- Karamoja / Adjumani rain, Adjumani lake -----------------------------------------------------

THR = pd.DataFrame(
    [
        dict(zone="karamoja", series="Abim", leg="rain", threshold=100.0),
        dict(zone="karamoja", series="Kotido", leg="rain", threshold=80.0),
        dict(zone="adjumani", series="Kyoga rise", leg="lake", threshold=1.5),
    ]
)
NAMES = {"P_ABIM": "Abim", "P_KOT": "Kotido"}


def test_rain_zone_met_at_the_threshold_and_missing_district_not_evaluated():
    cg = pd.DataFrame({"pcode": ["P_ABIM"], "mean": [100.0]})  # Kotido absent
    t = ev.rain_zone("karamoja", cg, THR, NAMES, ISSUE).set_index("place")
    assert state(t.loc["Abim", "met"]) is True
    assert state(t.loc["Kotido", "met"]) is None


def lake_passes(rise_m: float) -> pd.DataFrame:
    d = pd.date_range("2026-04-01", "2026-11-15", freq="10D")
    h = np.linspace(1035.0, 1035.0 + rise_m, len(d))
    return pd.DataFrame({"date": d, "height_m": h})


def test_lake_leg_met_and_not_met():
    assert state(ev.adjumani_lake(lake_passes(2.0), THR, ISSUE).met.iloc[0]) is True
    assert state(ev.adjumani_lake(lake_passes(0.5), THR, ISSUE).met.iloc[0]) is False


def test_lake_reads_only_passes_up_to_the_issue_day():
    p = lake_passes(2.0)
    p.loc[len(p)] = [pd.Timestamp("2026-12-30"), 1000.0]  # a pass after the issue day
    row = ev.adjumani_lake(p, THR, ISSUE).iloc[0]
    assert state(row.met) is True and row.source_date <= "2026-11-19"


# --- zone status, waiting, email ----------------------------------------------------------------


def day_table(met_values: dict[str, list]) -> pd.DataFrame:
    rows = []
    for z, vals in met_values.items():
        for m in vals:
            rows.append(
                dict(
                    zone=z,
                    trigger=f"{z} trigger",
                    place="x",
                    value=1.0,
                    threshold=2.0,
                    unit="m",
                    met=m,
                    detail="no data" if m is None else "",
                    source="GloFAS" if m is None else "test",
                    source_date="2026-11-19",
                )
            )
    df = ev.frame(rows)
    df.insert(0, "issue_date", ISSUE)
    return df


def test_zone_summary_met_incomplete_not_met():
    day = day_table(
        {
            "teso_kyoga": [None, False],
            "elgon": [True, None],
            "karamoja": [False],
            "adjumani": [False],
        }
    )
    s = R.zone_summary(day).set_index("zone").status
    assert s.to_dict() == {
        "teso_kyoga": "incomplete",
        "elgon": "met",
        "karamoja": "not met",
        "adjumani": "not met",
    }


def test_daily_waits_only_for_the_same_day_forecasts():
    day = day_table(
        {"teso_kyoga": [None], "elgon": [False], "karamoja": [False], "adjumani": [False]}
    )
    assert daily.waiting_for(day) == {"GloFAS"}


def test_headline_never_says_not_met_when_a_zone_was_not_evaluated():
    day = day_table(
        {"teso_kyoga": [None], "elgon": [False], "karamoja": [False], "adjumani": [False]}
    )
    subject, _ = notify.render(day, day, "chart.png")
    assert "not fully evaluated" in subject and "Teso" in subject
    met = day_table(
        {"teso_kyoga": [False], "elgon": [True], "karamoja": [False], "adjumani": [False]}
    )
    assert "Trigger met: Mount Elgon" in notify.render(met, met, "chart.png")[0]


def test_env_flags_are_strict(monkeypatch):
    monkeypatch.setenv("DRY_RUN", "maybe")
    with pytest.raises(ValueError):
        notify.env_flag("DRY_RUN", True)
    monkeypatch.delenv("DRY_RUN")
    assert notify.env_flag("DRY_RUN", True) is True


class FakeClient:
    calls: ClassVar[list] = []
    delivered = 1

    @classmethod
    def from_env(cls):
        return cls()

    def upload_media(self, data, filename="image.png"):
        FakeClient.calls.append(("upload", type(data), filename))
        return "https://example.invalid/chart.png"

    def create_campaign(self, *, name, subject, body, list_ids=None, template_id=8):
        FakeClient.calls.append(("create", name, subject, list_ids))
        return 1

    def send_campaign(self, campaign_id, *, skip_confirmation=False):
        FakeClient.calls.append(("send", campaign_id, skip_confirmation))

    def get_campaign(self, campaign_id):
        return {"sent": FakeClient.delivered, "to_send": 1, "status": "finished"}


@pytest.fixture
def fake_listmonk(monkeypatch, tmp_path):
    import ocha_relay.listmonk as lm

    FakeClient.calls = []
    FakeClient.delivered = 1
    monkeypatch.setattr(lm, "ListmonkClient", FakeClient)
    monkeypatch.setattr(notify.time, "sleep", lambda s: None)
    monkeypatch.setattr(notify, "OUT_DIR", tmp_path)
    return FakeClient


def test_fake_client_matches_the_real_listmonk_api():
    from ocha_relay.listmonk import ListmonkClient

    for name in ("upload_media", "create_campaign", "send_campaign", "get_campaign"):
        real = set(inspect.signature(getattr(ListmonkClient, name)).parameters)
        fake = set(inspect.signature(getattr(FakeClient, name)).parameters)
        assert fake <= real, name
    assert inspect.signature(ListmonkClient.upload_media).parameters["data"].annotation in (
        bytes,
        "bytes",
    )


def test_dry_run_sends_nothing(monkeypatch, fake_listmonk):
    monkeypatch.delenv("DRY_RUN", raising=False)
    day = day_table(
        {"teso_kyoga": [False], "elgon": [False], "karamoja": [False], "adjumani": [False]}
    )
    out = notify.send(day, day)
    assert out["sent"] is False and Path(out["html"]).exists() and fake_listmonk.calls == []


def test_test_send_goes_to_the_test_list_with_png_bytes(monkeypatch, fake_listmonk):
    monkeypatch.setenv("DRY_RUN", "false")
    monkeypatch.setenv("TEST_EMAIL", "true")
    monkeypatch.delenv("LISTMONK_LIST_ID", raising=False)
    day = day_table(
        {"teso_kyoga": [False], "elgon": [False], "karamoja": [False], "adjumani": [False]}
    )
    out = notify.send(day, day)
    upload = next(c for c in fake_listmonk.calls if c[0] == "upload")
    create = next(c for c in fake_listmonk.calls if c[0] == "create")
    assert upload[1] is bytes
    assert create[3] == [103] and create[2].startswith("[TEST]") and create[1].startswith("[test]")
    assert out["test"] is True and out["delivered"] is True


def test_a_send_listmonk_does_not_deliver_is_flagged(monkeypatch, fake_listmonk):
    monkeypatch.setenv("DRY_RUN", "false")
    monkeypatch.setenv("TEST_EMAIL", "true")
    monkeypatch.delenv("LISTMONK_LIST_ID", raising=False)
    fake_listmonk.delivered = 0  # "finished" with nothing sent: the instance has done this
    day = day_table(
        {"teso_kyoga": [False], "elgon": [False], "karamoja": [False], "adjumani": [False]}
    )
    out = notify.send(day, day)
    assert out["sent"] is True and out["delivered"] is False


def test_live_send_needs_a_list_and_a_test_never_reaches_it(monkeypatch, fake_listmonk):
    monkeypatch.setenv("DRY_RUN", "false")
    day = day_table(
        {"teso_kyoga": [False], "elgon": [False], "karamoja": [False], "adjumani": [False]}
    )
    monkeypatch.setenv("TEST_EMAIL", "false")
    monkeypatch.delenv("LISTMONK_LIST_ID", raising=False)
    with pytest.raises(SystemExit):
        notify.send(day, day)
    monkeypatch.setenv("TEST_EMAIL", "true")
    monkeypatch.setenv("LISTMONK_LIST_ID", "103")
    monkeypatch.setenv("LISTMONK_TEST_LIST_ID", "103")
    with pytest.raises(SystemExit):
        notify.send(day, day)


# --- feeds: failure handling --------------------------------------------------------------------


def test_chirps_404_is_not_published_and_429_is_a_failure(monkeypatch):
    def boom(url):
        raise rasterio.errors.RasterioIOError("HTTP response code: 429")

    monkeypatch.setattr(feeds, "read_windowed_url", boom)
    monkeypatch.setattr(feeds.time, "sleep", lambda s: None)
    monkeypatch.setattr(feeds, "_http_status", lambda url: 404)
    assert feeds.chirps3_gefs(ISSUE.date(), None) is None
    monkeypatch.setattr(feeds, "_http_status", lambda url: 429)
    with pytest.raises(rasterio.errors.RasterioIOError):
        feeds.chirps3_gefs(ISSUE.date(), None)


def test_openmeteo_total_needs_all_72_hours(monkeypatch):
    import geopandas as gpd
    from shapely.geometry import box

    adm = gpd.GeoDataFrame(
        {"ADM2_PCODE": ["P1"], "ADM2_EN": ["D1"]}, geometry=[box(34.0, 1.0, 34.05, 1.05)]
    )
    hours = [1.0] * 71 + [None]
    resp = {
        "hourly": {"precipitation_gfs_seamless": hours, "precipitation_icon_global": [1.0] * 72}
    }
    monkeypatch.setattr(feeds, "_retry", lambda fn, **k: [resp])
    monkeypatch.setattr(feeds.time, "sleep", lambda s: None)
    out = feeds.openmeteo_72h(ISSUE.date(), adm).set_index("model")
    assert np.isnan(out.loc["gfs_seamless", "mm_72h"])
    assert out.loc["icon_global", "mm_72h"] == 72.0


def test_one_failing_source_does_not_stop_the_others():
    val, err = R._try("NASA GWM", lambda: (_ for _ in ()).throw(TimeoutError("down")))
    assert val is None and "NASA GWM failed" in err


class StuckRemote:
    """An EWDS request that never leaves the queue."""

    deleted = False
    status = "accepted"

    def update(self):
        pass

    def delete(self):
        StuckRemote.deleted = True


def test_glofas_wait_stops_at_the_deadline_and_frees_the_queue(monkeypatch, tmp_path):
    import src.datasources.glofas as g

    class Client:
        def retrieve(self, name, request):
            return StuckRemote()

    monkeypatch.setattr(g, "_client", lambda wait_until_complete=True: Client())
    past = datetime.now(UTC) - timedelta(minutes=1)
    with pytest.raises(TimeoutError):
        feeds.download_glofas(ISSUE.date(), tmp_path / "x.zip", deadline=past, poll=0)
    assert StuckRemote.deleted
