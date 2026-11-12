#!/usr/bin/env python3
"""Fetch daily-mean sea-level pressure and 925 hPa wind for a box and a run of days
from the NCEP/NCAR Reanalysis 1 (NOAA PSL, public domain) and save them as JSON in
atlas/diagrams/. One-off and gentle: the server rate-limits (HTTP 429), so requests
are spaced and retried. Grid is 2.5 degrees.

    python3 atlas/diagrams/fetch_daily.py --name bv-oct2018 --from 2018-10-18 --to 2018-10-28 \
        --lat-from 25 --lat-to -10 --lon-from 95 --lon-to 130
"""
import argparse, datetime, json, re, time, urllib.request, urllib.error
from pathlib import Path

D = "https://psl.noaa.gov/thredds/dodsC/Datasets/ncep.reanalysis.dailyavgs/"


def get(url):
    for attempt in range(8):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "klimatikal-atlas/1.0"}), timeout=60) as r:
                return r.read().decode()
        except urllib.error.HTTPError as e:
            if e.code != 429:
                raise
            time.sleep(30 + 15 * attempt)
    raise SystemExit("rate-limited too long; try again later")


def rows(txt, n):
    vals = []
    for line in txt.splitlines():
        m = re.match(r"^(?:\[\d+\])+,(.*)$", line)
        if m:
            vals += [float(x) for x in m.group(1).split(",") if x.strip()]
    if len(vals) != n:
        raise SystemExit(f"expected {n} values, got {len(vals)}")
    return vals


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True)
    ap.add_argument("--from", dest="d0", required=True); ap.add_argument("--to", dest="d1", required=True)
    ap.add_argument("--lat-from", type=float, required=True); ap.add_argument("--lat-to", type=float, required=True)
    ap.add_argument("--lon-from", type=float, required=True); ap.add_argument("--lon-to", type=float, required=True)
    a = ap.parse_args()
    d0, d1 = datetime.date.fromisoformat(a.d0), datetime.date.fromisoformat(a.d1)
    if d0.year != d1.year:
        raise SystemExit("one calendar year per file")
    t0 = (d0 - datetime.date(d0.year, 1, 1)).days; t1 = (d1 - datetime.date(d0.year, 1, 1)).days
    i0, i1 = sorted((round((90 - a.lat_from) / 2.5), round((90 - a.lat_to) / 2.5)))
    j0, j1 = sorted((round(a.lon_from / 2.5), round(a.lon_to / 2.5)))
    nt, ny, nx = t1 - t0 + 1, i1 - i0 + 1, j1 - j0 + 1
    out = {}
    jobs = {"slp": f"surface/slp.{d0.year}.nc.ascii?slp%5B{t0}:{t1}%5D%5B{i0}:{i1}%5D%5B{j0}:{j1}%5D",
            "u": f"pressure/uwnd.{d0.year}.nc.ascii?uwnd%5B{t0}:{t1}%5D%5B1:1%5D%5B{i0}:{i1}%5D%5B{j0}:{j1}%5D",
            "v": f"pressure/vwnd.{d0.year}.nc.ascii?vwnd%5B{t0}:{t1}%5D%5B1:1%5D%5B{i0}:{i1}%5D%5B{j0}:{j1}%5D"}
    for k, path in jobs.items():
        v = rows(get(D + path), nt * ny * nx)
        out[k] = [[v[(t * ny + r) * nx:(t * ny + r + 1) * nx] for r in range(ny)] for t in range(nt)]
        time.sleep(35)
    lvl = get(D + f"pressure/uwnd.{d0.year}.nc.ascii?level%5B1:1%5D")
    if "925" not in lvl:
        raise SystemExit("level index 1 is not 925 hPa: " + lvl[-80:])
    doc = {"name": a.name, "source": "NCEP/NCAR Reanalysis 1, daily means, NOAA PSL (public domain)",
           "url": "https://psl.noaa.gov/data/gridded/data.ncep.reanalysis.html", "accessed": datetime.date.today().isoformat(),
           "dates": [(d0 + datetime.timedelta(days=i)).isoformat() for i in range(nt)],
           "lat": [90 - 2.5 * i for i in range(i0, i1 + 1)], "lon": [2.5 * j for j in range(j0, j1 + 1)],
           "slp_hpa": [[[round(x / 100, 2) for x in row] for row in fr] for fr in out["slp"]],
           "u925_ms": out["u"], "v925_ms": out["v"]}
    Path(__file__).with_name(f"{a.name}.json").write_text(json.dumps(doc))
    print("wrote", a.name, nt, "days", ny, "x", nx)


if __name__ == "__main__":
    main()
