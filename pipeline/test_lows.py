import numpy as np

from encoding import NLAT, NLON
from lows import LATS, detect_lows, track_lows


def field_with_lows(centres, base=1015.0, depth=30.0, radius_deg=6.0):
    lons = np.linspace(-180.0, 179.75, NLON)
    lon2, lat2 = np.meshgrid(lons, LATS)
    f = np.full((NLAT, NLON), base)
    for lon, lat in centres:
        dlon = (lon2 - lon + 180.0) % 360.0 - 180.0
        d2 = (dlon * np.cos(np.deg2rad(lat))) ** 2 + (lat2 - lat) ** 2
        f -= depth * np.exp(-d2 / radius_deg ** 2)
    return f


def test_finds_a_low_near_its_centre():
    lows = detect_lows(field_with_lows([(-30.0, 55.0)]))
    assert len(lows) == 1
    assert abs(lows[0]["lon"] + 30.0) <= 1.0 and abs(lows[0]["lat"] - 55.0) <= 1.0
    assert lows[0]["hpa"] < 990.0


def test_ignores_the_tropics():
    assert detect_lows(field_with_lows([(60.0, 10.0)])) == []


def test_tracks_a_moving_low_and_drops_a_weak_one():
    by_step = {}
    for i, step in enumerate(range(0, 30, 3)):
        by_step[step] = detect_lows(field_with_lows([(-40.0 + 2.0 * i, 55.0)])) + \
                        detect_lows(field_with_lows([(100.0, -50.0)], depth=5.0))
    tracks = track_lows(by_step)
    assert len(tracks) == 1
    assert len(tracks[0]["pts"]) == 10
    assert tracks[0]["id"] == "L1"
