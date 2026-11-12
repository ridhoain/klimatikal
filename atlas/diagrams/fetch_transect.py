#!/usr/bin/env python3
"""
Sample an elevation profile along a straight line and save it for the atlas
diagrams. Run by hand when a diagram needs new terrain; the result is committed,
so the site build never touches the network.

    python3 atlas/diagrams/fetch_transect.py --name bahorok-transect \
        --lat 3.60 --lon 98.10 --azimuth 45 --from-km -200 --to-km 120

The line passes through (lat, lon) at distance 0 and runs along `azimuth`
(degrees clockwise from north); distances are kilometres along it, negative
behind. Elevations come from NASA's SRTM 30 m model (public domain) through
the OpenTopoData public API, which asks for gentle use: 100 points per request
and about one request a second. Sea comes back as no data and is stored as null.

Only coordinates of public geography are sent.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://api.opentopodata.org/v1/srtm30m"
KM_PER_DEG_LAT = 111.19  # mean; this is a schematic, not a survey


def point_at(lat0, lon0, azimuth_deg, km):
    """Flat-earth step: accurate to well under a km over a few hundred km here."""
    th = math.radians(azimuth_deg)
    lat = lat0 + km * math.cos(th) / KM_PER_DEG_LAT
    mid = math.radians((lat + lat0) / 2)
    lon = lon0 + km * math.sin(th) / (KM_PER_DEG_LAT * math.cos(mid))
    return lat, lon


def fetch_batch(points):
    locs = "|".join(f"{la:.5f},{lo:.5f}" for la, lo in points)
    url = f"{API}?{urllib.parse.urlencode({'locations': locs, 'interpolation': 'bilinear'}, safe=',|')}"
    try:
        with urllib.request.urlopen(url, timeout=60) as r:
            data = json.load(r)
    except Exception as err:  # some Python installs lack CA certificates: fall back to curl
        print(f"  urllib failed ({err}); retrying with curl", file=sys.stderr)
        out = subprocess.run(["curl", "-s", "-m", "60", url], capture_output=True, text=True, check=True).stdout
        data = json.loads(out)
    if data.get("status") != "OK":
        raise SystemExit(f"API error: {data}")
    return [res["elevation"] for res in data["results"]]


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--name", required=True)
    p.add_argument("--lat", type=float, required=True)
    p.add_argument("--lon", type=float, required=True)
    p.add_argument("--azimuth", type=float, required=True)
    p.add_argument("--from-km", type=float, required=True)
    p.add_argument("--to-km", type=float, required=True)
    p.add_argument("--step-km", type=float, default=1.0)
    p.add_argument("--out", default=str(Path(__file__).resolve().parent))
    a = p.parse_args()

    n = int(round((a.to_km - a.from_km) / a.step_km)) + 1
    dists = [a.from_km + i * a.step_km for i in range(n)]
    pts = [point_at(a.lat, a.lon, a.azimuth, d) for d in dists]
    print(f"{n} points from {pts[0][0]:.3f},{pts[0][1]:.3f} to {pts[-1][0]:.3f},{pts[-1][1]:.3f}")

    elev = []
    for i in range(0, n, 100):
        elev += fetch_batch(pts[i:i + 100])
        print(f"  fetched {len(elev)}/{n}")
        time.sleep(1.2)

    result = {
        "name": a.name,
        "source": "NASA SRTM 30 m digital elevation model (public domain), via the OpenTopoData public API (dataset srtm30m)",
        "interpolation": "bilinear",
        "accessed": dt.date.today().isoformat(),
        "reference": {"lat": a.lat, "lon": a.lon, "note": "distance 0 km on the line"},
        "azimuth_deg": a.azimuth,
        "step_km": a.step_km,
        "from_km": a.from_km,
        "start": {"lat": round(pts[0][0], 5), "lon": round(pts[0][1], 5)},
        "end": {"lat": round(pts[-1][0], 5), "lon": round(pts[-1][1], 5)},
        "distance_km": [round(d, 3) for d in dists],
        "elevation_m": [None if e is None else round(e, 1) for e in elev],
        "landmarks": [],
    }
    out = Path(a.out) / f"{a.name}.json"
    out.write_text(json.dumps(result, indent=1))
    valid = [e for e in elev if e is not None]
    print(f"wrote {out}: {len(valid)} land/valid points, {n - len(valid)} sea/no-data, max {max(valid):.0f} m")


if __name__ == "__main__":
    main()
