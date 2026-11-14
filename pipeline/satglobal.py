#!/usr/bin/env python3
"""
Build the newest global infrared mosaic (Himawari-9 + GOES-West + GOES-East)
and publish it to R2.

    python3 satglobal.py --dry-run --dest ../web/data     # local test, no R2
    python3 satglobal.py                                  # newest slot -> R2
    python3 satglobal.py --slot 2026-11-14T12:00          # a named slot

Sources, all from the NOAA open-data buckets (public, anonymous), band 13
(10.4 um clean window infrared), one full disk every 10 minutes each:

    Himawari-9  (JMA)   140.7E   bucket noaa-himawari9   AHI-L1b-FLDK
    GOES-18     (NOAA) -137.2    bucket noaa-goes18      ABI-L1b-RadF  (GOES-West)
    GOES-19     (NOAA)  -75.2    bucket noaa-goes19      ABI-L1b-RadF  (GOES-East)

Together they cover everything except roughly 0E to 65E (Africa, Europe, the
western Indian Ocean), which only Meteosat sees. Meteosat needs an EUMETSAT
account and a licence check, so it is a later step; that stretch stays
transparent until then.

Every pixel takes its value from the satellite that looks straight down on it
most closely (smallest angle from that satellite's sub-point), which also keeps
the strongly limb-cooled pixels out. Seams fall about 40 degrees from both
satellites. No intercalibration is done between them, so a faint seam is
possible where two sensors disagree by a degree or so.

The mosaic is one Web Mercator grid at about 4 km, 60S to 60N, all the way
round. As one image it would be about 10000 x 4200 pixels, too big a texture for
many phones, so it is cut into four longitude tiles that overlap by a couple of
pixels (otherwise MapLibre draws hairline gaps between them).

Output (same safety order as himawari.py, the manifest goes last):
    sat/ir_g/<YYYYMMDDTHHMMZ>-t<k>-<hash>.webp   the four tiles of one slot
    sat/global.json                              frames, tiles, colour table

himawari.py and its sat/manifest.json are left alone; the site reads
global.json first and falls back to manifest.json.

Needs: pip install -r requirements-satglobal.txt
"""

from __future__ import annotations

import argparse
import datetime as dt
import gc
import hashlib
import json
import re
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

import himawari as hw   # shared: colours, WebP, R2 sink, Himawari slot lookup

R = 6378137.0
RES_M = 4000.0
# Pixel size is chosen so a whole number of pixels spans the world exactly.
W = int(round(2 * np.pi * R / RES_M))                 # 10019 columns round the world
PX = 2 * np.pi * R / W                                # metres per pixel
H = 4200                                              # rows, 60S to 60N
YMAX = H / 2 * PX                                     # mercator metres at the top edge
NORTH = float(np.degrees(2 * np.arctan(np.exp(YMAX / R)) - np.pi / 2))
SOUTH = -NORTH

TILES = 4
OVERLAP_PX = 2

# Use a satellite only within this many degrees of its sub-point. The disk edge
# is about 81 degrees; the last few degrees are mostly limb cooling and smear.
MAX_ANGLE = 76.0
MAX_WINDOW = 78.0     # half-width of the longitude window each satellite is resampled onto

SATS = {
    "himawari9": {"sub": 140.7, "reader": "ahi_hsd", "channel": "B13"},
    "goes18": {"sub": -137.2, "reader": "abi_l1b", "channel": "C13",
               "bucket": "noaa-goes18", "tag": "G18"},
    "goes19": {"sub": -75.2, "reader": "abi_l1b", "channel": "C13",
               "bucket": "noaa-goes19", "tag": "G19"},
}
GOES_PRODUCT = "ABI-L1b-RadF"

ATTRIBUTION = ("Satellite: Himawari-9 (JMA), GOES-18 and GOES-19 (NOAA/NESDIS), "
               "via NOAA Open Data")
