#!/usr/bin/env python3
"""
Build one forecast run: ECMWF open data -> PNG layers + manifest -> R2.

    python3 build_run.py --dry-run --steps 0,3,6      # local, no R2, 3 steps
    python3 build_run.py                              # newest run, all steps
    python3 build_run.py --run 2026-11-11T00Z         # a named run

The order at the end is the whole safety design: every file of the run is
uploaded first, and latest.json is written last. Until that final write the
site keeps serving the previous run, so a crash at any earlier point costs
nothing but disk.

ECMWF open data is CC BY 4.0 and the attribution travels in the manifest, so
the site can render it from the data rather than hard-coding a string that
drifts out of date.
"""

from __future__ import annotations

import argparse
import datetime as dt
import io
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

import numpy as np
from PIL import Image

from encoding import FORMAT_VERSION, LAYERS, NLAT, NLON, encode, layer_manifest, reproject

# 0 to 144 by 3 is published by all four daily cycles. 00z and 12z go on to
# 360 by 6; ignoring that keeps every cycle identical, which keeps the client
# simple and the time slider the same length all day.
STEPS = list(range(0, 145, 3))

ATTRIBUTION = (
    'Adapted from "ECMWF IFS 15-day Forecast Data" by ECMWF, '
    "licensed under CC BY 4.0, available at https://data.ecmwf.int/forecasts/"
)

# GRIB short name -> (our unit, conversion from the GRIB unit)
CONVERSIONS = {
    "10u": ("m s-1", lambda a: a),
    "10v": ("m s-1", lambda a: a),
    "2t": ("degC", lambda a: a - 273.15),      # Kelvin
    "tp": ("mm", lambda a: a * 1000.0),        # metres of water equivalent
    "tcc": ("%", lambda a: a * 100.0),         # 0..1 fraction
    "msl": ("hPa", lambda a: a / 100.0),       # Pascals
}

ALL_PARAMS = sorted({p for spec in LAYERS.values() for p in spec["params"]})

CACHE_RUN_FILES = "public, max-age=31536000, immutable"
CACHE_LATEST = "public, max-age=60"


# --------------------------------------------------------------------------
# download and decode
# --------------------------------------------------------------------------

def open_client():
    from ecmwf.opendata import Client

    return Client(source="ecmwf", model="ifs", resol="0p25")


def resolve_run(client, requested: str | None) -> dt.datetime:
    """Pick the run to build, and wait for it if it is not out yet.

    client.latest() asks ECMWF which run is actually complete, which is the
    only honest answer: open data appears one to two hours after the nominal
    run time and the exact delay moves.
    """
    if requested:
        return dt.datetime.strptime(requested, "%Y-%m-%dT%HZ").replace(tzinfo=dt.timezone.utc)

    deadline = time.time() + 3 * 3600
    while True:
        latest = client.latest(stream="oper", type="fc", param="10u")
        if latest is not None:
            return latest.replace(tzinfo=dt.timezone.utc)
        if time.time() > deadline:
            raise SystemExit("no complete run after 3 hours of polling")
        log("no complete run yet, sleeping 10 minutes")
        time.sleep(600)


def fetch_step(client, run: dt.datetime, step: int, workdir: Path) -> Path:
    target = workdir / f"step{step:03d}.grib2"
    if target.exists():
        return target
    client.retrieve(
        date=run.strftime("%Y%m%d"),
        time=run.hour,
        stream="oper",
        type="fc",
        param=ALL_PARAMS,
        step=step,
        target=str(target),
    )
    return target


def read_fields(path: Path) -> dict[str, np.ndarray]:
    """Read every parameter in a GRIB file into image-oriented arrays.

    cfgrib.open_datasets, not xarray.open_dataset: one GRIB file holds several
    incompatible hypercubes (different levels and step types) and the single
    open_dataset call silently drops all but one of them.
    """
    import cfgrib

    fields: dict[str, np.ndarray] = {}
    datasets = cfgrib.open_datasets(str(path))
    for ds in datasets:
        for name in ds.data_vars:
            short = ds[name].attrs.get("GRIB_shortName", str(name))
            if short not in ALL_PARAMS:
                continue
            values = np.asarray(ds[name].values, dtype=np.float64)
            if values.shape != (NLAT, NLON):
                raise SystemExit(f"{short}: unexpected grid {values.shape}")
            _, convert = CONVERSIONS[short]
            # Reorder with the file's own coordinates, never an assumption
            # about which way the grid runs.
            fields[short] = reproject(
                convert(values),
                lats=ds[name].coords["latitude"].values,
                lons=ds[name].coords["longitude"].values,
            )
    missing = set(ALL_PARAMS) - set(fields)
    if missing:
        raise SystemExit(f"missing parameters in {path.name}: {sorted(missing)}")
    return fields


