#!/usr/bin/env python3
"""
Build klimatikal.com/atlas-cuaca from atlas/phenomena/*.json.

    python3 atlas/build_atlas.py

One JSON file per phenomenon (see atlas/README.md for the fields). The page
is generated as plain static HTML so it is fast, works without JavaScript,
and can be read by search engines. Only the Python standard library is used.

What the build checks, because the atlas is a curated reference:
  - a photo must name its credit and licence, or the build stops;
  - a draft entry is shown with a visible "Draft" badge and a curator-notes
    box, and while ANY entry is a draft the page is marked noindex, so
    unreviewed content never gets into search results by accident;
  - a missing photo file or a missing field is reported, not hidden.

Locator maps are drawn from the Natural Earth coastlines already in
web/geo/ (public domain), simplified and clipped to Indonesia.
"""

from __future__ import annotations

import html
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PHENOMENA = ROOT / "atlas" / "phenomena"
WEB = ROOT / "web"
OUT = WEB / "atlas-cuaca"
GEO = WEB / "geo"

# Equirectangular frame over Indonesia. Near the equator that is a fair map,
# and it keeps the pin maths to two lines.
LON0, LON1 = 94.5, 141.5
LAT0, LAT1 = -11.5, 6.5
PPD = 20.0  # SVG units per degree
W, H = (LON1 - LON0) * PPD, (LAT1 - LAT0) * PPD

SCALES = {"local", "regional"}
DOCS = {"well", "poor"}
STATUSES = {"draft", "reviewed"}


# --------------------------------------------------------------------------
# locator map geometry
# --------------------------------------------------------------------------

def rdp(points, eps):
    """Iterative Ramer-Douglas-Peucker; points are (lon, lat)."""
    n = len(points)
    if n < 3:
        return points
    keep = [False] * n
    keep[0] = keep[-1] = True
    stack = [(0, n - 1)]
    while stack:
        a, b = stack.pop()
        if b <= a + 1:
            continue
        (ax, ay), (bx, by) = points[a], points[b]
        dx, dy = bx - ax, by - ay
        length = (dx * dx + dy * dy) ** 0.5
        best, best_i = -1.0, a
        for i in range(a + 1, b):
            px, py = points[i]
            if length == 0:
                d = ((px - ax) ** 2 + (py - ay) ** 2) ** 0.5
            else:
                d = abs(dx * (py - ay) - dy * (px - ax)) / length
            if d > best:
                best, best_i = d, i
        if best > eps:
            keep[best_i] = True
            stack.append((a, best_i))
            stack.append((best_i, b))
    return [p for p, k in zip(points, keep) if k]


def path_for(geojson_file: Path, eps: float, min_extent: float) -> str:
    """SVG path data for the lines of a geojson file inside the Indonesia box."""
    lines = json.loads(geojson_file.read_text())["geometry"]["coordinates"]
    pad = 1.0
    parts = []
    for line in lines:
        seg = []
        for lon, lat in line:
            if LON0 - pad <= lon <= LON1 + pad and LAT0 - pad <= lat <= LAT1 + pad:
                seg.append((lon, lat))
            else:
                if len(seg) > 1:
                    parts.append(seg)
                seg = []
        if len(seg) > 1:
            parts.append(seg)
    d = []
    for seg in parts:
        xs = [p[0] for p in seg]
        ys = [p[1] for p in seg]
        if max(max(xs) - min(xs), max(ys) - min(ys)) < min_extent:
            continue  # a speck of an islet: noise at this scale
        s = rdp(seg, eps)
        if len(s) < 2:
            continue
        pts = " L".join(f"{(lon - LON0) * PPD:.1f} {(LAT1 - lat) * PPD:.1f}" for lon, lat in s)
        d.append("M" + pts)
    return "".join(d)


def xy(lon: float, lat: float):
    return (lon - LON0) * PPD, (LAT1 - lat) * PPD


