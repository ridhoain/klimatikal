"""Extratropical low-pressure systems, found and followed in the model's sea-level pressure.

There is no open feed of every low on the map, and the named ones (the European
windstorm names, for example) are only a few of them, so the lows are detected
from the forecast itself: at each step a low is a minimum of the sea-level
pressure that is clearly below its surroundings (see find_lows in fronts.py, which
also needs it). Minima are then joined from one step to the next into tracks by
nearest neighbour, within the distance a low can plausibly travel in the time
between steps. A track that never gets below MIN_TRACK_HPA is dropped: it is a
weak trough, not a storm worth drawing.

Output, one file per run (lows.json):
  {"run": "...", "tracks": [{"id": "L1", "min_hpa": 958.3, "min_step": 72,
                             "pts": [[step, lon, lat, hpa], ...]}, ...]}
Tracks are numbered from the deepest. Positions are good to the 0.25 degree grid,
pressures to about a hPa (the field is smoothed a little, see CENTRE_SMOOTH_CELLS).
This is the model's lows, not an analysis, and not a list of named storms: names
come later, from a separate, hand-kept file.
"""
from __future__ import annotations

import numpy as np

from encoding import NLAT, NLON, _gaussian_blur
from fronts import EARTH_KM, find_lows

MIN_LAT = 25.0            # nearer the equator it is the tropical cyclone layer's business
MAX_LAT = 85.0
CENTRE_SMOOTH_CELLS = 2.0  # half a degree: takes the grid-scale noise out of the centre pressure
REFINE_CELLS = 6           # search +-1.5 degrees round the coarse minimum for the real one
MIN_TRACK_HPA = 1000.0     # a track must get at least this deep somewhere
MIN_STEPS = 3              # ...and last at least this many steps
SPEED_KMH = 110.0          # the fastest a low is allowed to move between two steps
SLACK_KM = 150.0           # plus this much, for the coarse centre
MAX_GAP = 1                # a track survives this many steps with no match

LATS = np.linspace(90.0, -90.0, NLAT)


def _km(lon1, lat1, lon2, lat2) -> float:
    la1, la2 = np.deg2rad(lat1), np.deg2rad(lat2)
    d = np.deg2rad(lon2 - lon1)
    c = np.sin(la1) * np.sin(la2) + np.cos(la1) * np.cos(la2) * np.cos(d)
    return float(EARTH_KM * np.arccos(np.clip(c, -1.0, 1.0)))


def detect_lows(msl_hpa: np.ndarray) -> list[dict]:
    """The lows of one step: [{"lon", "lat", "hpa"}], deepest first."""
    coarse = find_lows(msl_hpa)                    # (lon, lat) at 1 degree, |lat| > 15
    if not len(coarse):
        return []
    field = _gaussian_blur(msl_hpa, CENTRE_SMOOTH_CELLS)
    out = []
    for lon, lat in coarse:
        if not (MIN_LAT <= abs(lat) <= MAX_LAT):
            continue
        x = int(round((lon + 180.0) / 0.25)) % NLON
        y = int(round((90.0 - lat) / 0.25))
        y0, y1 = max(0, y - REFINE_CELLS), min(NLAT, y + REFINE_CELLS + 1)
        cols = [(x + dx) % NLON for dx in range(-REFINE_CELLS, REFINE_CELLS + 1)]
        window = field[y0:y1][:, cols]
        iy, ix = np.unravel_index(int(np.argmin(window)), window.shape)
        yy, xx = y0 + iy, cols[ix]
        out.append({"lon": float(-180.0 + xx * 0.25), "lat": float(LATS[yy]), "hpa": float(field[yy, xx])})
    # Two coarse minima can refine to the same centre.
    out.sort(key=lambda p: p["hpa"])
    kept: list[dict] = []
    for p in out:
        if all(_km(p["lon"], p["lat"], q["lon"], q["lat"]) > 300.0 for q in kept):
            kept.append(p)
    return kept


def track_lows(lows_by_step: dict[int, list[dict]]) -> list[dict]:
    """Join the lows of successive steps into tracks (see the module note)."""
    steps = sorted(lows_by_step)
    active: list[dict] = []        # {"pts": [[step, lon, lat, hpa]], "gap": int}
    done: list[dict] = []
    for step in steps:
        cands = list(lows_by_step[step])
        pairs = []
        for ti, tr in enumerate(active):
            ls, llon, llat, _ = tr["pts"][-1]
            reach = SPEED_KMH * (step - ls) + SLACK_KM
            for ci, c in enumerate(cands):
                d = _km(llon, llat, c["lon"], c["lat"])
                if d <= reach:
                    pairs.append((d / reach, ti, ci))
        pairs.sort()
        used_t, used_c = set(), set()
        for _, ti, ci in pairs:
            if ti in used_t or ci in used_c:
                continue
            used_t.add(ti); used_c.add(ci)
            c = cands[ci]
            active[ti]["pts"].append([step, c["lon"], c["lat"], c["hpa"]])
            active[ti]["gap"] = 0
        still = []
        for ti, tr in enumerate(active):
            if ti not in used_t:
                tr["gap"] += 1
            (done if tr["gap"] > MAX_GAP else still).append(tr)
        active = still
        for ci, c in enumerate(cands):
            if ci not in used_c:
                active.append({"pts": [[step, c["lon"], c["lat"], c["hpa"]]], "gap": 0})
    done.extend(active)

    tracks = []
    for tr in done:
        pts = tr["pts"]
        low = min(pts, key=lambda p: p[3])
        if len(pts) >= MIN_STEPS and low[3] <= MIN_TRACK_HPA:
            tracks.append({"min_hpa": round(low[3], 1), "min_step": int(low[0]),
                           "pts": [[int(s), round(lo, 2), round(la, 2), round(h, 1)] for s, lo, la, h in pts]})
    tracks.sort(key=lambda t: t["min_hpa"])
    for i, t in enumerate(tracks, 1):
        t["id"] = f"L{i}"
    return [{"id": t.pop("id"), **t} for t in tracks]
