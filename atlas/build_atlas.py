#!/usr/bin/env python3
"""
Build klimatikal.com/atlas-cuaca from atlas/phenomena/*.json.

    python3 atlas/build_atlas.py                 # what gets deployed
    python3 atlas/build_atlas.py --with-drafts   # preview: drafts shown in the index too

Two kinds of page come out of it, all plain static HTML (fast, readable
without JavaScript, indexable). Only the Python standard library is used.

  /atlas-cuaca/                   the index: compact cards you can filter and
                                  search, plus a map of every pin
  /atlas-cuaca/<id>/              one full page per phenomenon

What the build enforces, because the atlas is a curated reference:
  - a photo must name its credit and licence, or the build stops;
  - a DRAFT entry gets its page built (so you can preview it at its URL) but
    that page is marked noindex and the entry is left out of the public index
    and map; only `reviewed` entries are listed. One draft therefore never
    hides the rest of the atlas;
  - a missing photo file or a missing field is reported, not hidden.

Locator maps are drawn from the Natural Earth coastlines already in web/geo/
(public domain), simplified and clipped to Indonesia.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PHENOMENA = ROOT / "atlas" / "phenomena"
WEB = ROOT / "web"
OUT = WEB / "atlas-cuaca"
GEO = WEB / "geo"
DIAGRAMS = ROOT / "atlas" / "diagrams"

SITE = "https://klimatikal.com"
BASE = "/atlas-cuaca/"

# Equirectangular frame over Indonesia. Near the equator that is a fair map,
# and it keeps the pin maths to two lines.
LON0, LON1 = 94.5, 141.5
LAT0, LAT1 = -11.5, 6.5
PPD = 20.0  # SVG units per degree
W, H = (LON1 - LON0) * PPD, (LAT1 - LAT0) * PPD

SCALES = {"local", "regional"}
DOCS = {"well", "poor"}
STATUSES = {"draft", "reviewed"}

LAND = BORDER = ""  # filled in by main()


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
        "masih jarang dicatat, baik lokal maupun regional. Setiap fenomena punya halamannya sendiri: "
        "nama, penjelasan ilmiah, pengetahuan lokal, dan lokasi kejadiannya.",
        "A catalogue of weather and climate phenomena across Indonesia, from well documented to "
        "rarely recorded, local and regional. Each phenomenon has its own page: the name, the "
        "scientific explanation, local knowledge and where it occurs.",
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
    "none": ("Tidak ada fenomena yang cocok.", "No phenomena match."),
    "empty_atlas": ("Belum ada fenomena yang diterbitkan.", "No phenomena published yet."),
    "map_title": ("Sebaran lokasi", "Where they occur"),
    "name_local": ("Nama lokal", "Local name"),
    "name_en": ("Nama Inggris", "English name"),
    "scientific": ("Penjelasan ilmiah", "Scientific description"),
    "note": ("Catatan", "Note"),
    "local_knowledge": ("Pengetahuan lokal", "Local knowledge"),
    "location": ("Lokasi", "Location"),
    "sources": ("Sumber", "Sources"),
    "view_map": ("Lihat di peta cuaca", "View on the weather map"),
    "read_more": ("Baca selengkapnya", "Read more"),
    "all_entries": ("← Semua fenomena", "← All phenomena"),
    "draft": ("Draf — belum ditinjau", "Draft — not yet reviewed"),
    "photo_needed": ("Foto diperlukan", "Photo needed"),
    "pending": ("Belum diisi", "Not yet filled in"),
    # What the public sees once an entry is reviewed and still has no local
    # knowledge: the gap is stated as a fact about the record, not as a to-do.
    "no_local": ("Belum ada pengetahuan lokal yang terdokumentasi.", "No local knowledge documented yet."),
    "curator": ("Catatan kurator", "Curator notes"),
    "back": ("← Kembali ke peta cuaca", "← Back to the weather map"),
    # the foehn diagram: wording that is the same for every foehn entry
    "d_windward": ("Sisi hadap angin", "Windward side"),
    "d_windward_sub": ("udara naik & mendingin; awan, hujan", "air rises & cools; cloud, rain"),
    "d_lee": ("Sisi lee", "Lee side"),
    "d_lee_sub": ("udara turun, hangat & kering", "air sinks, warms & dries"),
    "d_key_up": ("Udara naik: lebih sejuk & lembap", "Rising air: cooler & moister"),
    "d_key_down": ("Udara turun: lebih hangat & kering", "Sinking air: warmer & drier"),
    "d_key_cloud": ("Awan", "Cloud"),
    "d_key_rain": ("Hujan", "Rain"),
    "d_hint": ("Geser ke samping untuk melihat seluruh penampang →", "Swipe sideways to see the whole cross-section →"),
    "d_region": ("Penampang medan", "Terrain cross-section"),
}


def t(key) -> str:
    return bi(*UI[key])


def summary(e, lang: str) -> str:
    """The short text for an index card: an explicit 'summary' if given,
    otherwise the first sentence of the scientific description."""
    explicit = (e.get("summary") or {}).get(lang)
    if explicit:
        return explicit
    text = e["scientific"][lang]
    m = re.match(r"(.+?[.!?])(\s|$)", text)
    first = m.group(1) if m else text
    return first if len(first) <= 260 else first[:257].rsplit(" ", 1)[0] + "…"


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
        need(bool(re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", str(e.get("id", "")))),
             "'id' must be a lowercase slug (letters, digits, hyphens): it becomes the page address")
        need(e.get("id") != "photos", "'photos' is reserved")
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

        for field in ("local_knowledge", "caveat", "summary"):
            val = e.get(field)
            if val is not None:
                need(val.get("id") and val.get("en"), f"'{field}' needs both 'id' and 'en', or leave it out")

        diag = e.get("diagram")
        if diag is not None:
            need(diag.get("type") == "foehn", "'diagram.type' must be 'foehn'")
            tfile = DIAGRAMS / f"{diag.get('transect', '')}.json"
            need(tfile.exists(), f"diagram transect file atlas/diagrams/{diag.get('transect')}.json does not exist")
            vk = diag.get("view_km")
            need(isinstance(vk, list) and len(vk) == 2 and vk[0] < vk[1], "'diagram.view_km' must be [from_km, to_km]")
            for key in ("sea_left", "sea_right", "range", "plain", "site"):
                lab = (diag.get("labels") or {}).get(key) or {}
                need(lab.get("id") and lab.get("en"), f"'diagram.labels.{key}' needs both 'id' and 'en'")
            need(isinstance((diag.get("labels") or {}).get("site", {}).get("km"), (int, float)),
                 "'diagram.labels.site.km' must be a number (where the entry's place lies on the line)")

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
# shared page furniture
# --------------------------------------------------------------------------

LANG_SCRIPT = """<script>
/* Language is chosen before first paint so the page never flashes the wrong one. */
(function () {
  var l = null;
  try { l = localStorage.getItem("kl-lang"); } catch (e) {}
  if (l !== "id" && l !== "en") l = (navigator.language || "id").toLowerCase().indexOf("id") === 0 ? "id" : "en";
  var d = document.documentElement; d.setAttribute("data-lang", l); d.lang = l;
})();
</script>
<script src="/atlas-cuaca/atlas.js" defer></script>"""


def head(title, desc, canonical, noindex, og_type="website", extra=""):
    robots = '<meta name="robots" content="noindex">\n' if noindex else ""
    return f"""<!doctype html>