CACHE_IMAGE = hw.CACHE_IMAGE
CACHE_MANIFEST = hw.CACHE_MANIFEST
HISTORY_HOURS = hw.HISTORY_HOURS
MAX_NEW = 3           # a frame takes longer than Himawari alone
PARTIAL_AFTER_MIN = 40  # build without a late GOES file only once the slot is this old

log = hw.log
iso = hw.iso


# --------------------------------------------------------------------------
# finding the files of one slot
# --------------------------------------------------------------------------

def goes_key(s3, name: str, slot: dt.datetime) -> str | None:
    """The band-13 file of GOES satellite `name` whose scan began at `slot`
    (within three minutes; scans start about 20 s past the 10-minute mark)."""
    spec = SATS[name]
    best = None
    for hour in {slot.replace(minute=0), (slot - dt.timedelta(minutes=5)).replace(minute=0)}:
        prefix = f"{GOES_PRODUCT}/{hour:%Y}/{hour:%j}/{hour:%H}/"
        for page in s3.get_paginator("list_objects_v2").paginate(Bucket=spec["bucket"], Prefix=prefix):
            for o in page.get("Contents", []):
                m = re.search(rf"C13_{spec['tag']}_s(\d{{4}})(\d{{3}})(\d{{2}})(\d{{2}})(\d{{2}})", o["Key"])
                if not m:
                    continue
                start = dt.datetime.strptime("".join(m.groups()), "%Y%j%H%M%S").replace(tzinfo=dt.timezone.utc)
                gap = abs((start - slot).total_seconds())
                if gap <= 180 and (best is None or gap < best[0]):
                    best = (gap, o["Key"])
    return best[1] if best else None


def sources_for(s3, slot: dt.datetime) -> dict[str, list[str]]:
    """{satellite: [keys]} for whatever is already uploaded for this slot."""
    found: dict[str, list[str]] = {}
    keys = hw.slot_keys(s3, slot)
    if hw.is_complete(keys):
        found["himawari9"] = keys
    for name in ("goes18", "goes19"):
        key = goes_key(s3, name, slot)
        if key:
            found[name] = [key]
    return found


def slot_ready(found: dict[str, list[str]], slot: dt.datetime, now: dt.datetime) -> bool:
    if "himawari9" not in found and len(found) < 2:
        return False
    if len(found) == len(SATS):
        return True
    return (now - slot) > dt.timedelta(minutes=PARTIAL_AFTER_MIN) and bool(found)


# --------------------------------------------------------------------------
# reading and merging
# --------------------------------------------------------------------------

def window_columns(sub: float) -> tuple[int, int]:
    """Canvas columns (unwrapped, may run past W) of the window around a sub-point."""
    c0 = int(np.floor((sub - MAX_WINDOW + 180.0) / 360.0 * W))
    c1 = int(np.ceil((sub + MAX_WINDOW + 180.0) / 360.0 * W))
    return c0, c1


def window_bt(files: list[str], name: str) -> tuple[np.ndarray, int]:
    """Brightness temperature (K) of one satellite on its canvas window, and the
    first column of that window. NaN outside the disk."""
    from pyresample.geometry import AreaDefinition
    from satpy import Scene

    spec = SATS[name]
    c0, c1 = window_columns(spec["sub"])
    x0 = -np.pi * R + c0 * PX
    x1 = -np.pi * R + c1 * PX
    scn = Scene(filenames=files, reader=spec["reader"])
    scn.load([spec["channel"]])
    area = AreaDefinition("g", "g", "g", "EPSG:3857", c1 - c0, H, (x0, -YMAX, x1, YMAX))
    out = scn.resample(area, resampler="nearest", radius_of_influence=2 * RES_M)
    bt = np.asarray(out[spec["channel"]].values, dtype="float32")
    del out, scn
    gc.collect()
    return bt, c0


def row_lat() -> np.ndarray:
    y = YMAX - (np.arange(H) + 0.5) * PX
    return np.degrees(2 * np.arctan(np.exp(y / R)) - np.pi / 2)


