#!/usr/bin/env python3
"""Fetch the daily 925 hPa meridional wind over a box from the NCEP/NCAR Reanalysis 1
(NOAA PSL, public domain), average it over the box and save the daily series as JSON in
atlas/diagrams/. Used for the CENS index of the cross-equatorial northerly surge entry.
One-off and gentle (rate-limited server: requests are spaced and retried). 2.5 degree grid.

    python3 atlas/diagrams/fetch_index.py --name cens-index-djfm2007 --from 2006-12-01 --to 2007-03-31 \
        --lat-from 0 --lat-to -5 --lon-from 105 --lon-to 115

The index is the box-mean NORTHERLY wind (minus the meridional component), in m/s. This is a
925 hPa reanalysis approximation of an index that its authors defined on QuikSCAT sea-surface wind.
"""
import argparse, datetime, json, time
from pathlib import Path
from fetch_daily import D, get, rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True)
    ap.add_argument("--from", dest="d0", required=True); ap.add_argument("--to", dest="d1", required=True)
    ap.add_argument("--lat-from", type=float, required=True); ap.add_argument("--lat-to", type=float, required=True)
    ap.add_argument("--lon-from", type=float, required=True); ap.add_argument("--lon-to", type=float, required=True)
    a = ap.parse_args()
    d0, d1 = datetime.date.fromisoformat(a.d0), datetime.date.fromisoformat(a.d1)
    i0, i1 = sorted((round((90 - a.lat_from) / 2.5), round((90 - a.lat_to) / 2.5)))
    j0, j1 = sorted((round(a.lon_from / 2.5), round(a.lon_to / 2.5)))
    ny, nx = i1 - i0 + 1, j1 - j0 + 1
    dates, index = [], []
    for year in range(d0.year, d1.year + 1):
        ya, yb = max(d0, datetime.date(year, 1, 1)), min(d1, datetime.date(year, 12, 31))
        t0, t1 = (ya - datetime.date(year, 1, 1)).days, (yb - datetime.date(year, 1, 1)).days
        nt = t1 - t0 + 1
        v = rows(get(D + f"pressure/vwnd.{year}.nc.ascii?vwnd%5B{t0}:{t1}%5D%5B1:1%5D%5B{i0}:{i1}%5D%5B{j0}:{j1}%5D"), nt * ny * nx)
        for t in range(nt):
            cell = v[t * ny * nx:(t + 1) * ny * nx]
            index.append(round(-sum(cell) / len(cell), 3))
            dates.append((ya + datetime.timedelta(days=t)).isoformat())
        time.sleep(35)
    lvl = get(D + f"pressure/vwnd.{d0.year}.nc.ascii?level%5B1:1%5D")
    if "925" not in lvl:
        raise SystemExit("level index 1 is not 925 hPa: " + lvl[-80:])
    doc = {"name": a.name, "source": "NCEP/NCAR Reanalysis 1, daily means, 925 hPa meridional wind, NOAA PSL (public domain)",
           "url": "https://psl.noaa.gov/data/gridded/data.ncep.reanalysis.html", "accessed": datetime.date.today().isoformat(),
           "box": {"lat": [min(a.lat_from, a.lat_to), max(a.lat_from, a.lat_to)], "lon": [a.lon_from, a.lon_to],
                   "grid_points": ny * nx},
           "dates": dates, "northerly_ms": index}
    Path(__file__).with_name(f"{a.name}.json").write_text(json.dumps(doc))
    print("wrote", a.name, len(dates), "days; max", max(index), "min", min(index))


if __name__ == "__main__":
    main()
