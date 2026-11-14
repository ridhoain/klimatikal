#!/usr/bin/env python3
"""
Archive the newest BMKG SIDARMA nowcast radar frame (CMAX) per station and
publish it to R2, in the same shape the site's radar layer already reads.

    python3 bmkg_radar.py --dry-run --dest ../web/data     # local test, no R2
    python3 bmkg_radar.py                                  # newest frames -> R2

PERMISSION: this fetches BMKG's public viewer endpoint (publik.bmkg.go.id/event/dwt).
BMKG has not confirmed in writing that third parties may republish it, and
radar_demo_gen.py documents that as an open item. The workflow that runs this
is therefore manual-only until that is settled. Do not schedule it first.

Source behaviour (observed 14 Nov 2026, not documented by BMKG):
    GET apihub?r=radar&site=<CODE>  ->  {"site", "bounds": [[N,W],[S,E]],
                                         "layers": [{"time": "... WIB", "url": signed}]}
Each call returns only the NEWEST frame (layers may be empty), so history exists
only because this job keeps polling. The signed url is short-lived and is used
immediately. The filename's time is UTC; the layer's "time" is WIB (UTC+7).

Output (manifest last, like himawari.py):
    radar/<SITE>/<YYYYMMDDTHHMMZ>.webp   lossless WebP, lon/lat-aligned, as BMKG serves it
    radar/manifest.json                  stations -> newest image + bounds, plus frames

Keeps HISTORY_HOURS of frames per station. Needs: pip install -r requirements-bmkg-radar.txt
"""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import io
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

from PIL import Image

BASE = "https://publik.bmkg.go.id/event/dwt/index.php/apihub"
REFERER = "https://publik.bmkg.go.id/event/dwt/"
USER_AGENT = "klimatikal-radar/0.1 (+https://klimatikal.com; low-rate polling)"
SITES = ["SMG", "YOG", "MCRC", "NGW", "IWJ", "PWK", "CGK", "JAK",
         "SBY", "PKN", "LPG", "PKP", "PLB", "PKY"]
ATTRIBUTION = "Radar: BMKG (SIDARMA nowcast, CMAX)"
CACHE_IMAGE = "public, max-age=31536000, immutable"
CACHE_MANIFEST = "public, max-age=60"
HISTORY_HOURS = 3
FILE_RE = re.compile(r"^([A-Z]+)-(\d{8})-(\d{4})\.png$")
# A frame stamped later than this past "now" is not trusted (PKP was seen
# stamped about 5 minutes ahead of the clock); it is kept but flagged.
FUTURE_SLACK = dt.timedelta(minutes=2)


def log(message: str) -> None:
    print(message, flush=True)


def http_get(url: str, accept: str) -> bytes:
    req = urllib.request.Request(
        url, headers={"Referer": REFERER, "Accept": accept, "User-Agent": USER_AGENT})
    last: Exception | None = None
    for attempt in range(3):               # a reset connection was seen once; retry
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.read()
        except Exception as err:           # noqa: BLE001 - retried, then re-raised
            last = err
            time.sleep(2 * (attempt + 1))
    raise last  # type: ignore[misc]


# --------------------------------------------------------------------------
# where the files go (a small copy of himawari.Sink: that module needs satpy)
# --------------------------------------------------------------------------