# --------------------------------------------------------------------------
# text helpers
# --------------------------------------------------------------------------

def esc(s) -> str:
    return html.escape(str(s), quote=True)


def bi(id_text, en_text) -> str:
    """A string in both languages; CSS shows the one the reader picked."""
    return f'<span lang="id">{esc(id_text)}</span><span lang="en">{esc(en_text)}</span>'


UI = {
    "title": ("Atlas Cuaca Indonesia", "Indonesian Weather Atlas"),
    "intro": (
        "Katalog fenomena cuaca dan iklim di Indonesia, dari yang terdokumentasi baik hingga yang "
        "masih jarang dicatat, baik lokal maupun regional. Setiap kartu memuat nama, penjelasan "
        "ilmiah, pengetahuan lokal, dan lokasi kejadiannya.",
        "A catalogue of weather and climate phenomena across Indonesia, from well documented to "
        "rarely recorded, local and regional. Each card gives the name, the scientific explanation, "
        "local knowledge and where it occurs.",
    ),
    "nav_map": ("Peta cuaca", "Weather map"),
    "nav_about": ("Tentang kami", "About us"),
    "nav_contact": ("Kontak", "Contact us"),
    "f_scale": ("Skala", "Scale"),
    "f_doc": ("Dokumentasi", "Documentation"),
    "all": ("Semua", "All"),
    "local": ("Lokal", "Local"),
    "regional": ("Regional", "Regional"),
    "well": ("Terdokumentasi baik", "Well documented"),
    "poor": ("Kurang terdokumentasi", "Poorly documented"),
    "search": ("Cari fenomena…", "Search phenomena…"),
    "shown": ("Menampilkan", "Showing"),
    "of": ("dari", "of"),
    "none": ("Tidak ada fenomena yang cocok.", "No phenomena match."),
    "map_title": ("Sebaran lokasi", "Where they occur"),
    "name_local": ("Nama lokal", "Local name"),
    "name_en": ("Nama Inggris", "English name"),
    "scientific": ("Penjelasan ilmiah", "Scientific description"),
    "note": ("Catatan", "Note"),
    "local_knowledge": ("Pengetahuan lokal", "Local knowledge"),
    "location": ("Lokasi", "Location"),
    "sources": ("Sumber", "Sources"),
    "view_map": ("Lihat di peta cuaca", "View on the weather map"),
    "draft": ("Draf — belum ditinjau", "Draft — not yet reviewed"),
    "photo_needed": ("Foto diperlukan", "Photo needed"),
    "pending": ("Belum diisi", "Not yet filled in"),
    "curator": ("Catatan kurator", "Curator notes"),
    "back": ("← Kembali ke peta cuaca", "← Back to the weather map"),
}


def t(key) -> str:
    return bi(*UI[key])


# --------------------------------------------------------------------------
# loading and validation
# --------------------------------------------------------------------------

