"""Reduction and encoding tests for darksky.py (no data download)."""
import numpy as np

import darksky


def test_block_mean_and_nan():
    a = np.array([[1, 3, np.nan, 4], [3, 5, 4, 0]], dtype=np.float32)
    m = darksky.block_mean(a, 2, 2)
    assert m.shape == (1, 2)
    assert m[0, 0] == 3.0 and m[0, 1] == 2.0      # NaN counts as 0


def test_encode_range_and_log_midpoint():
    r = np.array([0.0, darksky.LO_NW, np.sqrt(darksky.LO_NW * darksky.HI_NW), darksky.HI_NW, 5000.0])
    c = darksky.encode(r)
    assert list(c[:2]) == [0, 0]
    assert abs(int(c[2]) - 128) <= 1                # geometric mean sits mid-scale
    assert list(c[3:]) == [255, 255]


def test_spread_wraps_longitude():
    a = np.zeros((darksky.NLAT, darksky.NLON), dtype=np.float32)
    a[900, 0] = 100.0                               # a light at 180 W
    s = darksky.spread(a)
    assert s[900, darksky.NLON - 1] > 0.1           # its glow crosses the antimeridian
    assert s[900, 0] < 100.0


def test_synthetic_png_shape():
    code = darksky.encode(darksky.spread(darksky.synthetic()))
    assert code.shape == (darksky.NLAT, darksky.NLON)
    assert code.max() > 120 and (code == 0).mean() > 0.3   # bright cores, and plenty of dark sky left


def test_encode_dn_is_linear_and_clipped():
    c = darksky.encode_dn(np.array([0.0, 63.0 / 2, 63.0, 90.0]))
    assert list(c) == [0, 128, 255, 255]


def test_read_harmonized_blocks(tmp_path):
    import tifffile
    a = np.zeros((1200 + 12, darksky.NLON * 12 + 1), dtype=np.int16)
    a[0:12, 0:12] = 63                       # top-left 0.1 degree cell: 75 N, 180 W
    a[12 * 5: 12 * 6, 12 * 7: 12 * 8] = 30   # a cell at row 5, column 7 below it
    tifffile.imwrite(tmp_path / "h.tif", a)
    g = darksky.read_harmonized(tmp_path / "h.tif")
    assert g.shape == (darksky.NLAT, darksky.NLON)
    assert g[150, 0] == 63.0                 # 75 N is row 150 of the 0.1 degree frame
    assert g[155, 7] == 30.0
    assert g[:150].sum() == 0