<html lang="id">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
<meta name="description" content="{esc(desc)}">
{robots}<link rel="canonical" href="{esc(canonical)}">
<link rel="icon" href="/favicon.svg" type="image/svg+xml">
<link rel="icon" href="/favicon-32.png" sizes="32x32" type="image/png">
<link rel="icon" href="/favicon.ico" sizes="any">
<link rel="apple-touch-icon" href="/apple-touch-icon.png">
<meta name="theme-color" content="#0D0630">
<meta property="og:type" content="{og_type}">
<meta property="og:title" content="{esc(title)}">
<meta property="og:description" content="{esc(desc)}">
<meta property="og:url" content="{esc(canonical)}">
<meta property="og:image" content="{SITE}/brand/og-image.png">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta name="twitter:card" content="summary_large_image">
<link rel="stylesheet" href="/about-us/about.css">
<link rel="stylesheet" href="/atlas-cuaca/atlas.css">
{extra}{LANG_SCRIPT}
</head>
"""


def land_defs():
    return f"""<svg width="0" height="0" style="position:absolute" aria-hidden="true" focusable="false">
  <defs>
    <g id="idn-land">
      <path class="land-border" d="{BORDER}"/>
      <path class="land" d="{LAND}"/>
    </g>
  </defs>
</svg>"""


def site_header(here: str):
    """here: 'index' for the atlas page itself, 'entry' for a page inside it."""
    current = ' aria-current="page"' if here == "index" else ' aria-current="true"'
    return f"""<header class="site-header">
  <a class="logo" href="/" aria-label="Klimatikal home">
    <picture>
      <source media="(max-width: 600px)" srcset="/brand/klimatikal-mark-on-dark.svg">
      <img src="/brand/klimatikal-lockup-on-dark.svg" alt="Klimatikal" class="logo-img">
    </picture>
  </a>
  <nav aria-label="Main">
    <a href="/">{t("nav_map")}</a>
    <a href="{BASE}"{current}>Atlas Cuaca</a>
    <a href="/about-us/">{t("nav_about")}</a>
    <a href="/contact-us/">{t("nav_contact")}</a>
    <span class="lang" role="group" aria-label="Language">
      <button type="button" data-set-lang="id" aria-pressed="true">ID</button><button type="button" data-set-lang="en" aria-pressed="false">EN</button>
    </span>
  </nav>
