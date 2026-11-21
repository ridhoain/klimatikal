"""Compare thermal.py UTCI (sun) with ERA5-HEAT for one day over Indonesia.

Usage: python validate_era5heat.py <dir with in/ and heat/>   (see fetch_era5heat.py)
"""
import sys, datetime as dt, numpy as np, xarray as xr, glob
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import thermal
E = sys.argv[1]   # directory holding in/ (unzipped ERA5 netCDFs) and heat/ (unzipped ERA5-HEAT netCDFs)
acc = xr.open_dataset(f"{E}/in/data_stream-oper_stepType-accum.nc")
ins = xr.open_dataset(f"{E}/in/data_stream-oper_stepType-instant.nc")
u = xr.open_dataset(glob.glob(f"{E}/heat/*utci*.nc")[0]); m = xr.open_dataset(glob.glob(f"{E}/heat/*mrt*.nc")[0])
print("utci attrs", u.utci.attrs.get("units"), "mrt", m.mrt.attrs.get("units"))
def k2c(a): return a - 273.15 if np.nanmean(a) > 150 else a
U = k2c(u.utci.values); M = k2c(m.mrt.values)
lat = acc.latitude.values[:, None]; lon = acc.longitude.values[None, :]
A = {k: acc[k].values for k in ("ssrd", "ssr", "strd", "str", "fdir")}     # J m-2 per hour
T = k2c(ins.t2m.values); TD = k2c(ins.d2m.values); U10 = ins.u10.values; V10 = ins.v10.values
times = [dt.datetime.utcfromtimestamp(t.astype("datetime64[s]").astype(int)).replace(tzinfo=dt.timezone.utc) for t in acc.valid_time.values]
H = dt.timedelta(hours=1)

def run(i, hours, use_fdir):
    """Pipeline-style step ending at hour i: instants at i, mean flux over the `hours` before it."""
    sl = slice(i - hours + 1, i + 1)
    flux = {k: A[k][sl].sum(0) / (3600.0 * hours) for k in ("ssrd", "ssr", "strd", "str")}
    start, end = times[i] - hours * H, times[i]
    fields = {"2t": T[i], "2d": TD[i], "10u": U10[i], "10v": V10[i]}
    t, td = fields["2t"], fields["2d"]
    rh = thermal.relative_humidity(t, td); wind = np.hypot(fields["10u"], fields["10v"])
    mu0 = thermal.window_mean_mu0(lat, lon, start, end)
    i0 = thermal.SOLAR_CONSTANT * thermal.earth_sun_factor(start + (end - start) / 2)
    d = (A["fdir"][sl].sum(0) / (3600.0 * hours)) if use_fdir else None
    tm = thermal.mean_radiant_temperature(flux["ssrd"], flux["ssr"], flux["strd"], flux["str"], mu0, i0, sun=True, direct_horizontal=d)
    return tm, thermal.utci(t, rh, wind, tm), mu0

def stats(name, x, ref, mask):
    e = (x - ref)[mask]; e = e[np.isfinite(e)]
    print(f"  {name:34s} n={e.size:6d} bias={e.mean():+.2f} rmse={np.sqrt((e**2).mean()):.2f} mae={np.abs(e).mean():.2f} p95|e|={np.percentile(np.abs(e),95):.2f} within1C={100*(np.abs(e)<=1).mean():.0f}% within2C={100*(np.abs(e)<=2).mean():.0f}%")

variants = [("1 h, measured direct (fdir)", 1, True), ("1 h, Erbs split", 1, False), ("3 h, Erbs split (as shipped)", 3, False)]
res = {n: {"tm": np.full(U.shape, np.nan), "ut": np.full(U.shape, np.nan), "mu0": np.zeros(U.shape)} for n, _, _ in variants}
for i in range(3, 24):
    for n, h, f in variants:
        tm, ut, mu = run(i, h, f); res[n]["tm"][i] = tm; res[n]["ut"][i] = ut; res[n]["mu0"][i] = mu
U3 = np.full(U.shape, np.nan); M3 = np.full(U.shape, np.nan)
for i in range(3, 24): U3[i] = U[i-2:i+1].mean(0); M3[i] = M[i-2:i+1].mean(0)
valid = np.zeros(U.shape, bool); valid[3:] = True
for n, h, f in variants:
    r = res[n]; day = (r["mu0"] > 0.3) & valid; night = (r["mu0"] <= 0.0) & valid
    print(f"\n== {n}")
    ref_u, ref_m = (U3, M3) if h == 3 else (U, M)
    for lab, mk in (("all hours", valid), ("daytime (mean cos zenith>0.3)", day), ("night", night)):
        stats(f"UTCI sun, {lab}", r["ut"], ref_u, mk)
    stats("Tmrt, daytime", r["tm"], ref_m, day)
    if h == 3: stats("UTCI vs ERA5-HEAT at step end, day", r["ut"], U, day)
r = res["3 h, Erbs split (as shipped)"]
dayh = [i for i in range(3, 24) if (r["mu0"][i] > 0.3).mean() > 0.5]
print("\nhourly daytime bias/rmse of shipped config (UTC hour):")
for i in range(3, 24):
    mk = np.zeros(U.shape, bool); mk[i] = True
    e = (r["ut"][i] - U3[i]); print(f"  {times[i].hour:02d}Z bias={np.nanmean(e):+.2f} rmse={np.sqrt(np.nanmean(e**2)):.2f} mean ERA5-HEAT UTCI={np.nanmean(U3[i]):.1f}")
