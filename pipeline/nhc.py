"""Atlantic and eastern Pacific systems from the National Hurricane Center -> tropical/nhc.json.

NHC products are US Government works and public. Read:
  CurrentStorms.json     the storms with a current advisory: name, class (TD, TS,
                         HU, STS, PTC = post-tropical cyclone or remnants, ...),
                         position, wind, pressure, movement, links
  <forecast advisory>    the text bulletin linked from it, for the forecast
                         positions ("FORECAST VALID 17/1200Z 47.2N 63.2W")

A post-tropical cyclone is the stage a hurricane reaches when it becomes an
extratropical low: NHC keeps issuing advisories on it while it still matters,
often as a strong storm off Canada or Europe, so it is the link between the
tropical layer and the Lows layer. Written in the same shape as jtwc.py's
tropical.json (the page merges the two files), with "src": "NHC" and, on a
post-tropical system, "pt": true.

    python nhc.py                          # publish to R2 (needs R2_* env vars)
    python nhc.py --dry-run --dest ./out   # write to a folder instead
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
from datetime import datetime, timedelta, timezone

import jtwc
from jtwc import iso, merge_history

URL = "https://www.nhc.noaa.gov/CurrentStorms.json"
KEY = "tropical/nhc.json"
ATTRIBUTION = "Tropical cyclone data: US National Hurricane Center (NOAA / NWS)"
MPH_KT = 0.868976

CLASSES = {"TD": "Tropical depression", "STD": "Subtropical depression", "TS": "Tropical storm",
           "HU": "Hurricane", "STS": "Subtropical storm", "TY": "Typhoon",
           "PTC": "Post-tropical cyclone", "PC": "Potential tropical cyclone"}
BASINS = {"al": "Atlantic", "ep": "Eastern Pacific", "cp": "Central Pacific"}


def _num(d: dict, *keys):
    for k in keys:
        if isinstance(d.get(k), (int, float)):
            return d[k]
    return None


def _when(s: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)
    except (AttributeError, ValueError):
        return None


def bulletin_text(page: str) -> str:
    """The advisory text out of NHC's .shtml wrapper (it sits in a <pre>)."""
    m = re.search(r"<pre[^>]*>(.*?)</pre>", page, re.S)
    return html.unescape(re.sub(r"<[^>]+>", "", m.group(1))) if m else page


_CENTRE = re.compile(r"CENTER LOCATED NEAR\s+(\d+(?:\.\d+)?)([NS])\s+(\d+(?:\.\d+)?)([EW])\s+AT\s+(\d\d)/(\d\d)(\d\d)Z")
_FCST = re.compile(r"FORECAST VALID\s+(\d\d)/(\d\d)(\d\d)Z\s+(\d+(?:\.\d+)?)([NS])\s+(\d+(?:\.\d+)?)([EW])([^\n]*)\n\s*MAX WIND\s+(\d+)\s*KT")


def parse_forecast(text: str, ref: datetime) -> list[dict]:
    """Forecast positions from a forecast/advisory bulletin; [] when it has none
    (the last line is often 'FORECAST VALID ...DISSIPATED', which is skipped)."""
    c = _CENTRE.search(text)
    t0 = jtwc.at_ddhhmm(int(c.group(5)), int(c.group(6)), int(c.group(7)), ref) if c else ref
    out = []
    for m in _FCST.finditer(text):
        t = jtwc.at_ddhhmm(int(m.group(1)), int(m.group(2)), int(m.group(3)), t0)
        lat, lon = jtwc.latlon(m.group(4), m.group(5), m.group(6), m.group(7))
        out.append({"h": round((t - t0).total_seconds() / 3600), "t": iso(t), "lat": lat, "lon": lon,
                    "kt": int(m.group(9)), **({"xt": True} if "EXTRATROP" in m.group(8) or "POST-TROP" in m.group(8) else {})})
    return out


def parse_storm(s: dict) -> dict | None:
    lat = _num(s, "latitude_numeric", "latitudeNumeric")
    lon = _num(s, "longitude_numeric", "longitudeNumeric")
    t = _when(s.get("lastUpdate"))
    sid = str(s.get("id", ""))
    if lat is None or lon is None or t is None or len(sid) < 4:
        return None
    cls = str(s.get("classification", ""))
    kt = _num(s, "intensity")
    out = {"id": f"{sid[:4].upper()}", "kind": "tc", "name": str(s.get("name", sid)).title(),
           "class": CLASSES.get(cls, cls), "tcfa": False, "basin": BASINS.get(sid[:2].lower(), ""),
           "lat": lat, "lon": lon, "t": iso(t), "src": "NHC"}
    if kt is not None:
        out["wind_kt"] = out["wind_kt_max"] = int(kt)
    if _num(s, "pressure"):
        out["mslp"] = int(_num(s, "pressure"))
    d, v = _num(s, "movementDir"), _num(s, "movementSpeed")
    if d is not None and v is not None:
        out["move"] = {"deg": int(d), "kt": round(v * MPH_KT)}
    if cls == "PTC":
        out["pt"] = True
    adv = s.get("publicAdvisory") or {}
    if adv.get("url"):
        out["url"] = adv["url"]
    return out


def build(now: datetime, previous: dict | None, getter=jtwc.fetch) -> dict:
    systems = []
    for s in json.loads(getter(URL)).get("activeStorms", []):
        p = parse_storm(s)
        if not p:
            continue
        fa = (s.get("forecastAdvisory") or {}).get("url")
        if fa:
            try:
                p["forecast"] = parse_forecast(bulletin_text(getter(fa)), now)
            except Exception as err:                    # a missing forecast must not drop the storm
                print(f"no forecast for {p['id']}: {err}", file=sys.stderr)
        systems.append(p)
    return {"updated": iso(now), "attribution": ATTRIBUTION, "systems": merge_history(systems, previous, now)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--dest", default="./out")
    a = ap.parse_args()
    sink = jtwc.Sink(a.dest, a.dry_run)
    now = datetime.now(timezone.utc)
    try:
        doc = build(now, sink.read(KEY))
    except Exception as err:
        print(f"NHC read failed, keeping the previous file: {err}", file=sys.stderr)
        return 1
    sink.write(KEY, json.dumps(doc, separators=(",", ":")).encode())
    print(f"published {len(doc['systems'])} systems: " + ", ".join(s["id"] for s in doc["systems"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