# --------------------------------------------------------------------------
# encode and upload
# --------------------------------------------------------------------------

def png_bytes(rgba: np.ndarray) -> bytes:
    buf = io.BytesIO()
    Image.fromarray(rgba, mode="RGBA").save(buf, format="PNG", optimize=True)
    return buf.getvalue()


class Sink:
    """Where the files go. Local directory, or R2."""

    def __init__(self, dest: str, dry_run: bool):
        self.dry_run = dry_run
        self.dest = dest
        self.client = None
        if not dry_run:
            import boto3
            from botocore.config import Config

            account = require_env("R2_ACCOUNT_ID")
            self.client = boto3.client(
                "s3",
                endpoint_url=f"https://{account}.r2.cloudflarestorage.com",
                aws_access_key_id=require_env("R2_ACCESS_KEY_ID"),
                aws_secret_access_key=require_env("R2_SECRET_ACCESS_KEY"),
                config=Config(signature_version="s3v4", region_name="auto"),
            )
            self.bucket = require_env("R2_BUCKET")

    def put(self, key: str, body: bytes, content_type: str, cache_control: str) -> None:
        if self.dry_run:
            path = Path(self.dest) / key
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(body)
            return
        self.client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=body,
            ContentType=content_type,
            CacheControl=cache_control,
        )

    def list_run_prefixes(self) -> list[str]:
        if self.dry_run:
            root = Path(self.dest) / "runs"
            return sorted(p.name for p in root.iterdir()) if root.exists() else []
        paginator = self.client.get_paginator("list_objects_v2")
        names = set()
        for page in paginator.paginate(Bucket=self.bucket, Prefix="runs/", Delimiter="/"):
            for entry in page.get("CommonPrefixes", []):
                names.add(entry["Prefix"].split("/")[1])
        return sorted(names)

    def delete_run(self, name: str) -> None:
        if self.dry_run:
            shutil.rmtree(Path(self.dest) / "runs" / name, ignore_errors=True)
            return
        paginator = self.client.get_paginator("list_objects_v2")
        batch = []
        for page in paginator.paginate(Bucket=self.bucket, Prefix=f"runs/{name}/"):
            for obj in page.get("Contents", []):
                batch.append({"Key": obj["Key"]})
                if len(batch) == 1000:
                    self.client.delete_objects(Bucket=self.bucket, Delete={"Objects": batch})
                    batch = []
        if batch:
            self.client.delete_objects(Bucket=self.bucket, Delete={"Objects": batch})


def require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise SystemExit(f"environment variable {name} is not set")
    return value


# --------------------------------------------------------------------------
# the run
# --------------------------------------------------------------------------

def log(message: str) -> None:
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%H:%M:%S")
    print(f"[{stamp}] {message}", flush=True)


def synthetic_fields(step: int) -> dict[str, np.ndarray]:
    """Plausible-looking fields for --offline, so the plumbing either side of
    the download can be exercised without ECMWF or eccodes installed."""
    lat = np.linspace(90, -90, NLAT)[:, None]
    lon = np.linspace(-180, 180, NLON, endpoint=False)[None, :]
    phase = np.deg2rad(step * 2.0)
    swirl = np.sin(np.deg2rad(lon) * 3 + phase) * np.cos(np.deg2rad(lat) * 2)
    warm = 30.0 - 60.0 * (np.abs(lat) / 90.0) ** 1.5 + 4.0 * swirl
    return {
        "10u": 12.0 * swirl + 6.0 * np.sin(np.deg2rad(lat) * 4),
        "10v": 9.0 * np.cos(np.deg2rad(lon) * 2 + phase) * np.cos(np.deg2rad(lat)),
        "2t": np.broadcast_to(warm, (NLAT, NLON)).copy(),
        # tp is accumulated in the real data, so the fake must be too.
        "tp": np.clip(swirl, 0, None) * 0.4 * (step / 3.0 + 1),
        "tcc": np.clip(50 + 50 * swirl, 0, 100),
        "msl": 1013.0 + 25.0 * swirl,
    }


