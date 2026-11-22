"""NHC reader against a real archived advisory (Post-Tropical Cyclone Lee, 2023-09-17).

The JSON wrapper is rebuilt from NHC's documented format (CurrentStorms.json is
empty when nothing is active).    python -m pytest test_nhc.py
"""
from datetime import datetime, timezone
from pathlib import Path

import nhc

FX = Path(__file__).parent / "fixtures" / "nhc"
NOW = datetime(2023, 9, 17, 3, 20, tzinfo=timezone.utc)


def test_forecast_positions_and_post_tropical_flag():
    f = nhc.parse_forecast((FX / "fstadv_lee047.txt").read_text(), NOW)
    assert [p["h"] for p in f] == [9, 21, 33]                  # the DISSIPATED line is skipped
    assert (f[0]["lat"], f[0]["lon"], f[0]["kt"]) == (47.2, -63.2, 45)
    assert all(p.get("xt") for p in f)


def test_build_from_current_storms():
    def getter(url):
        if url == nhc.URL:
            return (FX / "current_lee.json").read_text()
        return (FX / "fstadv_lee047.txt").read_text()
    doc = nhc.build(NOW, None, getter)
    s, = doc["systems"]
    assert (s["id"], s["name"], s["class"], s["pt"], s["basin"]) == ("AL13", "Lee", "Post-tropical cyclone", True, "Atlantic")
    assert (s["lat"], s["lon"], s["wind_kt"], s["mslp"]) == (45.3, -65.5, 50, 979)
    assert s["move"] == {"deg": 20, "kt": 12}
    assert len(s["forecast"]) == 3 and s["src"] == "NHC"


def test_no_active_storms():
    assert nhc.build(NOW, None, lambda url: '{"activeStorms": []}')["systems"] == []
