#!/usr/bin/env python3
"""
Build the newest Himawari-9 infrared image and publish it to R2.

    python3 himawari.py --dry-run --dest ../web/data     # local test, no R2
    python3 himawari.py                                  # newest complete slot -> R2
    python3 himawari.py --slot 2026-11-12T13:00          # a named slot

Source: the NOAA open-data copy of JMA's Himawari-9 AHI Level-1b, bucket
noaa-himawari9 (public, anonymous). Band 13 (10.4 um, "clean" window infrared)
is 24 MB per 10-minute full disk, is available day and night, and shows cold
cloud tops, which is what a weather map wants. Visible and true colour are a
later phase: B03 alone is 140 MB per slot.

Output (same safety order as build_run.py, the manifest goes last):
    sat/ir/<YYYYMMDDTHHMMZ>.webp   image, Web Mercator, so MapLibre can place it
                                   with four corners and no distortion
    sat/manifest.json              frames, bounds, colour table, attribution

The colour table lives in the manifest, so the site draws its legend from the
same numbers that coloured the image and the two cannot drift apart.

Needs: pip install -r requirements-himawari.txt
"""

from __future__ import annotations

import argparse
import datetime as dt
import gc
import hashlib
import io
import json
import os
import re
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
from PIL import Image

BUCKET = "noaa-himawari9"
PRODUCT = "AHI-L1b-FLDK"
BAND = "B13"
SEGMENTS = 10          # a full disk is ten north-south strips; all ten or nothing

# The whole Himawari disk: the satellite sees roughly 59E to 222E at the equator
# (measured on real data). Latitude is cut at 60 because Web Mercator stretches
# without limit towards the poles. At 4 km this is ~4500 x 4200 pixels, about the
# size of the earlier 2 km Indonesia-only crop; the full area at 2 km would be
# four times that, too much to ship every ten minutes or to hold as one texture
# on a phone. The cost is blockier detail up close (B13 itself is 2 km).
WEST, EAST, SOUTH, NORTH = 59.0, 222.0, -60.0, 60.0
RES_M = 4000.0

# Brightness temperature in degrees C -> colour. Only cloud-top temperatures
# are drawn: everything at or above 0 C (surface, warm low cloud) is fully
# transparent so the forecast shows through, and the last 6 degrees fade in so
# there is no hard edge. Cold tops (deep convection) run through blue, green,
# yellow to magenta.
COLORMAP = [
    (-90, (255, 255, 255)), (-80, (255, 0, 255)), (-70, (80, 0, 160)),
    (-60, (0, 0, 255)), (-50, (0, 160, 255)), (-40, (0, 220, 0)),
    (-30, (255, 255, 0)), (-20, (215, 215, 215)), (0, (150, 150, 150)),
]
FADE_C = 6.0           # alpha runs from 0 at 0 C to full at -6 C
LEGEND_TICKS = [-80, -60, -40, -20, 0]

ATTRIBUTION = "Satellite: Himawari-9 (JMA), via NOAA Open Data"
CACHE_IMAGE = "public, max-age=31536000, immutable"
CACHE_MANIFEST = "public, max-age=60"
KEEP_FRAMES = 6


def log(message: str) -> None:
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%H:%M:%S")
    print(f"[{stamp}] {message}", flush=True)


# --------------------------------------------------------------------------
# finding the newest complete slot
# --------------------------------------------------------------------------

def noaa_client():
    import boto3
    from botocore import UNSIGNED
    from botocore.config import Config

    return boto3.client("s3", region_name="us-east-1", config=Config(signature_version=UNSIGNED))


def slot_keys(s3, slot: dt.datetime) -> list[str]:
    """Band-13 segment keys of one slot (sorted), empty if the slot is not there."""
    prefix = f"{PRODUCT}/{slot:%Y/%m/%d/%H%M}/"
    keys = []
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=BUCKET, Prefix=prefix):
        keys += [o["Key"] for o in page.get("Contents", []) if f"_{BAND}_" in o["Key"]]
    return sorted(keys)


def is_complete(keys: list[str]) -> bool:
    segs = {m.group(1) for k in keys if (m := re.search(r"_S(\d\d)\d\d\.DAT", k))}
    return len(segs) == SEGMENTS


