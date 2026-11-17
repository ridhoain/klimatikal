"""
Value <-> PNG encoding for Klimatikal.

One PNG per layer per forecast step. The PNG carries real meteorological
values, not colours: the browser decodes them in a shader and colours them
client-side. That is what lets one file serve the map, a point lookup and a
data download.

Two rules that are easy to get wrong and expensive to debug:

1. Alpha is always 255. Browsers premultiply alpha on texture upload, which
   would silently corrupt any value stored in a partly transparent pixel.
2. Ranges are FIXED per layer, not per run. Per-run min/max would squeeze out
   slightly more precision but the colour scale would shift between runs, so
   the same colour would mean different things six hours apart.

Row 0 of every PNG is 90 degrees north. Column 0 is 180 degrees west. The
source GRIB is reordered to that using its own coordinates; see reproject().
"""

from __future__ import annotations

import numpy as np

FORMAT_VERSION = 1

# FORMAT_VERSION says how a browser must decode the files; change it only when
# the decode changes. REVISION says the pipeline's output changed for the same
# input (a bug fix to the data, not to the format). Bump it so a run that is
# already published gets rebuilt once instead of being skipped by the
# "already published" guard in build_run.py.
#   1  initial
#   2  longitudes taken from the GRIB's own coordinates (half-world shift fix)
#   3  added the 16-bit "windspeed" layer (colour field and readout for wind)
#   4  added the derived "heatindex" layer (needs the 2 m dewpoint, "2d")
#   5  msl is 16-bit: the synoptic preset draws isobars, and at 8 bits the
#      tropics have only a dozen distinct pressure levels over 20 x 30 degrees,
#      so a 2 hPa isobar comes out as thick wandering bands, not a line
#   6  added 850 hPa wind and low/mid/high cloud cover for the synoptic preset
#   7  msl is smoothed over high ground (see smooth_over_terrain)
#   8  fronts/fNNN.json per step (see fronts.py)
REVISION = 8

# Grid of the ECMWF open data 0.25 degree product.
NLAT, NLON = 721, 1440

# encoding:
#   "scalar8"   value in R,              1 byte,  optional gamma curve
#   "scalar16"  value in R (high), G (low), 2 bytes
#   "vector8"   u in R, v in G,          1 byte each
#
# A layer with "derive": "speed" is computed from its two params (u, v) as
# sqrt(u^2 + v^2) before encoding, and "hidden": True keeps it out of the
# browser's layer buttons.
#
# gamma: stored = (normalised ** (1/gamma)), decoded = stored ** gamma.
# gamma > 1 spends more of the byte budget near the low end, which is what
# precipitation needs: 0.2 mm and 0.4 mm must stay distinguishable while the
# scale still reaches 100 mm.
LAYERS: dict[str, dict] = {
    "wind": {
        "params": ["10u", "10v"],
        "encoding": "vector8",
        "unit": "m s-1",
        "range": [-50.0, 50.0],
        "label": "10 m wind",
    },
    # Wind speed on its own, at 16 bits. The colour map and the hover value read
    # this one; the particles still read the 8-bit u/v pair above, where
    # direction needs no more precision. At 8 bits the colour field showed
    # diagonal bands in light wind, where speed moves in steps of ~0.4 m/s.
    "windspeed": {
        "params": ["10u", "10v"],
        "derive": "speed",
        "hidden": True,
        "encoding": "scalar16",
        "unit": "m s-1",
        "range": [0.0, 70.0],
        "label": "10 m wind speed",
    },
    "temp": {
        "params": ["2t"],
        "encoding": "scalar8",
        "unit": "degC",
        "range": [-80.0, 60.0],
        "label": "2 m temperature",
    },
    # NWS heat index (shade, light wind) from 2 m temperature and dewpoint. It is
    # derived here, not in the browser, so the map and the hover value read the
    # same bytes like every other layer. Range is wide so nothing clips; the
    # useful part of the scale (27 to 54 degC) is what the page colours.
    "heatindex": {
        "params": ["2t", "2d"],
        "derive": "heatindex",
        "hidden": True,    # reached through the "Heat stress" preset, not a layer button of its own
        "encoding": "scalar8",
        "unit": "degC",
        "range": [-10.0, 70.0],
        "label": "heat index",
    },
    "precip": {
        "params": ["tp"],
        "encoding": "scalar8",
        "unit": "mm/3h",
        "range": [0.0, 100.0],
        "gamma": 3.0,
        "label": "precipitation",
    },
    "cloud": {
        "params": ["tcc"],
        "encoding": "scalar8",
        "unit": "%",
        "range": [0.0, 100.0],
        "label": "total cloud cover",
    },
    # Cloud by level, for the synoptic preset's cloud colouring. Data-only.
    "lcc": {"params": ["lcc"], "hidden": True, "encoding": "scalar8", "unit": "%",
            "range": [0.0, 100.0], "label": "low cloud cover"},
    "mcc": {"params": ["mcc"], "hidden": True, "encoding": "scalar8", "unit": "%",
            "range": [0.0, 100.0], "label": "medium cloud cover"},
    "hcc": {"params": ["hcc"], "hidden": True, "encoding": "scalar8", "unit": "%",
            "range": [0.0, 100.0], "label": "high cloud cover"},
    # 850 hPa wind, for the synoptic preset's streaks. Data-only.
    "wind850": {"params": ["u850", "v850"], "hidden": True, "encoding": "vector8",
                "unit": "m s-1", "range": [-60.0, 60.0], "label": "850 hPa wind"},
    "msl": {
        "params": ["msl"],
        "encoding": "scalar16",
        "unit": "hPa",
        "range": [870.0, 1085.0],
        "label": "mean sea level pressure",
    },
}

