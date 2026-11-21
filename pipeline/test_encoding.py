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
    if spec.get("derive") == "heatindex":
        t = synthetic(15.0, 40.0, 0)
        return [t, t - synthetic(2.0, 15.0, 1)]  # dewpoint below temperature
    return [synthetic(lo, hi, i) for i in range(len(spec["params"]))]


def expected(spec: dict, fields: list[np.ndarray]) -> list[np.ndarray]:
    """What decode() should give back for these input fields."""
    if spec.get("derive") == "heatindex":
        return [encoding.heat_index(*fields)]
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


def test_heat_index_matches_nws_reference_points():
    # NWS heat index chart: 90 F / 70% RH -> 106 F; 96 F / 65% -> ~121 F.
    def hi_f(t_f, rh):
        t_c = (t_f - 32) * 5 / 9
        a, b = 17.625, 243.04
        # dewpoint that gives this RH at this temperature (inverse Magnus)
        g = np.log(rh / 100.0) + a * t_c / (b + t_c)
        td = b * g / (a - g)
        return encoding.heat_index(np.array([t_c]), np.array([td]))[0] * 9 / 5 + 32
    assert abs(hi_f(90, 70) - 106) <= 2, hi_f(90, 70)
    assert abs(hi_f(96, 65) - 121) <= 3, hi_f(96, 65)
    assert abs(hi_f(75, 50) - 75) <= 3     # mild air: close to the air temperature


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


def test_msl_is_smoothed_over_high_ground_only():
    rng = np.random.default_rng(1)
    sp = np.full((NLAT, NLON), 1000.0)
    sp[200:300, 600:700] = 600.0                       # a plateau
    msl = 1013.0 + rng.normal(0.0, 4.0, size=(NLAT, NLON))   # noisy everywhere
    weight = encoding.terrain_weight(sp)
    out = encoding.smooth_over_terrain(msl, weight)
    assert np.array_equal(out[400:500, 100:200], msl[400:500, 100:200])   # lowland untouched
    assert out[230:270, 630:670].std() < 0.1 * msl[230:270, 630:670].std()  # plateau smoothed
    assert abs(out[230:270, 630:670].mean() - 1013.0) < 1.0                 # same level, no bias
    assert np.array_equal(encoding.smooth_over_terrain(msl, np.zeros_like(weight)), msl)


# ---- thermal comfort (thermal.py) -------------------------------------------

def test_utci_matches_reference_values():
    """Reference points from the UTCI operational procedure (Broede et al. 2012)."""
    import thermal
    f = lambda *a: float(thermal.utci(*[np.array([x]) for x in a])[0])
    assert abs(f(25.0, 50.0, 1.0, 25.0) - 24.6) < 0.3           # comfortable
    assert abs(f(35.0, 60.0, 1.0, 35.0) - 38.5) < 1.5           # hot, humid: strong-very strong
    assert f(30.0, 60.0, 1.0, 55.0) > f(30.0, 60.0, 1.0, 30.0) + 5.0   # radiant load raises it
    assert f(30.0, 60.0, 8.0, 30.0) < f(30.0, 60.0, 1.0, 30.0)         # wind cools


def test_sun_is_hotter_than_shade_and_night_is_equal():
    import datetime as dt
    import thermal
    lat = np.array([[-6.2]]); lon = np.array([[106.8]])        # Jakarta
    noon = dt.datetime(2026, 11, 18, 5, 0, tzinfo=dt.timezone.utc)   # 12:00 local
    night = dt.datetime(2026, 11, 18, 17, 0, tzinfo=dt.timezone.utc)
    for when, sunny in ((noon, True), (night, False)):
        start, end = when - dt.timedelta(hours=1.5), when + dt.timedelta(hours=1.5)
        mu0 = thermal.window_mean_mu0(lat, lon, start, end)
        i0 = thermal.SOLAR_CONSTANT * thermal.earth_sun_factor(when)
        ssrd = np.array([[700.0 if sunny else 0.0]])
        args = (ssrd, 0.85 * ssrd, np.array([[420.0]]), np.array([[-60.0]]), mu0, i0)
        sun = thermal.mean_radiant_temperature(*args, sun=True)[0, 0]
        shade = thermal.mean_radiant_temperature(*args, sun=False)[0, 0]
        if sunny:
            assert sun > shade + 3.0 and 45 < sun < 75, (sun, shade)
        else:
            assert abs(sun - shade) < 1e-9


