"""Build the compact label files the map draws as text (web/geo/labels-*.json).

Source: Natural Earth 10m (public domain), the same family as the boundary
lines. Run once, commit the output; the site never fetches Natural Earth.

    python3 pipeline/build_labels.py <dir with the four .geojson files> web/geo

Needs: shapely. Inputs: ne_10m_populated_places_simple, ne_10m_admin_0_countries,
ne_10m_geography_marine_polys, ne_10m_lakes.
"""
import json, sys
from pathlib import Path
from shapely.geometry import shape

src, out = Path(sys.argv[1]), Path(sys.argv[2])
load = lambda n: json.load(open(src / f"{n}.geojson"))["features"]
pt = lambda x, y: {"type": "Point", "coordinates": [round(x, 3), round(y, 3)]}

def inside_point(geom):
    """A point that is really inside the (largest part of the) polygon."""
    g = shape(geom)
    if g.geom_type == "MultiPolygon":
        g = max(g.geoms, key=lambda p: p.area)
    p = g.representative_point()
    return p.x, p.y

def latin(*names):
    """First name the bundled glyph ranges (Latin, U+0000-01FF) can draw."""
    for n in names:
        if n and all(ord(c) < 512 for c in n): return n
    return None

def write(name, feats):
    fc = {"type": "FeatureCollection", "features": feats}
    (out / f"labels-{name}.json").write_text(json.dumps(fc, ensure_ascii=False, separators=(",", ":")))
    print(name, len(feats))

# Cities. mz = Natural Earth's own "show from this zoom" rank; pop for ordering.
cities = []
for f in load("ne_10m_populated_places_simple"):
    p = f["properties"]
    name = latin(p["name"], p["nameascii"])
    if p["min_zoom"] is None or p["min_zoom"] > 8 or not name:
        continue
    x, y = f["geometry"]["coordinates"]
    cities.append({"type": "Feature", "geometry": pt(x, y), "properties": {
        "n": name, "mz": p["min_zoom"], "pop": p["pop_max"] or 0,
        "cap": 1 if p["adm0cap"] else 0}})
write("cities", cities)

# Countries, drawn at low zoom only.
countries = []
for f in load("ne_10m_admin_0_countries"):
    p = f["properties"]
    name = latin(p.get("NAME_EN"), p.get("NAME"))
    if not name: continue
    if p.get("LABEL_X") is not None: x, y = p["LABEL_X"], p["LABEL_Y"]
    else: x, y = inside_point(f["geometry"])
    countries.append({"type": "Feature", "geometry": pt(x, y), "properties": {
        "n": name, "mz": p.get("MIN_LABEL") or 2, "mx": p.get("MAX_LABEL") or 8,
        "r": p.get("LABELRANK") or 5}})
write("countries", countries)

# Oceans, seas, gulfs, bays, straits (en + id names), and lakes.
water = []
for f in load("ne_10m_geography_marine_polys"):
    p = f["properties"]
    nm = latin(p["name_en"], p["name"])
    if not nm: continue  # a few unnamed "generic" polygons
    x, y = inside_point(f["geometry"])
    water.append({"type": "Feature", "geometry": pt(x, y), "properties": {
        "n": nm, "id": p.get("name_id"), "k": p["featurecla"],
        "mz": p["min_label"], "mx": p["max_label"]}})
for f in load("ne_10m_lakes"):
    p = f["properties"]
    # `name` keeps the proper noun ("Danau Toba"); name_en drops the "Lake"/"Laguna".
    nm = latin(p.get("name"), p.get("name_en"), p.get("name_abb"))
    if not nm or (p["min_label"] or 99) > 8: continue
    x, y = inside_point(f["geometry"])
    water.append({"type": "Feature", "geometry": pt(x, y), "properties": {
        "n": nm, "id": p.get("name_id"), "k": "lake", "mz": p["min_label"], "mx": 10}})
write("water", water)