</header>"""


def site_footer():
    return f"""<footer class="site-footer">
  <a href="/">{t("back")}</a>
  <span>Klimatikal · Climate risk strategy</span>
</footer>"""


# --------------------------------------------------------------------------
# pieces shared by the index card and the entry page
# --------------------------------------------------------------------------

def entry_url(e):
    return f"{BASE}{e['id']}/"


def pin(e, r=9, link=False):
    x, y = xy(e["lon"], e["lat"])
    title = f"<title>{esc(e['name_id'])}</title>"
    circle = (f'<circle class="pin-halo" cx="{x:.1f}" cy="{y:.1f}" r="{r * 2}"/>'
              f'<circle class="pin" cx="{x:.1f}" cy="{y:.1f}" r="{r}"/>')
    if link:
        return f'<a href="{esc(entry_url(e))}" class="pin-link" data-id="{esc(e["id"])}">{title}{circle}</a>'
    return circle


def locator(e):
    return (f'<svg class="locator" viewBox="0 0 {W:.0f} {H:.0f}" role="img" '
            f'aria-label="{esc(e["name_id"])}">'
            f'<use href="#idn-land"/>{pin(e)}</svg>')


def badges(e):
    out = [
        f'<span class="badge scale">{t(e["scale"])}</span>',
        f'<span class="badge doc {e["documentation"]}">{t(e["documentation"])}</span>',
    ]
    if e["status"] == "draft":
        out.append(f'<span class="badge draft">{t("draft")}</span>')
    return f'<div class="badges">{"".join(out)}</div>'


def alt_names(e):
    out = []
    if e.get("name_local"):
        out.append(f'<p class="alt"><small>{t("name_local")}</small> {esc(e["name_local"])}</p>')
    out.append(f'<p class="alt"><small>{t("name_en")}</small> <i>{esc(e["name_en"])}</i></p>')
    return "".join(out)


def photo_block(e, thumb=False):
    photo = e.get("photo")
    draft = e["status"] == "draft"
    if photo:
        cap = "" if thumb else f'<figcaption>{esc(photo["credit"])} · {esc(photo["licence"])}</figcaption>'
        return (f'<figure class="photo"><img src="{BASE}photos/{esc(photo["file"])}" alt="{esc(photo["alt"])}" '
                f'loading="lazy">{cap}</figure>')
    if draft and not thumb:
        return f'<div class="photo placeholder"><span>{t("photo_needed")}</span></div>'
    return ""  # a reviewed entry without a photo simply has none


# --------------------------------------------------------------------------
# the index: compact cards
# --------------------------------------------------------------------------

def card(e):
    place = e["place"]
    search = " ".join(str(x).lower() for x in (
        e["name_id"], e.get("name_local") or "", e["name_en"], place["id"], place["en"]))
    return f"""    <article class="card" id="{esc(e['id'])}" data-scale="{e['scale']}" data-doc="{e['documentation']}" data-search="{esc(search)}">
      {photo_block(e, thumb=True)}
      <div class="body">
        {badges(e)}
        <h3><a class="card-link" href="{esc(entry_url(e))}">{esc(e["name_id"])}</a></h3>
        {alt_names(e)}
        <p class="summary">{bi(summary(e, "id"), summary(e, "en"))}</p>
        <p class="place">{bi(place["id"], place["en"])}</p>
        <p class="more">{t("read_more")} →</p>
      </div>
    </article>"""


def chips(group, options):
    out = []
    for i, (value, key) in enumerate(options):
        pressed = "true" if i == 0 else "false"
        out.append(f'<button type="button" data-group="{group}" data-value="{value}" aria-pressed="{pressed}">{t(key)}</button>')
    return "".join(out)


def index_page(listed, with_drafts):
    n = len(listed)
    noindex = with_drafts or not any(e["status"] == "reviewed" for e in listed)
    overview = "".join(pin(e, r=8, link=True) for e in listed)
    cards = "\n".join(card(e) for e in listed)
    desc_id, _ = UI["intro"]
    empty = f'<p class="none">{t("empty_atlas")}</p>' if n == 0 else ""
    return head("Atlas Cuaca Indonesia · Klimatikal", desc_id, f"{SITE}{BASE}", noindex) + f"""<body class="atlas-page" data-page="index">
{land_defs()}
{site_header("index")}

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
  {empty}<p class="none" hidden>{t("none")}</p>
