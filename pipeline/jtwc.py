"""Tropical systems from the Joint Typhoon Warning Center -> tropical/tropical.json.

JTWC products are US Government works and public. The browser never calls JTWC
(it blocks many automated clients and sends no CORS headers); this job reads
the text products and publishes one small JSON file next to the forecast data.

Read:
  jtwc.rss          which warnings and formation alerts are current (links)
  abpwweb.txt       ABPW10 outlook, Western + South Pacific: invests
  abioweb.txt       ABIO10 outlook, Indian Ocean: invests
  <bb><nn><yy>web.txt   each current warning (tropical cyclone, with forecast
                    track) or formation alert (TCFA, for an invest)

Written (tropical/tropical.json):
  {"updated", "attribution", "systems": [{
      "id": "95P", "kind": "invest" | "tc", "name", "class", "tcfa", "basin",
      "lat", "lon", "t", "wind_kt", "wind_kt_max", "mslp", "potential",
      "move": {"deg", "kt"}, "past": [[lat, lon, t, kt], ...],
      "forecast": [{"h", "t", "lat", "lon", "kt"}, ...], "url"}]}

Past positions are not in any JTWC text, so each run reads the previous file
and appends the new position, which gives a track that grows while a system
lives. A system that has not been seen for a few days is dropped with its track.

    python jtwc.py                          # publish to R2 (needs R2_* env vars)
    python jtwc.py --dry-run --dest ./out   # write to a folder instead
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE = "https://www.metoc.navy.mil/jtwc"
RSS = f"{BASE}/rss/jtwc.rss"
OUTLOOKS = [f"{BASE}/products/abpwweb.txt", f"{BASE}/products/abioweb.txt"]
KEY = "tropical/tropical.json"
ATTRIBUTION = "Tropical cyclone data: Joint Typhoon Warning Center (US Navy / US Air Force)"
UA = "klimatikal-tropical/1.0 (+https://klimatikal.com)"
KEEP_PAST = timedelta(days=5)
MAX_PAST = 60

BASINS = {"W": "Western North Pacific", "P": "South Pacific", "S": "South Indian Ocean",
          "B": "Bay of Bengal", "A": "Arabian Sea", "E": "Eastern Pacific",
          "C": "Central Pacific", "L": "Atlantic"}


# --- small helpers ---------------------------------------------------------

def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def latlon(lat: str, ns: str, lon: str, ew: str) -> tuple[float, float]:
    la = float(lat) * (-1 if ns == "S" else 1)
    lo = float(lon) * (-1 if ew == "W" else 1)
    return la, lo


def at_ddhhmm(dd: int, hh: int, mm: int, ref: datetime) -> datetime:
    """The datetime with this day/hour/minute closest to `ref`. JTWC stamps
    carry day and time only; the month is whichever fits."""
    best = None
    for dm in (-1, 0, 1):
        y, m = ref.year, ref.month + dm
        if m < 1: y, m = y - 1, 12
        if m > 12: y, m = y + 1, 1
        try:
            cand = datetime(y, m, dd, hh, mm, tzinfo=timezone.utc)
        except ValueError:
            continue
        if best is None or abs(cand - ref) < abs(best - ref):
            best = cand
    if best is None:
        raise ValueError(f"no date for day {dd}")
    return best


def iso(d: datetime) -> str:
    return d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")


def basin_of(sid: str) -> str:
    return BASINS.get(sid[-1], "")


def intensity_class(kt: float | None) -> str:
    """JTWC one-minute-wind classes."""
    if kt is None: return ""
    if kt >= 130: return "Super typhoon"
    if kt >= 64: return "Typhoon / hurricane"
    if kt >= 34: return "Tropical storm"
    return "Tropical depression"


# --- the outlooks (invests) -----------------------------------------------

_NEAR = re.compile(r"NEAR\s+(\d+(?:\.\d+)?)([NS])\s+(\d+(?:\.\d+)?)([EW])")


def parse_outlook(text: str, ref: datetime) -> list[dict]:
    """Every INVEST named in a Significant Tropical Weather Advisory."""
    flat = re.sub(r"\s+", " ", text.replace("\r", " "))
    # Issue time from the first line: "ABPW10 PGTW 150600".
    m = re.search(r"\b(?:ABPW10|ABIO10) PGTW (\d{2})(\d{2})(\d{2})", flat)
    issued = at_ddhhmm(int(m[1]), int(m[2]), int(m[3]), ref) if m else ref
    out = []
    # Each suspect area is one numbered paragraph: "(1) THE AREA OF CONVECTION
    # (INVEST 95P) ..." up to the next "(n)" or the next lettered section.
    parts = re.split(r"\s(?=\(\d+\)\s)|\s(?=[A-C]\.\s[A-Z ]+SUMMARY)", flat)
    for part in parts:
        iv = re.search(r"\(INVEST (\d{2}[A-Z])\)", part)
        if not iv:
            continue
        sid = iv[1]
        # "PREVIOUSLY LOCATED NEAR a IS NOW LOCATED NEAR b": the new position is
        # the last "NEAR" before the descriptive text starts.
        head = part[: part.find("APPROXIMATELY")] if "APPROXIMATELY" in part else part[:400]
        near = _NEAR.findall(head)
        if not near:
            continue
        lat, lon = latlon(*near[-1])
        w = re.search(r"WINDS ARE ESTIMATED AT (\d+)(?: TO (\d+))? KNOTS", part)
        p = re.search(r"SEA LEVEL PRESSURE IS ESTIMATED TO BE NEAR (\d+) MB", part)
        pot = re.search(r"WITHIN THE NEXT 24 HOURS (?:IS|REMAINS|HAS (?:INCREASED|DECREASED) TO)? ?(?:BEEN )?(LOW|MEDIUM|HIGH)", part)
        out.append({
            "id": sid, "kind": "invest", "name": f"INVEST {sid}", "class": "Suspect area",
            "tcfa": False, "basin": basin_of(sid), "lat": lat, "lon": lon, "t": iso(issued),
            "wind_kt": int(w[1]) if w else None,
            "wind_kt_max": int(w[2] or w[1]) if w else None,
            "mslp": int(p[1]) if p else None,
            "potential": pot[1].lower() if pot else None,
        })
    return out


# --- a formation alert (TCFA) ---------------------------------------------

def parse_tcfa(text: str, ref: datetime) -> dict | None:
    flat = re.sub(r"\s+", " ", text)
    if "FORMATION ALERT" not in flat:
        return None
    iv = re.search(r"\(INVEST (\d{2}[A-Z])\)", flat)
    if not iv:
        return None
    sid = iv[1]
    hdr = re.search(r"\bPGTW (\d{2})(\d{2})(\d{2})", flat)
    issued = at_ddhhmm(int(hdr[1]), int(hdr[2]), int(hdr[3]), ref) if hdr else ref
    c = re.search(r"CIRCULATION CENTER IS LOCATED NEAR (\d+(?:\.\d+)?)([NS]) (\d+(?:\.\d+)?)([EW])", flat)
    mv = re.search(r"MOVING ([A-Z\-]+) AT (\d+) KNOTS", flat)
    w = re.search(r"WINDS IN THE AREA ARE ESTIMATED TO BE (\d+)(?: TO (\d+))? KNOTS", flat)
    p = re.search(r"SEA LEVEL PRESSURE IS ESTIMATED TO BE NEAR (\d+) MB", flat)
    d: dict = {"id": sid, "tcfa": True, "t": iso(issued)}
    if c:
        d["lat"], d["lon"] = latlon(*c.groups())
    if w:
        d["wind_kt"], d["wind_kt_max"] = int(w[1]), int(w[2] or w[1])
    if p:
        d["mslp"] = int(p[1])
    if mv:
        d["move_text"] = f"{mv[1].lower()} at {int(mv[2])} kt"
    return d


# --- a warning (tropical cyclone with a forecast track) --------------------

_SUBJ = re.compile(
    r"(SUPER TYPHOON|TYPHOON|TROPICAL STORM|TROPICAL DEPRESSION|TROPICAL CYCLONE|"
    r"SUBTROPICAL STORM|HURRICANE|CYCLONE)\s+(\d{2}[A-Z])\s*(?:\(([A-Z0-9\- ]+)\))?\s+WARNING NR\s+(\d+)")


def parse_warning(text: str, ref: datetime) -> dict | None:
    flat = re.sub(r"[ \t]+", " ", text.replace("\r", ""))
    s = _SUBJ.search(flat)
    if not s:
        return None
    word, sid, name, nr = s.groups()
    hdr = re.search(r"\bPGTW (\d{2})(\d{2})(\d{2})", flat)
    issued = at_ddhhmm(int(hdr[1]), int(hdr[2]), int(hdr[3]), ref) if hdr else ref
    pos = re.search(r"WARNING POSITION:\s*(\d{2})(\d{2})(\d{2})Z\s*---\s*NEAR (\d+(?:\.\d+)?)([NS]) (\d+(?:\.\d+)?)([EW])", flat)
    if not pos:
        return None
    t0 = at_ddhhmm(int(pos[1]), int(pos[2]), int(pos[3]), issued)
    lat, lon = latlon(*pos.groups()[3:])
    mv = re.search(r"MOVEMENT PAST SIX HOURS - (\d+) DEGREES AT (\d+) KTS", flat)
    wnd = re.search(r"MAX SUSTAINED WINDS - (\d+) KT", flat)
    kt = int(wnd[1]) if wnd else None
    forecast = []
    for f in re.finditer(
            r"(\d+) HRS, VALID AT:\s*(\d{2})(\d{2})(\d{2})Z\s*---\s*(\d+(?:\.\d+)?)([NS]) (\d+(?:\.\d+)?)([EW])"
            r"\s*MAX SUSTAINED WINDS - (\d+) KT", flat):
        fla, flo = latlon(*f.groups()[4:8])
        forecast.append({"h": int(f[1]), "t": iso(at_ddhhmm(int(f[2]), int(f[3]), int(f[4]), t0)),
                         "lat": fla, "lon": flo, "kt": int(f[9])})
    return {
        "id": sid, "kind": "tc", "name": (name or "").strip().title() or sid,
        "class": word.title(), "tcfa": False, "basin": basin_of(sid),
        "lat": lat, "lon": lon, "t": iso(t0), "wind_kt": kt, "wind_kt_max": kt,
        "move": {"deg": int(mv[1]), "kt": int(mv[2])} if mv else None,
        "warning_nr": int(nr), "forecast": forecast,
    }


# --- gluing it together ----------------------------------------------------

def current_product_links(rss: str) -> list[str]:
    """Warning and TCFA texts linked from the feed; the two outlooks are read
    directly. Order is the feed's."""
    links = re.findall(r"href=['\"](https://[^'\"]+?web\.txt)['\"]", rss)
    return [u for u in dict.fromkeys(links) if "/abpw" not in u and "/abio" not in u]


