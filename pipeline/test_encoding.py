"""Round-trip test: values -> PNG on disk -> values.

Run it before trusting a single number on the map:

    python3 -m pytest test_encoding.py -q     (if you have pytest)
    python3 test_encoding.py                  (plain, prints a table)

It also prints the real PNG size per layer, which is the number every cost
estimate in the architecture doc depends on. Synthetic fields here are smooth
in the way weather is smooth, so the sizes are indicative, not final: rerun
with a real GRIB field before quoting them.
"""

from __future__ import annotations

import io
import os

import numpy as np
from PIL import Image

import encoding
from encoding import LAYERS, NLAT, NLON, decode, encode, reproject


def make_fields(spec: dict) -> list[np.ndarray]:
    """Input fields for one layer. A derived speed layer gets u and v small
    enough that the speed stays inside the layer's range."""
    lo, hi = spec["range"]
    if spec.get("derive") == "speed":
        return [synthetic(-hi * 0.7, hi * 0.7, i) for i in range(2)]
    return [synthetic(lo, hi, i) for i in range(len(spec["params"]))]


def expected(spec: dict, fields: list[np.ndarray]) -> list[np.ndarray]:
    """What decode() should give back for these input fields."""
    return [np.hypot(*fields)] if spec.get("derive") == "speed" else fields


def synthetic(lo: float, hi: float, seed: int) -> np.ndarray:
    """A smooth global field in [lo, hi], shaped a bit like a weather field."""
    rng = np.random.default_rng(seed)
    lat = np.linspace(90, -90, NLAT)[:, None]
    lon = np.linspace(0, 360, NLON, endpoint=False)[None, :]
    wave = (
        np.sin(np.deg2rad(lat) * 3.0)
        + 0.6 * np.cos(np.deg2rad(lon) * 4.0 + 0.4)
        + 0.3 * np.sin(np.deg2rad(lat) * 7.0 + np.deg2rad(lon) * 2.0)
    )
    wave += rng.normal(0.0, 0.02, size=wave.shape)
    unit = (wave - wave.min()) / (wave.max() - wave.min())
    return unit * (hi - lo) + lo


def png_bytes(rgba: np.ndarray) -> bytes:
    buf = io.BytesIO()
    Image.fromarray(rgba, mode="RGBA").save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def _lon_tagged_field(lons: np.ndarray) -> np.ndarray:
    """A field whose value is its own longitude (wrapped to -180..180)."""
    wrapped = (lons + 180.0) % 360.0 - 180.0
    return np.tile(wrapped, (NLAT, 1))