</main>

{site_footer()}
</body>
</html>
"""


# --------------------------------------------------------------------------
# one page per phenomenon
# --------------------------------------------------------------------------

# --------------------------------------------------------------------------
# the foehn diagram: real terrain, illustrative airflow
# --------------------------------------------------------------------------

TEAL, LIME, MID = (139, 190, 178), (230, 249, 175), (184, 220, 176)  # brand teal / lime / a blend


def _lerp(a, b, t):
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))


def _hex(c):
    return "#%02x%02x%02x" % tuple(c)


def _smooth(values, half):
    out = []
    for i in range(len(values)):
        seg = values[max(0, i - half): i + half + 1]
        out.append(sum(seg) / len(seg))
    return out


def _fmt_m(m, lang):
    s = f"{int(round(m)):,}"
    return s.replace(",", ".") if lang == "id" else s


def _fmt_coord(lat, lon, lang):
    ns, ew = ("LU" if lat >= 0 else "LS", "BT" if lon >= 0 else "BB") if lang == "id" else \
             ("N" if lat >= 0 else "S", "E" if lon >= 0 else "W")
    f = (lambda v: f"{abs(v):.2f}".replace(".", ",")) if lang == "id" else (lambda v: f"{abs(v):.2f}")
    return f"{f(lat)}°{ns} {f(lon)}°{ew}"


def foehn_figure(e):
    """A cross-section built from a real elevation profile (atlas/diagrams/),
    with the airflow, cloud and rain drawn over it as an illustration of the
    mechanism, never as a measurement. Labels are HTML laid over the SVG so
    they stay readable at phone widths, where scaled SVG text would not."""
    cfg = e["diagram"]
    labels = cfg["labels"]
    tr = json.loads((DIAGRAMS / f"{cfg['transect']}.json").read_text())
    v0, v1 = cfg["view_km"]
    step = tr["step_km"]
    pairs = [(d, (m if m is not None else 0.0)) for d, m in zip(tr["distance_km"], tr["elevation_m"]) if v0 <= d <= v1]
    xs, el = [p[0] for p in pairs], [p[1] for p in pairs]
    n = len(xs)

    VW, VH, Y0, YMAX = 1000.0, 330.0, 300.0, 2800.0
    sc = (Y0 - 14) / YMAX                                   # SVG units per metre of height
    ve = sc / (VW / ((v1 - v0) * 1000.0))                   # vertical exaggeration
    X = lambda km: (km - v0) / (v1 - v0) * VW
    Y = lambda m: Y0 - m * sc
    el_at = lambda km: el[min(range(n), key=lambda i: abs(xs[i] - km))]

    crest_i = max(range(n), key=lambda i: el[i])
    crest_km, crest_m = xs[crest_i], el[crest_i]
    lee_end = next((xs[i] for i in range(crest_i, n) if el[i] <= 150), crest_km + 40)
    sm = _smooth(el, max(1, int(round(7 / step))))
    sm_at = lambda km: sm[min(range(n), key=lambda i: abs(xs[i] - km))]

    # colour of the air along the line: starts mild, is coolest at the crest,
    # and ends warmer than it began on the lee side
    stops = [(v0, MID), (crest_km, TEAL), (lee_end, LIME), (v1, LIME)]

    def air(km):
        for (ka, ca), (kb, cb) in zip(stops, stops[1:]):
            if ka <= km <= kb:
                return _lerp(ca, cb, 0 if kb == ka else (km - ka) / (kb - ka))
        return stops[-1][1] if km > stops[-1][0] else stops[0][1]

    gid = f"air-{e['id']}"
    grad = "".join(f'<stop offset="{(k - v0) / (v1 - v0) * 100:.1f}%" stop-color="{_hex(c)}"/>' for k, c in stops)

    # terrain: one polygon per stretch of land, so the sea stays open water
    segs, cur = [], []
    for x, m in zip(xs, el):
        if m > 1.0:
            cur.append((x, m))
        elif cur:
            segs.append(cur)
            cur = []
    if cur:
        segs.append(cur)
    # A flat coastal plain dips to 0-1 m between wet patches, which would split it
    # into pieces with gaps; bridge gaps of 4 km or less so it draws as one coast.
    merged = []
    for sg in segs:
        if merged and sg[0][0] - merged[-1][-1][0] <= 4:
            gap = [(x, m) for x, m in zip(xs, el) if merged[-1][-1][0] < x < sg[0][0]]
            merged[-1] = merged[-1] + gap + sg
        else:
            merged.append(sg)
    # SRTM also leaves 1-3 m of noise over open water: a stretch under 6 km that
    # never rises above 10 m is that noise, not a coast.
    segs = [sg for sg in merged if (sg[-1][0] - sg[0][0]) >= 6 or max(m for _, m in sg) > 10]
    land = ridge = ""
    for seg in segs:
        top = " L".join(f"{X(x):.1f} {Y(m):.1f}" for x, m in seg)
        land += f'<path class="d-land" d="M{X(seg[0][0]):.1f} {VH:.0f} L{top} L{X(seg[-1][0]):.1f} {VH:.0f} Z"/>'
        ridge += f'<path class="d-ridge" d="M{top}"/>'

    grid = "".join(f'<line class="d-grid" x1="0" x2="{VW:.0f}" y1="{Y(m):.1f}" y2="{Y(m):.1f}"/>' for m in (1000, 2000))

    # airflow: smoothed terrain plus clearance, so each line rides over the range
    flows, chevrons = "", ""
    for clr in (260, 640, 1020):
        hs = [max(s + clr, m + 140) for s, m in zip(sm, el)]
        pts = [(X(x), Y(h)) for x, h in zip(xs, hs)]
        flows += f'<path class="d-air" stroke="url(#{gid})" d="M{" L".join(f"{px:.1f} {py:.1f}" for px, py in pts)}"/>'
        for km in [v0 + 16 + 30 * k for k in range(int((v1 - v0 - 20) / 30))]:
            i = min(range(n), key=lambda j: abs(xs[j] - km))
            (ax, ay), (bx, by) = pts[max(0, i - 2)], pts[min(n - 1, i + 2)]
            L = ((bx - ax) ** 2 + (by - ay) ** 2) ** 0.5 or 1.0
            ux, uy = (bx - ax) / L, (by - ay) / L
            nx, ny = -uy, ux
            px, py = pts[i]
            tri = [(px + 11 * ux, py + 11 * uy), (px - 8 * ux + 7 * nx, py - 8 * uy + 7 * ny),
                   (px - 8 * ux - 7 * nx, py - 8 * uy - 7 * ny)]
            chevrons += (f'<polygon points="{" ".join(f"{a:.1f},{b:.1f}" for a, b in tri)}" '
                         f'fill="{_hex(air(km))}"/>')

    # cloud and rain over the windward slope, up to the crest
    rnd = lambda i: ((i * 7919) % 101) / 100.0
    first_high = next((x for x, m in zip(xs, el) if m >= 300), crest_km - 40)
    cloud, rain, k = "", "", 0
    km = first_high
    while km < crest_km - 1:
        base = sm_at(km) + 360
        for j in range(2):
            cx = X(km) + (rnd(k * 3 + j) - 0.5) * 18
            cy = Y(base + 110 + 230 * rnd(k * 5 + j + 2))
            cloud += f'<circle class="d-cloud" cx="{cx:.1f}" cy="{cy:.1f}" r="{11 + 10 * rnd(k + j * 7):.1f}"/>'
        top_y, bot_y = Y(base + 40), Y(el_at(km))
        # no rain into a deep interior valley: it falls on the ridges and slopes
        in_valley = el_at(km) < 0.5 * sm_at(km)
        if bot_y - top_y > 10 and not in_valley:
            rain += (f'<line class="d-rain" x1="{X(km):.1f}" y1="{top_y:.1f}" x2="{X(km) - 4:.1f}" '
                     f'y2="{min(bot_y, top_y + 62):.1f}"/>')
        km += 3
        k += 1

    site_km = labels["site"]["km"]
    sx, sy = X(site_km), Y(el_at(site_km))
    site = (f'<line class="d-site" x1="{sx:.1f}" y1="{sy:.1f}" x2="{sx:.1f}" y2="{Y(el_at(site_km) + 520):.1f}"/>'
            f'<circle class="pin" cx="{sx:.1f}" cy="{sy:.1f}" r="7"/>')

    def dl(km, m, text, cls="", sub=None):
        sub_html = f'<span class="sub">{bi(*sub)}</span>' if sub else ""
        return (f'<div class="dlabel {cls}" style="left:{X(km) / VW * 100:.2f}%;top:{Y(m) / VH * 100:.2f}%">'
                f'{bi(*text)}{sub_html}</div>')

    pair = lambda key: (labels[key]["id"], labels[key]["en"])
    crest_sub = (f'{_fmt_m(crest_m, "id")} m', f'{_fmt_m(crest_m, "en")} m')
    # Place names that sit at sea level go in the strip below the shoreline, where
    # nothing else is drawn; the rest get a dark pill so lines cannot run through.
    base_y = -150
    overlay = "".join([
        dl(v0 + 1, base_y, pair("sea_left"), "al-left"),
        dl(v1 - 1, base_y, pair("sea_right"), "al-right"),
        dl(lee_end + 14, base_y, pair("plain")),
        dl(crest_km - 40, 2560, UI["d_windward"], "b pill", UI["d_windward_sub"]),
        dl(crest_km, crest_m + 380, pair("range"), "b pill", crest_sub),
        dl(site_km, el_at(site_km) + 620, pair("site"), "pill"),
        dl(lee_end + 24, 1500, UI["d_lee"], "b pill", UI["d_lee_sub"]),
        dl(v0 + 1, 1000, ("1.000 m", "1,000 m"), "scale al-left pill"),
        dl(v0 + 1, 2000, ("2.000 m", "2,000 m"), "scale al-left pill"),
    ])

    s, en_ = tr["start"], tr["end"]
    site_lab = pair("site")
    cap_id = (f"Skema ilustratif mekanisme foehn. Udara lembap naik di sisi hadap angin, mendingin, membentuk awan dan "
              f"menurunkan hujan; setelah melewati punggungan, udara turun di sisi lee, memanas dan mengering, lalu tiba di "
              f"{labels['plain']['id']} sebagai udara hangat dan kering.")
    cap_en = (f"Illustrative schematic of the foehn mechanism. Moist air rises on the windward side, cools, forms cloud and "
              f"sheds rain; after the crest it sinks on the lee side, warms and dries, and reaches the "
              f"{labels['plain']['en']} as warm, dry air.")
    src_id = (f"Medan: profil ketinggian SRTM 30 m (NASA, domain publik) lewat OpenTopoData, sepanjang garis dari "
              f"{_fmt_coord(s['lat'], s['lon'], 'id')} ke {_fmt_coord(en_['lat'], en_['lon'], 'id')} yang melintasi "
              f"{site_lab[0]} (diakses {tr['accessed']}); eksagerasi vertikal sekitar ×{ve:.0f}. Titik tertinggi pada "
              f"garis ini {_fmt_m(crest_m, 'id')} m. Panah, awan, dan hujan hanya menggambarkan mekanisme, bukan "
              f"pengukuran.")
    src_en = (f"Terrain: SRTM 30 m elevation profile (NASA, public domain) via OpenTopoData, along a line from "
              f"{_fmt_coord(s['lat'], s['lon'], 'en')} to {_fmt_coord(en_['lat'], en_['lon'], 'en')} passing through "
              f"{site_lab[1]} (accessed {tr['accessed']}); vertical exaggeration about ×{ve:.0f}. The highest point on "
              f"this line is {_fmt_m(crest_m, 'en')} m. The arrows, cloud and rain only illustrate the mechanism; they "
              f"are not measurements.")

    return f"""<figure class="diagram">
  <p class="dhint">{t("d_hint")}</p>
  <div class="dscroll" tabindex="0" role="region" aria-label="{esc(UI['d_region'][0])}" data-focus="{X(crest_km) / VW * 100:.1f}">
  <div class="dstage">
    <svg class="dsvg" viewBox="0 0 {VW:.0f} {VH:.0f}" preserveAspectRatio="none" aria-hidden="true" focusable="false">
      <defs><linearGradient id="{gid}" gradientUnits="userSpaceOnUse" x1="0" y1="0" x2="{VW:.0f}" y2="0">{grad}</linearGradient></defs>
      <rect class="d-water" x="0" y="{Y0:.0f}" width="{VW:.0f}" height="{VH - Y0:.0f}"/>
      {grid}{land}{rain}{cloud}{flows}{chevrons}{ridge}{site}
    </svg>
    {overlay}
  </div>
  </div>
  <div class="dkey">
    <span><i class="sw" style="background:{_hex(TEAL)}"></i>{t("d_key_up")}</span>
    <span><i class="sw" style="background:{_hex(LIME)}"></i>{t("d_key_down")}</span>
    <span><i class="sw cloud"></i>{t("d_key_cloud")}</span>
    <span><i class="sw rain"></i>{t("d_key_rain")}</span>
  </div>
  <figcaption><p>{bi(cap_id, cap_en)}</p><p class="src">{bi(src_id, src_en)}</p></figcaption>
