"""Thermal comfort from ECMWF open data: mean radiant temperature and UTCI.

Follows the ERA5-HEAT approach (Di Napoli et al. 2020, "Mean radiant temperature
from global-scale numerical weather prediction models"), so the numbers are
comparable with the Copernicus thermal comfort dataset. UTCI itself comes from
pythermalcomfort (Broede et al. polynomial), not from coefficients typed here.

Inputs are the accumulated radiation fields of the open data (J m-2 from the
start of the forecast). Two consecutive steps give a mean flux over the window
between them; the solar geometry is averaged over the same window.

Known approximations, all visible on the map as small errors rather than
failures:
  * The Erbs direct/diffuse split was fitted on hourly data and is applied to a
    3-hour mean. It tends to give a little too much diffuse light.
  * The projected-area factor uses the window-mean solar elevation.
  * Step 0 has no radiation to difference, so it is computed with the radiant
    load set to air temperature (no sun term). Treat step 0 as "no solar data".
"""

from __future__ import annotations

import datetime as dt

import numpy as np

SIGMA = 5.670374419e-8      # Stefan-Boltzmann, W m-2 K-4
SOLAR_CONSTANT = 1361.0     # W m-2
ALPHA_IRR = 0.7             # absorption of short-wave by a clothed person (Di Napoli)
EPS_P = 0.97                # emissivity of the person
MU0_MIN = 0.05              # below this the sun counts as on the horizon

# UTCI's polynomial is only valid inside these input ranges; inputs are clamped.
TA_RANGE = (-50.0, 50.0)
WIND_RANGE = (0.5, 17.0)
DTMRT_RANGE = (-30.0, 70.0)


# --------------------------------------------------------------------------
# solar geometry
# --------------------------------------------------------------------------

def cos_zenith(lat_deg: np.ndarray, lon_deg: np.ndarray, when: dt.datetime) -> np.ndarray:
    """Cosine of the solar zenith angle (Spencer declination and equation of
    time, good to well under a degree). `when` is UTC."""
    when = when.astimezone(dt.timezone.utc) if when.tzinfo else when
    doy = when.timetuple().tm_yday
    g = 2.0 * np.pi / 365.0 * (doy - 1 + (when.hour - 12) / 24.0)
    decl = (0.006918 - 0.399912 * np.cos(g) + 0.070257 * np.sin(g)
            - 0.006758 * np.cos(2 * g) + 0.000907 * np.sin(2 * g)
            - 0.002697 * np.cos(3 * g) + 0.00148 * np.sin(3 * g))
    eot_min = 229.18 * (0.000075 + 0.001868 * np.cos(g) - 0.032077 * np.sin(g)
                        - 0.014615 * np.cos(2 * g) - 0.040849 * np.sin(2 * g))
    utc_h = when.hour + when.minute / 60.0 + when.second / 3600.0
    solar_h = utc_h + eot_min / 60.0 + lon_deg / 15.0
    hour_angle = np.deg2rad(15.0 * (solar_h - 12.0))
    lat = np.deg2rad(lat_deg)
    return np.sin(lat) * np.sin(decl) + np.cos(lat) * np.cos(decl) * np.cos(hour_angle)


def earth_sun_factor(when: dt.datetime) -> float:
    return 1.0 + 0.033 * np.cos(2.0 * np.pi * when.timetuple().tm_yday / 365.0)


def window_mean_mu0(lat_deg, lon_deg, start: dt.datetime, end: dt.datetime, samples: int = 7) -> np.ndarray:
    """Mean of max(cos zenith, 0) over [start, end]: the horizontal share of
    sunlight that the window's mean flux has to be compared with."""
    total = np.zeros(np.broadcast(lat_deg, lon_deg).shape)
    for i in range(samples):
        t = start + (end - start) * (i / (samples - 1))
        total += np.maximum(cos_zenith(lat_deg, lon_deg, t), 0.0)
    return total / samples


def grid_latlon(nlat: int, nlon: int) -> tuple[np.ndarray, np.ndarray]:
    """Image-oriented grid of the pipeline: row 0 is 90N, column 0 is 180W."""
    lat = np.linspace(90.0, -90.0, nlat)[:, None]
    lon = (-180.0 + 360.0 * np.arange(nlon) / nlon)[None, :]
    return lat, lon


# --------------------------------------------------------------------------
# humidity and radiation
# --------------------------------------------------------------------------

def relative_humidity(t_c, td_c) -> np.ndarray:
    """Relative humidity in % from temperature and dewpoint (Magnus)."""
    t_c = np.asarray(t_c, dtype=np.float64)
    td_c = np.minimum(np.asarray(td_c, dtype=np.float64), t_c)
    a, b = 17.625, 243.04
    return np.clip(100.0 * np.exp(a * td_c / (b + td_c) - a * t_c / (b + t_c)), 0.0, 100.0)


