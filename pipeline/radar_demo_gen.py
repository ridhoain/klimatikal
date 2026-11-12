#!/usr/bin/env python3
"""
Generate placeholder radar imagery so the web UI's radar layer can be built
and reviewed before a real feed exists.

These are NOT real weather and are NOT fetched from BMKG, or from any other
radar provider: every pixel is synthetic, built from random Gaussian blobs.
manifest.json carries "demo": true and every station name is suffixed
"(demo)" so the page can never show this as live data by accident.

We do not currently have permission to pull BMKG's SIDARMA nowcast radar
feed (see memory: klimatikal-deployment.md, "open items"). This script is
the stand-in until that is resolved: swap web/radar/manifest.json for one a
real pipeline job produces, in the same shape, and nothing else changes.

Run manually; this is not part of the scheduled pipeline:
    python3 radar_demo_gen.py --out ../web/radar
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path

import numpy as np
from PIL import Image

SIZE = 320  # px, square per station tile

# City centre + a public, generic approximation of BMKG C-band radar range
# (about 250 km). These are ordinary city coordinates, not pulled from any
# BMKG endpoint, and deliberately not the stations seen in any gated
# response: this is placeholder geography for layout testing only.
STATIONS = [
    {"id": "demo-medan", "name": "Medan (demo)", "lat": 3.5952, "lon": 98.6722},
    {"id": "demo-palembang", "name": "Palembang (demo)", "lat": -2.9909, "lon": 104.7566},
    {"id": "demo-surabaya", "name": "Surabaya (demo)", "lat": -7.2458, "lon": 112.7378},
    {"id": "demo-makassar", "name": "Makassar (demo)", "lat": -5.1477, "lon": 119.4327},
    {"id": "demo-balikpapan", "name": "Balikpapan (demo)", "lat": -1.2654, "lon": 116.8312},
    {"id": "demo-jayapura", "name": "Jayapura (demo)", "lat": -2.5337, "lon": 140.7181},
]
HALF_SPAN = 2.25  # degrees, ~250 km

# Reflectivity colour ramp, loosely NWS-style. Keep this in step with
# RADAR_RAMP in web/index.html: that builds the legend key, this bakes the
# same colours into the pixels, and the two must agree the way the ECMWF
# layers' encode/decode do (see pipeline/encoding.py's "one rule").
STOPS = [
    (5, (0, 0, 0, 0)),
    (10, (100, 180, 230, 90)),
    (20, (60, 190, 90, 190)),
    (30, (235, 220, 70, 220)),
    (40, (240, 150, 40, 235)),
    (50, (220, 50, 50, 245)),
    (60, (190, 60, 190, 255)),
]


def colour_for(dbz: np.ndarray) -> np.ndarray:
    out = np.zeros(dbz.shape + (4,), dtype=np.uint8)
    for (v0, c0), (v1, c1) in zip(STOPS, STOPS[1:]):
        mask = (dbz >= v0) & (dbz <= v1)
        if not mask.any():
            continue
        t = ((dbz[mask] - v0) / (v1 - v0))[:, None]
        a, b = np.array(c0, dtype=np.float64), np.array(c1, dtype=np.float64)
        out[mask] = np.round(a + (b - a) * t).astype(np.uint8)
    out[dbz > STOPS[-1][0]] = STOPS[-1][1]
    return out


def synthetic_tile(seed: int) -> np.ndarray:
    """A few soft Gaussian blobs, shaped roughly like a rain cell cluster."""
    rng = np.random.default_rng(seed)
    y, x = np.mgrid[0:SIZE, 0:SIZE]
    field = np.zeros((SIZE, SIZE))
    for _ in range(rng.integers(3, 7)):
        cx, cy = rng.uniform(0, SIZE, 2)
        sx, sy = rng.uniform(SIZE * 0.08, SIZE * 0.22, 2)
        amp = rng.uniform(15, 55)
        field += amp * np.exp(-(((x - cx) ** 2) / (2 * sx**2) + ((y - cy) ** 2) / (2 * sy**2)))
    field += rng.normal(0, 1.5, field.shape)
    return np.clip(field, 0, 65)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="../web/radar", help="output directory")
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    manifest = {
        "demo": True,
        "note": "Synthetic placeholder imagery for UI development. Not from BMKG or any live radar feed.",
        "unit": "dBZ",
        "generated": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "stations": [],
    }
    for i, station in enumerate(STATIONS):
        rgba = colour_for(synthetic_tile(seed=i))
        Image.fromarray(rgba, mode="RGBA").save(out / f"{station['id']}.png", optimize=True)
        manifest["stations"].append(
            {
                "id": station["id"],
                "name": station["name"],
                "image": f"{station['id']}.png",
                "bounds": {
                    "south": round(station["lat"] - HALF_SPAN, 4),
                    "north": round(station["lat"] + HALF_SPAN, 4),
                    "west": round(station["lon"] - HALF_SPAN, 4),
                    "east": round(station["lon"] + HALF_SPAN, 4),
                },
            }
        )
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"wrote {len(STATIONS)} demo station tiles + manifest.json to {out}")


if __name__ == "__main__":
    main()