class Sink:
    def __init__(self, dest: str, dry_run: bool):
        self.dry_run, self.dest = dry_run, dest
        if not dry_run:
            import boto3
            from botocore.config import Config

            self.client = boto3.client(
                "s3", endpoint_url=f"https://{require_env('R2_ACCOUNT_ID')}.r2.cloudflarestorage.com",
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

    def exists(self, key: str) -> bool:
        if self.dry_run:
            return (Path(self.dest) / key).exists()
        from botocore.exceptions import ClientError

        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
            return True
        except ClientError as err:
            if err.response.get("Error", {}).get("Code") in ("404", "NoSuchKey", "NotFound"):
                return False
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

def iso(t: dt.datetime) -> str:
    return f"{t:%Y-%m-%dT%H:%MZ}"


def webp_bytes(png: bytes) -> bytes:
    img = Image.open(io.BytesIO(png)).convert("RGBA")
    buf = io.BytesIO()
    # Lossless: the colours ARE the dBZ scale, and lossy WebP would smear them.
    img.save(buf, format="WEBP", lossless=True, method=4)
    return buf.getvalue()


def fetch_site(site: str, sink: Sink, now: dt.datetime) -> dict | None:
    """Fetch and store the newest frame for one site; return its frame entry
    (with station fields), or None when the site has no frame right now."""
    meta = json.loads(http_get(f"{BASE}?r=radar&site={site}", "application/json"))
    layers = meta.get("layers") or []
    if not layers:
        log(f"{site}: no frame right now")
        return None
    layer = layers[-1]
    query = urllib.parse.parse_qs(urllib.parse.urlparse(layer["url"]).query)
    src = base64.b64decode(query["file"][0]).decode("utf-8")
    parts = src.rstrip("/").split("/")
    m = FILE_RE.match(parts[-1])
    if not m or "CMAX" not in parts:
        log(f"{site}: unexpected file name {parts[-1]!r}, skipped")
        return None
    t = dt.datetime.strptime(m[2] + m[3], "%Y%m%d%H%M").replace(tzinfo=dt.timezone.utc)
    (north, west), (south, east) = meta["bounds"]          # BMKG: [[N, W], [S, E]]
    frame = {
        "t": iso(t),
        "image": f"{site}/{t:%Y%m%dT%H%MZ}.webp",
        "bounds": {"south": south, "north": north, "west": west, "east": east},
    }
    if t > now + FUTURE_SLACK:
        frame["suspect_time"] = True
    # Cross-check: the WIB label must agree with the UTC filename.
    wib = layer.get("time", "")
    try:
        label = dt.datetime.strptime(wib.replace(" WIB", ""), "%Y-%m-%d %H:%M") - dt.timedelta(hours=7)
        if label.replace(tzinfo=dt.timezone.utc) != t:
            frame["suspect_time"] = True
            log(f"{site}: WIB label {wib!r} disagrees with file time {iso(t)}")
    except ValueError:
        pass
    station = {"id": site, "name": parts[parts.index("CMAX") - 1]}
    if not sink.exists(f"radar/{frame['image']}"):
        png = http_get(layer["url"], "image/png")
        if not png.startswith(b"\x89PNG"):
            log(f"{site}: not a PNG, skipped")
            return None
        body = webp_bytes(png)
        sink.put(f"radar/{frame['image']}", body, "image/webp", CACHE_IMAGE)
        log(f"{site}: {frame['image']} ({len(png) / 1024:.0f} kB png -> {len(body) / 1024:.0f} kB webp)")
    else:
        log(f"{site}: {frame['image']} already published")
    return {"station": station, "frame": frame}


def build_manifest(stations: dict[str, dict]) -> dict:
    out = []
    for sid in sorted(stations):
        s = stations[sid]
        frames = sorted(s["frames"], key=lambda f: f["t"])
        newest = frames[-1]
        out.append({"id": sid, "name": s["name"], "image": newest["image"],
                    "bounds": newest["bounds"], "t": newest["t"], "frames": frames})
    return {
        "product": "bmkg-sidarma-nowcast-cmax",
        "label": "Radar",
        "unit": "dBZ",
        "attribution": ATTRIBUTION,
        "stations": out,
        "updated": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dry-run", action="store_true", help="write under --dest instead of R2")
    ap.add_argument("--dest", default="../web/data")
    ap.add_argument("--sites", nargs="*", default=SITES)
    ap.add_argument("--hours", type=float, default=HISTORY_HOURS)
    ap.add_argument("--delay", type=float, default=1.0, help="seconds between sites")
    args = ap.parse_args()

    t0 = time.time()
    now = dt.datetime.now(dt.timezone.utc)
    sink = Sink(args.dest, args.dry_run)
    old = sink.read_json("radar/manifest.json") or {"stations": []}
    stations = {s["id"]: {"name": s["name"], "frames": list(s.get("frames", []))}
                for s in old["stations"]}

    got = 0
    for site in args.sites:
        try:
            res = fetch_site(site, sink, now)
        except Exception as err:           # noqa: BLE001 - one site must not stop the rest
            log(f"{site}: ERROR {err}")
            res = None
        if res:
            st = stations.setdefault(site, {"name": res["station"]["name"], "frames": []})
            st["name"] = res["station"]["name"]
            st["frames"] = [f for f in st["frames"] if f["t"] != res["frame"]["t"]] + [res["frame"]]
            got += 1
        time.sleep(args.delay)

    # Drop frames outside the window, and any whose image has gone.
    cutoff = iso(now - dt.timedelta(hours=args.hours))
    dropped: list[str] = []
    for sid, st in list(stations.items()):
        keep = [f for f in st["frames"] if f["t"] >= cutoff and sink.exists(f"radar/{f['image']}")]
        dropped += [f["image"] for f in st["frames"] if f not in keep]
        st["frames"] = keep
        if not keep:
            del stations[sid]

    if not stations:
        log("no radar frames available from any site; manifest left as it was")
        return 1 if got == 0 and not old["stations"] else 0
    # Manifest goes last: until this write the site keeps showing what it had.
    sink.put("radar/manifest.json", json.dumps(build_manifest(stations)).encode(),
             "application/json", CACHE_MANIFEST)
    still = {f["image"] for st in stations.values() for f in st["frames"]}
    for key in dropped:
        if key not in still:
            sink.delete(f"radar/{key}")
    log(f"done in {time.time() - t0:.0f}s: {got} new/current frames, "
        f"{len(stations)} stations, {len(dropped)} pruned")
    return 0


if __name__ == "__main__":
    sys.exit(main())