SAME_SYSTEM_DEG = 4.0     # an invest this close to a warned cyclone of the same basin is its remnant


def absorb_invests(systems: dict[str, dict], texts: dict[str, str]) -> dict[str, str]:
    """Drop an invest once it has become a numbered cyclone, and say which.

    JTWC renumbers (INVEST 95P becomes 08P) and the outlook can keep listing the
    old area for a while, which would draw two symbols on one storm. An invest
    goes if its id is named in a warning's text, or if it sits within a few
    degrees of a warned cyclone of the same basin letter. Returns
    {cyclone id: invest id} so the cyclone can inherit the invest's track.
    """
    alias: dict[str, str] = {}
    tcs = [s for s in systems.values() if s["kind"] == "tc"]
    for iid in [i for i, s in systems.items() if s["kind"] == "invest"]:
        inv = systems[iid]
        for tc in tcs:
            named = re.search(rf"\b{re.escape(iid)}\b", texts.get(tc["id"], ""))
            near = (tc["id"][-1] == iid[-1]
                    and abs(tc["lat"] - inv["lat"]) <= SAME_SYSTEM_DEG
                    and abs(((tc["lon"] - inv["lon"] + 180) % 360) - 180) <= SAME_SYSTEM_DEG)
            if named or near:
                alias.setdefault(tc["id"], iid)
                del systems[iid]
                break
    return alias


