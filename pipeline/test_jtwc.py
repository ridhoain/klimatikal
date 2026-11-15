"""Parser tests against real JTWC text saved in fixtures/jtwc/.

abpw10, abio10, tcfa_sh9527 and the feed were captured on 2026-11-15; the
warning is an archived real one (TS 20W Roke, 2022-10-01) from the Wayback
Machine, because no tropical cyclone was active when this was written.

    python -m pytest test_jtwc.py
"""
from datetime import datetime, timezone
from pathlib import Path

import jtwc

FX = Path(__file__).parent / "fixtures" / "jtwc"
NOW = datetime(2026, 11, 15, 8, 40, tzinfo=timezone.utc)


def text(name):
    return (FX / name).read_text()


def test_outlook_finds_invests_with_positions():
    pw = jtwc.parse_outlook(text("abpw10.txt"), NOW)
    assert [s["id"] for s in pw] == ["95P"]
    s = pw[0]
    assert (s["lat"], s["lon"]) == (-8.5, -158.0)          # the NEW position, not "previously located"
    assert (s["wind_kt"], s["wind_kt_max"], s["mslp"]) == (28, 33, 1002)
    assert s["potential"] == "high" and s["basin"] == "South Pacific"
    assert s["t"] == "2026-11-15T06:00Z"


def test_indian_ocean_outlook_has_both_hemispheres():
    io = {s["id"]: s for s in jtwc.parse_outlook(text("abio10.txt"), NOW)}
    assert {"92B", "96S"} <= set(io)
    assert (io["92B"]["lat"], io["92B"]["lon"]) == (9.1, 86.2)
    assert io["92B"]["potential"] == "low"
    assert io["96S"]["lat"] == -1.2 and io["96S"]["lon"] == 91.0


def test_tcfa_flags_invest_and_gives_centre():
    a = jtwc.parse_tcfa(text("tcfa_sh9527.txt"), NOW)
    assert a["id"] == "95P" and a["tcfa"] is True
    assert (a["lat"], a["lon"]) == (-9.2, -157.1)
    assert a["mslp"] == 998 and a["t"] == "2026-11-14T13:00Z"


def test_warning_position_and_forecast_track():
    ref = datetime(2022, 10, 1, 10, 0, tzinfo=timezone.utc)
    w = jtwc.parse_warning(text("warning_wp2022.txt"), ref)
    assert w["id"] == "20W" and w["name"] == "Roke" and w["class"] == "Tropical Storm"
    assert (w["lat"], w["lon"], w["wind_kt"]) == (33.1, 146.5, 55)
    assert w["t"] == "2022-10-01T06:00Z" and w["move"] == {"deg": 50, "kt": 19}
    assert [f["h"] for f in w["forecast"]] == [12, 24, 36]
    assert w["forecast"][0] == {"h": 12, "t": "2022-10-01T18:00Z", "lat": 35.2, "lon": 150.2, "kt": 60}
    assert w["forecast"][2]["t"] == "2022-10-02T18:00Z"     # crosses midnight


def test_month_rollover_picks_the_nearest_day():
    ref = datetime(2026, 12, 1, 1, 0, tzinfo=timezone.utc)
    assert jtwc.at_ddhhmm(30, 18, 0, ref) == datetime(2026, 11, 30, 18, 0, tzinfo=timezone.utc)


def test_links_skip_outlooks_and_keep_the_alert():
    links = jtwc.current_product_links(text("jtwc.rss"))
    assert links == ["https://www.metoc.navy.mil/jtwc/products/sh9527web.txt"]


def test_build_merges_tcfa_into_outlook_and_extends_the_past():
    texts = {jtwc.RSS: text("jtwc.rss"), jtwc.OUTLOOKS[0]: text("abpw10.txt"),
             jtwc.OUTLOOKS[1]: text("abio10.txt"),
             "https://www.metoc.navy.mil/jtwc/products/sh9527web.txt": text("tcfa_sh9527.txt")}
    prev = {"systems": [{"id": "95P", "t": "2026-11-14T13:00Z", "lat": -9.2, "lon": -157.1, "wind_kt": 28, "past": []}]}
    doc = jtwc.build(NOW, prev, getter=texts.__getitem__)
    ids = [s["id"] for s in doc["systems"]]
    assert ids == ["92B", "95P", "96S"]
    p95 = next(s for s in doc["systems"] if s["id"] == "95P")
    assert p95["tcfa"] is True and p95["url"].endswith("sh9527web.txt")
    assert p95["past"] == [[-9.2, -157.1, "2026-11-14T13:00Z", 28]]