</figure>"""


def entry_page(e):
    draft = e["status"] == "draft"
    sci, kl, place, cav = e["scientific"], e.get("local_knowledge"), e["place"], e.get("caveat")
    url = f"{SITE}{entry_url(e)}"

    local = (f'<p>{bi(kl["id"], kl["en"])}</p>' if kl
             else f'<p class="empty">{t("pending" if draft else "no_local")}</p>')

    caveat = (f'<p class="caveat"><b>{t("note")}</b> {bi(cav["id"], cav["en"])}</p>' if cav else "")

    sources = ""
    if e.get("sources"):
        items = []
        for s in e["sources"]:
            txt = esc(s["text"])
            items.append(f'<li><a href="{esc(s["url"])}">{txt}</a></li>' if s.get("url") else f"<li>{txt}</li>")
        sources = f'<h2>{t("sources")}</h2><ul class="sources">{"".join(items)}</ul>'
    elif draft:
        sources = f'<h2>{t("sources")}</h2><p class="empty">{t("pending")}</p>'

    curator = ""
    if draft and e.get("curator_notes"):
        notes = "".join(f"<li>{esc(n)}</li>" for n in e["curator_notes"])
        curator = f'<details class="curator"><summary>{t("curator")}</summary><ul>{notes}</ul></details>'

    map_href = f'/#layer=wind&step=0&at={e["lon"]:.2f},{e["lat"]:.2f},7'
    ld = {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "Atlas Cuaca", "item": f"{SITE}{BASE}"},
            {"@type": "ListItem", "position": 2, "name": e["name_id"], "item": url},
        ],
    }
    extra = f'<script type="application/ld+json">{json.dumps(ld, indent=2, ensure_ascii=False)}</script>\n'

    return head(f'{e["name_id"]} · Atlas Cuaca · Klimatikal', summary(e, "id"), url,
                noindex=draft, og_type="article", extra=extra) + f"""<body class="atlas-page" data-page="entry">
{land_defs()}
{site_header("entry")}

