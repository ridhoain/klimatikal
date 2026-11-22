"""Light pollution texture from a night-lights composite -> darksky/lights.png + darksky/darksky.json.

Two sources, chosen with --kind:

  harmonized (default)  Li et al., harmonized DMSP + VIIRS-like annual night
      lights 1992-2024, CC BY 4.0, https://doi.org/10.6084/m9.figshare.9828827
      (no login; one ~30 MB GeoTIFF per year, `Harmonized_DN_NTL_<year>_simVIIRS.tif`).
      30 arc-second integer index 0..63 on the old DMSP scale, not radiance, and
      city cores saturate at 63. Covers 75 N to 65 S. Fine for ranking dark against
      bright places, which is all the page claims. Stored linearly, units "dn".
  vnl  Earth Observation Group, Colorado School of Mines, VIIRS Nighttime Lights
      (VNL) v2.2 annual composite, CC BY 4.0, `*average_masked.dat.tif`
      (15 arc-second radiance in nW/cm2/sr; free EOG account to download).
      Stored on a log scale, units "nw".

Either is static: rerun this only when a new year is out.

What is built, and what it is not. The radiance is block-averaged to 0.1 degree,
then spread with a Gaussian (SPREAD_DEG) because the sky glow of a town reaches
well beyond the town. That gives a light-pollution proxy, in nW/cm2/sr, good for
"where is it dark". It is not sky brightness in mcd/m2 or a Bortle class: that
needs an atmospheric propagation model (Falchi et al.) and the glow of a big
city 100 km away is understated here. The page says so.

Written:
  darksky/lights.png   3600 x 1800, row 0 = 90 N, column 0 = 180 W; value in R; G, B = 0; A = 255
  darksky/darksky.json {"year", "units", ..., "spread_deg", "image", "attribution"}
Decode, by "units":
  "dn"  index = R / 255 * dn_max            (harmonized; dn_max = 63)
  "nw"  radiance = lo_nw * (hi_nw / lo_nw) ** (R / 255), R == 0 meaning "below lo_nw"   (vnl, synthetic)

    python darksky.py --src Harmonized_DN_NTL_2024_simVIIRS.tif --year 2024 --dest ../web/data
    python darksky.py --kind vnl --src VNL_v22_..._average_masked.dat.tif --year 2024 --dest ./out
    python darksky.py --synthetic --dest ./out        # a made-up field for testing the page, not data
"""
from __future__ import annotations

import argparse
import io
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

NLAT, NLON = 1800, 3600          # 0.1 degree
LO_NW, HI_NW = 0.1, 200.0        # log range stored; below LO is dark enough to be "no glow"
SPREAD_DEG = 0.25                # Gaussian sigma of the glow spread, about 28 km
DN_MAX = 63.0                    # harmonized series: integer index 0..63 (DMSP scale)
ATTRIBUTIONS = {
    "vnl": "Light pollution: VIIRS Nighttime Lights, Earth Observation Group, Colorado School of Mines (CC BY 4.0)",
    "harmonized": "Light pollution: harmonized DMSP and VIIRS night-time light, Li et al. 2020, Scientific Data (CC BY 4.0)",
}
IMAGE_KEY = "darksky/lights.png"
JSON_KEY = "darksky/darksky.json"