def load_entries():
    entries, problems = [], []
    for path in sorted(PHENOMENA.glob("*.json")):
        try:
            e = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as err:
            problems.append(f"{path.name}: not valid JSON ({err})")
            continue
        where = path.name

        def need(cond, msg):
            if not cond:
                problems.append(f"{where}: {msg}")

        need(e.get("id") == path.stem, f"'id' must equal the file name ({path.stem})")
        need(e.get("status") in STATUSES, f"'status' must be one of {sorted(STATUSES)}")
        need(e.get("scale") in SCALES, f"'scale' must be one of {sorted(SCALES)}")
        need(e.get("documentation") in DOCS, f"'documentation' must be one of {sorted(DOCS)}")
        for f in ("name_id", "name_en"):
            need(isinstance(e.get(f), str) and e[f].strip(), f"'{f}' is required")
        sci = e.get("scientific") or {}
        need(sci.get("id") and sci.get("en"), "'scientific' needs both 'id' and 'en' text")
        place = e.get("place") or {}
        need(place.get("id") and place.get("en"), "'place' needs both 'id' and 'en'")
        lat, lon = e.get("lat"), e.get("lon")
        need(isinstance(lat, (int, float)) and LAT0 <= lat <= LAT1, f"'lat' must be a number in {LAT0}..{LAT1}")
        need(isinstance(lon, (int, float)) and LON0 <= lon <= LON1, f"'lon' must be a number in {LON0}..{LON1}")

        kl = e.get("local_knowledge")
        if kl is not None:
            need(kl.get("id") and kl.get("en"), "'local_knowledge' needs both 'id' and 'en', or null")
        cav = e.get("caveat")
        if cav is not None:
            need(cav.get("id") and cav.get("en"), "'caveat' needs both 'id' and 'en', or leave it out")

        photo = e.get("photo")
        if photo is not None:
            for f in ("file", "alt", "credit", "licence"):
                need(photo.get(f), f"photo needs '{f}' (credit and licence are mandatory)")
            if photo.get("file") and not (OUT / "photos" / photo["file"]).exists():
                problems.append(f"{where}: photo file web/atlas-cuaca/photos/{photo['file']} does not exist")
        entries.append(e)
    ids = [e.get("id") for e in entries]
    for dup in {i for i in ids if ids.count(i) > 1}:
        problems.append(f"duplicate id: {dup}")
    return entries, problems


# --------------------------------------------------------------------------
# rendering
# --------------------------------------------------------------------------

def pin(e, r=9, link=False):
    x, y = xy(e["lon"], e["lat"])
    title = f"<title>{esc(e['name_id'])}</title>"
    circle = (f'<circle class="pin-halo" cx="{x:.1f}" cy="{y:.1f}" r="{r * 2}"/>'
              f'<circle class="pin" cx="{x:.1f}" cy="{y:.1f}" r="{r}"/>')
    if link:
        return f'<a href="#{esc(e["id"])}" class="pin-link" data-id="{esc(e["id"])}">{title}{circle}</a>'
    return circle


def locator(e):
    return (f'<svg class="locator" viewBox="0 0 {W:.0f} {H:.0f}" role="img" '
            f'aria-label="{esc(e["name_id"])}">'
            f'<use href="#idn-land"/>{pin(e)}</svg>')


def card(e):
    draft = e["status"] == "draft"
    sci, kl, place = e["scientific"], e.get("local_knowledge"), e["place"]
    photo = e.get("photo")
    search = " ".join(str(x).lower() for x in (
        e["name_id"], e.get("name_local") or "", e["name_en"], place["id"], place["en"]))

    if photo:
        media = (f'<figure class="photo"><img src="photos/{esc(photo["file"])}" alt="{esc(photo["alt"])}" '
                 f'loading="lazy"><figcaption>{esc(photo["credit"])} · {esc(photo["licence"])}</figcaption></figure>')
    else:
        media = f'<div class="photo placeholder"><span>{t("photo_needed")}</span></div>'

    badges = [
        f'<span class="badge scale">{t(e["scale"])}</span>',
        f'<span class="badge doc {e["documentation"]}">{t(e["documentation"])}</span>',
    ]
    if draft:
        badges.append(f'<span class="badge draft">{t("draft")}</span>')

    names = [f'<h3>{esc(e["name_id"])}</h3>']
    if e.get("name_local"):
        names.append(f'<p class="alt"><small>{t("name_local")}</small> {esc(e["name_local"])}</p>')
    names.append(f'<p class="alt en-name"><small>{t("name_en")}</small> <i>{esc(e["name_en"])}</i></p>')

    if kl:
        local = f'<p>{bi(kl["id"], kl["en"])}</p>'
    else:
        local = f'<p class="empty">{t("pending")}</p>'

    sources = ""
    if e.get("sources"):
        items = []
        for s in e["sources"]:
            txt = esc(s["text"])
            items.append(f'<li><a href="{esc(s["url"])}">{txt}</a></li>' if s.get("url") else f"<li>{txt}</li>")
        sources = f'<h4>{t("sources")}</h4><ul class="sources">{"".join(items)}</ul>'
    elif draft:
        sources = f'<h4>{t("sources")}</h4><p class="empty">{t("pending")}</p>'

    curator = ""
    if draft and e.get("curator_notes"):
        notes = "".join(f"<li>{esc(n)}</li>" for n in e["curator_notes"])
        curator = f'<details class="curator"><summary>{t("curator")}</summary><ul>{notes}</ul></details>'

    # An optional note under the science text, for where sources disagree or
    # something is not settled. Public, so it must be written for readers.
    cav = e.get("caveat")
    caveat_html = (f'<p class="caveat"><b>{t("note")}</b> {bi(cav["id"], cav["en"])}</p>' if cav else "")

    map_href = f'/#layer=wind&step=0&at={e["lon"]:.2f},{e["lat"]:.2f},7'
    return f"""    <article class="card" id="{esc(e['id'])}" data-scale="{e['scale']}" data-doc="{e['documentation']}" data-search="{esc(search)}">
      {media}
      <div class="body">
        <div class="badges">{"".join(badges)}</div>
        {"".join(names)}
        <h4>{t("scientific")}</h4>
        <p>{bi(sci["id"], sci["en"])}</p>
        {caveat_html}
        <h4>{t("local_knowledge")}</h4>
        {local}
        <h4>{t("location")}</h4>
        <p class="place">{bi(place["id"], place["en"])} <span class="coords">({e["lat"]:.2f}°, {e["lon"]:.2f}°)</span></p>
        {locator(e)}
        <p><a class="maplink" href="{esc(map_href)}">{t("view_map")} →</a></p>
        {sources}
        {curator}
      </div>
    </article>"""


