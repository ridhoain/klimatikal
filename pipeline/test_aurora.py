"""Orientation and Kp tests for aurora.py (no network)."""
import io
from datetime import datetime, timezone

import numpy as np
from PIL import Image

import aurora


def test_grid_orientation():
    # lon 0 / lat 90 is the top row, and lon 0 is the middle column (180 W is column 0).
    g = aurora.to_grid([[0, 90, 40], [180, -90, 70], [359, 0, 100]])
    assert g.shape == (181, 360)
    assert g[0, 180] == 40            # 0 E, 90 N
    assert g[180, 0] == 70            # 180 E = 180 W, 90 S
    assert g[90, 179] == 100          # 359 E = 1 W, equator
    assert g.sum() == 210


def test_png_keeps_value_in_red_and_alpha_opaque():
    g = aurora.to_grid([[10, 60, 55]])
    im = np.asarray(Image.open(io.BytesIO(aurora.to_png(g))))
    assert im.shape == (181, 360, 4)
    assert (im[..., 3] == 255).all()
    assert im[30, 190, 0] == 55       # 10 E = column 190, 60 N = row 30


def test_rejects_other_layouts():
    for bad in ([[400, 0, 1]], [[0, 95, 1]], [[1, 2]]):
        try:
            aurora.to_grid(bad)
        except ValueError:
            continue
        raise AssertionError(f"accepted {bad}")


def test_kp_summary():
    now = datetime(2026, 11, 22, 10, 0, tzinfo=timezone.utc)
    rows = [{"time_tag": "2026-11-22T06:00:00", "kp": "2.33"}, {"time_tag": "2026-11-22T09:00:00", "kp": "3.00"},
            {"time_tag": "2026-11-22T12:00:00", "kp": "5.67"}, {"time_tag": "2026-11-24T00:00:00", "kp": "9.00"}]
    assert aurora.kp_summary(rows, now) == (3.0, 5.67)
