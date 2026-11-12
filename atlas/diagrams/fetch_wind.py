#!/usr/bin/env python3
"""Fetch a long-term-mean near-surface wind field (NCEP/NCAR Reanalysis 1,
0.995 sigma level, public domain, NOAA PSL) for one month and one box, and save it
as JSON in atlas/diagrams/. One-off, gentle use: the server rate-limits (HTTP 429),
so requests are spaced out and retried.

    python3 atlas/diagrams/fetch_wind.py --name wind-aug-seasia --month 8 \
        --lat-from 10 --lat-to -30 --lon-from 90 --lon-to 160
"""
import argparse, json, re, time, urllib.request, urllib.error, datetime
from pathlib import Path

B = "https://psl.noaa.gov/thredds/dodsC/Datasets/ncep.reanalysis.derived/surface/%s.sig995.mon.ltm.nc.ascii?"


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


def nums(txt):
    return [float(x) for x in re.findall(r"-?\d+\.?\d*(?:[eE][-+]?\d+)?", txt)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True); ap.add_argument("--month", type=int, required=True)
    ap.add_argument("--lat-from", type=float, required=True); ap.add_argument("--lat-to", type=float, required=True)
    ap.add_argument("--lon-from", type=float, required=True); ap.add_argument("--lon-to", type=float, required=True)
    a = ap.parse_args()
    # NCEP grid: lat 90 .. -90 step -2.5 (73), lon 0 .. 357.5 step 2.5 (144)
    i0, i1 = sorted((round((90 - a.lat_from) / 2.5), round((90 - a.lat_to) / 2.5)))
    j0, j1 = sorted((round(a.lon_from / 2.5), round(a.lon_to / 2.5)))
    t = a.month - 1
    lats = [90 - 2.5 * i for i in range(i0, i1 + 1)]; lons = [2.5 * j for j in range(j0, j1 + 1)]
    out = {}
    for var in ("uwnd", "vwnd"):
        txt = get(B % var + f"{var}%5B{t}:{t}%5D%5B{i0}:{i1}%5D%5B{j0}:{j1}%5D")
        vals = []
        for line in txt.splitlines():
            m = re.match(r"^\[\d+\]\[\d+\],(.*)$", line)
            if m:
                vals += nums(m.group(1))
        if len(vals) != len(lats) * len(lons):
            raise SystemExit(f"{var}: got {len(vals)} values, expected {len(lats) * len(lons)}")
        out[var] = [vals[r * len(lons):(r + 1) * len(lons)] for r in range(len(lats))]
        time.sleep(35)
    meta = get(B % "uwnd" + f"climatology_bounds%5B{t}:{t}%5D%5B0:1%5D")
    rows = [nums(l.split("],", 1)[1]) for l in meta.splitlines() if re.match(r"^\[\d+\]\[\d+\]", l)]
    hrs = rows[0][-2:] if rows else []
    if len(hrs) != 2:
        hrs = nums(meta.split("climatology_bounds[", 1)[-1].split("\n", 2)[-1])[-2:]
    base = datetime.datetime(1800, 1, 1)
    per = [(base + datetime.timedelta(hours=h)).year for h in hrs]
    doc = {"name": a.name, "month": a.month, "source": "NCEP/NCAR Reanalysis 1, long-term monthly mean, 0.995 sigma level (near surface), NOAA PSL (public domain)",
           "url": "https://psl.noaa.gov/data/gridded/data.ncep.reanalysis.derived.html", "climatology_years": per,
           "accessed": datetime.date.today().isoformat(), "lat": lats, "lon": lons, "u_ms": out["uwnd"], "v_ms": out["vwnd"]}
    Path(__file__).with_name(f"{a.name}.json").write_text(json.dumps(doc))
    print("wrote", a.name, len(lats), "x", len(lons), "years", per)


if __name__ == "__main__":
    main()