def block_mean(a: np.ndarray, fy: int, fx: int) -> np.ndarray:
    """Mean over fy x fx blocks; NaN (masked, no data) counts as 0 radiance."""
    a = np.nan_to_num(a, nan=0.0)
    h, w = a.shape
    return a[: h // fy * fy, : w // fx * fx].reshape(h // fy, fy, w // fx, fx).mean(axis=(1, 3))


def read_source(path: Path) -> np.ndarray:
    """Whole-globe radiance at 0.1 degree, north first, 180 W first, float32 nW/cm2/sr.

    Reads the GeoTIFF in bands of rows so the 15 arc-second raster (86400 x 33600,
    11 GB as float32) never sits in memory whole.
    """
    import tifffile
    out = np.zeros((NLAT, NLON), dtype=np.float32)
    with tifffile.TiffFile(path) as tf:
        page = tf.pages[0]
        h, w = page.shape[:2]
        # VNL covers 75 N to 65 S. 0.1 degree is 24 pixels of 15 arc-seconds.
        px = 360.0 / w
        fy = fx = int(round(0.1 / px))
        if abs(fx * px - 0.1) > 1e-6 or w // fx != NLON:
            raise ValueError(f"unexpected raster width {w}; expected 15 arc-second global ({NLON * 24})")
        top_row = int(round((90.0 - 75.0) / 0.1))          # where 75 N falls in the 0.1 degree frame
        store = tf.aszarr()
        try:
            import zarr
            z = zarr.open(store, mode="r")
            z = z[0] if isinstance(z, zarr.Group) else z
        except ImportError as err:
            raise SystemExit("reading the full-size GeoTIFF needs zarr: pip install zarr") from err
        band = fy * 50
        for y0 in range(0, h, band):
            y1 = min(h, y0 + band)
            block = np.asarray(z[y0:y1, :], dtype=np.float32)
            block[block < 0] = 0.0                          # fill values and negatives
            m = block_mean(block, fy, fx)
            r0 = top_row + y0 // fy
            out[r0: r0 + m.shape[0]] = m[: NLAT - r0]
    return out


def read_harmonized(path: Path) -> np.ndarray:
    """Harmonized DN (30 arc-second, 43201 x 16801, 75 N to 65 S) -> 0.1 degree float32 DN, whole globe.

    The file has one extra column (the 180 E edge repeated) and its pixel centres sit on whole
    multiples of 1/120 degree, so 12 x 12 blocks starting at the top-left pixel are 0.1 degree cells
    to within half a pixel. About 1.5 GB as int16 while it is read; reduced band by band.
    """
    import tifffile
    a = tifffile.imread(path)
    h, w = a.shape
    if w not in (NLON * 12, NLON * 12 + 1) or h < 1200:
        raise ValueError(f"unexpected raster shape {a.shape}; expected the harmonized 30 arc-second global grid")
    a = a[:, : NLON * 12]
    out = np.zeros((NLAT, NLON), dtype=np.float32)
    top_row = int(round((90.0 - 75.0) / 0.1))
    band = 12 * 50
    for y0 in range(0, h - h % 12, band):
        y1 = min(h - h % 12, y0 + band)
        blk = np.clip(a[y0:y1].astype(np.float32), 0, DN_MAX)
        m = block_mean(blk, 12, 12)
        r0 = top_row + y0 // 12
        out[r0: r0 + m.shape[0]] = m[: NLAT - r0]
    return out


def synthetic() -> np.ndarray:
    """Made-up lights: a few bright cities with long tails. For testing the page only."""
    rng = np.random.default_rng(7)
    lat = np.linspace(90, -90, NLAT)[:, None]
    lon = np.linspace(-180, 180, NLON, endpoint=False)[None, :]
    out = np.zeros((NLAT, NLON), dtype=np.float32)
    cities = [(-6.2, 106.8, 60), (-7.25, 112.75, 30), (35.7, 139.7, 90), (40.7, -74, 80), (51.5, -0.1, 60),
              (28.6, 77.2, 70), (30, 31, 50), (-23.5, -46.6, 60), (55.7, 37.6, 50), (-33.9, 151.2, 40)]
    for la, lo, peak in cities + [(rng.uniform(-50, 60), rng.uniform(-170, 170), rng.uniform(3, 25)) for _ in range(160)]:
        d2 = (lat - la) ** 2 + ((lon - lo) * np.cos(np.radians(la))) ** 2
        out += (peak * np.exp(-d2 / (2 * 0.06 ** 2))).astype(np.float32)
    return out


def spread(a: np.ndarray, sigma_deg: float = SPREAD_DEG) -> np.ndarray:
    from scipy.ndimage import gaussian_filter
    s = sigma_deg / 0.1
    # Wrap in longitude. Latitude rows are not shrunk by cos(lat); fine for a glow proxy.
    return gaussian_filter(a, sigma=s, mode=("nearest", "wrap"))


def encode(radiance: np.ndarray) -> np.ndarray:
    """Log-scale radiance onto 0..255 (0 = at or below LO_NW)."""
    r = np.clip(radiance, LO_NW, HI_NW)
    return np.round(255.0 * np.log(r / LO_NW) / np.log(HI_NW / LO_NW)).astype(np.uint8)


def encode_dn(index: np.ndarray) -> np.ndarray:
    """Linear 0..DN_MAX onto 0..255."""
    return np.round(255.0 * np.clip(index, 0, DN_MAX) / DN_MAX).astype(np.uint8)


def to_png(code: np.ndarray) -> bytes:
    rgba = np.zeros(code.shape + (4,), dtype=np.uint8)
    rgba[..., 0] = code
    rgba[..., 3] = 255
    buf = io.BytesIO()
    Image.fromarray(rgba).save(buf, "PNG", optimize=True)
    return buf.getvalue()


def main() -> int:
    ap = argparse.ArgumentParser()
    src = ap.add_mutually_exclusive_group(required=True)
    ap.add_argument("--kind", choices=["harmonized", "vnl"], default="harmonized")
    src.add_argument("--src", type=Path, help="the GeoTIFF (unzipped)")
    src.add_argument("--synthetic", action="store_true")
    ap.add_argument("--year", type=int, help="composite year, shown on the page")
    ap.add_argument("--dest", default="./out")
    a = ap.parse_args()
    if a.src and not a.year:
        ap.error("--year is required with --src")
    kind = "vnl" if a.synthetic else a.kind
    if a.synthetic:
        raw = synthetic()
    else:
        raw = read_harmonized(a.src) if kind == "harmonized" else read_source(a.src)
    glow = spread(raw)
    if kind == "harmonized":
        png = to_png(encode_dn(glow))
        scale = {"units": "dn", "dn_max": DN_MAX}
    else:
        png = to_png(encode(glow))
        scale = {"units": "nw", "lo_nw": LO_NW, "hi_nw": HI_NW}
    doc = {"year": a.year, "synthetic": a.synthetic, **scale, "spread_deg": SPREAD_DEG,
           "image": IMAGE_KEY, "attribution": ATTRIBUTIONS[kind]}
    base = Path(a.dest)
    (base / IMAGE_KEY).parent.mkdir(parents=True, exist_ok=True)
    (base / IMAGE_KEY).write_bytes(png)
    (base / JSON_KEY).write_text(json.dumps(doc, separators=(",", ":")))
    print(f"wrote {base / IMAGE_KEY} ({len(png) / 1e6:.2f} MB)")
    print("Upload darksky/ to the data bucket (aws s3 cp --endpoint-url ... or the R2 dashboard); it is static.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