<main class="atlas entry">
  <nav class="crumbs" aria-label="Breadcrumb"><a href="{BASE}">Atlas Cuaca</a><span aria-hidden="true">›</span><span>{esc(e["name_id"])}</span></nav>

  <header class="entry-head">
    {badges(e)}
    <h1>{esc(e["name_id"])}</h1>
    {alt_names(e)}
  </header>

  <div class="entry-grid">
    <div class="entry-main">
      {photo_block(e)}
      <h2>{t("scientific")}</h2>
      <p>{bi(sci["id"], sci["en"])}</p>
      {foehn_figure(e) if e.get("diagram") else ""}
      {caveat}
      <h2>{t("local_knowledge")}</h2>
      {local}
      {sources}
      {curator}
    </div>
    <aside class="entry-side" aria-label="{esc(UI["location"][0])}">
      <h2>{t("location")}</h2>
      <p class="place">{bi(place["id"], place["en"])} <span class="coords">({e["lat"]:.2f}°, {e["lon"]:.2f}°)</span></p>
      {locator(e)}
      <p><a class="maplink" href="{esc(map_href)}">{t("view_map")} →</a></p>
    </aside>
  </div>

  <p class="backlink"><a href="{BASE}">{t("all_entries")}</a></p>
</main>

{site_footer()}
</body>
</html>
"""


# --------------------------------------------------------------------------

def main():
    global LAND, BORDER
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--with-drafts", action="store_true",
                        help="list drafts in the index too, and mark the index noindex (a preview, not for deploy)")
    args = parser.parse_args()

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

    LAND = path_for(GEO / "coast.json", eps=0.06, min_extent=0.15)
    BORDER = path_for(GEO / "admin0.json", eps=0.06, min_extent=0.15)

    listed = entries if args.with_drafts else [e for e in entries if e["status"] == "reviewed"]
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "index.html").write_text(index_page(listed, args.with_drafts), encoding="utf-8")
    for e in entries:
        d = OUT / e["id"]
        d.mkdir(parents=True, exist_ok=True)
        (d / "index.html").write_text(entry_page(e), encoding="utf-8")

    # A removed entry must not leave its page behind. Only folders that hold an
    # index.html are touched, and 'photos' never is.
    ids = {e["id"] for e in entries}
    for child in OUT.iterdir():
        if child.is_dir() and child.name != "photos" and child.name not in ids and (child / "index.html").exists():
            shutil.rmtree(child)
            print(f"  removed stale page /{child.name}/")

    drafts = [e["id"] for e in entries if e["status"] == "draft"]
    print(f"built {OUT / 'index.html'}  (index lists {len(listed)} of {len(entries)}) and {len(entries)} entry page(s)")
    if drafts and not args.with_drafts:
        print(f"  {len(drafts)} draft, preview-only (noindex, not listed): "
              + ", ".join(f"{BASE}{i}/" for i in drafts))
    if not listed:
        print("  note: nothing is listed in the public index yet (no entry is 'reviewed')")
    for e in entries:
        missing = [n for n, v in (("photo", e.get("photo")), ("local_knowledge", e.get("local_knowledge")),
                                  ("sources", e.get("sources"))) if not v]
        if missing:
            print(f"  note: {e['id']} has no {', '.join(missing)}")


if __name__ == "__main__":
    main()