def newest_complete_slot(s3, now: dt.datetime, tries: int = 12) -> tuple[dt.datetime, list[str]] | None:
    """Walk back from now in 10-minute steps. Slots land about 14 minutes late, so
    the first few are normally empty or partial; an incomplete one is skipped
    rather than waited for, the next run picks it up if it finishes."""
    slot = now.replace(minute=now.minute // 10 * 10, second=0, microsecond=0)
    for _ in range(tries):
        keys = slot_keys(s3, slot)
        if is_complete(keys):
            return slot, keys
        slot -= dt.timedelta(minutes=10)
    return None


# --------------------------------------------------------------------------
# reading, reprojecting, colouring
# --------------------------------------------------------------------------

def mercator(lon, lat):
    r = 6378137.0
    lat = np.clip(lat, -85, 85)
    return np.radians(lon) * r, np.log(np.tan(np.pi / 4 + np.radians(lat) / 2)) * r


def brightness_temperature(files: list[str]) -> np.ndarray:
    """Band 13 brightness temperature in kelvin on the Web Mercator grid
    (rows run north to south, NaN outside the satellite's disk)."""
    from pyresample.geometry import AreaDefinition
    from satpy import Scene

    scn = Scene(filenames=files, reader="ahi_hsd")
    scn.load([BAND])
    x0, y0 = mercator(WEST, SOUTH)
    x1, y1 = mercator(EAST, NORTH)
    w, h = int(round((x1 - x0) / RES_M)), int(round((y1 - y0) / RES_M))
    area = AreaDefinition("merc", "merc", "merc", "EPSG:3857", w, h, (x0, y0, x1, y1))
    out = scn.resample(area, resampler="nearest", radius_of_influence=2 * RES_M)
    result = np.asarray(out[BAND].values, dtype="float32")
    # Close the file handlers now. Left to interpreter shutdown, satpy's
    # __del__ prints a dozen harmless tracebacks that bury any real error.
    del out, scn
    gc.collect()
    return result


def colourise(kelvin: np.ndarray) -> np.ndarray:
    c = kelvin - 273.15
    xs = [s[0] for s in COLORMAP]
    rgb = np.stack([np.interp(c, xs, [s[1][i] for s in COLORMAP]) for i in range(3)], -1)
    # NaN (outside the disk) and anything warmer than 0 C end up at alpha 0.
    alpha = np.nan_to_num(np.clip(-c / FADE_C, 0.0, 1.0) * 255.0, nan=0.0)
    return np.dstack([rgb, alpha]).astype("uint8")


def webp_bytes(rgba: np.ndarray) -> bytes:
    buf = io.BytesIO()
    # Lossy at q80 is about 1.6 MB for this grid; lossless is 8 MB and PNG 13 MB.
    # Alpha stays exact, so the disk edge is clean.
    Image.fromarray(rgba).save(buf, format="WEBP", quality=80, method=4)
    return buf.getvalue()


# --------------------------------------------------------------------------
# where the files go
# --------------------------------------------------------------------------

class Sink:
    """Local directory (--dry-run) or R2. A small copy of build_run.Sink on
    purpose: that module pulls in the whole GRIB stack and this job must not."""

    def __init__(self, dest: str, dry_run: bool):
        self.dry_run, self.dest = dry_run, dest
        if not dry_run:
            import boto3
            from botocore.config import Config

            account = require_env("R2_ACCOUNT_ID")
            self.client = boto3.client(
                "s3", endpoint_url=f"https://{account}.r2.cloudflarestorage.com",
                aws_access_key_id=require_env("R2_ACCESS_KEY_ID"),
                aws_secret_access_key=require_env("R2_SECRET_ACCESS_KEY"),
                config=Config(signature_version="s3v4", region_name="auto"))
            self.bucket = require_env("R2_BUCKET")

    def put(self, key: str, body: bytes, content_type: str, cache_control: str) -> None:
        if self.dry_run:
            path = Path(self.dest) / key
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(body)
            return
        self.client.put_object(Bucket=self.bucket, Key=key, Body=body,
                               ContentType=content_type, CacheControl=cache_control)

    def read_json(self, key: str) -> dict | None:
        """None only when the object does not exist; any other failure raises, so
        an outage is never mistaken for 'nothing published yet'."""
        if self.dry_run:
            path = Path(self.dest) / key
            return json.loads(path.read_text()) if path.exists() else None
        from botocore.exceptions import ClientError

        try:
            return json.loads(self.client.get_object(Bucket=self.bucket, Key=key)["Body"].read())
        except ClientError as err:
            if err.response.get("Error", {}).get("Code") in ("NoSuchKey", "404", "NotFound"):
                return None
            raise

    def delete(self, key: str) -> None:
        if self.dry_run:
            (Path(self.dest) / key).unlink(missing_ok=True)
        else:
            self.client.delete_object(Bucket=self.bucket, Key=key)


def require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise SystemExit(f"environment variable {name} is not set")
    return value


# --------------------------------------------------------------------------
# the run
# --------------------------------------------------------------------------

def frame_bounds() -> dict:
    return {"west": WEST, "south": SOUTH, "east": EAST, "north": NORTH}


def manifest_for(frames: list[dict]) -> dict:
    return {
        "product": "himawari9-b13-ir",
        "label": "Satellite IR",
        "unit": "°C",
        "bounds": frame_bounds(),       # of the newest frame; each frame also carries its own
        "projection": "web-mercator",   # image rows are Mercator, corners are lon/lat
        "colormap": [[v, list(c)] for v, c in COLORMAP],
        "legend_ticks": LEGEND_TICKS,
        "attribution": ATTRIBUTION,
        "frames": frames,               # oldest first, newest last
        "updated": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--slot", help="UTC slot to build, e.g. 2026-11-12T13:00; default newest complete")
    ap.add_argument("--dry-run", action="store_true", help="write to --dest instead of R2")
    ap.add_argument("--dest", default="./out", help="output directory for --dry-run")
    ap.add_argument("--keep", type=int, default=KEEP_FRAMES, help="frames to retain")
    ap.add_argument("--force", action="store_true", help="rebuild even if this slot is published")
    args = ap.parse_args()

    t0 = time.time()
    s3 = noaa_client()
    if args.slot:
        slot = dt.datetime.strptime(args.slot, "%Y-%m-%dT%H:%M").replace(tzinfo=dt.timezone.utc)
        keys = slot_keys(s3, slot)
        if not is_complete(keys):
            raise SystemExit(f"slot {args.slot} is missing or incomplete ({len(keys)} files)")
    else:
        found = newest_complete_slot(s3, dt.datetime.now(dt.timezone.utc))
        if not found:
            raise SystemExit("no complete slot in the last two hours; NOAA copy may be behind")
        slot, keys = found
    stamp = f"{slot:%Y%m%dT%H%MZ}"
    log(f"newest complete slot: {stamp} ({len(keys)} segments)")

    sink = Sink(args.dest, args.dry_run)
    old = sink.read_json("sat/manifest.json") or {"frames": []}
    frames = old["frames"]
    # Frames from before bounds were stored per frame came from an older, smaller
    # crop. Drop them (and their images) so they can never be drawn with the
    # wrong corners.
    stale = [f for f in frames if "bounds" not in f]
    frames = [f for f in frames if "bounds" in f]
    if any(f["t"] == f"{slot:%Y-%m-%dT%H:%MZ}" for f in frames) and not args.force:
        log("already published, nothing to do")
        return

    with tempfile.TemporaryDirectory() as tmp:
        def fetch(key: str) -> str:
            path = Path(tmp) / Path(key).name
            s3.download_file(BUCKET, key, str(path))
            return str(path)

        with ThreadPoolExecutor(max_workers=SEGMENTS) as pool:   # boto3 clients are thread-safe
            files = list(pool.map(fetch, keys))
        log(f"downloaded {sum(Path(f).stat().st_size for f in files) / 1e6:.0f} MB")
        kelvin = brightness_temperature(files)

    valid = np.isfinite(kelvin)
    if valid.mean() < 0.5:
        # Nearest-neighbour onto a grid that is mostly on-disk should be mostly
        # valid; anything else means the read or the geolocation failed.
        raise SystemExit(f"only {valid.mean():.0%} of pixels valid, refusing to publish")
    log(f"reprojected {kelvin.shape[1]}x{kelvin.shape[0]}, "
        f"{np.nanmin(kelvin) - 273.15:.0f} to {np.nanmax(kelvin) - 273.15:.0f} C")

    body = webp_bytes(colourise(kelvin))
    # The file name carries a hash of the content. Images are cached for a year
    # ("immutable"), so one name must never mean two different pictures: when it
    # did (a changed crop rebuilt under the same slot name), browsers kept the old
    # picture and drew it with the new corners, squeezed.
    name = f"ir/{stamp}-{hashlib.sha1(body).hexdigest()[:8]}.webp"
    key = f"sat/{name}"
    sink.put(key, body, "image/webp", CACHE_IMAGE)
    log(f"uploaded {key} ({len(body) / 1e6:.1f} MB)")

    frames = [f for f in frames if f["t"] != f"{slot:%Y-%m-%dT%H:%MZ}"]
    frames.append({"t": f"{slot:%Y-%m-%dT%H:%MZ}", "image": name, "bounds": frame_bounds()})
    frames.sort(key=lambda f: f["t"])
    dropped, frames = frames[:-args.keep] + stale, frames[-args.keep:]

    # Manifest last: until this write the site keeps showing the previous frame.
    sink.put("sat/manifest.json", json.dumps(manifest_for(frames)).encode(),
             "application/json", CACHE_MANIFEST)
    keep_images = {f["image"] for f in frames}
    for f in dropped:
        if f["image"] not in keep_images:      # never delete a file a kept frame still uses
            sink.delete(f"sat/{f['image']}")
    log(f"done in {time.time() - t0:.0f}s, {len(frames)} frames kept, {len(dropped)} pruned")


if __name__ == "__main__":
    sys.exit(main())