def merge_history(systems: list[dict], previous: dict | None, now: datetime,
                  alias: dict[str, str] | None = None) -> list[dict]:
    """Attach `past` from the last published file, extended by the new position.
    A cyclone that was an invest picks up the invest's track."""
    old = {s["id"]: s for s in (previous or {}).get("systems", [])}
    for s in systems:
        prev = old.get(s["id"]) or old.get((alias or {}).get(s["id"], ""))
        past = [list(p) for p in (prev or {}).get("past", [])]
        # The previous file's own current position becomes part of the past.
        if prev and prev.get("t") and prev["t"] != s["t"] and "lat" in prev:
            past.append([prev["lat"], prev["lon"], prev["t"], prev.get("wind_kt")])
        seen, uniq = set(), []
        for p in past:
            if p[2] in seen:
                continue
            seen.add(p[2]); uniq.append(p)
        cutoff = iso(now - KEEP_PAST)
        s["past"] = [p for p in uniq if p[2] >= cutoff and p[2] < s["t"]][-MAX_PAST:]
    return systems


def build(now: datetime, previous: dict | None, getter=fetch) -> dict:
    rss = getter(RSS)
    systems: dict[str, dict] = {}
    texts: dict[str, str] = {}              # warning text by cyclone id
    for url in OUTLOOKS:
        for s in parse_outlook(getter(url), now):
            systems[s["id"]] = s
    for url in current_product_links(rss):
        try:
            text = getter(url)
        except Exception as err:                      # one bad link must not drop the rest
            print(f"skipped {url}: {err}", file=sys.stderr)
            continue
        w = parse_warning(text, now)
        if w:
            w["url"] = url
            texts[w["id"]] = text
            systems[w["id"]] = {**systems.get(w["id"], {}), **w}   # a warning outranks its old invest entry
            continue
        a = parse_tcfa(text, now)
        if a:
            if a["id"] in systems:
                # The outlook position is usually newer than the alert's; the
                # alert only adds its flag and link.
                systems[a["id"]].update({"tcfa": True, "url": url})
            else:
                base = {"id": a["id"], "kind": "invest", "name": f"INVEST {a['id']}",
                        "class": "Suspect area", "basin": basin_of(a["id"])}
                base.update({k: v for k, v in a.items() if v is not None})
                base["url"] = url
                systems[a["id"]] = base
    alias = absorb_invests(systems, texts)
    ordered = sorted(systems.values(), key=lambda s: (s["kind"] != "tc", s["id"]))
    ordered = [s for s in ordered if "lat" in s and "lon" in s]
    return {"updated": iso(now), "attribution": ATTRIBUTION,
            "systems": merge_history(ordered, previous, now, alias)}


