"""Aurora probability from NOAA SWPC's OVATION model -> aurora/ovation.png + aurora/aurora.json.

OVATION Prime is NOAA's short-term aurora forecast (about 30 to 90 minutes
ahead of the solar wind measured at L1). SWPC publishes it as a 1 degree global
grid of "aurora" values, 0 to 100, which it describes as the probability of
visible aurora. US Government work, public. The browser does not call SWPC
(no promise of CORS or uptime for third parties); this job reads the feed and
publishes a small image and a small JSON next to the forecast data.

Read:
  ovation_aurora_latest.json            [[lon 0..359, lat -90..90, value], ...]
  noaa-planetary-k-index-forecast.json  observed and predicted Kp, 3-hourly

Written:
  aurora/ovation.png   360 x 181, row 0 = 90 N, column 0 = 180 W (same layout as
                       the forecast PNGs); value 0..100 in R; G, B = 0; A = 255
  aurora/aurora.json   {"updated", "observation_time", "forecast_time", "image",
                        "kp_now", "kp_max_24h", "attribution"}
The JSON is written last, so a crash leaves the previous pair in place.

    python aurora.py                          # publish to R2 (needs R2_* env vars)
    python aurora.py --dry-run --dest ./out   # write to a folder instead
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
from PIL import Image

OVATION_URL = "https://services.swpc.noaa.gov/json/ovation_aurora_latest.json"
KP_URL = "https://services.swpc.noaa.gov/products/noaa-planetary-k-index-forecast.json"
IMAGE_KEY = "aurora/ovation.png"
JSON_KEY = "aurora/aurora.json"
ATTRIBUTION = "Aurora: NOAA Space Weather Prediction Center (OVATION)"
NLAT, NLON = 181, 360


def fetch_json(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": "klimatikal-aurora/1.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def to_grid(coordinates) -> np.ndarray:
    """OVATION [[lon 0..359, lat -90..90, value]] -> uint8 (181, 360), north first, 180 W first."""
    pts = np.asarray(coordinates, dtype=np.float64)
    if pts.ndim != 2 or pts.shape[1] != 3:
        raise ValueError("unexpected OVATION layout")
    lon = pts[:, 0].astype(int)
    lat = pts[:, 1].astype(int)
    if lon.min() < 0 or lon.max() > 359 or lat.min() < -90 or lat.max() > 90:
        raise ValueError("OVATION coordinates outside the 1 degree global grid")
    wrapped = np.where(lon >= 180, lon - 360, lon)       # 180..359 -> -180..-1
    cols = wrapped + 180
    rows = 90 - lat
    grid = np.zeros((NLAT, NLON), dtype=np.uint8)
    grid[rows, cols] = np.clip(np.round(pts[:, 2]), 0, 100).astype(np.uint8)
    return grid


def to_png(grid: np.ndarray) -> bytes:
    rgba = np.zeros(grid.shape + (4,), dtype=np.uint8)
    rgba[..., 0] = grid
    rgba[..., 3] = 255            # alpha stays 255: browsers premultiply on upload
    buf = io.BytesIO()
    Image.fromarray(rgba).save(buf, "PNG", optimize=True)
    return buf.getvalue()


def kp_summary(rows, now: datetime) -> tuple[float | None, float | None]:
    """(latest observed or estimated Kp at or before now, highest Kp in the next 24 h)."""
    now_kp, peak = None, None
    for r in rows:
        try:
            t = datetime.fromisoformat(r["time_tag"]).replace(tzinfo=timezone.utc)
            kp = float(r["kp"])
        except (KeyError, ValueError, TypeError):
            continue
        if t <= now:
            now_kp = kp
        if now <= t <= now + timedelta(hours=24):
            peak = kp if peak is None else max(peak, kp)
    return now_kp, peak


def build(ovation: dict, kp_rows, now: datetime) -> tuple[bytes, dict]:
    grid = to_grid(ovation["coordinates"])
    now_kp, peak = kp_summary(kp_rows or [], now)
    doc = {
        "updated": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "observation_time": ovation.get("Observation Time"),
        "forecast_time": ovation.get("Forecast Time"),
        "image": IMAGE_KEY,
        "kp_now": now_kp,
        "kp_max_24h": peak,
        "attribution": ATTRIBUTION,
    }
    return to_png(grid), doc


class Sink:
    def __init__(self, dest: str, dry_run: bool):
        self.dry_run, self.dest = dry_run, dest
        if not dry_run:
            import boto3
            from botocore.config import Config
            self.client = boto3.client(
                "s3", endpoint_url=f"https://{os.environ['R2_ACCOUNT_ID']}.r2.cloudflarestorage.com",
                aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
                aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
                config=Config(signature_version="s3v4", region_name="auto"))
            self.bucket = os.environ["R2_BUCKET"]

    def write(self, key: str, body: bytes, content_type: str) -> None:
        if self.dry_run:
            p = Path(self.dest) / key
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(body)
            return
        self.client.put_object(Bucket=self.bucket, Key=key, Body=body, ContentType=content_type,
                               CacheControl="public, max-age=60")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--dest", default="./out")
    a = ap.parse_args()
    now = datetime.now(timezone.utc)
    try:
        ovation = fetch_json(OVATION_URL)
        try:
            kp_rows = fetch_json(KP_URL)
        except Exception as err:       # Kp is a nicety; the grid alone is still worth publishing
            print(f"Kp unavailable: {err}", file=sys.stderr)
            kp_rows = []
        png, doc = build(ovation, kp_rows, now)
    except Exception as err:
        # Keep the last good pair rather than publish nothing because SWPC blinked.
        print(f"aurora read failed, keeping the previous files: {err}", file=sys.stderr)
        return 1
    sink = Sink(a.dest, a.dry_run)
    sink.write(IMAGE_KEY, png, "image/png")
    sink.write(JSON_KEY, json.dumps(doc, separators=(",", ":")).encode(), "application/json")
    print(f"published aurora for {doc['forecast_time']} (Kp now {doc['kp_now']}, 24 h max {doc['kp_max_24h']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