def erbs_diffuse_fraction(kt: np.ndarray) -> np.ndarray:
    """Diffuse share of global horizontal radiation from the clearness index."""
    kt = np.clip(kt, 0.0, 1.0)
    mid = 0.9511 - 0.1604 * kt + 4.388 * kt**2 - 16.638 * kt**3 + 12.336 * kt**4
    return np.where(kt < 0.22, 1.0 - 0.09 * kt, np.where(kt <= 0.80, mid, 0.165))


def projected_area_factor(elevation_deg: np.ndarray) -> np.ndarray:
    """Share of the beam's cross-section a standing person presents
    (Di Napoli et al. 2020, after Jendritzky)."""
    g = np.asarray(elevation_deg, dtype=np.float64)
    return 0.308 * np.cos(np.deg2rad(g * (0.998 - g**2 / 50000.0)))


def mean_radiant_temperature(
    ssrd: np.ndarray, ssr: np.ndarray, strd: np.ndarray, str_: np.ndarray,
    mean_mu0: np.ndarray, i0: float, sun: bool, direct_horizontal: np.ndarray | None = None,
) -> np.ndarray:
    """Tmrt in degC for a standing person. ssrd, ssr, strd, str_ are mean fluxes
    over the window in W m-2 (downward positive, as ECMWF accumulates them).
    `sun` False drops the direct beam and keeps diffuse, reflected and thermal.
    `direct_horizontal` is the measured direct beam on a horizontal surface
    (ERA5's fdir) where there is one; the open data has none, so the default
    estimates it from the clearness index. Used to validate against ERA5-HEAT."""
    ssrd = np.maximum(ssrd, 0.0)
    reflected = np.maximum(ssrd - ssr, 0.0)               # ground-reflected short-wave
    lw_down = np.maximum(strd, 0.0)
    lw_up = np.maximum(strd - str_, 0.0)                  # thermal emitted by the ground

    sunlit = mean_mu0 >= MU0_MIN
    mu0 = np.where(sunlit, mean_mu0, 1.0)
    kt = np.where(sunlit, ssrd / (i0 * mu0), 0.0)
    diffuse_share = np.where(sunlit, erbs_diffuse_fraction(kt), 1.0)
    if direct_horizontal is None:
        direct_horizontal = ssrd * (1.0 - diffuse_share)
    else:
        direct_horizontal = np.where(sunlit, np.clip(direct_horizontal, 0.0, ssrd), 0.0)
    diffuse = ssrd - direct_horizontal
    direct_normal = np.minimum(direct_horizontal / mu0, 1.2 * i0)   # cap: noise near the horizon
    elevation = np.rad2deg(np.arcsin(np.clip(mu0, 0.0, 1.0)))
    fp = projected_area_factor(elevation)

    beam = fp * direct_normal if sun else 0.0
    absorbed_sw = (ALPHA_IRR / EPS_P) * (beam + 0.5 * (diffuse + reflected))
    absorbed_lw = 0.5 * lw_down + 0.5 * lw_up
    return np.power((absorbed_sw + absorbed_lw) / SIGMA, 0.25) - 273.15


# --------------------------------------------------------------------------
# UTCI
# --------------------------------------------------------------------------

def utci(t_c, rh_pct, wind_ms, tmrt_c) -> np.ndarray:
    """UTCI in degC. Inputs are clamped to the polynomial's valid ranges."""
    from pythermalcomfort.models import utci as _utci

    ta = np.clip(t_c, *TA_RANGE)
    v = np.clip(wind_ms, *WIND_RANGE)
    tr = ta + np.clip(tmrt_c - ta, *DTMRT_RANGE)
    result = _utci(tdb=ta.ravel(), tr=tr.ravel(), v=v.ravel(), rh=np.clip(rh_pct, 1.0, 100.0).ravel(),
                   limit_inputs=False)
    return np.asarray(getattr(result, "utci", result), dtype=np.float64).reshape(np.shape(ta))