def test_solar_noon_zenith_at_the_equator_in_equinox():
    import datetime as dt
    import thermal
    mu0 = thermal.cos_zenith(np.array(0.0), np.array(0.0), dt.datetime(2026, 3, 20, 12, 0, tzinfo=dt.timezone.utc))
    assert mu0 > 0.99


def test_utci_layers_encode_and_stay_inside_the_range():
    import datetime as dt
    import thermal
    lat, lon = thermal.grid_latlon(NLAT, NLON)
    t = np.broadcast_to(32.0 + 0 * lat, (NLAT, NLON)).copy()
    fields = {"2t": t, "2d": t - 6.0, "10u": 0 * t + 2.0, "10v": 0 * t}
    ssrd = 600.0 * np.maximum(np.cos(np.deg2rad(lat)), 0) + 0 * lon
    flux = {"ssrd": ssrd, "ssr": 0.85 * ssrd, "strd": 0 * ssrd + 420.0, "str": 0 * ssrd - 60.0}
    when = dt.datetime(2026, 11, 18, 3, 0, tzinfo=dt.timezone.utc)
    sun, shade = thermal.utci_sun_shade(fields, flux, when, when + dt.timedelta(hours=3))
    assert np.isfinite(sun).all() and np.isfinite(shade).all()
    assert (sun >= shade - 1e-6).all() and (sun - shade).max() > 3.0
    assert -20.0 < sun.min() and sun.max() < 60.0


def test_wet_bulb_matches_a_psychrometric_solution():
    """Independent check: solve the psychrometer equation at 1013 hPa for the wet-bulb temperature."""
    import thermal

    def es(t):  # hPa, Magnus
        return 6.1094 * np.exp(17.625 * t / (t + 243.04))

    def psychrometric(t, rh, p=1013.25):
        e = rh / 100.0 * es(t)
        lo, hi = -20.0, t
        for _ in range(60):
            mid = (lo + hi) / 2
            if es(mid) - 0.00066 * (1 + 0.00115 * mid) * p * (t - mid) > e:
                hi = mid
            else:
                lo = mid
        return (lo + hi) / 2

    for t, rh in ((20, 50), (26, 85), (30, 70), (32, 60), (35, 50), (38, 40), (28, 95)):
        got = float(thermal.wet_bulb(np.array(t, float), np.array(rh, float)))
        assert abs(got - psychrometric(t, rh)) < 0.6, (t, rh, got, psychrometric(t, rh))
    assert abs(float(thermal.wet_bulb(np.array(20.0), np.array(50.0))) - 13.7) < 0.2   # Stull's own check value


def test_uv_index_clear_sky_jakarta_noon_cloud_and_night():
    import datetime as dt
    import thermal
    lat = np.array([[-6.2]]); lon = np.array([[106.8]])
    noon = dt.datetime(2026, 11, 18, 5, 0, tzinfo=dt.timezone.utc)      # 12:00 WIB
    start = noon - dt.timedelta(hours=3)
    ghi_clear = thermal.window_mean_haurwitz(lat, lon, start, noon)
    tcc = np.array([[0.0]])
    clear = thermal.uv_index({"tcc": tcc}, {"ssrd": 0.9 * ghi_clear}, start, noon, lat, lon)[0, 0]
    assert 12.0 < clear < 15.5, clear                                   # the plan's sanity check: about 14 for Jakarta
    overcast = thermal.uv_index({"tcc": tcc}, {"ssrd": 0.3 * ghi_clear}, start, noon, lat, lon)[0, 0]
    assert 0.25 * clear < overcast < 0.4 * clear
    night = dt.datetime(2026, 11, 18, 17, 0, tzinfo=dt.timezone.utc)
    assert thermal.uv_index({"tcc": tcc}, None, night - dt.timedelta(hours=3), night, lat, lon)[0, 0] == 0.0
    # no radiation window (step 0): cloud cover stands in
    assert thermal.uv_index({"tcc": np.array([[100.0]])}, None, noon, noon, lat, lon)[0, 0] < 0.3 * clear
