"""Needs a CDS account (~/.cdsapirc) with both dataset licences accepted. Unzip the results into in/ and heat/.
Fetch one day of ERA5 inputs and ERA5-HEAT UTCI over Indonesia (small netCDFs)."""
import sys, cdsapi
out = sys.argv[1]
area = [8, 95, -11, 141]
day = dict(year="2026", month="11", day="05", time=[f"{h:02d}:00" for h in range(24)])
c = cdsapi.Client()
c.retrieve("reanalysis-era5-single-levels", dict(
    product_type="reanalysis", data_format="netcdf", download_format="unarchived", area=area, grid=[0.25, 0.25],
    variable=["2m_temperature", "2m_dewpoint_temperature", "10m_u_component_of_wind", "10m_v_component_of_wind",
              "surface_solar_radiation_downwards", "surface_net_solar_radiation",
              "surface_thermal_radiation_downwards", "surface_net_thermal_radiation",
              "total_sky_direct_solar_radiation_at_surface"], **day), f"{out}/era5_inputs.nc")
print("inputs ok", flush=True)
for product in ("consolidated_dataset", "intermediate_dataset"):
    try:
        c.retrieve("derived-utci-historical", dict(
            variable=["universal_thermal_climate_index", "mean_radiant_temperature"], version="1_1",
            product_type=product, data_format="netcdf", download_format="unarchived", area=area, **day),
            f"{out}/era5heat.nc")
        print("heat ok", product, flush=True); break
    except Exception as e:
        print("heat failed", product, str(e)[:300], flush=True)
