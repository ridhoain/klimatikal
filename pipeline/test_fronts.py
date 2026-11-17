"""Run with: python -m pytest pipeline/test_fronts.py (or python test_fronts.py)."""
import numpy as np

from encoding import NLAT, NLON
from fronts import LATS, detect_fronts


def _field(wind_v):
    """Cold air north of 45N, warm south, a smooth step; wind v given."""
    lat = LATS[:, None] * np.ones((1, NLON))
    t = 10.0 + 10.0 * np.tanh((45.0 - lat) / 2.0)     # 20 C south, 0 C north
    rh = np.full((NLAT, NLON), 70.0)
    return t, rh, np.zeros((NLAT, NLON)), np.full((NLAT, NLON), wind_v)


def test_front_found_near_the_step_and_cold_when_wind_blows_south():
    out = detect_fronts(*_field(-8.0))          # wind towards the warm (south) side
    assert out["features"], "no front found"
    for f in out["features"]:
        ys = [c[1] for c in f["geometry"]["coordinates"]]
        assert all(40 < y < 50 for y in ys)
        assert f["properties"]["t"] == "c"


def test_warm_front_when_wind_blows_north():
    out = detect_fronts(*_field(8.0))
    assert out["features"] and all(f["properties"]["t"] == "w" for f in out["features"])


def test_no_front_in_uniform_air():
    t = np.full((NLAT, NLON), 15.0)
    out = detect_fronts(t, np.full_like(t, 60.0), np.zeros_like(t), np.zeros_like(t))
    assert out["features"] == []


def test_line_runs_with_the_moving_side_on_its_left():
    # Cold front, moving south: facing west puts south on the left.
    for f in detect_fronts(*_field(-8.0))["features"]:
        xs = [c[0] for c in f["geometry"]["coordinates"]]
        assert xs[-1] < xs[0]
    # Warm front moves towards the cold air (north): facing east puts north on the left.
    for f in detect_fronts(*_field(8.0))["features"]:
        xs = [c[0] for c in f["geometry"]["coordinates"]]
        assert xs[-1] > xs[0]


def test_monsoon_trough_where_westerlies_meet_easterlies():
    from fronts import detect_troughs
    lat = LATS[:, None] * np.ones((1, NLON))
    u = 6.0 * np.tanh((10.0 - lat) / 5.0)         # westerly south of 10N, easterly north of it
    out = detect_troughs(u, np.full((NLAT, NLON), 1010.0))
    assert out and all(f["properties"]["t"] == "m" for f in out)
    assert all(8 < c[1] < 12 for f in out for c in f["geometry"]["coordinates"])
    # the same shear the other way round (easterlies equatorward) is not a trough
    assert not detect_troughs(-u, np.full((NLAT, NLON), 1010.0))
