#!/usr/bin/env python3
"""
Sample a regular grid of elevations for an illustrated relief map and save it for
the atlas diagrams. Run by hand; the result is committed, so the site build never
touches the network.

    python3 atlas/diagrams/fetch_grid.py --name bromo-grid --lat-from -8.03 --lat-to -7.855 \
        --lon-from 112.86 --lon-to 113.04 --step 0.003

Elevations come from NASA's SRTM 30 m model (public domain) through the OpenTopoData
public API, which asks for gentle use: 100 points per request and about one request a
second (HTTP 429 is retried after a pause). Only coordinates of public geography are sent.
"""
from __future__ import annotations
import argparse, datetime as dt, json, subprocess, sys, time, urllib.error, urllib.parse, urllib.request
from pathlib import Path

API = "https://api.opentopodata.org/v1/srtm30m"


def fetch_batch(points):
    locs = "|".join(f"{la:.5f},{lo:.5f}" for la, lo in points)
    url = f"{API}?{urllib.parse.urlencode({'locations': locs, 'interpolation': 'bilinear'}, safe=',|')}"
    for attempt in range(8):
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                data = json.load(r)
        except urllib.error.HTTPError as err:
            if err.code == 429:
                time.sleep(20 + 10 * attempt)
                continue
            raise
        except Exception as err:  # some Python installs lack CA certificates: fall back to curl
            print(f"  urllib failed ({err}); retrying with curl", file=sys.stderr)
            data = json.loads(subprocess.run(["curl", "-s", "-m", "60", url], capture_output=True, text=True, check=True).stdout)
        if data.get("status") == "OK":
            return [res["elevation"] for res in data["results"]]
        time.sleep(20)
    raise SystemExit("API kept refusing; try again later")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--name", required=True)
    p.add_argument("--lat-from", type=float, required=True); p.add_argument("--lat-to", type=float, required=True)
    p.add_argument("--lon-from", type=float, required=True); p.add_argument("--lon-to", type=float, required=True)
    p.add_argument("--step", type=float, default=0.003)
    a = p.parse_args()
    lats, la = [], max(a.lat_from, a.lat_to)       # north first, like an image
    while la >= min(a.lat_from, a.lat_to) - 1e-9:
        lats.append(round(la, 5)); la -= a.step
    lons, lo = [], min(a.lon_from, a.lon_to)
    while lo <= max(a.lon_from, a.lon_to) + 1e-9:
        lons.append(round(lo, 5)); lo += a.step
    pts = [(la_, lo_) for la_ in lats for lo_ in lons]
    print(f"{len(lats)} x {len(lons)} = {len(pts)} points")
    elev = []
    for i in range(0, len(pts), 100):
        elev += fetch_batch(pts[i:i + 100]); time.sleep(1.2)
        if (i // 100) % 5 == 0:
            print(f"  {len(elev)}/{len(pts)}", flush=True)
    grid = [[(None if v is None else round(v)) for v in elev[r * len(lons):(r + 1) * len(lons)]] for r in range(len(lats))]
    doc = {"name": a.name, "source": "NASA SRTM 30 m (public domain) via OpenTopoData", "url": "https://www.opentopodata.org/datasets/srtm/",
           "accessed": dt.date.today().isoformat(), "lat": lats, "lon": lons, "step_deg": a.step, "elevation_m": grid}
    Path(__file__).with_name(f"{a.name}.json").write_text(json.dumps(doc))
    flat = [v for row in grid for v in row if v is not None]
    print("wrote", a.name, "min", min(flat), "max", max(flat))


if __name__ == "__main__":
    main()