def merge(parts: dict[str, tuple[np.ndarray, int]]) -> np.ndarray:
    """Each pixel from the satellite with the smallest angle to its sub-point."""
    out = np.full((H, W), np.nan, dtype="float32")
    best = np.full((H, W), np.inf, dtype="float32")
    cos_lat = np.cos(np.radians(row_lat()))[:, None].astype("float32")
    for name, (bt, c0) in parts.items():
        nc = bt.shape[1]
        cols = np.arange(c0, c0 + nc)
        lon = (cols + 0.5) / W * 360.0 - 180.0
        delta = (lon - SATS[name]["sub"] + 180.0) % 360.0 - 180.0
        cos_d = np.clip(cos_lat * np.cos(np.radians(delta))[None, :], -1.0, 1.0)
        ang = np.degrees(np.arccos(cos_d)).astype("float32")
        ok = np.isfinite(bt) & (ang <= MAX_ANGLE)
        idx = cols % W
        cur_best = best[:, idx]
        take = ok & (ang < cur_best)
        out[:, idx] = np.where(take, bt, out[:, idx])
        best[:, idx] = np.where(take, ang, cur_best)
        del ang, cos_d, ok, take, cur_best
        gc.collect()
    del best
    return out


# --------------------------------------------------------------------------
# tiles
# --------------------------------------------------------------------------

def tile_ranges() -> list[tuple[int, int]]:
    edges = [round(k * W / TILES) for k in range(TILES + 1)]
    return [(max(0, edges[k] - OVERLAP_PX), min(W, edges[k + 1] + OVERLAP_PX)) for k in range(TILES)]


def tile_bounds(c0: int, c1: int) -> dict:
    return {"west": c0 / W * 360.0 - 180.0, "south": SOUTH,
            "east": c1 / W * 360.0 - 180.0, "north": NORTH}


# --------------------------------------------------------------------------
# the run
# --------------------------------------------------------------------------

def manifest_for(frames: list[dict]) -> dict:
    return {
        "product": "global-geo-b13-ir",
        "label": "Satellite IR",
        "unit": "°C",
        "bounds": {"west": -180.0, "south": SOUTH, "east": 180.0, "north": NORTH},
        "projection": "web-mercator",
        "colormap": [[v, list(c)] for v, c in hw.COLORMAP],
        "legend_ticks": hw.LEGEND_TICKS,
        "attribution": ATTRIBUTION,
        "frames": frames,               # oldest first; each has "tiles": [{image, bounds}]
        "updated": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
    }


def write_manifest(sink, frames: list[dict]) -> None:
    sink.put("sat/global.json", json.dumps(manifest_for(frames)).encode(),
             "application/json", CACHE_MANIFEST)


