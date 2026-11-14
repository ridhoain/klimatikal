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
REVISION = 3

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
    "msl": {
        "params": ["msl"],
        "encoding": "scalar8",
        "unit": "hPa",
        "range": [870.0, 1085.0],
        "label": "mean sea level pressure",
    },
}

# Why everything is scalar8 even though scalar16 is implemented and tested:
# a 16-bit field is 4 to 8 times the bytes of an 8-bit one, because the low
# byte is close to random and PNG cannot compress it. At 8 bits, temperature
# resolves to 0.55 degC and pressure to 0.84 hPa, which no one can see on a
# colour map. Pressure is the one field where it shows, as slight stepping in
# tightly spaced isobars; if that bothers you, set msl to "scalar16" above and
# accept roughly 1.4 MB more per forecast step.
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


def encode(layer: str, fields: list[np.ndarray]) -> np.ndarray:
    """Encode one layer's fields into an (NLAT, NLON, 4) uint8 RGBA array."""
    spec = LAYERS[layer]
    lo, hi = spec["range"]
    gamma = spec.get("gamma")
    kind = spec["encoding"]

    if spec.get("derive") == "speed":
        u, v = fields
        fields = [np.hypot(u.astype(np.float64), v.astype(np.float64))]

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