# Why almost everything is scalar8 even though scalar16 is implemented and tested
# (msl and windspeed are the exceptions, for the reasons given at each):
# a 16-bit field is 4 to 8 times the bytes of an 8-bit one, because the low
# byte is close to random and PNG cannot compress it. At 8 bits, temperature
# resolves to 0.55 degC and pressure to 0.84 hPa, which no one can see on a
# colour map. Pressure is the one field where it shows, and it is now 16-bit for
# that reason: isobars are drawn from it (roughly 1.4 MB more per forecast step).
#
# The consequence for the product: these PNGs are display-grade, not
# archive-grade. A data customer who needs full precision should be served the
# original GRIB, which the pipeline downloads anyway, not these files.


def reproject(
    field: np.ndarray,
    lats: np.ndarray | None = None,
    lons: np.ndarray | None = None,
) -> np.ndarray:
    """Put a raw 0.25 degree GRIB field into image orientation.

    The image wants latitude 90 -> -90 (row 0 is north) and longitude
    -180 -> 179.75 (column 0 is the antimeridian).

    Do not assume which way the source file is laid out: take its own
    latitude and longitude coordinates and sort to the target. A hard-coded
    "GRIB runs 0..359.75, so roll half a turn" was wrong for the ECMWF open
    data files, which already start at -180, and the map came out shifted by
    exactly half the world. That error looks plausible enough at a glance to
    waste an afternoon, so the coordinates are also checked.

    With no coordinates given the layout is assumed to be the target layout.
    """
    if field.shape != (NLAT, NLON):
        raise ValueError(f"expected {(NLAT, NLON)}, got {field.shape}")

    out = field
    if lats is not None:
        lats = np.asarray(lats, dtype=np.float64)
        order = np.argsort(-lats, kind="stable")  # north first
        out = out[order, :]
        if not np.allclose(lats[order], np.linspace(90.0, -90.0, NLAT), atol=1e-3):
            raise ValueError("latitudes are not a 90..-90 grid at 0.25 degree")
    if lons is not None:
        lons = np.asarray(lons, dtype=np.float64)
        wrapped = (lons + 180.0) % 360.0 - 180.0  # 180 -> -180, 359.75 -> -0.25
        order = np.argsort(wrapped, kind="stable")
        out = out[:, order]
        if not np.allclose(wrapped[order], np.arange(-180.0, 180.0, 0.25), atol=1e-3):
            raise ValueError("longitudes are not a full 0.25 degree global ring")
    return out