def build_frame(s3, slot: dt.datetime, found: dict[str, list[str]], sink) -> dict:
    stamp = f"{slot:%Y%m%dT%H%MZ}"
    with tempfile.TemporaryDirectory() as tmp:
        def fetch(item):
            name, key = item
            bucket = hw.BUCKET if name == "himawari9" else SATS[name]["bucket"]
            # Original file name, in a folder per satellite: satpy recognises
            # its files by name, so they must not be renamed.
            path = Path(tmp) / name / Path(key).name
            path.parent.mkdir(parents=True, exist_ok=True)
            s3.download_file(bucket, key, str(path))
            return name, str(path)

        jobs = [(n, k) for n, keys in found.items() for k in keys]
        with ThreadPoolExecutor(max_workers=12) as pool:
            got = list(pool.map(fetch, jobs))
        files: dict[str, list[str]] = {}
        for name, path in got:
            files.setdefault(name, []).append(path)
        log(f"{stamp}: downloaded {sum(Path(p).stat().st_size for _, p in got) / 1e6:.0f} MB "
            f"from {', '.join(sorted(files))}")

        parts = {}
        for name in files:
            parts[name] = window_bt(sorted(files[name]), name)
            log(f"{stamp}: {name} resampled")

    kelvin = merge(parts)
    del parts
    gc.collect()
    valid = np.isfinite(kelvin)
    if valid.mean() < 0.4:
        raise SystemExit(f"{stamp}: only {valid.mean():.0%} of the canvas valid, refusing to publish")
    rgba = hw.colourise(kelvin)
    del kelvin, valid
    gc.collect()

    tiles = []
    for k, (c0, c1) in enumerate(tile_ranges()):
        body = hw.webp_bytes(rgba[:, c0:c1])
        # Content hash in the name, as in himawari.py: images are cached for a
        # year, so one name must never mean two pictures.
        name = f"ir_g/{stamp}-t{k}-{hashlib.sha1(body).hexdigest()[:8]}.webp"
        sink.put(f"sat/{name}", body, "image/webp", CACHE_IMAGE)
        tiles.append({"image": name, "bounds": tile_bounds(c0, c1)})
    log(f"{stamp}: uploaded {len(tiles)} tiles")
    return {"t": iso(slot), "tiles": tiles, "sources": sorted(found)}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--slot", help="treat this UTC slot as the newest, e.g. 2026-11-14T12:00")
    ap.add_argument("--dry-run", action="store_true", help="write to --dest instead of R2")
    ap.add_argument("--dest", default="./out", help="output directory for --dry-run")
    ap.add_argument("--hours", type=float, default=HISTORY_HOURS, help="hours of history to keep")
    ap.add_argument("--max-new", type=int, default=MAX_NEW, help="most frames to build in this run")
    ap.add_argument("--force", action="store_true", help="rebuild the newest slot even if published")
    args = ap.parse_args()

    t0 = time.time()
    now = dt.datetime.now(dt.timezone.utc)
    s3 = hw.noaa_client()
    if args.slot:
        newest = dt.datetime.strptime(args.slot, "%Y-%m-%dT%H:%M").replace(tzinfo=dt.timezone.utc)
    else:
        # Himawari decides which slot is the newest; GOES lands about as fast.
        found = hw.newest_complete_slot(s3, now)
        if not found:
            raise SystemExit("no complete Himawari slot in the last two hours; NOAA copy may be behind")
        newest = found[0]
    log(f"newest slot: {iso(newest)}")

    sink = hw.Sink(args.dest, args.dry_run)
    old = sink.read_json("sat/global.json") or {"frames": []}
    frames = [f for f in old["frames"] if all(sink.exists(f"sat/{t['image']}") for t in f.get("tiles", []))
              and f.get("tiles")]
    stale = [f for f in old["frames"] if f not in frames]

    n = int(round(args.hours * 6))
    wanted = [newest - dt.timedelta(minutes=10 * k) for k in range(n + 1)]
    have = {f["t"] for f in frames}
    todo = [sl for sl in wanted if iso(sl) not in have or (sl == newest and args.force)]
    if not todo:
        log("already published, nothing to do")
        if stale:
            write_manifest(sink, frames)
        return
    todo = todo[:args.max_new]
    log(f"building up to {len(todo)} of {len(wanted)} slots in the window")

    for slot in todo:
        found = sources_for(s3, slot)
        if not slot_ready(found, slot, now):
            log(f"{iso(slot)}: sources not all there yet ({', '.join(sorted(found)) or 'none'}), skipped")
            continue
        frame = build_frame(s3, slot, found, sink)
        frames = [f for f in frames if f["t"] != frame["t"]] + [frame]
        frames.sort(key=lambda f: f["t"])
        write_manifest(sink, frames)      # after every frame: a crash loses nothing built

    oldest = iso(newest - dt.timedelta(minutes=10 * n))
    dropped = [f for f in frames if f["t"] < oldest] + stale
    frames = [f for f in frames if f["t"] >= oldest]
    if dropped:
        write_manifest(sink, frames)
        keep = {t["image"] for f in frames for t in f["tiles"]}
        for f in dropped:
            for t in f.get("tiles", []):
                if t["image"] not in keep:
                    sink.delete(f"sat/{t['image']}")
    log(f"done in {time.time() - t0:.0f}s, {len(frames)} frames kept, {len(dropped)} pruned")


if __name__ == "__main__":
    sys.exit(main())