# --- output ----------------------------------------------------------------

class Sink:
    def __init__(self, dest: str, dry_run: bool):
        self.dry_run, self.dest = dry_run, dest
        if not dry_run:
            import boto3
            from botocore.config import Config
            self.client = boto3.client(
                "s3", endpoint_url=f"https://{os.environ['R2_ACCOUNT_ID']}.r2.cloudflarestorage.com",
                aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
                aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
                config=Config(signature_version="s3v4", region_name="auto"))
            self.bucket = os.environ["R2_BUCKET"]

    def read(self, key: str) -> dict | None:
        if self.dry_run:
            p = Path(self.dest) / key
            return json.loads(p.read_text()) if p.exists() else None
        from botocore.exceptions import ClientError
        try:
            return json.loads(self.client.get_object(Bucket=self.bucket, Key=key)["Body"].read())
        except ClientError as err:
            if err.response.get("Error", {}).get("Code") in ("NoSuchKey", "404", "NotFound"):
                return None
            raise

    def write(self, key: str, body: bytes) -> None:
        if self.dry_run:
            p = Path(self.dest) / key
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(body)
            return
        self.client.put_object(Bucket=self.bucket, Key=key, Body=body,
                               ContentType="application/json", CacheControl="public, max-age=60")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--dest", default="./out")
    a = ap.parse_args()
    sink = Sink(a.dest, a.dry_run)
    now = datetime.now(timezone.utc)
    try:
        doc = build(now, sink.read(KEY))
    except Exception as err:
        # Leave the last good file in place rather than publish an empty one
        # because JTWC was briefly unreachable.
        print(f"JTWC read failed, keeping the previous file: {err}", file=sys.stderr)
        return 1
    sink.write(KEY, json.dumps(doc, separators=(",", ":")).encode())
    print(f"published {len(doc['systems'])} systems: " + ", ".join(s["id"] for s in doc["systems"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