def test_reproject_handles_a_grid_that_starts_at_minus_180():
    # ECMWF open data layout. This is the case that was shifted by half the
    # world when the pipeline assumed 0..359.75.
    lons = np.arange(-180.0, 180.0, 0.25)
    out = reproject(_lon_tagged_field(lons), lons=lons)
    assert out[0, 0] == -180.0
    assert out[0, NLON // 2] == 0.0
    assert out[0, -1] == 179.75


def test_reproject_handles_a_grid_that_starts_at_0():
    lons = np.arange(0.0, 360.0, 0.25)
    out = reproject(_lon_tagged_field(lons), lons=lons)
    assert out[0, 0] == -180.0
    assert out[0, NLON // 2] == 0.0
    assert out[0, -1] == 179.75


def test_reproject_orders_latitude_north_first():
    lats = np.linspace(-90.0, 90.0, NLAT)  # south first, as some files are
    field = np.tile(lats[:, None], (1, NLON))
    out = reproject(field, lats=lats)
    assert out[0, 0] == 90.0 and out[-1, 0] == -90.0


def test_reproject_rejects_a_grid_that_is_not_global():
    lons = np.arange(0.0, 360.0, 0.25)
    lons[10] += 0.1  # a grid with a wrong coordinate must fail loudly
    try:
        reproject(_lon_tagged_field(lons), lons=lons)
    except ValueError:
        return
    raise AssertionError("expected ValueError")


def test_guard_skips_a_run_that_is_already_published():
    import argparse
    import contextlib
    import tempfile
    from pathlib import Path

    import build_run

    def go(dest, **over):
        args = argparse.Namespace(dest=dest, dry_run=True, offline=True, run=None,
                                  steps=[0], keep=2, force=False)
        for k, v in over.items():
            setattr(args, k, v)
        with contextlib.redirect_stdout(io.StringIO()) as out:
            build_run.build(args)
        return out.getvalue()

    with tempfile.TemporaryDirectory() as dest:
        first = go(dest)
        assert "building run" in first
        marker = next(Path(dest).glob("runs/*/manifest.json"))
        before = marker.stat().st_mtime_ns

        second = go(dest)
        assert "already published" in second, second
        assert marker.stat().st_mtime_ns == before, "a skipped run must not write anything"

        forced = go(dest, force=True)
        assert "building run" in forced and marker.stat().st_mtime_ns != before

        # A different step list is a different build, not a duplicate.
        assert "building run" in go(dest, steps=[0, 3])

        # A pipeline fix bumps REVISION; the same run must then be rebuilt.
        old = encoding.REVISION
        try:
            build_run.REVISION = old + 1
            assert "building run" in go(dest, steps=[0, 3])
        finally:
            build_run.REVISION = old


def test_alpha_is_always_opaque():
    for layer, spec in LAYERS.items():
        fields = make_fields(spec)
        rgba = encode(layer, fields)
        assert (rgba[..., 3] == 255).all(), f"{layer} has non-opaque pixels"


def test_round_trip_through_a_real_png():
    for layer, spec in LAYERS.items():
        fields = make_fields(spec)
        raw = png_bytes(encode(layer, fields))
        back = np.array(Image.open(io.BytesIO(raw)).convert("RGBA"))
        got = decode(layer, back)
        for original, recovered in zip(expected(spec, fields), got):
            err = np.abs(original - recovered).max()
            tolerance = worst_case_step(spec)
            assert err <= tolerance, f"{layer}: {err:.4g} > {tolerance:.4g}"


def worst_case_step(spec: dict) -> float:
    """Largest quantisation step the encoding can produce across its range."""
    lo, hi = spec["range"]
    levels = 65535.0 if spec["encoding"] == "scalar16" else 255.0
    gamma = spec.get("gamma")
    if gamma is None:
        return (hi - lo) / levels * 1.000001
    # With a gamma curve the step is widest at the top of the range.
    top = 1.0
    below = (levels - 1.0) / levels
    return (top**gamma - below**gamma) * (hi - lo) * 1.000001


def report() -> None:
    print(f"format version {encoding.FORMAT_VERSION}   grid {NLAT} x {NLON}\n")
    print(f"{'layer':8} {'encoding':10} {'unit':8} {'max error':>12}  {'PNG':>9}")
    print("-" * 54)
    total = 0
    for layer, spec in LAYERS.items():
        fields = make_fields(spec)
        raw = png_bytes(encode(layer, fields))
        total += len(raw)
        back = np.array(Image.open(io.BytesIO(raw)).convert("RGBA"))
        got = decode(layer, back)
        err = max(np.abs(o - r).max() for o, r in zip(expected(spec, fields), got))
        kb = len(raw) / 1024
        print(
            f"{layer:8} {spec['encoding']:10} {spec['unit']:8} "
            f"{err:12.5f}  {kb:7.0f}KB"
        )
    per_run = total * 49 / 1024 / 1024
    print("-" * 54)
    print(f"one step, all layers: {total/1024:.0f} KB")
    print(f"one run (49 steps):   {per_run:.0f} MB")
    print(f"two runs retained:    {per_run*2:.0f} MB  (free R2 tier is 10 GB)")

    # Precipitation is the one with a curve: show what it buys at the low end.
    spec = LAYERS["precip"]
    light = np.full((NLAT, NLON), 0.3)
    rgba = encode("precip", [light])
    back = decode("precip", rgba)[0]
    print(f"\nlight rain check: 0.300 mm/3h encodes and returns as {back[0,0]:.3f}")


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except AssertionError as exc:
                failures += 1
                print(f"FAIL {name}: {exc}")
    print()
    report()
    raise SystemExit(1 if failures else 0)