def utci_sun_shade(
    fields: dict[str, np.ndarray], flux: dict[str, np.ndarray] | None,
    start: dt.datetime, end: dt.datetime,
    lat: np.ndarray | None = None, lon: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """UTCI in sun and in shade for one step.

    `fields` holds 2t and 2d (degC) and 10u, 10v (m/s). `flux` holds the mean
    ssrd, ssr, strd, str in W m-2 over [start, end], or None at step 0 (no
    window yet), where the radiant load is taken as the air temperature.
    """
    t, td = fields["2t"], fields["2d"]
    rh = relative_humidity(t, td)
    wind = np.hypot(fields["10u"], fields["10v"])
    if flux is None:
        tmrt_sun = tmrt_shade = t
    else:
        if lat is None:
            lat, lon = grid_latlon(*t.shape)
        mu0 = window_mean_mu0(lat, lon, start, end)
        mid = start + (end - start) / 2
        i0 = SOLAR_CONSTANT * earth_sun_factor(mid)
        args = (flux["ssrd"], flux["ssr"], flux["strd"], flux["str"], mu0, i0)
        tmrt_sun = mean_radiant_temperature(*args, sun=True)
        tmrt_shade = mean_radiant_temperature(*args, sun=False)
    return utci(t, rh, wind, tmrt_sun), utci(t, rh, wind, tmrt_shade)


# --------------------------------------------------------------------------
# wet-bulb temperature
# --------------------------------------------------------------------------

def wet_bulb(t_c, rh_pct) -> np.ndarray:
    """Wet-bulb temperature in degC (Stull 2011), from temperature and relative
    humidity. Fitted for RH 5 to 99 % and T -20 to 50 degC, good to about 1 degC
    there; RH is clipped into that range. Not WBGT: it has no radiation."""
    t = np.asarray(t_c, dtype=np.float64)
    rh = np.clip(np.asarray(rh_pct, dtype=np.float64), 5.0, 99.0)
    return (t * np.arctan(0.151977 * np.sqrt(rh + 8.313659)) + np.arctan(t + rh) - np.arctan(rh - 1.676331)
            + 0.00391838 * rh**1.5 * np.arctan(0.023101 * rh) - 4.686035)


# --------------------------------------------------------------------------
# estimated UV index
# --------------------------------------------------------------------------

OZONE_DU = 255.0            # fixed column ozone for the equatorial band
UVI_SCALE = 1.0             # tunable: the clear-sky formula reads a little high against observations
CLOUD_K = 1.0               # UVI = clear * cloud_factor ** k; cloud passes slightly more UV than total sunlight
CLOUD_FACTOR_MIN = 0.05
CLEAR_GHI_MIN = 50.0        # W m-2: below this window-mean clear-sky radiation the ratio is noise


def clear_sky_uvi(mu0, ozone_du: float = OZONE_DU, scale: float = UVI_SCALE) -> np.ndarray:
    """Clear-sky UV index from the cosine of the zenith angle and total ozone."""
    mu0 = np.asarray(mu0, dtype=np.float64)
    ok = mu0 >= MU0_MIN
    m = np.where(ok, mu0, 1.0)
    return np.where(ok, scale * 12.5 * m**2.42 * (ozone_du / 300.0) ** -1.23, 0.0)


def haurwitz_ghi(mu0) -> np.ndarray:
    """Clear-sky global horizontal radiation, W m-2 (Haurwitz)."""
    mu0 = np.asarray(mu0, dtype=np.float64)
    ok = mu0 > 0.0
    m = np.where(ok, mu0, 1.0)
    return np.where(ok, 1098.0 * m * np.exp(-0.059 / m), 0.0)


def window_mean_haurwitz(lat_deg, lon_deg, start: dt.datetime, end: dt.datetime, samples: int = 7) -> np.ndarray:
    total = np.zeros(np.broadcast(lat_deg, lon_deg).shape)
    for i in range(samples):
        t = start + (end - start) * (i / (samples - 1))
        total += haurwitz_ghi(cos_zenith(lat_deg, lon_deg, t))
    return total / samples


def cloud_factor_from_tcc(tcc_pct) -> np.ndarray:
    """Fallback when there is no radiation window (step 0) or the sun is too low
    for the ratio: Kasten and Czeplak, 1 - 0.75 n^3.4."""
    n = np.clip(np.asarray(tcc_pct, dtype=np.float64) / 100.0, 0.0, 1.0)
    return 1.0 - 0.75 * n**3.4


def uv_index(
    fields: dict[str, np.ndarray], flux: dict[str, np.ndarray] | None,
    start: dt.datetime, end: dt.datetime,
    lat: np.ndarray | None = None, lon: np.ndarray | None = None,
    k: float = CLOUD_K, scale: float = UVI_SCALE,
) -> np.ndarray:
    """Estimated UV index at the end of the window (the step's valid time).

    Cloud factor = forecast global radiation / clear-sky (Haurwitz) global
    radiation over the window, clamped to 0.05..1. Haze and aerosols beyond
    ECMWF's fixed climatology are not modelled."""
    shape = fields["tcc"].shape
    if lat is None:
        lat, lon = grid_latlon(*shape)
    clear = clear_sky_uvi(cos_zenith(lat, lon, end), scale=scale)
    fallback = cloud_factor_from_tcc(fields["tcc"])
    if flux is None:
        cf = fallback
    else:
        ghi_clear = window_mean_haurwitz(lat, lon, start, end)
        usable = ghi_clear >= CLEAR_GHI_MIN
        cf = np.where(usable, flux["ssrd"] / np.where(usable, ghi_clear, 1.0), fallback)
    cf = np.clip(cf, CLOUD_FACTOR_MIN, 1.0)
    return clear * cf**k
