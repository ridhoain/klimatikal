"""Weather fronts, found in the model's own 850 hPa fields.

ECMWF's open data has no front lines, so they are detected, not read. The
method is the thermal front parameter of Hewson (1998) on the 850 hPa
wet-bulb temperature: smooth the field, take the gradient, and mark the line
where the gradient is steepest across itself (the zero line of TFP). Only
strong, long pieces of that line are kept. A piece is a cold front if the
850 hPa wind blows from the cold side towards the warm side, a warm front if it
blows the other way. Where the wind runs along the front (it is barely moving)
close to a deep low, it is called occluded: an approximation, since a real
occlusion is a three-air-mass structure this single level cannot show.
Also drawn, as plain lines without symbols: the monsoon trough (the zero line
of the 850 hPa westerly wind where it turns cyclonically from westerlies on the
equator side to easterlies, within 20 degrees of the equator) and pressure
troughs (the ridge of strongest upward curvature of the sea-level pressure
field, away from the tropics and high ground).
Every piece is oriented so the side the front is moving towards is on the left
of its direction, which is where the map draws the triangles and semicircles.

Output is a GeoJSON FeatureCollection per forecast step. Not an analysis: it
is what the model's temperature field implies, so it is tuned to show the
large fronts and leave out the small ones (see the constants).
"""
from __future__ import annotations

import numpy as np

from encoding import NLAT, NLON, _gaussian_blur

SMOOTH_CELLS = 4.0        # 1 degree: smoothing of the wet-bulb field
TFP_SMOOTH_CELLS = 1.0    # smoothing of the parameter itself
ADV_SMOOTH_CELLS = 3.0    # smoothing of the wind across the front
MIN_GRADIENT = 0.020      # K/km: 2 K per 100 km, or the piece is not a front
MIN_POINTS = 30           # grid steps (about 700 km at 0.25 degree) of front
MIN_LAT = 10.0            # no fronts within 10 degrees of the equator
MAX_LAT = 80.0
OCCLUDED_WIND = 2.5       # m/s across the front, below which a front near a low is called occluded
LOW_RADIUS_KM = 1200.0
LOW_DEPTH_HPA = 4.0       # a low is a minimum this far below the mean of the ring 8 degrees out
TROUGH_SMOOTH_CELLS = 12.0   # 3 degrees: smoothing before looking for the trough axis
MIN_TROUGH_CURVATURE = 2e-5  # hPa/km2: how sharply pressure must curve up across a trough
MIN_TROUGH_POINTS = 30
MONSOON_SMOOTH_CELLS = 12.0
MIN_MONSOON_SHEAR = 0.004    # (m/s)/km of cyclonic shear across the axis
MIN_MONSOON_POINTS = 40
MAX_MONSOON_LAT = 20.0
MIN_TROUGH_LAT, MAX_TROUGH_LAT = 15.0, 70.0
MIN_RUN = 10              # a run of one type shorter than this takes the type before it
EARTH_KM = 6371.0
STEP = np.deg2rad(0.25)

LATS = np.linspace(90.0, -90.0, NLAT)
LONS = np.arange(-180.0, 180.0, 0.25)


def wet_bulb(t_c: np.ndarray, rh: np.ndarray) -> np.ndarray:
    """Stull (2011) wet-bulb temperature, degC, from temperature and RH (%)."""
    rh = np.clip(rh, 1.0, 100.0)
    return (t_c * np.arctan(0.151977 * np.sqrt(rh + 8.313659)) + np.arctan(t_c + rh)
            - np.arctan(rh - 1.676331) + 0.00391838 * rh ** 1.5 * np.arctan(0.023101 * rh)
            - 4.686035)