def heat_index(t_c: np.ndarray, td_c: np.ndarray) -> np.ndarray:
    """NWS heat index in degC from 2 m temperature and dewpoint (both degC).

    Steadman's simple formula first; where its mean with the air temperature
    reaches 80 F the Rothfusz regression takes over, with the NWS low- and
    high-humidity adjustments. Defined for shade and light wind: full sun can
    add several degrees, which this does not know about. Below ~27 degC it is
    roughly the air temperature, so only the warm end is meaningful.
    """
    t_c = np.asarray(t_c, dtype=np.float64)
    td_c = np.minimum(np.asarray(td_c, dtype=np.float64), t_c)  # dewpoint cannot exceed T
    # Relative humidity from the Magnus formula.
    a, b = 17.625, 243.04
    rh = 100.0 * np.exp(a * td_c / (b + td_c) - a * t_c / (b + t_c))
    rh = np.clip(rh, 0.0, 100.0)
    t = t_c * 9.0 / 5.0 + 32.0  # degF
    simple = 0.5 * (t + 61.0 + (t - 68.0) * 1.2 + rh * 0.094)
    hi = (-42.379 + 2.04901523 * t + 10.14333127 * rh - 0.22475541 * t * rh
          - 0.00683783 * t * t - 0.05481717 * rh * rh + 0.00122874 * t * t * rh
          + 0.00085282 * t * rh * rh - 0.00000199 * t * t * rh * rh)
    dry = (rh < 13.0) & (t >= 80.0) & (t <= 112.0)
    hi = np.where(dry, hi - ((13.0 - rh) / 4.0) * np.sqrt(np.abs(17.0 - np.abs(t - 95.0)) / 17.0), hi)
    humid = (rh > 85.0) & (t >= 80.0) & (t <= 87.0)
    hi = np.where(humid, hi + ((rh - 85.0) / 10.0) * ((87.0 - t) / 5.0), hi)
    out_f = np.where((simple + t) / 2.0 >= 80.0, hi, simple)
    return (out_f - 32.0) * 5.0 / 9.0


def _normalise(values: np.ndarray, lo: float, hi: float, gamma: float | None) -> np.ndarray:
    """Map values onto 0..1, clipped, with an optional gamma curve."""
    out = (values.astype(np.float64) - lo) / (hi - lo)
    # A missing value (NaN) encodes as the bottom of the range, on purpose: the
    # cast to uint8 of a NaN is otherwise undefined. For precipitation that is
    # 0 mm, which the map draws white.
    out = np.nan_to_num(out, nan=0.0)
    out = np.clip(out, 0.0, 1.0)
    if gamma is not None:
        out = out ** (1.0 / gamma)
    return out


def _denormalise(unit: np.ndarray, lo: float, hi: float, gamma: float | None) -> np.ndarray:
    if gamma is not None:
        unit = unit**gamma
    return unit * (hi - lo) + lo


# Mean sea level pressure is the surface pressure reduced to sea level. Over
# high ground (Tibet, the Andes, Greenland, Antarctica) that reduction runs
# through kilometres of rock, so every bump of the terrain and every small error
# in the surface temperature is multiplied into pressure differences of many
# hPa, and the isobars come out as noise that follows the mountains. Where the
# ground is high, msl is replaced by a heavily smoothed copy: fully from
# TERRAIN_SP_FULL hPa of surface pressure (about 1700 m) and not at all from
# TERRAIN_SP_NONE (about 700 m), with a smooth blend between, so there is no
# seam. Lowlands are untouched.
TERRAIN_SP_NONE = 930.0
TERRAIN_SP_FULL = 830.0
TERRAIN_SIGMA_CELLS = 10.0      # 2.5 degrees at 0.25 degree resolution


