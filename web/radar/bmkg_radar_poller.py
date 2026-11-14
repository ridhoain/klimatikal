#!/usr/bin/env python3
"""Poll BMKG radar frames (publik.bmkg.go.id/event/dwt) and archive new PNGs.

Each call to apihub?r=radar&site=X returns only the latest frame, so history
only exists if this script keeps polling. Frames are deduped by filename.

Usage:
  python3 bmkg_radar_poller.py --once --sites SMG YOG       # single test pass
  python3 bmkg_radar_poller.py --interval 300               # loop every 5 min
"""
import argparse, base64, json, os, sys, time
import urllib.parse, urllib.request
from datetime import datetime, timezone, timedelta

BASE = "https://publik.bmkg.go.id/event/dwt/index.php/apihub"
REFERER = "https://publik.bmkg.go.id/event/dwt/"
UA = "klimatikal-radar-archiver/0.1 (research; low-rate polling)"
DEFAULT_SITES = ["SMG", "YOG", "MCRC", "NGW", "IWJ", "PWK", "CGK", "JAK",
                 "SBY", "PKN", "LPG", "PKP", "PLB", "PKY"]


def get(url, accept):
    req = urllib.request.Request(
        url, headers={"Referer": REFERER, "Accept": accept, "User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def poll_site(site, out_dir):
    meta = json.loads(get(f"{BASE}?r=radar&site={site}", "application/json"))
    saved = 0
    for layer in meta.get("layers", []):
        q = urllib.parse.parse_qs(urllib.parse.urlparse(layer["url"]).query)
        src = base64.b64decode(q["file"][0]).decode("utf-8")
        name = os.path.basename(src)
        png = os.path.join(out_dir, site, name)
        if os.path.exists(png):
            print(f"  {site}: {name} already have")
            continue
        os.makedirs(os.path.dirname(png), exist_ok=True)
        data = get(layer["url"], "image/png")
        if not data.startswith(b"\x89PNG"):
            print(f"  {site}: {name} not a PNG ({len(data)} bytes), skipped")
            continue
        with open(png, "wb") as f:
            f.write(data)
        # time string is WIB (UTC+7); filename time is UTC
        wib = datetime.strptime(layer["time"].replace(" WIB", ""),
                                "%Y-%m-%d %H:%M")
        utc = (wib - timedelta(hours=7)).replace(tzinfo=timezone.utc)
        side = {"site": site, "file": name, "source": src,
                "time_wib": layer["time"], "time_utc": utc.isoformat(),
                "bounds": meta.get("bounds")}
        with open(png[:-4] + ".json", "w") as f:
            json.dump(side, f, indent=1)
        print(f"  {site}: saved {name} ({len(data)/1024:.0f} kB)")
        saved += 1
    return saved


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sites", nargs="*", default=DEFAULT_SITES)
    ap.add_argument("--out", default="radar_archive")
    ap.add_argument("--interval", type=int, default=300)
    ap.add_argument("--delay", type=float, default=1.0)
    ap.add_argument("--once", action="store_true")
    a = ap.parse_args()
    while True:
        print(datetime.now(timezone.utc).strftime("[%Y-%m-%d %H:%M UTC] pass"))
        for s in a.sites:
            try:
                poll_site(s, a.out)
            except Exception as e:
                print(f"  {s}: ERROR {e}", file=sys.stderr)
            time.sleep(a.delay)
        if a.once:
            break
        time.sleep(a.interval)


if __name__ == "__main__":
    main()