def _grad(a: np.ndarray, cos_lat: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """(d/dx east, d/dy north) per km on the image grid (row 0 is north)."""
    d_row = np.gradient(a, axis=0)
    d_col = (np.roll(a, -1, axis=1) - np.roll(a, 1, axis=1)) / 2.0     # periodic in longitude
    return d_col / (EARTH_KM * STEP * cos_lat), -d_row / (EARTH_KM * STEP)


def _sample(a: np.ndarray, lon: np.ndarray, lat: np.ndarray) -> np.ndarray:
    """Bilinear value of a grid at points (periodic in longitude)."""
    x = (lon + 180.0) / 0.25
    y = (90.0 - lat) / 0.25
    x0 = np.floor(x).astype(int)
    y0 = np.clip(np.floor(y).astype(int), 0, NLAT - 2)
    fx, fy = x - x0, y - y0
    x0 %= NLON
    x1 = (x0 + 1) % NLON
    return ((a[y0, x0] * (1 - fx) + a[y0, x1] * fx) * (1 - fy)
            + (a[y0 + 1, x0] * (1 - fx) + a[y0 + 1, x1] * fx) * fy)


def find_lows(msl_hpa: np.ndarray) -> np.ndarray:
    """(lon, lat) of deep lows: minima of the 1-degree field, 8 degrees clear and 4 hPa deep."""
    c = _gaussian_blur(msl_hpa, 4.0)[::4, ::4]            # 1 degree
    h, w = c.shape
    window = 7
    lowest = np.full_like(c, np.inf)
    ring = np.zeros_like(c)
    for dy in range(-window, window + 1):
        rolled_y = np.roll(c, dy, axis=0)
        for dx in range(-window, window + 1):
            lowest = np.minimum(lowest, np.roll(rolled_y, dx, axis=1))
    for ang in range(0, 360, 45):
        dy, dx = int(round(8 * np.sin(np.deg2rad(ang)))), int(round(8 * np.cos(np.deg2rad(ang))))
        ring += np.roll(np.roll(c, dy, axis=0), dx, axis=1) / 8.0
    ys, xs = np.nonzero((c <= lowest) & (ring - c >= LOW_DEPTH_HPA))
    lat = 90.0 - ys * 1.0
    lon = -180.0 + xs * 1.0
    keep = np.abs(lat) > 15
    return np.column_stack([lon[keep], lat[keep]])


def _km_to_nearest(lon: np.ndarray, lat: np.ndarray, points: np.ndarray) -> np.ndarray:
    if not len(points):
        return np.full(len(lon), np.inf)
    d = np.deg2rad(points[None, :, 0] - lon[:, None])
    la1, la2 = np.deg2rad(lat)[:, None], np.deg2rad(points[None, :, 1])
    cosd = np.sin(la1) * np.sin(la2) + np.cos(la1) * np.cos(la2) * np.cos(d)
    return EARTH_KM * np.arccos(np.clip(cosd, -1.0, 1.0)).min(axis=1)


def _runs(ok: np.ndarray, min_points: int):
    i = 0
    while i < len(ok):
        if not ok[i]:
            i += 1
            continue
        j = i
        while j < len(ok) and ok[j]:
            j += 1
        if j - i >= min_points:
            yield i, j
        i = j


def _line_feature(lon, lat, kind: str) -> dict:
    keep = slice(None, None, 2)
    xs = np.append(lon[keep], lon[-1]) if (len(lon) - 1) % 2 else lon[keep]
    ys = np.append(lat[keep], lat[-1]) if (len(lat) - 1) % 2 else lat[keep]
    return {"type": "Feature", "properties": {"t": kind},
            "geometry": {"type": "LineString",
                         "coordinates": [[round(float(p), 2), round(float(q), 2)] for p, q in zip(xs, ys)]}}


def _zero_lines(field: np.ndarray):
    import contourpy
    gen = contourpy.contour_generator(LONS, LATS[::-1], field[::-1], line_type=contourpy.LineType.Separate)
    return gen.lines(0.0)


def detect_troughs(u850: np.ndarray, msl_hpa: np.ndarray, terrain_weight: np.ndarray | None = None) -> list[dict]:
    """Monsoon trough ("m") and pressure trough ("p") lines."""
    cos_lat = np.maximum(np.cos(np.deg2rad(LATS)), 0.05)[:, None]
    lat2 = LATS[:, None]
    features = []

    # Monsoon trough: where smoothed u850 is zero and turns cyclonically with latitude.
    u = _gaussian_blur(u850, MONSOON_SMOOTH_CELLS)
    _, du_dy = _grad(u, cos_lat)
    shear = -np.sign(lat2) * du_dy
    for line in _zero_lines(u):
        lon, lat = line[:, 0], line[:, 1]
        ok = (_sample(shear, lon, lat) > MIN_MONSOON_SHEAR) & (np.abs(lat) < MAX_MONSOON_LAT) & (np.abs(lat) > 2)
        for i, j in _runs(ok, MIN_MONSOON_POINTS):
            features.append(_line_feature(lon[i:j], lat[i:j], "m"))

    # Pressure trough: the zero line of the pressure gradient taken along the direction
    # of strongest curvature (across the trough), where that curvature is upward.
    m = _gaussian_blur(msl_hpa, TROUGH_SMOOTH_CELLS)
    gx, gy = _grad(m, cos_lat)
    gxx, gxy = _grad(gx, cos_lat)
    gyx, gyy = _grad(gy, cos_lat)
    hxy = 0.5 * (gxy + gyx)
    lam = (gxx + gyy) / 2 + np.sqrt(((gxx - gyy) / 2) ** 2 + hxy ** 2)     # curvature across the axis
    angle = 0.5 * np.arctan2(2 * hxy, gxx - gyy)
    nx, ny = np.cos(angle), np.sin(angle)
    flip = np.where(nx < 0, -1.0, 1.0)
    across = gx * nx * flip + gy * ny * flip
    for line in _zero_lines(across):
        lon, lat = line[:, 0], line[:, 1]
        ok = (_sample(lam, lon, lat) > MIN_TROUGH_CURVATURE) & (np.abs(lat) > MIN_TROUGH_LAT) & (np.abs(lat) < MAX_TROUGH_LAT)
        if terrain_weight is not None:
            ok &= _sample(terrain_weight, lon, lat) < 0.3
        for i, j in _runs(ok, MIN_TROUGH_POINTS):
            features.append(_line_feature(lon[i:j], lat[i:j], "p"))
    return features


def detect_fronts(t850_c: np.ndarray, rh850: np.ndarray, u850: np.ndarray, v850: np.ndarray,
                  msl_hpa: np.ndarray | None = None, terrain_weight: np.ndarray | None = None) -> dict:
    """GeoJSON LineStrings with property "t": "c" cold, "w" warm or "o" occluded.

    Arrays are (NLAT, NLON) in image orientation: row 0 is 90N, column 0 is 180W.
    Each line runs with the side the front moves towards on its left.
    """
    import contourpy
    lows = find_lows(msl_hpa) if msl_hpa is not None else np.empty((0, 2))

    cos_lat = np.maximum(np.cos(np.deg2rad(LATS)), 0.05)[:, None]
    tau = _gaussian_blur(wet_bulb(t850_c, rh850), SMOOTH_CELLS)
    gx, gy = _grad(tau, cos_lat)
    mag = np.hypot(gx, gy)
    mx, my = _grad(mag, cos_lat)
    tfp = _gaussian_blur(-(mx * gx + my * gy) / np.maximum(mag, 1e-6), TFP_SMOOTH_CELLS)
    # Positive: the wind blows towards the warm side, so cold air is advancing.
    adv = _gaussian_blur((u850 * gx + v850 * gy) / np.maximum(mag, 1e-6), ADV_SMOOTH_CELLS)

    # contourpy wants the rows in ascending order of y: flip, and say so below.
    gen = contourpy.contour_generator(LONS, LATS[::-1], tfp[::-1], line_type=contourpy.LineType.Separate)
    features = []
    for line in gen.lines(0.0):
        lon, lat = line[:, 0], line[:, 1]
        if len(lon) < MIN_POINTS:
            continue
        g = _sample(mag, lon, lat)
        a = _sample(adv, lon, lat)
        ok = (g > MIN_GRADIENT) & (np.abs(lat) > MIN_LAT) & (np.abs(lat) < MAX_LAT)
        i = 0
        while i < len(lon):
            if not ok[i]:
                i += 1
                continue
            j = i
            while j < len(lon) and ok[j]:
                j += 1
            if j - i >= MIN_POINTS:
                features.extend(_pieces(lon[i:j], lat[i:j], a[i:j], _sample(gx / np.maximum(mag, 1e-6), lon[i:j], lat[i:j]),
                                        _sample(gy / np.maximum(mag, 1e-6), lon[i:j], lat[i:j]),
                                        _km_to_nearest(lon[i:j], lat[i:j], lows)))
            i = j
    if msl_hpa is not None:
        features.extend(detect_troughs(u850, msl_hpa, terrain_weight))
    return {"type": "FeatureCollection", "features": features}


def _pieces(lon, lat, across, nx, ny, low_km) -> list[dict]:
    """Split one front into runs of one type, oriented, as GeoJSON features.

    across: wind towards the warm side (m/s); (nx, ny): unit vector towards warm air.
    """
    smooth_across = np.convolve(across, np.ones(5) / 5.0, mode="same")
    kind = np.where((np.abs(smooth_across) < OCCLUDED_WIND) & (low_km < LOW_RADIUS_KM), "o",
                    np.where(smooth_across > 0, "c", "w"))
    runs, start = [], 0
    for k in range(1, len(kind) + 1):
        if k == len(kind) or kind[k] != kind[start]:
            runs.append([start, k, kind[start]])
            start = k
    for r in range(1, len(runs)):                  # absorb runs that are too short into the one before
        if runs[r][1] - runs[r][0] < MIN_RUN:
            runs[r][2] = runs[r - 1][2]
    merged = []
    for s0, e0, t in runs:
        if merged and merged[-1][2] == t:
            merged[-1][1] = e0
        else:
            merged.append([s0, e0, t])
    out = []
    for s0, e0, t in merged:
        e1 = min(len(lon), e0 + 1)                 # share the join point so pieces touch
        if e1 - s0 < 4:
            continue
        x, y = lon[s0:e1], lat[s0:e1]
        # motion: cold and occluded move towards the warm air, warm fronts towards the cold
        sign = -1.0 if t == "w" else 1.0
        mx, my = sign * nx[s0:e1].mean(), sign * ny[s0:e1].mean()
        tx = (x[-1] - x[0]) * np.cos(np.deg2rad(y.mean()))
        ty = y[-1] - y[0]
        if (-ty) * mx + tx * my < 0:               # left normal of the direction of travel, against the motion
            x, y = x[::-1], y[::-1]
        keep = slice(None, None, 2)
        xs = np.append(x[keep], x[-1]) if (len(x) - 1) % 2 else x[keep]
        ys = np.append(y[keep], y[-1]) if (len(y) - 1) % 2 else y[keep]
        out.append({"type": "Feature", "properties": {"t": str(t)},
                    "geometry": {"type": "LineString",
                                 "coordinates": [[round(float(p), 2), round(float(q), 2)] for p, q in zip(xs, ys)]}})
    return out