def chips(group, options):
    out = []
    for i, (value, key) in enumerate(options):
        pressed = "true" if i == 0 else "false"
        out.append(f'<button type="button" data-group="{group}" data-value="{value}" aria-pressed="{pressed}">{t(key)}</button>')
    return "".join(out)


def page(entries):
    land = path_for(GEO / "coast.json", eps=0.06, min_extent=0.15)
    border = path_for(GEO / "admin0.json", eps=0.06, min_extent=0.15)
    any_draft = any(e["status"] == "draft" for e in entries)
    robots = '<meta name="robots" content="noindex">\n' if any_draft else ""
    overview = "".join(pin(e, r=8, link=True) for e in entries)
    cards = "\n".join(card(e) for e in entries)
    n = len(entries)
    desc_id, desc_en = UI["intro"]

    return f"""<!doctype html>
<html lang="id">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Atlas Cuaca Indonesia · Klimatikal</title>
<meta name="description" content="{esc(desc_id)}">
{robots}<link rel="canonical" href="https://klimatikal.com/atlas-cuaca/">
<link rel="icon" href="/favicon.svg" type="image/svg+xml">
<link rel="icon" href="/favicon-32.png" sizes="32x32" type="image/png">
<link rel="icon" href="/favicon.ico" sizes="any">
<link rel="apple-touch-icon" href="/apple-touch-icon.png">
<meta name="theme-color" content="#0D0630">
<meta property="og:type" content="website">
<meta property="og:title" content="Atlas Cuaca Indonesia · Klimatikal">
<meta property="og:description" content="{esc(desc_id)}">
<meta property="og:url" content="https://klimatikal.com/atlas-cuaca/">
<meta property="og:image" content="https://klimatikal.com/brand/og-image.png">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta name="twitter:card" content="summary_large_image">
<link rel="stylesheet" href="/about-us/about.css">
<link rel="stylesheet" href="/atlas-cuaca/atlas.css">
<script>
/* Language is chosen before first paint so the page never flashes the wrong one. */
(function () {{
  var l = null;
  try {{ l = localStorage.getItem("kl-lang"); }} catch (e) {{}}
  if (l !== "id" && l !== "en") l = (navigator.language || "id").toLowerCase().indexOf("id") === 0 ? "id" : "en";
  var d = document.documentElement; d.setAttribute("data-lang", l); d.lang = l;
}})();
</script>
<script src="/atlas-cuaca/atlas.js" defer></script>
</head>
<body class="atlas-page">
<svg width="0" height="0" style="position:absolute" aria-hidden="true" focusable="false">
  <defs>
    <g id="idn-land">
      <path class="land-border" d="{border}"/>
      <path class="land" d="{land}"/>
    </g>
  </defs>
</svg>

<header class="site-header">
  <a class="logo" href="/" aria-label="Klimatikal home">
    <picture>
      <source media="(max-width: 600px)" srcset="/brand/klimatikal-mark-on-dark.svg">
      <img src="/brand/klimatikal-lockup-on-dark.svg" alt="Klimatikal" class="logo-img">
    </picture>
  </a>
  <nav aria-label="Main">
    <a href="/">{t("nav_map")}</a>
    <a href="/about-us/">{t("nav_about")}</a>
    <a href="/contact-us/">{t("nav_contact")}</a>
    <span class="lang" role="group" aria-label="Language">
      <button type="button" data-set-lang="id" aria-pressed="true">ID</button><button type="button" data-set-lang="en" aria-pressed="false">EN</button>
    </span>
  </nav>
</header>

<main class="atlas">
  <p class="eyebrow">Klimatikal</p>
  <h1>{t("title")}</h1>
  <p class="lede">{t("intro")}</p>

  <section class="overview" aria-label="{esc(UI["map_title"][0])}">
    <svg class="locator wide" viewBox="0 0 {W:.0f} {H:.0f}" role="group" aria-label="{esc(UI["map_title"][0])}">
      <use href="#idn-land"/>{overview}
    </svg>
  </section>

  <div class="controls">
    <div class="group"><span class="glabel">{t("f_scale")}</span>{chips("scale", [("all", "all"), ("local", "local"), ("regional", "regional")])}</div>
    <div class="group"><span class="glabel">{t("f_doc")}</span>{chips("doc", [("all", "all"), ("well", "well"), ("poor", "poor")])}</div>
    <input id="q" type="search" autocomplete="off" placeholder="{esc(UI["search"][0])}" data-ph-id="{esc(UI["search"][0])}" data-ph-en="{esc(UI["search"][1])}" aria-label="{esc(UI["search"][0])}">
  </div>
  <p class="count" aria-live="polite">{bi("Menampilkan", "Showing")} <b data-shown>{n}</b> {bi("dari", "of")} <b data-total>{n}</b></p>

  <div class="grid">
{cards}
  </div>
  <p class="none" hidden>{t("none")}</p>
</main>

<footer class="site-footer">
  <a href="/">{t("back")}</a>
  <span>Klimatikal · Climate risk strategy</span>
</footer>
</body>
</html>
"""


def main():
    entries, problems = load_entries()
    if problems:
        print("Cannot build:", file=sys.stderr)
        for p in problems:
            print("  -", p, file=sys.stderr)
        sys.exit(1)
    if not entries:
        print("No phenomena found in", PHENOMENA, file=sys.stderr)
        sys.exit(1)
    entries.sort(key=lambda e: e["name_id"].lower())
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "index.html").write_text(page(entries), encoding="utf-8")
    drafts = [e["id"] for e in entries if e["status"] == "draft"]
    print(f"built {OUT / 'index.html'}  ({len(entries)} phenomena)")
    if drafts:
        print(f"  {len(drafts)} draft: {', '.join(drafts)}")
        print("  page is marked noindex until every entry is 'reviewed'")
    for e in entries:
        missing = [n for n, v in (("photo", e.get("photo")), ("local_knowledge", e.get("local_knowledge")),
                                  ("sources", e.get("sources"))) if not v]
        if missing:
            print(f"  note: {e['id']} has no {', '.join(missing)}")


if __name__ == "__main__":
    main()