def build(args) -> None:
    sink = Sink(args.dest, args.dry_run)
    client = None if args.offline else open_client()

    run = resolve_run(client, args.run) if client else dt.datetime.now(dt.timezone.utc)
    run_id = run.strftime("%Y-%m-%dT%HZ")
    steps = args.steps or STEPS
    log(f"building run {run_id}, {len(steps)} steps, {len(LAYERS)} layers")

    workdir = Path(tempfile.mkdtemp(prefix="klimatikal-"))
    previous_tp: np.ndarray | None = None
    written = 0
    total_bytes = 0

    try:
        for step in steps:
            if args.offline:
                grib = None
                fields = synthetic_fields(step)
            else:
                grib = fetch_step(client, run, step, workdir)
                fields = read_fields(grib)

            # tp is accumulated from the start of the forecast, so the rate
            # over this step is the difference from the step before. Step 0 is
            # all zeros by definition.
            accumulated = fields["tp"]
            if step == 0:
                fields["tp"] = np.zeros_like(accumulated)
            elif previous_tp is None:
                raise SystemExit(
                    f"step {step} needs step {step-3} for precipitation; "
                    "run consecutive steps or start at 0"
                )
            else:
                fields["tp"] = np.maximum(accumulated - previous_tp, 0.0)
            previous_tp = accumulated

            for layer, spec in LAYERS.items():
                rgba = encode(layer, [fields[p] for p in spec["params"]])
                body = png_bytes(rgba)
                sink.put(
                    f"runs/{run_id}/{layer}/f{step:03d}.png",
                    body,
                    "image/png",
                    CACHE_RUN_FILES,
                )
                written += 1
                total_bytes += len(body)

            if grib is not None:
                grib.unlink(missing_ok=True)
            log(f"step {step:3d} done  ({total_bytes/1024/1024:.0f} MB so far)")

        manifest = {
            "format_version": FORMAT_VERSION,
            "run": run_id,
            "model": "ECMWF IFS open data 0.25 degree",
            "generated": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "grid": {
                "width": NLON,
                "height": NLAT,
                "lon_min": -180.0,
                "lon_max": 180.0,
                "lat_min": -90.0,
                "lat_max": 90.0,
            },
            "steps": steps,
            "layers": {name: layer_manifest(name) for name in LAYERS},
            "attribution": ATTRIBUTION,
            "licence": "CC BY 4.0",
        }
        sink.put(
            f"runs/{run_id}/manifest.json",
            json.dumps(manifest, indent=2).encode(),
            "application/json",
            CACHE_RUN_FILES,
        )

        # Everything is up. Only now does the run become visible.
        sink.put(
            "latest.json",
            json.dumps({"run": run_id, "manifest": f"runs/{run_id}/manifest.json"}).encode(),
            "application/json",
            CACHE_LATEST,
        )
        log(f"published {run_id}: {written} files, {total_bytes/1024/1024:.0f} MB")

        prune(sink, keep=args.keep, current=run_id)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def prune(sink: Sink, keep: int, current: str) -> None:
    runs = sink.list_run_prefixes()
    stale = [r for r in runs if r != current][: max(0, len(runs) - keep)]
    for name in stale:
        log(f"deleting old run {name}")
        sink.delete_run(name)


def parse_steps(value: str) -> list[int]:
    return [int(piece) for piece in value.split(",") if piece.strip()]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", help="run to build, e.g. 2026-11-11T00Z; default newest")
    parser.add_argument("--steps", type=parse_steps, help="comma-separated, default 0..144 by 3")
    parser.add_argument("--dry-run", action="store_true", help="write to --dest instead of R2")
    parser.add_argument("--offline", action="store_true", help="skip ECMWF; for wiring tests only")
    parser.add_argument("--dest", default="./out", help="output directory for --dry-run")
    parser.add_argument("--keep", type=int, default=2, help="how many runs to retain")
    args = parser.parse_args()

    if args.offline and not args.dry_run:
        parser.error("--offline only makes sense with --dry-run")
    build(args)


if __name__ == "__main__":
    main()