def _gaussian_blur(a: np.ndarray, sigma: float) -> np.ndarray:
    """Gaussian blur of an (NLAT, NLON) global grid: periodic in longitude,
    mirrored at the poles. FFT-based, no SciPy needed."""
    pad = int(4 * sigma)
    tall = np.concatenate([a[pad:0:-1], a, a[-2:-pad - 2:-1]], axis=0)
    for axis in (0, 1):
        n = tall.shape[axis]
        response = np.exp(-2.0 * (np.pi * sigma * np.fft.rfftfreq(n)) ** 2)
        shape = [1, 1]
        shape[axis] = -1
        tall = np.fft.irfft(np.fft.rfft(tall, axis=axis) * response.reshape(shape), n=n, axis=axis)
    return tall[pad:-pad]


def terrain_weight(sp_hpa: np.ndarray) -> np.ndarray:
    """0 on low ground, 1 on high ground, smoothly in between."""
    t = np.clip((TERRAIN_SP_NONE - sp_hpa) / (TERRAIN_SP_NONE - TERRAIN_SP_FULL), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def smooth_over_terrain(msl: np.ndarray, weight: np.ndarray) -> np.ndarray:
    """msl with high ground (weight near 1) replaced by a heavily smoothed copy."""
    if not weight.any():
        return msl
    return msl + weight * (_gaussian_blur(msl, TERRAIN_SIGMA_CELLS) - msl)


def encode(layer: str, fields: list[np.ndarray]) -> np.ndarray:
    """Encode one layer's fields into an (NLAT, NLON, 4) uint8 RGBA array."""
    spec = LAYERS[layer]
    lo, hi = spec["range"]
    gamma = spec.get("gamma")
    kind = spec["encoding"]

    if spec.get("derive") == "speed":
        u, v = fields
        fields = [np.hypot(u.astype(np.float64), v.astype(np.float64))]
    elif spec.get("derive") == "heatindex":
        t, td = fields
        fields = [heat_index(t, td)]

    rgba = np.zeros((NLAT, NLON, 4), dtype=np.uint8)
    rgba[..., 3] = 255  # see module docstring: never anything but 255

    if kind == "vector8":
        u, v = fields
        rgba[..., 0] = np.round(_normalise(u, lo, hi, gamma) * 255.0).astype(np.uint8)
        rgba[..., 1] = np.round(_normalise(v, lo, hi, gamma) * 255.0).astype(np.uint8)
    elif kind == "scalar8":
        rgba[..., 0] = np.round(_normalise(fields[0], lo, hi, gamma) * 255.0).astype(np.uint8)
    elif kind == "scalar16":
        q = np.round(_normalise(fields[0], lo, hi, gamma) * 65535.0).astype(np.uint32)
        rgba[..., 0] = (q >> 8).astype(np.uint8)
        rgba[..., 1] = (q & 0xFF).astype(np.uint8)
    else:
        raise ValueError(f"unknown encoding {kind}")

    return rgba


def decode(layer: str, rgba: np.ndarray) -> list[np.ndarray]:
    """Inverse of encode(). Mirrors what the fragment shader does, so the test
    that compares the two is also a test of the shader's arithmetic."""
    spec = LAYERS[layer]
    lo, hi = spec["range"]
    gamma = spec.get("gamma")
    kind = spec["encoding"]
    r = rgba[..., 0].astype(np.float64)
    g = rgba[..., 1].astype(np.float64)

    if kind == "vector8":
        return [
            _denormalise(r / 255.0, lo, hi, gamma),
            _denormalise(g / 255.0, lo, hi, gamma),
        ]
    if kind == "scalar8":
        return [_denormalise(r / 255.0, lo, hi, gamma)]
    if kind == "scalar16":
        return [_denormalise((r * 256.0 + g) / 65535.0, lo, hi, gamma)]
    raise ValueError(f"unknown encoding {kind}")


def layer_manifest(layer: str) -> dict:
    """The per-layer block the browser needs to decode this layer's PNGs."""
    spec = LAYERS[layer]
    block = {
        "label": spec["label"],
        "encoding": spec["encoding"],
        "unit": spec["unit"],
        "min": spec["range"][0],
        "max": spec["range"][1],
    }
    if spec.get("hidden"):
        block["hidden"] = True
    if "gamma" in spec:
        block["gamma"] = spec["gamma"]
    return block
