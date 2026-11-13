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
import datetime
import hashlib
import html
import json
import math
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


MONTHS = [("Januari", "January"), ("Februari", "February"), ("Maret", "March"), ("April", "April"), ("Mei", "May"), ("Juni", "June"),
          ("Juli", "July"), ("Agustus", "August"), ("September", "September"), ("Oktober", "October"), ("November", "November"), ("Desember", "December")]

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
    "c_tab1": ("1 · Udara dari ketinggian", "1 · Air from height"),
    "c_tab2": ("2 · Udara menyusuri permukaan", "2 · Air along the surface"),
    "c_tab3": ("3 · Pendinginan malam", "3 · Night cooling"),
    "c_tab4": ("4 · Peta aliran Agustus", "4 · August flow map"),
    "c_m_ph0": ("Udara di atas Australia bagian utara, sepuluh hari sebelum tiba.", "Air over northern Australia, ten days before arrival."),
    "c_m_ph1": ("Aliran rata-rata dekat permukaan bergerak ke barat laut melintasi Laut Timor dan perairan selatan Nusa Tenggara.", "The mean near-surface flow moves north-west across the Timor Sea and the waters south of Nusa Tenggara."),
    "c_m_ph2": ("Aliran itu tiba di Jawa dari arah tenggara.", "The flow reaches Java from the south-east."),
    "cn_flow": ("Garis alir bergerak (arah angin)", "Moving flow lines (wind direction)"),
    "cn_hint": ("Geser ke samping untuk melihat seluruh grafik →", "Swipe sideways to see the whole chart →"),
    "cn_box": ("Kotak indeks CENS", "CENS index box"),
    "cn_chart": ("Indeks CENS harian (angin utara rata-rata di kotak, m/s)", "Daily CENS index (box-mean northerly wind, m/s)"),
    "s_box": ("Kotak definisi pusaran Borneo (EUMeTrain)", "Borneo vortex definition box (EUMeTrain)"),
    "s_hint": ("Geser ke samping untuk melihat seluruh peta →", "Swipe sideways to see the whole map →"),
    "s_region": ("Peta cuaca harian", "Daily weather map"),
    "s_slider": ("Hari", "Day"),
    "s_k0": ("Angin 925 hPa < 5 m/s", "925 hPa wind < 5 m/s"),
    "s_k1": ("5–10 m/s", "5–10 m/s"),
    "s_k2": ("> 10 m/s", "> 10 m/s"),
    "s_kiso": ("Isobar (2 hPa)", "Isobar (2 hPa)"),
    "c_tabs": ("Pilih ilustrasi", "Choose an illustration"),
    "c_start_hi": ("Udara dari ketinggian", "Air from height"),
    "c_start_hi_sub": ("di wilayah tropis atau lintang tinggi", "in the tropics or at high latitudes"),
    "c_cold_arr": ("Tiba di permukaan: dingin", "Arrives at the surface: cold"),
    "c_start_lo": ("Udara menyusuri permukaan hangat", "Air travelling over the warm surface"),
    "c_start_lo_sub": ("lama, di wilayah tropis", "for a long time, in the tropics"),
    "c_warm_arr": ("Tiba di permukaan: hangat", "Arrives at the surface: warm"),
    "c_clear": ("Malam cerah", "Clear night"),
    "c_clear_sub": ("panas lolos ke atas", "heat escapes upward"),
    "c_cloudy": ("Malam berawan", "Cloudy night"),
    "c_cloudy_sub": ("awan menahan panas", "clouds hold heat in"),
    "c_key_cold": ("Udara dingin", "Cold air"),
    "c_key_warm": ("Udara hangat", "Warm air"),
    "c_key_path": ("Jalur aliran rata-rata", "Mean flow path"),
    "c_key_wind": ("Angin rata-rata Agustus", "Mean August wind"),
    "c_key_heat": ("Panas dari tanah", "Heat from the ground"),
    "c_a_ph0": ("Udara berada tinggi di atmosfer.", "The air starts high in the atmosphere."),
    "c_a_ph1": ("Udara turun menuju permukaan Jawa tanpa banyak menghangat.", "The air sinks towards Java's surface without warming much."),
    "c_a_ph2": ("Udara tiba dekat permukaan dalam keadaan dingin.", "The air arrives near the surface still cold."),
    "c_b_ph0": ("Udara bergerak dekat permukaan hangat di wilayah tropis.", "The air moves close to the warm tropical surface."),
    "c_b_ph1": ("Selama perjalanan panjang, udara ikut menghangat.", "Over a long journey the air warms up."),
    "c_b_ph2": ("Udara tiba di Jawa dalam keadaan hangat.", "The air arrives in Java warm."),
    "c_c_ph0": ("Siang: tanah menyerap panas dan udara dekat tanah hangat.", "Day: the ground absorbs heat and the air next to it is warm."),
    "c_c_ph1": ("Malam: tanah melepas panas ke atas.", "Night: the ground gives its heat back upward."),
    "c_c_ph2": ("Langit cerah: panas lolos dan udara dekat tanah mendingin. Berawan: sebagian panas tertahan.", "Clear sky: heat escapes and the air near the ground cools. Cloudy: some heat is held in."),
    "d_play": ("Putar", "Play"),
    "d_pause": ("Jeda", "Pause"),
    "d_slider": ("Posisi animasi", "Animation position"),
    "d_ph0": ("Udara lembap bergerak mendekati pegunungan.", "Moist air moves in towards the mountains."),
    "d_ph1": ("Udara naik di sisi hadap angin, mendingin; awan terbentuk dan hujan turun.",
              "Air rises up the windward slope and cools; cloud forms and rain falls."),
    "d_ph2": ("Melewati puncak, udara kini lebih kering.", "Past the crest, the air is drier."),
    "d_ph3": ("Udara turun di sisi lee, memanas dan mengering.", "The air sinks on the lee side, warming and drying."),
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
            need(diag.get("type") in ("foehn", "coldair", "synoptic", "frost", "cens", "fogbasin"), "'diagram.type' must be 'foehn', 'coldair', 'synoptic', 'frost', 'cens' or 'fogbasin'")
            if diag.get("type") == "fogbasin":
                need((DIAGRAMS / f"{diag.get('grid', '')}.json").exists(), f"diagram grid file atlas/diagrams/{diag.get('grid')}.json does not exist")
                need(all(diag.get(k_) for k_ in ("camera", "basin", "frame", "marks")), "'diagram' needs camera, basin, frame and marks")
                need(diag["camera"].get("heading_deg") in (180, 180.0), "'camera.heading_deg' must be 180 (rows of latitude are the rows of depth)")
            if diag.get("type") in ("frost", "fogbasin"):
                pass  # frost: self-contained schematic; fogbasin: checked above
            elif diag.get("type") == "cens":
                for f_ in ("data", "index"):
                    need((DIAGRAMS / f"{diag.get(f_, '')}.json").exists(), f"diagram {f_} file atlas/diagrams/{diag.get(f_)}.json does not exist")
                need(diag.get("view") and diag.get("box") and diag.get("labels"), "'diagram' needs view, box and labels")
            elif diag.get("type") == "synoptic":
                need((DIAGRAMS / f"{diag.get('data', '')}.json").exists(), f"diagram data file atlas/diagrams/{diag.get('data')}.json does not exist")
                need(diag.get("view") and diag.get("bv_box") and diag.get("labels"), "'diagram' needs view, bv_box and labels")
            else:
                tfile = DIAGRAMS / f"{diag.get('transect', '')}.json"
                need(tfile.exists(), f"diagram transect file atlas/diagrams/{diag.get('transect')}.json does not exist")
                vk = diag.get("view_km")
                need(isinstance(vk, list) and len(vk) == 2 and vk[0] < vk[1], "'diagram.view_km' must be [from_km, to_km]")
            for key in (() if diag.get("type") in ("synoptic", "frost", "cens", "fogbasin") else ("sea_left", "sea_right", "range") if diag.get("type") == "coldair"
                        else ("sea_left", "sea_right", "range", "plain", "site")):
                lab = (diag.get("labels") or {}).get(key) or {}
                need(lab.get("id") and lab.get("en"), f"'diagram.labels.{key}' needs both 'id' and 'en'")
            need(diag.get("type") in ("coldair", "synoptic", "frost", "cens", "fogbasin") or isinstance((diag.get("labels") or {}).get("site", {}).get("km"), (int, float)),
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
<script src="__ATLAS_JS__" defer></script>"""


def asset_url(path: str) -> str:
    """A site file's URL plus a short hash of its content.

    Cloudflare serves stylesheets and scripts with a four-hour cache, while the
    HTML is always fetched fresh. Without this, right after a deploy a returning
    visitor gets the NEW page with their cached OLD stylesheet, and a new
    component renders unstyled (the foehn diagram did exactly that). A URL that
    changes with the file's content cannot be stale. Rebuild after editing
    atlas.css or atlas.js so the pages pick up the new hash."""
    digest = hashlib.sha1((WEB / path.lstrip("/")).read_bytes()).hexdigest()[:10]
    return f"{path}?v={digest}"


def lang_script() -> str:
    return LANG_SCRIPT.replace("__ATLAS_JS__", asset_url(f"{BASE}atlas.js"))


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
<link rel="stylesheet" href="{asset_url('/about-us/about.css')}">
<link rel="stylesheet" href="{asset_url(BASE + 'atlas.css')}">
{extra}{lang_script()}
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
      <img src="/brand/klimatikal-lockup-on-dark.svg?v=2" alt="Klimatikal" class="logo-img">
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
  <span>© 2026 Klimatikal · Weather and Climate Intelligence · <a href="/privacy/">Privacy</a></span>
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

COOL, WARM, START = (29, 95, 209), (214, 45, 32), (240, 160, 122)  # blue = cool air, red = warm air, a warm start


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


def _land_paths(xs, el, X, Y, VH):
    """Land polygons and the ridge line from an elevation profile; the sea stays open."""
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
    return land, ridge


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
    stops = [(v0, START), (crest_km, COOL), (lee_end, WARM), (v1, WARM)]

    def air(km):
        for (ka, ca), (kb, cb) in zip(stops, stops[1:]):
            if ka <= km <= kb:
                return _lerp(ca, cb, 0 if kb == ka else (km - ka) / (kb - ka))
        return stops[-1][1] if km > stops[-1][0] else stops[0][1]

    gid = f"air-{e['id']}"
    grad = "".join(f'<stop offset="{(k - v0) / (v1 - v0) * 100:.1f}%" stop-color="{_hex(c)}"/>' for k, c in stops)

    land, ridge = _land_paths(xs, el, X, Y, VH)

    grid = "".join(f'<line class="d-grid" x1="0" x2="{VW:.0f}" y1="{Y(m):.1f}" y2="{Y(m):.1f}"/>' for m in (1000, 2000))

    # airflow: smoothed terrain plus clearance, so each line rides over the range
    flows, chevrons = "", ""
    for clr in (260, 640, 1020):
        hs = [max(s + clr, m + 140) for s, m in zip(sm, el)]
        pts = [(X(x), Y(h)) for x, h in zip(xs, hs)]
        flows += f'<path class="d-air" data-lane="1" stroke="url(#{gid})" d="M{" L".join(f"{px:.1f} {py:.1f}" for px, py in pts)}"/>'
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
    cloud, cloud_edge, rain, k = "", "", "", 0
    km = first_high
    while km < crest_km - 1:
        base = sm_at(km) + 360
        for j in range(2):
            cx = X(km) + (rnd(k * 3 + j) - 0.5) * 18
            cy = Y(base + 110 + 230 * rnd(k * 5 + j + 2))
            rr = 11 + 10 * rnd(k + j * 7)
            cloud_edge += f'<circle class="d-cloud-edge" data-x="{cx:.0f}" cx="{cx:.1f}" cy="{cy:.1f}" r="{rr + 1.8:.1f}"/>'
            cloud += f'<circle class="d-cloud" data-x="{cx:.0f}" cx="{cx:.1f}" cy="{cy:.1f}" r="{rr:.1f}"/>'
        top_y, bot_y = Y(base + 40), Y(el_at(km))
        # no rain into a deep interior valley: it falls on the ridges and slopes
        in_valley = el_at(km) < 0.5 * sm_at(km)
        if bot_y - top_y > 10 and not in_valley:
            rain += (f'<line class="d-rain" data-x="{X(km):.0f}" x1="{X(km):.1f}" y1="{top_y:.1f}" x2="{X(km) - 4:.1f}" '
                     f'y2="{min(bot_y, top_y + 62):.1f}"/>')
        km += 3
        k += 1

    site_km = labels["site"]["km"]
    sx, sy = X(site_km), Y(el_at(site_km))
    site = (f'<line class="d-site" x1="{sx:.1f}" y1="{sy:.1f}" x2="{sx:.1f}" y2="{Y(el_at(site_km) + 520):.1f}"/>'
            f'<circle class="d-pin" cx="{sx:.1f}" cy="{sy:.1f}" r="7"/>')

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

    stops_attr = ";".join(f"{X(k):.0f}:{c[0]},{c[1]},{c[2]}" for k, c in stops)
    ph_x = f'{X(crest_km - 40):.0f},{X(crest_km):.0f},{X(lee_end):.0f}'
    return f"""<figure class="diagram" data-stops="{stops_attr}" data-phases="{ph_x}">
  <p class="dhint">{t("d_hint")}</p>
  <div class="dscroll" tabindex="0" role="region" aria-label="{esc(UI['d_region'][0])}" data-focus="{X(crest_km) / VW * 100:.1f}">
  <div class="dstage">
    <svg class="dsvg" viewBox="0 0 {VW:.0f} {VH:.0f}" preserveAspectRatio="none" aria-hidden="true" focusable="false">
      <defs><linearGradient id="{gid}" gradientUnits="userSpaceOnUse" x1="0" y1="0" x2="{VW:.0f}" y2="0">{grad}</linearGradient></defs>
      <rect class="d-water" x="0" y="{Y0:.0f}" width="{VW:.0f}" height="{VH - Y0:.0f}"/>
      {grid}{land}{rain}{cloud_edge}{cloud}{flows}{chevrons}{ridge}{site}
      <g class="d-parcels"></g>
    </svg>
    {overlay}
  </div>
  </div>
  <div class="dctl" hidden>
    <button type="button" class="dplay" aria-pressed="false"><span class="lp">{t("d_play")}</span><span class="lq">{t("d_pause")}</span></button>
    <input type="range" class="dscrub" min="0" max="1000" value="0" aria-label="{esc(UI['d_slider'][1])}">
    <p class="dphase"><span data-ph="0" class="on">{t("d_ph0")}</span><span data-ph="1">{t("d_ph1")}</span><span data-ph="2">{t("d_ph2")}</span><span data-ph="3">{t("d_ph3")}</span></p>
  </div>
  <div class="dkey">
    <span><i class="sw" style="background:{_hex(COOL)}"></i>{t("d_key_up")}</span>
    <span><i class="sw" style="background:{_hex(WARM)}"></i>{t("d_key_down")}</span>
    <span><i class="sw cloud"></i>{t("d_key_cloud")}</span>
    <span><i class="sw rain"></i>{t("d_key_rain")}</span>
  </div>
  <figcaption><p>{bi(cap_id, cap_en)}</p><p class="src">{bi(src_id, src_en)}</p></figcaption>
</figure>"""


def _coast_paths(px, py, LON0, LON1, LAT1, LAT0):
    """Natural Earth coastlines (web/geo/coast.json) inside a box, as filled land paths."""
    # coastlines inside the box, thinned
    coast = json.loads((ROOT / "web" / "geo" / "coast.json").read_text())["geometry"]["coordinates"]
    land = ""
    # the source cuts Australia's outline in two at a shared end point: join them
    lines = [list(l) for l in coast]
    joined = True
    while joined:
        joined = False
        for i, a_ in enumerate(lines):
            for j, b_ in enumerate(lines):
                if i != j and a_[-1] == b_[0] and a_[0] != a_[-1] and b_[0] != b_[-1]:
                    lines[i] = a_ + b_[1:]
                    del lines[j]
                    joined = True
                    break
            if joined:
                break
    for line in lines:
        if not any(LON0 - 2 <= x <= LON1 + 2 and LAT1 - 2 <= y <= LAT0 + 2 for x, y in line):
            continue
        keep, lx, ly = [], None, None
        for x, y in line:
            if lx is None or abs(x - lx) + abs(y - ly) >= 0.3:
                keep.append((x, y)); lx, ly = x, y
        if len(keep) > 2:
            land += f'<path class="m-land" d="M{" L".join(f"{px(x):.1f} {py(y):.1f}" for x, y in keep)}Z"/>'
    return land


def wind_map_scene(cfg):
    """Scene 4: a map. Streamlines are traced backward for 10 days from Java through
    the long-term mean August near-surface wind (NCEP/NCAR Reanalysis 1, 1991-2020),
    drawn over the real coastlines. A mean-flow approximation, not a set of
    individual air-parcel trajectories like the paper's HYSPLIT runs."""
    import math
    w = json.loads((DIAGRAMS / f"{cfg['map']['wind']}.json").read_text())
    lats, lons, U, V = w["lat"], w["lon"], w["u_ms"], w["v_ms"]
    LON0, LON1, LAT1, LAT0 = 92.0, 158.0, -30.0, 10.0          # map box
    MW = 1000.0
    MH = MW * (LAT0 - LAT1) / (LON1 - LON0)
    px = lambda lon: (lon - LON0) / (LON1 - LON0) * MW
    py = lambda lat: (LAT0 - lat) / (LAT0 - LAT1) * MH

    def wind(lat, lon):
        if not (lats[-1] <= lat <= lats[0] and lons[0] <= lon <= lons[-1]):
            return None
        fi = (lats[0] - lat) / (lats[0] - lats[1]); fj = (lon - lons[0]) / (lons[1] - lons[0])
        i, j = min(int(fi), len(lats) - 2), min(int(fj), len(lons) - 2)
        a, b = fi - i, fj - j
        g = lambda F: (F[i][j] * (1 - a) * (1 - b) + F[i][j + 1] * (1 - a) * b + F[i + 1][j] * a * (1 - b) + F[i + 1][j + 1] * a * b)
        return g(U), g(V)

    R, DT = 6371000.0, 3 * 3600.0

    def back(lat, lon, steps=80):
        pts = [(lat, lon)]
        for _ in range(steps):
            k1 = wind(lat, lon)
            if not k1:
                break
            mid = (lat - k1[1] * DT / 2 / R * 57.2958, lon - k1[0] * DT / 2 / (R * math.cos(math.radians(lat))) * 57.2958)
            k2 = wind(*mid)
            if not k2:
                break
            lat -= k2[1] * DT / R * 57.2958
            lon -= k2[0] * DT / (R * math.cos(math.radians(lat))) * 57.2958
            pts.append((lat, lon))
        return pts[::-1]                                          # earliest point first

    starts = cfg["map"]["starts"]
    trajs = [back(la, lo) for la, lo in starts]

    land = _coast_paths(px, py, LON0, LON1, LAT1, LAT0)

    # quiver of the mean wind on the data grid
    quiver = ""
    for i, la in enumerate(lats):
        for j, lo in enumerate(lons):
            if not (LON0 + 1 <= lo <= LON1 - 1):
                continue
            u, v = U[i][j], V[i][j]
            sp = math.hypot(u, v)
            if sp < 0.3:
                continue
            L = 4.2 * sp
            ux, uy = u / sp, -v / sp                              # svg y points down
            x0, y0 = px(lo) - ux * L / 2, py(la) - uy * L / 2
            x1, y1 = x0 + ux * L, y0 + uy * L
            h = 5.0
            hx = [(x1, y1), (x1 - ux * h + -uy * h * .5, y1 - uy * h + ux * h * .5), (x1 - ux * h - -uy * h * .5, y1 - uy * h - ux * h * .5)]
            quiver += (f'<line class="m-wind" x1="{x0:.1f}" y1="{y0:.1f}" x2="{x1:.1f}" y2="{y1:.1f}"/>'
                       f'<polygon class="m-windhead" points="{" ".join(f"{a:.1f},{b:.1f}" for a, b in hx)}"/>')
    paths = ""
    for tj in trajs:
        paths += f'<path class="m-traj" d="M{" L".join(f"{px(lo):.1f} {py(la):.1f}" for la, lo in tj)}"/>'
    jx, jy = px(110.0), py(-7.4)
    pin_ = f'<circle class="d-pin" cx="{jx:.1f}" cy="{jy:.1f}" r="6"/>'
    keyL = 4.2 * 5
    scalebar = (f'<line class="m-wind" x1="22" y1="{MH - 24:.0f}" x2="{22 + keyL:.0f}" y2="{MH - 24:.0f}"/>'
                f'<polygon class="m-windhead" points="{22 + keyL:.0f},{MH - 24:.0f} {22 + keyL - 5:.0f},{MH - 26.5:.0f} {22 + keyL - 5:.0f},{MH - 21.5:.0f}"/>')
    svg = (f'<svg class="dsvg" viewBox="0 0 {MW:.0f} {MH:.0f}" preserveAspectRatio="none" aria-hidden="true" focusable="false">'
           f'<rect class="d-water" x="0" y="0" width="{MW:.0f}" height="{MH:.0f}"/>{land}{quiver}{paths}{pin_}{scalebar}<g class="d-parcels"></g></svg>')

    def lab(lon, lat, text, cls=""):
        return (f'<div class="dlabel {cls}" style="left:{px(lon) / MW * 100:.2f}%;top:{py(lat) / MH * 100:.2f}%">{bi(*text)}</div>')

    labels = "".join([
        lab(133, -25, ("Australia", "Australia"), "b"),
        lab(110, -4.2, ("Pulau Jawa", "Java"), "b pill"),
        lab(104, -18, ("Samudra Hindia", "Indian Ocean"), "m-sea"),
        lab(145, -4, ("Papua", "Papua"), "m-sea"),
        lab(122, 7, ("Laut Cina Selatan / Pasifik", "South China Sea / Pacific"), "m-sea"),
        lab(92 + 21 / 1000 * 66 + 6, -28.6, ("5 m/s", "5 m/s"), "scale al-left"),
    ])
    return svg, labels, MH, trajs


def coldair_figure(e):
    """Three illustrations of why surface air in Java can be cold, on one real
    terrain profile: (1) air that came down from height, (2) air that travelled
    along the warm surface, (3) heat lost on a clear night. Each is its own
    figure so the page is complete without JavaScript; with it, tabs show one at
    a time. All of it is a schematic of a mechanism, never a measurement."""
    cfg = e["diagram"]
    labels = cfg["labels"]
    tr = json.loads((DIAGRAMS / f"{cfg['transect']}.json").read_text())
    v0, v1 = cfg["view_km"]
    step = tr["step_km"]
    pairs = [(d, (m if m is not None else 0.0)) for d, m in zip(tr["distance_km"], tr["elevation_m"]) if v0 <= d <= v1]
    xs, el = [p[0] for p in pairs], [p[1] for p in pairs]
    n = len(xs)
    VW, VH, Y0, YMAX = 1000.0, 330.0, 300.0, 2800.0
    sc = (Y0 - 14) / YMAX
    ve = sc / (VW / ((v1 - v0) * 1000.0))
    X = lambda km: (km - v0) / (v1 - v0) * VW
    Y = lambda m: Y0 - m * sc
    idx = lambda km: min(range(n), key=lambda i: abs(xs[i] - km))
    el_at = lambda km: el[idx(km)]
    crest_i = max(range(n), key=lambda i: el[i])
    crest_km, crest_m = xs[crest_i], el[crest_i]
    sm = _smooth(el, max(1, int(round(7 / step))))
    sm_at = lambda km: sm[idx(km)]
    land, ridge = _land_paths(xs, el, X, Y, VH)
    first_land = next((x for x, m in zip(xs, el) if m > 60), v0 + 30)
    grid = "".join(f'<line class="d-grid" x1="0" x2="{VW:.0f}" y1="{Y(m):.1f}" y2="{Y(m):.1f}"/>' for m in (1000, 2000))
    scale_lab = ("".join(f'<div class="dlabel scale al-left pill" style="left:0.6%;top:{Y(m) / VH * 100:.2f}%">'
                         f'{bi(f"{m:,}".replace(",", ".") + " m", f"{m:,} m")}</div>' for m in (1000, 2000)))

    def dl(km, m, text, cls="", sub=None, xpct=None):
        sub_html = f'<span class="sub">{bi(*sub)}</span>' if sub else ""
        left = X(km) / VW * 100 if xpct is None else xpct
        return (f'<div class="dlabel {cls}" style="left:{left:.2f}%;top:{Y(m) / VH * 100:.2f}%">'
                f'{bi(*text)}{sub_html}</div>')

    pair = lambda key: (labels[key]["id"], labels[key]["en"])
    crest_sub = (f'{_fmt_m(crest_m, "id")} m', f'{_fmt_m(crest_m, "en")} m')
    base = -150
    common = "".join([dl(v0 + 1, base, pair("sea_left"), "al-left"), dl(v1 - 1, base, pair("sea_right"), "al-right"),
                      dl(crest_km, crest_m + 330, pair("range"), "b pill", crest_sub), scale_lab])

    def stops_attr(stops):
        return ";".join(f"{X(k):.0f}:{c[0]},{c[1]},{c[2]}" for k, c in stops)

    def lane(h):
        pts = [(X(x), Y(h(x))) for x in xs]
        return "M" + " L".join(f"{px:.1f} {py:.1f}" for px, py in pts)

    xd = first_land - 6          # where descending air reaches the surface
    smooth = lambda u: u * u * (3 - 2 * u)

    def descent(start_abs, clr):
        def h(x):
            u = max(0.0, min(1.0, (x - v0) / (xd - v0)))
            end = sm_at(xd) + clr
            top = start_abs + (end - start_abs) * smooth(u)
            return top if x < xd else max(sm_at(x) + clr, el_at(x) + 90)
        return h

    def along(clr):
        return lambda x: max(sm_at(x) + clr, el_at(x) + 90)

    gid_c, gid_w = f"cair-{e['id']}", f"wair-{e['id']}"
    stops_c = [(v0, COOL), (v1, COOL)]
    stops_w = [(v0, START), (xd, WARM), (v1, WARM)]
    grad = lambda gid, st: (f'<linearGradient id="{gid}" gradientUnits="userSpaceOnUse" x1="0" y1="0" x2="{VW:.0f}" y2="0">'
                            + "".join(f'<stop offset="{(k - v0) / (v1 - v0) * 100:.1f}%" stop-color="{_hex(c)}"/>' for k, c in st)
                            + "</linearGradient>")
    water = f'<rect class="d-water" x="0" y="{Y0:.0f}" width="{VW:.0f}" height="{VH - Y0:.0f}"/>'

    def chev(h, st):
        out = ""
        for km in [v0 + 16 + 34 * k for k in range(int((v1 - v0 - 20) / 34))]:
            i = idx(km)
            a_, b_ = max(0, i - 2), min(n - 1, i + 2)
            ax, ay, bx, by = X(xs[a_]), Y(h(xs[a_])), X(xs[b_]), Y(h(xs[b_]))
            L = ((bx - ax) ** 2 + (by - ay) ** 2) ** 0.5 or 1.0
            ux, uy = (bx - ax) / L, (by - ay) / L
            nx, ny = -uy, ux
            px, py = X(xs[i]), Y(h(xs[i]))
            tri = [(px + 11 * ux, py + 11 * uy), (px - 8 * ux + 7 * nx, py - 8 * uy + 7 * ny),
                   (px - 8 * ux - 7 * nx, py - 8 * uy - 7 * ny)]
            col = st[0][1] if len(st) == 2 else (st[0][1] if km < st[1][0] else st[-1][1])
            out += f'<polygon points="{" ".join(f"{a:.1f},{b:.1f}" for a, b in tri)}" fill="{_hex(col)}"/>'
        return out

    def scene_svg(inner, gid=None, gdef=""):
        return (f'<svg class="dsvg" viewBox="0 0 {VW:.0f} {VH:.0f}" preserveAspectRatio="none" aria-hidden="true" focusable="false">'
                f'<defs>{gdef}</defs>{water}{inner}<g class="d-parcels"></g></svg>')

    def air_scene(hs, gid, st, stops_list, gdef):
        flows = "".join(f'<path class="d-air" data-lane="1" stroke="url(#{gid})" d="{lane(h)}"/>' for h in hs)
        return scene_svg(f'{grid}{land}{flows}{chev(hs[1], st)}{ridge}', gid, gdef)

    hs_c = [descent(2650, 70), descent(2400, 170), descent(2150, 270)]
    hs_w = [along(90), along(200), along(310)]
    svg_a = air_scene(hs_c, gid_c, stops_c, stops_c, grad(gid_c, stops_c))
    svg_b = air_scene(hs_w, gid_w, stops_w, stops_w, grad(gid_w, stops_w))
    lab_a = common + dl(v0 + 24, 2480, UI["c_start_hi"], "b pill", UI["c_start_hi_sub"]) + dl(v1 - 34, 1250, UI["c_cold_arr"], "b pill")
    lab_b = common + dl(v0 + 26, 1040, UI["c_start_lo"], "b pill", UI["c_start_lo_sub"]) + dl(v1 - 34, 1250, UI["c_warm_arr"], "b pill")

    # scene 3: night cooling, clear half on the left, cloudy half on the right
    mid = (v0 + v1) / 2
    top_y, cloud_m = Y(2650), 1850
    chill = ""
    for side, (ka, kb) in (("clear", (v0, mid)), ("cloud", (mid, v1))):
        ptsx = [x for x in xs if ka <= x <= kb]
        up = " L".join(f"{X(x):.1f} {Y(el_at(x)) - 5:.1f}" for x in ptsx)
        dn = " L".join(f"{X(x):.1f} {Y(el_at(x)) - 44:.1f}" for x in reversed(ptsx))
        chill += f'<path class="d-chill" data-side="{side}" d="M{up} L{dn} Z"/>'
    heat = ""
    for i, km in enumerate([v0 + 4 + 5.2 * j for j in range(int((v1 - v0 - 8) / 5.2))]):
        if el_at(km) < 5:
            continue
        side = "clear" if km < mid else "cloud"
        y0 = Y(el_at(km)) - 6
        y1 = top_y if side == "clear" else Y(cloud_m) + 16
        heat += (f'<circle class="d-heat" data-side="{side}" data-x="{X(km):.1f}" data-y0="{y0:.1f}" data-y1="{y1:.1f}" '
                 f'data-ph="{(i * 0.37) % 1:.2f}" r="3.6" cx="{X(km):.1f}" cy="{y0:.1f}"/>')
    rnd = lambda i: ((i * 7919) % 101) / 100.0
    cl_e = cl_f = ""
    for j in range(15):
        cx = X(mid) + 40 + j * ((VW - X(mid) - 70) / 14)
        cy = Y(cloud_m) + (rnd(j * 3) - 0.5) * 16
        r_ = 20 + 12 * rnd(j + 5)
        cl_e += f'<circle class="d-cloud-edge" cx="{cx:.1f}" cy="{cy:.1f}" r="{r_ + 1.8:.1f}"/>'
        cl_f += f'<circle class="d-cloud" cx="{cx:.1f}" cy="{cy:.1f}" r="{r_:.1f}"/>'
    divider = f'<line class="d-site" x1="{X(mid):.1f}" y1="14" x2="{X(mid):.1f}" y2="{Y0:.0f}"/>'
    svg_c = scene_svg(f'<rect class="d-sky" x="0" y="0" width="{VW:.0f}" height="{Y0:.0f}"/>{grid}{land}{chill}{cl_e}{cl_f}{heat}{divider}{ridge}')
    lab_c = (dl(v0 + 1, base, pair("sea_left"), "al-left") + dl(v1 - 1, base, pair("sea_right"), "al-right") + scale_lab
             + dl((v0 + mid) / 2, 2620, UI["c_clear"], "b pill", UI["c_clear_sub"])
             + dl((mid + v1) / 2, 2620, UI["c_cloudy"], "b pill", UI["c_cloudy_sub"])
             + dl(crest_km + 6, base, pair("range"), "b"))

    has_map = bool(cfg.get("map"))
    if has_map:
        svg_m, lab_m, MH, _tj = wind_map_scene(cfg)
        wp = json.loads((DIAGRAMS / f"{cfg['map']['wind']}.json").read_text())
        y0_, y1_ = wp["climatology_years"]
    s_, en_ = tr["start"], tr["end"]
    terr_id = (f"Medan: profil ketinggian SRTM 30 m (NASA, domain publik) lewat OpenTopoData, sepanjang garis dari "
               f"{_fmt_coord(s_['lat'], s_['lon'], 'id')} ke {_fmt_coord(en_['lat'], en_['lon'], 'id')} (diakses {tr['accessed']}); "
               f"eksagerasi vertikal sekitar ×{ve:.0f}. Titik tertinggi pada garis ini {_fmt_m(crest_m, 'id')} m. Kiri-kanan pada "
               f"gambar bukan arah mata angin. Perjalanan udara yang sebenarnya berlangsung berhari-hari dan ribuan kilometer; "
               f"di sini dipadatkan ke satu penampang. Warna hanya kualitatif, bukan suhu terukur.")
    terr_en = (f"Terrain: SRTM 30 m elevation profile (NASA, public domain) via OpenTopoData, along a line from "
               f"{_fmt_coord(s_['lat'], s_['lon'], 'en')} to {_fmt_coord(en_['lat'], en_['lon'], 'en')} (accessed {tr['accessed']}); "
               f"vertical exaggeration about ×{ve:.0f}. The highest point on this line is {_fmt_m(crest_m, 'en')} m. Left and "
               f"right in the picture are not compass directions. Real air journeys take days and thousands of kilometres; "
               f"here they are squeezed into one cross-section. Colours are qualitative, not measured temperatures.")
    caps = {
        1: (("Gambaran dari studi Suaydhi (2022), yang meneliti bulan Juni: suhu permukaan Jawa lebih dingin ketika udara yang "
             "tiba dekat permukaan berasal dari ketinggian di wilayah tropis atau dari lintang tinggi.",
             "After Suaydhi (2022), a study of June: surface temperature over Java is colder when the air arriving near the "
             "surface comes from high altitude in the tropics or from high latitudes.")),
        2: (("Gambaran dari studi yang sama: suhu tetap hangat ketika udara sudah lama bergerak dekat permukaan di wilayah "
             "tropis yang hangat sebelum tiba.",
             "From the same study: temperature stays warm when the air has long been travelling near the surface through the "
             "warm tropics before it arrives.")),
        4: ((f"Garis aliran yang ditelusuri mundur 10 hari dari Jawa melalui angin rata-rata jangka panjang bulan Agustus dekat permukaan "
             f"({y0_}–{y1_}, NCEP/NCAR Reanalysis 1, NOAA PSL). Ini perkiraan aliran rata-rata, bukan lintasan parsel udara pada hari tertentu "
             f"seperti analisis HYSPLIT dalam Suaydhi (2022), yang meneliti Juni. Gagasan bahwa angin musim dingin Australia ikut mendinginkan Jawa "
             f"berasal dari artikel Wikipedia yang mengutip petugas BMKG. Panah abu-abu: angin rata-rata pada titik grid 2,5°; garis biru: jalur aliran; "
             f"waktu perjalanan dipadatkan dalam animasi.",
             f"Streamlines traced backward 10 days from Java through the long-term mean August near-surface wind ({y0_}–{y1_}, NCEP/NCAR "
             f"Reanalysis 1, NOAA PSL). This is a mean-flow approximation, not the trajectory of an air parcel on a given day like the HYSPLIT "
             f"analysis in Suaydhi (2022), which studied June. The idea that Australian winter winds help cool Java comes from the Indonesian "
             f"Wikipedia article relaying BMKG staff. Grey arrows: mean wind at the 2.5° grid points; blue lines: flow paths; travel time is "
             f"compressed in the animation.")) if has_map else ("", ""),
        3: (("Penjelasan pendinginan malam ini berasal dari artikel Wikipedia (bahasa Indonesia) yang mengutip petugas BMKG, "
             "bukan dari Suaydhi (2022). Skema ini hanya menggambarkan gagasannya.",
             "This night-cooling explanation comes from the Indonesian Wikipedia article relaying BMKG staff, not from "
             "Suaydhi (2022). The schematic only illustrates the idea.")),
    }
    keys = {
        1: f'<span><i class="sw" style="background:{_hex(COOL)}"></i>{t("c_key_cold")}</span>',
        2: f'<span><i class="sw" style="background:{_hex(WARM)}"></i>{t("c_key_warm")}</span>',
        4: f'<span><i class="sw" style="background:{_hex(COOL)}"></i>{t("c_key_path")}</span><span><i class="sw" style="background:#9aa9bb"></i>{t("c_key_wind")}</span>',
        3: (f'<span><i class="sw" style="background:{_hex(WARM)}"></i>{t("c_key_heat")}</span>'
            f'<span><i class="sw cloud"></i>{t("d_key_cloud")}</span>'),
    }
    phases = {k: "".join(f'<span data-ph="{i}"{" class=on" if i == 0 else ""}>{t(f"c_{k_}_ph{i}")}</span>' for i in range(3))
              for k, k_ in ((1, "a"), (2, "b"), (3, "c"), (4, "m"))}
    svgs, labs = {1: svg_a, 2: svg_b, 3: svg_c}, {1: lab_a, 2: lab_b, 3: lab_c}
    scenes = (1, 2, 3)
    if has_map:
        svgs[4], labs[4], scenes = svg_m, lab_m, (1, 2, 3, 4)
    tabs = "".join(f'<button type="button" role="tab" data-scene="{i}" aria-selected="{"true" if i == 1 else "false"}">{t(f"c_tab{i}")}</button>'
                   for i in scenes)
    figs = ""
    for i in scenes:
        kind = ' data-kind="night"' if i == 3 else ' data-kind="map"' if i == 4 else f' data-stops="{stops_attr(stops_c if i == 1 else stops_w)}" data-phases="{X(xd):.0f},{X(crest_km):.0f},{X(v1 - 20):.0f}"'
        figs += f"""<figure class="diagram dscene" data-scene="{i}"{kind}>
  <p class="dhint">{t("d_hint")}</p>
  <div class="dscroll" tabindex="0" role="region" aria-label="{esc(UI['d_region'][0])}" data-focus="{X(crest_km) / VW * 100:.1f}">
  <div class="dstage{" dmap" if i == 4 else ""}"{f' style="aspect-ratio:1000/{MH:.0f}"' if i == 4 else ""}>{svgs[i]}{labs[i]}</div>
  </div>
  <div class="dctl" hidden>
    <button type="button" class="dplay" aria-pressed="false"><span class="lp">{t("d_play")}</span><span class="lq">{t("d_pause")}</span></button>
    <input type="range" class="dscrub" min="0" max="1000" value="0" aria-label="{esc(UI['d_slider'][1])}">
    <p class="dphase">{phases[i]}</p>
  </div>
  <div class="dkey">{keys[i]}</div>
  <figcaption><p>{bi(*caps[i])}</p></figcaption>
</figure>
"""
    return (f'<div class="dscenes"><div class="dtabs" role="tablist" aria-label="{esc(UI["c_tabs"][1])}" hidden>{tabs}</div>{figs}'
            f'<p class="dsrc">{bi(terr_id, terr_en)}</p></div>')


def frost_figure(e):
    """Radiation frost in four slices of grass and air (dusk, clear night, before
    dawn, and a cloudy night for comparison). A schematic of a mechanism, never a
    measurement: no terrain file, no temperatures, layer depths exaggerated. Plain
    SVG plus HTML labels, so it is complete without JavaScript; the upward heat
    arrows drift by CSS only (and stand still under prefers-reduced-motion)."""
    VW, VH, SPACE, GR = 1000.0, 330.0, 34.0, 248.0
    rnd = lambda i: ((i * 7919 + 13) % 101) / 100.0
    P = lambda *xs: " ".join(f"{x:.1f}" for x in xs)

    def lab(x, y, text, cls="b pill", sub=None):
        s = f'<span class="sub">{bi(*sub)}</span>' if sub else ""
        return f'<div class="dlabel {cls}" style="left:{x / VW * 100:.2f}%;top:{y / VH * 100:.2f}%">{bi(*text)}{s}</div>'

    def wave(x, y0, y1, amp=5.0, period=24.0, cls="f-lw", op=1.0):
        pts, y, k = [], y0, 0
        while y > y1:
            pts.append((x + amp * math.sin(k * 6.2832 * 6 / period), y))
            y -= 6
            k += 1
        d = "M" + " L".join(f"{px:.1f} {py:.1f}" for px, py in pts)
        head = f'<polygon class="f-head" points="{P(x, y1 - 8, x - 6, y1 + 4, x + 6, y1 + 4)}"/>'
        return f'<g class="{cls}" opacity="{op}"><path d="{d}"/>{head}</g>'

    def wave_down(x, y0, y1):
        d = "M" + " L".join(f"{x + 4 * math.sin(k):.1f} {y0 + k * 6:.1f}" for k in range(int((y1 - y0) / 6)))
        head = f'<polygon class="f-head back" points="{P(x, y1 + 8, x - 6, y1 - 4, x + 6, y1 - 4)}"/>'
        return f'<g class="f-lw back"><path d="{d}"/>{head}</g>'

    xs_arrow = [60 + 90 * k for k in range(10)]

    def blades(ice):
        under = over = crystals = ""
        for i, x in enumerate(range(8, 1000, 14)):
            h = 20 + 12 * rnd(i)
            lean = (rnd(i + 3) - 0.5) * 12
            d = f"M{x} {GR + 2:.0f} Q{x + lean * 0.3:.1f} {GR - h * 0.6:.1f} {x + lean:.1f} {GR - h:.1f}"
            tx, ty = x + lean, GR - h
            if ice:
                under += f'<path class="f-bl-ice" d="{d}"/>'
                over += f'<path class="f-bl-frost" d="{d}"/>'
                if i % 2 == 0:
                    crystals += (f'<path class="f-cr" d="M{tx - 4.5:.1f} {ty:.1f} L{tx + 4.5:.1f} {ty:.1f} M{tx:.1f} {ty - 4.5:.1f} '
                                 f'L{tx:.1f} {ty + 4.5:.1f} M{tx - 3:.1f} {ty - 3:.1f} L{tx + 3:.1f} {ty + 3:.1f} '
                                 f'M{tx - 3:.1f} {ty + 3:.1f} L{tx + 3:.1f} {ty - 3:.1f}"/>')
            else:
                over += f'<path class="f-bl" d="{d}"/>'
        return under + over + crystals

    def shelter():
        return (f'<line class="f-post" x1="820" y1="146" x2="820" y2="{GR:.0f}"/>'
                f'<rect class="f-box" x="798" y="116" width="44" height="30" rx="2"/>'
                + "".join(f'<line class="f-slat" x1="802" x2="838" y1="{y}" y2="{y}"/>' for y in (124, 131, 138)))

    stars = lambda k: "".join(f'<circle class="f-star" cx="{(37 + 113 * i + 29 * k) % 980 + 10}" cy="{8 + (i * 7 + k * 5) % 18}" r="{1.1 + 0.5 * rnd(i + k):.1f}"/>'
                              for i in range(14))

    def cloud():
        edge = fill = ""
        for j in range(16):
            cx = 70 + j * 57
            cy = 92 + (rnd(j * 3) - 0.5) * 18
            r = 24 + 14 * rnd(j + 5)
            edge += f'<circle class="d-cloud-edge" cx="{cx}" cy="{cy:.1f}" r="{r + 1.8:.1f}"/>'
            fill += f'<circle class="d-cloud" cx="{cx}" cy="{cy:.1f}" r="{r:.1f}"/>'
        return edge + fill

    def stage(n, stops, inner, labels):
        gid = f"fa-{e['id']}-{n}"
        grad = (f'<linearGradient id="{gid}" x1="0" y1="0" x2="0" y2="1">'
                + "".join(f'<stop offset="{o}%" stop-color="{c}"/>' for o, c in stops) + "</linearGradient>")
        svg = (f'<svg class="dsvg" viewBox="0 0 {VW:.0f} {VH:.0f}" preserveAspectRatio="none" aria-hidden="true" focusable="false">'
               f'<defs>{grad}</defs><rect x="0" y="{SPACE:.0f}" width="{VW:.0f}" height="{GR - SPACE:.0f}" fill="url(#{gid})"/>'
               f'<rect class="f-space" x="0" y="0" width="{VW:.0f}" height="{SPACE:.0f}"/>{stars(n)}'
               f'<rect class="f-soil" x="0" y="{GR:.0f}" width="{VW:.0f}" height="{VH - GR:.0f}"/>{inner}</svg>')
        common = lab(500, 17, ("Angkasa", "Space"), "onspace") + lab(10, 292, ("Tanah", "Soil"), "onsoil al-left")
        return (f'<div class="dscroll" tabindex="0" role="region" aria-label="{esc(FROST_UI["region"][0])}">'
                f'<div class="dstage">{svg}{common}{labels}</div></div>')

    air_warm = [(0, "#f4ece3"), (100, "#f2cfae")]
    air_cold = [(0, "#eef1f6"), (45, "#cfe0f3"), (100, "#5a93d4")]
    air_cold2 = [(0, "#eef1f6"), (40, "#c4d9f0"), (100, "#4a86cc")]
    air_mild = [(0, "#eef1f6"), (100, "#dbe7f4")]
    A = "".join(wave(x, GR - 4, 150, op=0.6) for x in xs_arrow)
    B = "".join(wave(x, GR - 4, SPACE + 8) for x in xs_arrow)
    D = "".join(wave(x, GR - 4, 128) for x in xs_arrow) + "".join(wave_down(x + 45, 126, 200) for x in xs_arrow[:-1])

    panels = [
        (1, ("Senja: tanah mulai melepas panas", "Dusk: the ground starts giving off heat"), air_warm,
         f'{A}{blades(False)}',
         lab(500, 120, ("Tanah melepas panas ke atas", "The ground gives heat off upward"), "b pill",
             ("radiasi gelombang panjang", "longwave radiation"))),
        (2, ("Malam cerah dan tenang: panas lolos, udara tepat di atas rumput paling dingin",
             "Clear, calm night: heat escapes, the air right above the grass is coldest"), air_cold,
         f'{B}{shelter()}{blades(False)}',
         lab(250, 95, ("Panas lolos ke angkasa", "Heat escapes to space"))
         + lab(820, 88, ("Termometer standar", "Standard thermometer"), "b pill", ("± 1,25–2 m dari tanah", "about 1.25–2 m above ground"))
         + lab(470, 212, ("Udara terdingin di rumput", "Coldest air at the grass"), "b pill",
               ("makin ke atas makin hangat", "warmer with height")),),
        (3, ("Menjelang fajar, bila permukaan mencapai titik beku: es terbentuk",
             "Before dawn, if the surface reaches freezing: ice forms"), air_cold2,
         f'{B}{blades(True)}',
         lab(500, 205, ("Es menyelimuti rumput dan daun", "Ice coats grass and leaves"), "b pill",
             ("uap air menjadi es, atau embun membeku", "vapour turns to ice, or dew freezes"))),
        (4, ("Pembanding, malam berawan", "For comparison, a cloudy night"), air_mild,
         f'<g>{cloud()}</g>{D}{blades(False)}',
         lab(500, 92, ("Awan", "Cloud"), "b")
         + lab(500, 188, ("Awan mengembalikan sebagian panas", "Cloud sends part of the heat back"), "b pill",
               ("pendinginan lebih lemah", "cooling is weaker"))),
    ]
    figs = ""
    for n, title, stops, inner, labels in panels:
        hint = f'<p class="dhint">{t("d_hint")}</p>' if n == 1 else ""   # once is enough
        figs += (f'<figure class="fstep"><p class="ftitle"><b>{n}</b> {bi(*title)}</p>'
                 f'{hint}{stage(n, stops, inner, labels)}</figure>\n')
    key = (f'<span><i class="sw" style="background:#5a93d4"></i>{bi(*FROST_UI["k_cold"])}</span>'
           f'<span><i class="sw" style="background:#f2cfae"></i>{bi(*FROST_UI["k_warm"])}</span>'
           f'<span><i class="sw" style="background:#c4452d"></i>{bi(*FROST_UI["k_heat"])}</span>'
           f'<span><i class="sw ice"></i>{bi(*FROST_UI["k_ice"])}</span>')
    return (f'<div class="fsteps">{figs}<div class="dkey">{key}</div>'
            f'<div class="diagram frostcap"><p class="fcap">{bi(*FROST_UI["caption"])}</p></div></div>')


FROST_UI = {
    "region": ("Irisan rumput dan udara", "Slice of grass and air"),
    "k_cold": ("Udara dingin", "Cold air"),
    "k_warm": ("Udara lebih hangat", "Milder air"),
    "k_heat": ("Panas yang dilepas", "Heat given off"),
    "k_ice": ("Es", "Ice"),
    "caption": (
        "Skema satu malam, bukan hasil pengukuran dan tanpa skala: lapisan udara dekat tanah digambar jauh lebih tebal daripada "
        "aslinya (menurut FAO, puncak lapisan inversi pada malam radiasi umumnya sekitar 9–60 m), dan warna hanya kualitatif, "
        "bukan suhu. Urutan langit cerah dan kering, panas lolos, lalu udara dekat permukaan mendingin mengikuti artikel BMKG (2021), "
        "yang juga menyebut bahwa awan menahan panas. Lapisan terdingin tepat di atas tanah (inversi permukaan), selisih antara "
        "termometer standar dan permukaan tanah, serta pembentukan es melalui deposisi uap atau pembekuan embun berasal dari FAO "
        "dan materi pelatihan NWS tentang embun beku radiasi pada umumnya. Studi Dieng (Kurniawan dan Kristianto, 2026) sesuai dengan gambaran ini tetapi tidak memiliki data awan atau suhu permukaan untuk membuktikannya.",
        "A one-night schematic, not a measurement and not to scale: the air layer near the ground is drawn far thicker than in "
        "reality (according to FAO, the top of the inversion on a radiation night is typically about 9–60 m), and colours are "
        "qualitative, not temperatures. The sequence of clear dry sky, heat escaping, then the air near the surface cooling follows "
        "the BMKG article (2021), which also says clouds hold heat in. The coldest layer right above the ground (surface inversion), "
        "the gap between a standard thermometer and the ground surface, and ice forming by vapour deposition or by dew freezing come "
        "from FAO and an NWS training page on radiation frost in general. The Dieng study (Kurniawan and Kristianto, 2026) is consistent with this picture but has no cloud or surface-temperature data to prove it."),
}


def fogbasin_figure(e):
    """Basin fog in a volcanic caldera over one day, drawn from a real SRTM elevation grid that
    is smoothed by bicubic interpolation: a plan-view contour map with the helicopter's position,
    and ONE high-oblique scene whose time of day can be played or scrubbed (sky, sun, moon,
    stars, light colour and the fog layer all change). Terrain is real but stylised: layered
    smooth ridges with distance haze and a decorative backdrop. The fog, its depth, the
    arrows and the clock times are an illustration of a mechanism, never a measurement.
    The fog is drawn as its own ridge layer per row, far to near, so nearer ridges and the
    peaks correctly cut across it."""
    import math
    cfg = e["diagram"]
    g = json.loads((DIAGRAMS / f"{cfg['grid']}.json").read_text())
    lat, lon, E = g["lat"], g["lon"], g["elevation_m"]
    ny, nx = len(lat), len(lon)
    lat0, lon0 = (lat[0] + lat[-1]) / 2, (lon[0] + lon[-1]) / 2
    kx, ky = 111320.0 * math.cos(math.radians(lat0)), 110570.0
    tx = lambda la, lo: ((lo - lon0) * kx, (la - lat0) * ky)
    GX = [(lo - lon0) * kx for lo in lon]
    GY = [(la - lat0) * ky for la in lat]
    dxm, dym = abs(GX[1] - GX[0]), abs(GY[1] - GY[0])

    # ---- smooth the terrain: bicubic interpolation (x3) of the real grid ----
    F = 3
    U = _upsample([[float(v) for v in row] for row in E], F)
    nyU, nxU = len(U), len(U[0])
    latU = [lat[0] + (lat[-1] - lat[0]) * r / (nyU - 1) for r in range(nyU)]
    lonU = [lon[0] + (lon[-1] - lon[0]) * c / (nxU - 1) for c in range(nxU)]
    GXu = [(lo - lon0) * kx for lo in lonU]
    GYu = [(la - lat0) * ky for la in latU]
    dxu, dyu = dxm / F, dym / F

    def shade(r, c):
        r0, r1, c0, c1 = max(r - 1, 0), min(r + 1, nyU - 1), max(c - 1, 0), min(c + 1, nxU - 1)
        dzdx = 1.6 * (U[r][c1] - U[r][c0]) / ((c1 - c0) * dxu)
        dzdy = 1.6 * (U[r0][c] - U[r1][c]) / ((r1 - r0) * dyu)
        slope = math.atan(math.hypot(dzdx, dzdy))
        asp = math.atan2(dzdy, -dzdx)
        az, alt = math.radians(225), math.radians(40)
        return max(0.0, math.sin(alt) * math.cos(slope) + math.cos(alt) * math.sin(slope) * math.cos(az - asp))

    ramp = [(1500, (176, 168, 120)), (2080, (214, 200, 160)), (2140, (198, 186, 140)), (2260, (168, 168, 112)),
            (2400, (124, 148, 82)), (2550, (92, 120, 66)), (2700, (86, 100, 62)), (2800, (104, 92, 70))]

    def tint(h):
        for (a_, ca), (b_, cb) in zip(ramp, ramp[1:]):
            if h <= b_:
                f = max(0.0, (h - a_) / (b_ - a_))
                return tuple(ca[k] + (cb[k] - ca[k]) * f for k in range(3))
        return ramp[-1][1]

    hexc = lambda col: "#%02x%02x%02x" % tuple(max(0, min(255, int(v))) for v in col)
    sky_rgb = (203, 216, 234)

    # ---- the basin (an ellipse that keeps the fog inside the caldera) ----
    ctr = cfg["basin"]["centre"]
    rlat, rlon = cfg["basin"]["radius_deg"]
    in_basin = lambda la, lo: ((lo - ctr[1]) / rlon) ** 2 + ((la - ctr[0]) / rlat) ** 2 <= 1.0

    # ---- helicopter camera (heading must be 180: rows of latitude are then rows of depth) ----
    cam = cfg["camera"]
    ve = cfg.get("vertical_exaggeration", 1.6)
    base_h = 2000.0
    Hx = lambda h: (h - base_h) * ve + base_h
    ccx, ccy = tx(cam["lat"], cam["lon"])
    cch = Hx(cam["alt_m"])
    psi, pit = math.radians(cam["heading_deg"]), math.radians(cam["pitch_deg"])
    fx, fy = math.sin(psi), math.cos(psi)
    rx_, ry_ = math.cos(psi), -math.sin(psi)
    FOC = 1.0 / math.tan(math.radians(cam["fov_deg"]) / 2)

    def proj(x, y, h):
        dx_, dy_, dz_ = x - ccx, y - ccy, Hx(h) - cch
        z = (dx_ * fx + dy_ * fy) * math.cos(pit) - dz_ * math.sin(pit)
        if z < 150:
            return None
        xc = dx_ * rx_ + dy_ * ry_
        yc = (dx_ * fx + dy_ * fy) * math.sin(pit) + dz_ * math.cos(pit)
        return FOC * xc / z, -FOC * yc / z, z

    rows = list(range(nyU - 1, -1, -1))                 # far to near, every interpolated row
    cols = list(range(0, nxU, 3))
    if cols[-1] != nxU - 1:
        cols.append(nxU - 1)
    raw = {r: [proj(GXu[c], GYu[r], U[r][c]) for c in cols] for r in rows}
    ys_all = [p[1] for r in rows for p in raw[r] if p]
    fr = cfg["frame"]
    x0, x1 = fr["x"]
    ybot = fr["bottom"]
    ytop_t = min(ys_all)
    y0 = ytop_t - fr.get("sky_frac", 0.55) * (ybot - ytop_t)
    sc = 1000.0 / (x1 - x0)
    VW, VH = 1000.0, (ybot - y0) * sc
    S = lambda p: ((p[0] - x0) * sc, (p[1] - y0) * sc)
    zs = [p[2] for r in rows for p in raw[r] if p]
    zmin, zmax = min(zs), max(zs)
    haze_k = cfg.get("haze", 0.5)

    def pts_str(pts):
        return " ".join(f"{a:.0f} {b:.0f}" for a, b in pts)

    # ---- terrain rows, each a smooth filled ridge with a horizontal colour gradient ----
    defs, terr = "", {}
    Ps = {r: [S(p) for p in raw[r]] for r in rows}
    def band_bottom(r):
        # a row only has to cover down to the deepest of the next few nearer ridges, not to the frame bottom
        out = []
        for i in range(len(cols)):
            near = [Ps[r - k][i][1] for k in range(1, 5) if (r - k) in Ps]
            out.append(min(VH + 30, max(near) + 8) if len(near) == 4 else VH + 30)
        return out
    for r in rows:
        P = Ps[r]
        zrow = sum(p[2] for p in raw[r]) / len(raw[r])
        hz = ((zrow - zmin) / (zmax - zmin or 1.0)) ** 1.1 * haze_k
        stops = ""
        xa, xb = P[0][0], P[-1][0]
        span = (xb - xa) or 1.0
        for i in range(0, len(cols), 2):
            c = cols[i]
            base = tint(U[r][c])
            f = 0.42 + 0.95 * shade(r, c)
            col = tuple((base[k] * f) * (1 - hz) + sky_rgb[k] * hz for k in range(3))
            stops += f'<stop offset="{max(0.0, min(1.0, (P[i][0] - xa) / span)):.3f}" stop-color="{hexc(col)}"/>'
        defs += f'<linearGradient id="gr{r}" gradientUnits="userSpaceOnUse" x1="{xa:.0f}" y1="0" x2="{xb:.0f}" y2="0">{stops}</linearGradient>'
        bb = band_bottom(r)
        under = [(P[i][0], max(bb[i], P[i][1] + 4)) for i in range(len(cols))]
        poly = "M" + pts_str(P) + " L" + pts_str(list(reversed(under))) + "z"
        terr[r] = f'<path fill="url(#gr{r})" d="{poly}"/>'

    # ---- the day: keyframes (times, sky, light, sun and moon, fog level) ----
    keys = [dict(k) for k in FOG_DAY]
    for i, fk in enumerate(cfg.get("fog", [])):
        keys[i].update(fk)
    start = cfg.get("start_key", 3)
    noise = lambda a, b, k: (math.sin(a * 0.23 + b * 0.15 + k * 1.7) + math.sin(a * 0.12 - b * 0.21 + k * 0.9) + 2) / 4.0

    fog_polys = {}   # (row, key) -> svg path string
    for k, kf in enumerate(keys):
        H = kf.get("level") or 0
        if not H:
            continue
        for r in rows:
            run, runs = [], []
            for ci, c in enumerate(cols):
                ok_ = in_basin(latU[r], lonU[c]) and U[r][c] < H and not (kf.get("patch") and noise(r, c, k) > 1 - kf["patch"])
                if ok_:
                    run.append(c)
                else:
                    if len(run) >= 3:
                        runs.append(run)
                    run = []
            if len(run) >= 3:
                runs.append(run)
            parts = ""
            rb = max(r - 3, 0)
            for run in runs:
                top = [proj(GXu[c], GYu[r], H) for c in run]
                bot = [proj(GXu[c], GYu[rb], min(U[rb][c], H)) for c in run]
                if any(v is None for v in top + bot):
                    continue
                tp = [S(v) for v in top]
                bp = [(S(v)[0], max(S(v)[1], tp[i][1] + 3)) for i, v in enumerate(bot)]
                parts += "M" + pts_str(tp) + " L" + pts_str(list(reversed(bp))) + "z"
            if parts:
                fog_polys[(r, k)] = f'<path class="fd-fg{(r // 4) % 3}" d="{parts}"/>'

    band_rows = cfg.get("band_rows", 6)
    body = ""
    for b0 in range(0, len(rows), band_rows):
        band = rows[b0:b0 + band_rows]
        body += "".join(terr[r] for r in band)
        for k in range(len(keys)):
            inner = "".join(fog_polys.get((r, k), "") for r in band)
            if inner:
                op = 1 if k == start else 0
                body += f'<g class="fd-fog" data-k="{k}" style="opacity:{op}">{inner}</g>'

    # decorative backdrop: two hazy ridges behind the far edge of the data (schematic, not real terrain)
    top_y = ytop_t
    def ridge(seed, amp, lift, col):
        pts = []
        for i in range(0, 41):
            x = VW * i / 40.0
            yy = (top_y - y0) * sc - lift + amp * (math.sin(i * 0.55 + seed) * 0.6 + math.sin(i * 1.3 + seed * 2) * 0.4)
            pts.append((x, yy))
        return f'<path fill="{col}" d="M{pts_str(pts)} L{VW:.0f} {VH + 30:.0f} L0 {VH + 30:.0f}z"/>'
    backdrop = ridge(1.3, 16, 34, "#9db1cd") + ridge(4.1, 20, 14, "#86a0c2")

    # ---- cold-air drainage arrows (far walls only) ----
    def arrows():
        out = ""
        n_dir = cfg.get("arrows", 24)
        for k in range(n_dir):
            th = 2 * math.pi * k / n_dir
            r = cfg.get("arrow_scan_from_m", 3200.0)
            pos = None
            while r < 9000.0:
                r += 150.0
                la = ctr[0] + (r * math.cos(th)) / ky
                lo = ctr[1] + (r * math.sin(th)) / kx
                i = min(range(ny), key=lambda q: abs(lat[q] - la)); j = min(range(nx), key=lambda q: abs(lon[q] - lo))
                if E[i][j] >= cfg.get("arrow_start_m", 2420):
                    pos = (GX[j], GY[i], E[i][j]); break
            if not pos:
                continue
            path = [pos]
            x, y, _h = pos
            for _ in range(14):
                j = min(range(nx), key=lambda q: abs(GX[q] - x)); i = min(range(ny), key=lambda q: abs(GY[q] - y))
                i0, i1, j0, j1 = max(i - 1, 0), min(i + 1, ny - 1), max(j - 1, 0), min(j + 1, nx - 1)
                gx_ = (E[i][j1] - E[i][j0]) / ((j1 - j0) * dxm)
                gy_ = (E[i0][j] - E[i1][j]) / ((i1 - i0) * dym)
                m = math.hypot(gx_, gy_)
                if m < 0.03:
                    break
                x -= 230.0 * gx_ / m; y -= 230.0 * gy_ / m
                j = min(range(nx), key=lambda q: abs(GX[q] - x)); i = min(range(ny), key=lambda q: abs(GY[q] - y))
                path.append((x, y, E[i][j]))
                if E[i][j] < 2125:
                    break
            if len(path) < 3:
                continue
            if ((path[-1][0] - path[0][0]) * fx + (path[-1][1] - path[0][1]) * fy) > 0:
                continue
            pr = [proj(a, b, c + 45) for a, b, c in path]
            if any(v is None for v in pr):
                continue
            pts = [S(v) for v in pr]
            (ax, ay), (bx, by) = pts[-2], pts[-1]
            L = math.hypot(bx - ax, by - ay) or 1.0
            ux, uy = (bx - ax) / L, (by - ay) / L
            hd = [(bx + 11 * ux, by + 11 * uy), (bx - 6 * ux + 6 * uy, by - 6 * uy - 6 * ux), (bx - 6 * ux - 6 * uy, by - 6 * uy + 6 * ux)]
            out += (f'<path class="f-cold" d="M{"L".join(f"{a:.0f} {b:.0f}" for a, b in pts)}"/>'
                    f'<polygon class="f-coldhead" points="{" ".join(f"{a:.0f},{b:.0f}" for a, b in hd)}"/>')
        return out

    # ---- sky layer: gradient, stars, glow, sun, moon (all behind the terrain) ----
    st = keys[start]
    star_pts = "".join(f'<circle cx="{(37 + 113 * i) % 990 + 5}" cy="{(i * 53) % int(VH * 0.30) + 6}" r="{1.0 + 0.9 * ((i * 7) % 5) / 4:.1f}"/>' for i in range(46))
    sky = (f'<rect class="fd-skyrect" width="{VW:.0f}" height="{VH:.0f}" fill="url(#fdsky)"/>'
           f'<g class="fd-stars" style="opacity:{st["stars"]}">{star_pts}</g>'
           f'<circle class="fd-glow" r="300" cx="{st["sun"][0] * VW:.0f}" cy="{st["sun"][1] * VH:.0f}" fill="url(#fdglow)" style="opacity:{st["glow"]}"/>'
           f'<circle class="fd-sun" r="26" cx="{st["sun"][0] * VW:.0f}" cy="{st["sun"][1] * VH:.0f}" style="opacity:{st["sun"][2]}"/>'
           f'<circle class="fd-moon" r="19" cx="{st["moon"][0] * VW:.0f}" cy="{st["moon"][1] * VH:.0f}" style="opacity:{st["moon"][2]}"/>')

    def tint_values(m):
        return f"{m[0]:.3f} 0 0 0 0  0 {m[1]:.3f} 0 0 0  0 0 {m[2]:.3f} 0 0  0 0 0 1 0"

    svg_defs = (f'<defs>{defs}'
                f'<linearGradient id="fdsky" x1="0" y1="0" x2="0" y2="1"><stop class="fd-stop-top" offset="0" stop-color="{hexc(st["top"])}"/>'
                f'<stop class="fd-stop-bot" offset="1" stop-color="{hexc(st["bot"])}"/></linearGradient>'
                f'<radialGradient id="fdglow"><stop offset="0" stop-color="#ffe0a8" stop-opacity=".95"/><stop offset="1" stop-color="#ffe0a8" stop-opacity="0"/></radialGradient>'
                f'<filter id="fdtint" color-interpolation-filters="sRGB" x="0" y="0" width="1" height="1"><feColorMatrix class="fd-tint" type="matrix" values="{tint_values(st["tint"])}"/></filter>'
                f'</defs>')
    scene_svg = (f'<svg class="dsvg fd-svg" viewBox="0 0 {VW:.0f} {VH:.0f}" preserveAspectRatio="xMidYMid slice" aria-hidden="true" focusable="false">'
                 f'{svg_defs}{sky}<g filter="url(#fdtint)">{backdrop}{body}</g>'
                 f'<g class="fd-arrows" style="opacity:{st["arrows"]}">{arrows()}</g></svg>')

    # ---- labels (positions are real terrain points; names and heights are cited) ----
    def label_at(la, lo, text, sub=None, cls="b pill", lift=0):
        i = min(range(ny), key=lambda q: abs(lat[q] - la)); j = min(range(nx), key=lambda q: abs(lon[q] - lo))
        pr = proj(GX[j], GY[i], E[i][j] + lift)
        if pr is None:
            return ""
        a, b = S(pr)
        fx_, fy_ = a / VW * 100, b / VH * 100
        if not (2 < fx_ < 98 and 2 < fy_ < 98):
            return ""
        subh = f'<span class="sub">{bi(*sub)}</span>' if sub else ""
        return f'<div class="dlabel {cls}" style="left:{fx_:.2f}%;top:{fy_:.2f}%">{bi(*text)}{subh}</div>'

    marks = cfg["marks"]
    labels3d = "".join(label_at(m["lat"], m["lon"], (m["id"], m["en"]), (m["sub_id"], m["sub_en"]) if m.get("sub_id") else None,
                                m.get("cls", "b pill"), m.get("lift", 120)) for m in marks)

    # ---- plan-view map: soft hypsometric shading under smooth contour lines ----
    PW = 800.0
    mx_ = lambda x: (x - GX[0]) / (GX[-1] - GX[0]) * PW
    PH = PW * (GY[0] - GY[-1]) / (GX[-1] - GX[0])
    my_ = lambda y: (GY[0] - y) / (GY[0] - GY[-1]) * PH
    plan = ""
    for r in range(0, nyU - 1, 1):
        for c in range(0, nxU - 1, 1):
            if (r % 2) or (c % 2):
                continue
            base = tint(U[r][c])
            col = tuple(b_ * (0.5 + 0.9 * shade(r, c)) for b_ in base)
            plan += f'<path fill="{hexc(col)}" d="M{mx_(GXu[c]):.1f} {my_(GYu[r]):.1f}H{mx_(GXu[c + 2] if c + 2 < nxU else GXu[-1]) + .5:.1f}V{my_(GYu[r + 2] if r + 2 < nyU else GYu[-1]) + .5:.1f}H{mx_(GXu[c]):.1f}z"/>'
    cont_thin, cont_idx = "", ""
    lvl = 2060
    while lvl <= 2760:
        lines = [ln for ln in _contours(U, lvl) if len(ln) > 5]
        d_ = "".join("M" + " L".join(f"{c / (nxU - 1) * PW:.0f} {r / (nyU - 1) * PH:.0f}" for c, r in ln[::2] + [ln[-1]]) for ln in lines)
        if lvl % 500 == 0 or lvl % 250 == 0 and lvl >= 2500:
            cont_idx += d_
        else:
            cont_thin += d_
        lvl += 50 if lvl < 2500 else 50
    cam_x, cam_y = mx_(ccx), my_(ccy)
    half = math.radians(cam["fov_deg"] / 2 + 6)
    fan = ""
    for sgn in (-1, 1):
        ang = psi + sgn * half
        fan += f'<line class="p-fan" x1="{cam_x:.0f}" y1="{cam_y:.0f}" x2="{cam_x + 900 * math.sin(ang):.0f}" y2="{cam_y - 900 * math.cos(ang):.0f}"/>'
    heli = (f'<g transform="translate({cam_x:.0f} {cam_y:.0f}) rotate({cam["heading_deg"]})">'
            f'<ellipse class="p-heli" cx="0" cy="0" rx="9" ry="14"/><rect class="p-heli" x="-1.6" y="12" width="3.2" height="22" rx="1.4"/>'
            f'<line class="p-rotor" x1="-24" y1="-4" x2="24" y2="-4"/><line class="p-rotor" x1="-4" y1="-24" x2="4" y2="16"/></g>')
    plan_labels = ""
    for m in marks:
        if m.get("plan", True):
            pxm, pym = tx(m["lat"], m["lon"])
            plan_labels += f'<div class="dlabel {m.get("cls", "b pill")}" style="left:{mx_(pxm) / PW * 100:.2f}%;top:{my_(pym) / PH * 100:.2f}%">{bi(m["id"], m["en"])}</div>'
    plan_svg = (f'<svg class="dsvg" viewBox="0 0 {PW:.0f} {PH:.0f}" preserveAspectRatio="none" aria-hidden="true" focusable="false">'
                f'<defs><filter id="softplan" x="0" y="0" width="1" height="1"><feGaussianBlur stdDeviation="5"/></filter></defs>'
                f'<g filter="url(#softplan)">{plan}</g><path class="p-cont" d="{cont_thin}"/><path class="p-cont idx" d="{cont_idx}"/>{fan}{heli}</svg>')
    plan_fig = (f'<figure class="fstep"><p class="ftitle"><b>0</b> {bi(*FOG_UI["plan"])}</p>'
                f'<div class="dscroll fogplan" tabindex="0" role="region" aria-label="{esc(FOG_UI["plan"][0])}">'
                f'<div class="dstage fogstage" style="aspect-ratio:{PW:.0f}/{PH:.0f}">{plan_svg}{plan_labels}'
                f'<div class="dlabel pill pheli" style="left:{cam_x / PW * 100:.2f}%;top:{max(cam_y / PH * 100 - 6, 3):.2f}%">{bi(*FOG_UI["heli"])}</div></div></div></figure>')

    # ---- the day scene, its controls and the timeline ----
    def hhmm(m):
        m = int(round(m)) % 1440
        return f"{m // 60:02d}.{m % 60:02d}", f"{m // 60:02d}:{m % 60:02d}"
    data_keys = json.dumps([{k_: kf[k_] for k_ in ("min", "top", "bot", "tint", "sun", "moon", "stars", "glow", "arrows")} for kf in keys])
    clock = hhmm(st["min"])
    items = ""
    for i, kf in enumerate(keys):
        hid, hen = hhmm(kf["min"])
        items += (f'<li data-k="{i}"{" class=on" if i == start else ""}><b>{bi(hid, hen)}</b> <span class="fd-name">{bi(*kf["name"])}</span>: '
                  f'{bi(*kf["text"])}</li>')
    aspect = f"{VW:.0f}/{VH:.0f}"
    day_fig = (f'<figure class="fstep diagram fogday" data-kind="fogday" data-start="{start}" data-keys=\'{data_keys}\'>'
               f'<p class="ftitle">{bi(*FOG_UI["day"])}</p><p class="dhint">{t("d_hint")}</p>'
               f'<div class="dscroll" tabindex="0" role="region" aria-label="{esc(FOG_UI["view"][0])}" data-focus="50">'
               f'<div class="dstage fogstage" style="aspect-ratio:{aspect}">{scene_svg}{labels3d}'
               f'<div class="fd-clock"><span class="fd-time">{clock[1]}</span> <span class="fd-tz">WIB</span></div></div></div>'
               f'<div class="dctl" hidden><button type="button" class="dplay" aria-pressed="false"><span class="lp">{t("d_play")}</span><span class="lq">{t("d_pause")}</span></button>'
               f'<input type="range" class="dscrub" min="0" max="{(len(keys) - 1) * 100}" value="{start * 100}" step="1" aria-label="{esc(FOG_UI["slider"][1])}">'
               f'<span class="fd-clock2"><span class="fd-time">{clock[1]}</span> WIB</span>'
               f'<span class="fd-ends"><span>{hhmm(keys[0]["min"])[1]}</span><span>{hhmm(keys[-1]["min"])[1]}</span></span></div>'
               f'<ol class="fd-list">{items}</ol></figure>')
    key = (f'<span><i class="sw" style="background:#fff;border:1.5px solid #8da0b6;height:10px;width:14px;border-radius:50%"></i>{bi(*FOG_UI["k_fog"])}</span>'
           f'<span><i class="sw" style="background:#1f5fae"></i>{bi(*FOG_UI["k_cold"])}</span>')
    cap = FOG_UI["caption"]
    return (f'<div class="fsteps fogsteps">{plan_fig}{day_fig}<div class="dkey">{key}</div>'
            f'<div class="diagram frostcap"><p class="fcap">{bi(cap[0].format(acc=g["accessed"]), cap[1].format(acc=g["accessed"]))}</p></div></div>')


# One day, as keyframes. Times are illustrative (WIB), not measured. Colours are RGB;
# `tint` multiplies the lit scene, sun/moon are [x, y, opacity] as fractions of the frame,
# `level` (m) is the illustrative fog-top height (0 = no fog) and `patch` the share of holes.
FOG_DAY = [
    {"min": 17 * 60 + 30, "name": ("Sore", "Late afternoon"), "text": (
        "Matahari rendah di barat. Tanah mulai melepas panas ke langit yang cerah, dan udara dingin mulai mengalir turun di dinding kaldera ke dasarnya.",
        "The sun is low in the west. The ground starts giving off heat to a clear sky, and cold air starts to drain down the caldera walls onto the floor."),
     "top": [96, 134, 196], "bot": [246, 196, 140], "tint": [1.0, 0.86, 0.70], "sun": [0.86, 0.20, 1], "moon": [0.72, 0.18, 0],
     "stars": 0, "glow": 0.75, "arrows": 1, "level": 0},
    {"min": 21 * 60, "name": ("Malam", "Night"), "text": (
        "Langit cerah, angin lemah, udara lembap: dasar kaldera mendingin sampai titik embun dan kabut tipis mulai terbentuk.",
        "Clear sky, light wind, moist air: the caldera floor cools to the dew point and thin fog starts to form."),
     "top": [8, 16, 40], "bot": [26, 44, 82], "tint": [0.46, 0.54, 0.78], "sun": [0.98, 0.70, 0], "moon": [0.70, 0.16, 1],
     "stars": 1, "glow": 0, "arrows": 1, "level": 2138, "patch": 0.5},
    {"min": 4 * 60 + 30, "name": ("Menjelang subuh", "Before dawn"), "text": (
        "Pendinginan berlanjut. Kabut menebal dan mengisi kaldera, dan puncak-puncak menyembul darinya (kedalaman hanya ilustrasi).",
        "Cooling continues. The fog deepens and fills the caldera, with the peaks poking out of it (depth is illustrative)."),
     "top": [14, 28, 62], "bot": [58, 82, 128], "tint": [0.50, 0.58, 0.82], "sun": [0.10, 0.70, 0], "moon": [0.82, 0.26, 0.8],
     "stars": 0.7, "glow": 0, "arrows": 0.25, "level": 2185},
    {"min": 5 * 60 + 45, "name": ("Matahari terbit", "Sunrise"), "text": (
        "Cahaya pertama menyentuh puncak-puncak dan permukaan kabut; kabut masih penuh.",
        "The first light touches the peaks and the top of the fog; the fog is still full."),
     "top": [70, 98, 160], "bot": [255, 190, 150], "tint": [1.0, 0.80, 0.72], "sun": [0.11, 0.30, 1], "moon": [0.86, 0.34, 0],
     "stars": 0.1, "glow": 1, "arrows": 0, "level": 2192},
    {"min": 8 * 60, "name": ("Pagi", "Morning"), "text": (
        "Tanah menghangat dan lapisan udara terbawah menjadi tidak stabil: kabut tercampur dan mulai pecah menjadi bercak.",
        "The ground warms and the lowest air layer becomes unstable: the fog mixes and starts to break into patches."),
     "top": [110, 160, 220], "bot": [214, 230, 246], "tint": [1.0, 0.98, 0.94], "sun": [0.24, 0.13, 1], "moon": [0.86, 0.34, 0],
     "stars": 0, "glow": 0.3, "arrows": 0, "level": 2158, "patch": 0.4},
    {"min": 10 * 60 + 30, "name": ("Menjelang siang", "Late morning"), "text": (
        "Sebagian besar kabut menguap; sisa bercak menipis dan kaldera terlihat jelas.",
        "Most of the fog has evaporated; the remaining patches thin out and the caldera is clearly visible."),
     "top": [100, 154, 218], "bot": [206, 227, 246], "tint": [1.0, 1.0, 1.0], "sun": [0.38, 0.07, 1], "moon": [0.86, 0.34, 0],
     "stars": 0, "glow": 0.12, "arrows": 0, "level": 2132, "patch": 0.72},
]


FOG_UI = {
    "plan": ("Peta relief dari atas, dengan posisi dan arah pandang helikopter", "Relief map from above, with the helicopter's position and viewing direction"),
    "heli": ("Helikopter", "Helicopter"),
    "day": ("Satu hari di kaldera: geser atau putar waktu (jam hanya ilustrasi)", "One day in the caldera: scrub or play the time (clock times are illustrative)"),
    "view": ("Pemandangan dari helikopter", "View from the helicopter"),
    "slider": ("Waktu", "Time of day"),
    "k_fog": ("Kabut (ilustrasi)", "Fog (illustrative)"),
    "k_cold": ("Udara dingin mengalir turun (ilustrasi)", "Cold air draining downslope (illustrative)"),
    "caption": (
        "Medan berasal dari data ketinggian nyata, model SRTM 30 m (NASA, domain publik) lewat OpenTopoData, kisi sekitar 330 m (diakses {acc}), yang dihaluskan dengan interpolasi bikubik "
        "dan digambar bergaya skematis (lapisan punggungan, kontur tiap 50 m pada peta, eksagerasi vertikal); warna hanya pewarnaan ketinggian dan bayangan lereng, bukan tutupan lahan, "
        "dan punggungan kabur di latar belakang hanyalah hiasan. Posisi dan ketinggian helikopter (kamera sekitar 5,6 km, lebih tinggi dari ketinggian terbang helikopter biasa, agar seluruh kaldera terlihat), "
        "langit, matahari, bulan, jam, kabut, kedalamannya, dan panah udara dingin hanyalah ilustrasi mekanisme, bukan pengukuran, dan tidak menunjukkan kapan atau seberapa tebal kabut Bromo sebenarnya. "
        "Urutan malam cerah dan tenang, udara lembap, pendinginan sampai titik embun, dan pencampuran serta penguapan setelah matahari menghangatkan tanah mengikuti rujukan umum tentang kabut radiasi (NOAA dan NWS); "
        "udara dingin yang mengalir turun dan menggenang di cekungan berasal dari studi embun beku di Dieng (Ashari dkk., 2024), bukan studi kabut atau studi di Bromo. "
        "Bahwa kabut terjadi hampir setiap pagi dan sore di kawasan wisata Bromo berasal dari Meilani dkk. (2018); sumber itu tidak menjelaskan cara terbentuknya.",
        "Terrain comes from real elevation data, the SRTM 30 m model (NASA, public domain) via OpenTopoData, a grid of about 330 m (accessed {acc}), smoothed by bicubic interpolation "
        "and drawn in a stylised way (layered ridges, 50 m contours on the map, vertical exaggeration); colours are only elevation tint and slope shading, not land cover, "
        "and the hazy ridges in the background are decoration. The helicopter position and height (the camera is at about 5.6 km, higher than a helicopter normally flies, so the whole caldera fits), "
        "the sky, sun, moon, clock, fog, its depth and the cold-air arrows are only an illustration of a mechanism, not measurements, and do not show when or how deep Bromo's fog really is. "
        "The sequence of a clear calm night, moist air, cooling to the dew point, and mixing and evaporation once the sun warms the ground follows general references on radiation fog (NOAA and NWS); "
        "cold air draining down and pooling in basins comes from a frost study at Dieng (Ashari et al., 2024), not a fog study and not a study at Bromo. "
        "That fog occurs almost every morning and afternoon in the Bromo tourist area comes from Meilani et al. (2018); that source does not explain how it forms."),
}


def _catmull(p0, p1, p2, p3, t):
    return 0.5 * ((2 * p1) + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t * t + (-p0 + 3 * p1 - 3 * p2 + p3) * t ** 3)


def _upsample(G, f):
    """Bicubic (Catmull-Rom) upsampling of a regular grid by an integer factor, for smooth isobars."""
    ny, nx = len(G), len(G[0])
    cl = lambda i, n: max(0, min(n - 1, i))
    rows = []
    for i in range(ny):
        r = []
        for j in range(nx - 1):
            for k in range(f):
                r.append(_catmull(G[i][cl(j - 1, nx)], G[i][j], G[i][j + 1], G[i][cl(j + 2, nx)], k / f))
        r.append(G[i][-1])
        rows.append(r)
    out = []
    for i in range(ny - 1):
        for k in range(f):
            out.append([_catmull(rows[cl(i - 1, ny)][j], rows[i][j], rows[i + 1][j], rows[cl(i + 2, ny)][j], k / f) for j in range(len(rows[0]))])
    out.append(rows[-1])
    return out


def _contours(G, level):
    """Marching squares: polylines (lists of (col,row) in grid units) where G crosses level."""
    ny, nx = len(G), len(G[0])
    segs = []
    for i in range(ny - 1):
        for j in range(nx - 1):
            v = (G[i][j], G[i][j + 1], G[i + 1][j + 1], G[i + 1][j])
            pts = []
            for a_, b_, (ax, ay), (bx, by) in ((0, 1, (j, i), (j + 1, i)), (1, 2, (j + 1, i), (j + 1, i + 1)),
                                               (2, 3, (j + 1, i + 1), (j, i + 1)), (3, 0, (j, i + 1), (j, i))):
                if (v[a_] - level) * (v[b_] - level) < 0:
                    f = (level - v[a_]) / (v[b_] - v[a_])
                    pts.append((round(ax + (bx - ax) * f, 3), round(ay + (by - ay) * f, 3)))
            if len(pts) == 2:
                segs.append(tuple(pts))
            elif len(pts) == 4:
                segs.append((pts[0], pts[1])); segs.append((pts[2], pts[3]))
    ends = {}
    for k, (a_, b_) in enumerate(segs):
        ends.setdefault(a_, []).append(k); ends.setdefault(b_, []).append(k)
    used, lines = set(), []
    for k in range(len(segs)):
        if k in used:
            continue
        used.add(k)
        line = [segs[k][0], segs[k][1]]
        for end in (0, 1):
            while True:
                tip = line[-1] if end == 0 else line[0]
                nxt = next((m for m in ends.get(tip, []) if m not in used), None)
                if nxt is None:
                    break
                used.add(nxt)
                other = segs[nxt][1] if segs[nxt][0] == tip else segs[nxt][0]
                if end == 0:
                    line.append(other)
                else:
                    line.insert(0, other)
        lines.append(line)
    return lines


def synoptic_figure(e):
    """A real weather-map sequence: sea-level pressure isobars, 925 hPa wind arrows,
    pressure extremes and the strongest cyclonic vorticity, for a run of days from
    the NCEP/NCAR Reanalysis 1. Drawn by this script from data committed in
    atlas/diagrams/; the page never loads data at run time."""
    import math
    tt = globals()["t"]
    cfg = e["diagram"]
    d = json.loads((DIAGRAMS / f"{cfg['data']}.json").read_text())
    LON0, LON1, LAT1, LAT0 = cfg["view"]["lon"][0], cfg["view"]["lon"][1], cfg["view"]["lat"][0], cfg["view"]["lat"][1]
    W = 1000.0
    H = W * (LAT0 - LAT1) / (LON1 - LON0)
    px = lambda lon: (lon - LON0) / (LON1 - LON0) * W
    py = lambda lat: (LAT0 - lat) / (LAT0 - LAT1) * H
    lats, lons = d["lat"], d["lon"]
    F = 3
    ulat = [lats[0] + (lats[-1] - lats[0]) * r / ((len(lats) - 1) * F) for r in range((len(lats) - 1) * F + 1)]
    ulon = [lons[0] + (lons[-1] - lons[0]) * c / ((len(lons) - 1) * F) for c in range((len(lons) - 1) * F + 1)]
    gx = lambda c: px(ulon[0] + (ulon[-1] - ulon[0]) * c / (len(ulon) - 1))
    gy = lambda r: py(ulat[0] + (ulat[-1] - ulat[0]) * r / (len(ulat) - 1))
    inview = lambda la, lo: LAT1 <= la <= LAT0 and LON0 <= lo <= LON1
    land = _coast_paths(px, py, LON0, LON1, LAT1, LAT0)
    grat = ""
    for lo in range(int(LON0), int(LON1) + 1, 5):
        if lo % 5 == 0:
            grat += f'<line class="s-grat" x1="{px(lo):.1f}" y1="0" x2="{px(lo):.1f}" y2="{H:.0f}"/><text class="s-gt" x="{px(lo) + 4:.1f}" y="{H - 8:.0f}">{lo}°E</text>'
    for la in range(int(math.ceil(LAT1 / 5) * 5), int(LAT0) + 1, 5):
        grat += (f'<line class="s-grat" x1="0" y1="{py(la):.1f}" x2="{W:.0f}" y2="{py(la):.1f}"/>'
                 f'<text class="s-gt" x="6" y="{py(la) - 4:.1f}">{abs(la)}°{"N" if la > 0 else "S" if la < 0 else ""}</text>')
    bx = cfg["bv_box"]
    bvbox = (f'<rect class="s-bv" x="{px(bx["lon"][0]):.1f}" y="{py(bx["lat"][1]):.1f}" width="{px(bx["lon"][1]) - px(bx["lon"][0]):.1f}" '
             f'height="{py(bx["lat"][0]) - py(bx["lat"][1]):.1f}"/>')

    frames, days_txt = "", []
    key_i = cfg.get("key_day", 0)
    for t, day in enumerate(d["dates"]):
        S = d["slp_hpa"][t]
        U, V = d["u925_ms"][t], d["v925_ms"][t]
        SS = _upsample(S, F)
        iso = {"minor": "", "major": ""}
        labs = ""
        for lev in range(int(min(min(r) for r in S)) // 2 * 2, int(max(max(r) for r in S)) + 3, 2):
            lines = [ln for ln in _contours(SS, lev) if len(ln) > 3]
            if not lines:
                continue
            kind = "major" if lev % 4 == 0 else "minor"
            for ln in lines:
                iso[kind] += "M" + " L".join(f"{gx(c):.0f} {gy(r):.0f}" for c, r in ln)
            if kind == "major":
                ln = max(lines, key=len)
                cand = [(c, r) for c, r in ln[len(ln) // 3: 2 * len(ln) // 3 + 1] if 50 < gx(c) < W - 50 and 40 < gy(r) < H - 40]
                if cand:
                    c, r = cand[len(cand) // 2]
                    labs += f'<text class="s-il" x="{gx(c):.0f}" y="{gy(r) + 4:.0f}">{lev}</text>'
        # wind arrows in three speed classes
        arrows = {0: "", 1: "", 2: ""}
        for i, la in enumerate(lats):
            for j, lo in enumerate(lons):
                if not inview(la, lo):
                    continue
                u, v = U[i][j], V[i][j]
                sp = math.hypot(u, v)
                if sp < 0.5:
                    continue
                L = 4.0 * sp
                ux, uy = u / sp, -v / sp
                x0, y0 = px(lo) - ux * L / 2, py(la) - uy * L / 2
                x1, y1 = x0 + ux * L, y0 + uy * L
                hh = 6.0
                a1 = (x1 - hh * (ux * .85 - uy * .5), y1 - hh * (uy * .85 + ux * .5))
                a2 = (x1 - hh * (ux * .85 + uy * .5), y1 - hh * (uy * .85 - ux * .5))
                cls = 0 if sp < 5 else 1 if sp < 10 else 2
                arrows[cls] += f"M{x0:.0f} {y0:.0f} L{x1:.0f} {y1:.0f} M{a1[0]:.0f} {a1[1]:.0f} L{x1:.0f} {y1:.0f} L{a2[0]:.0f} {a2[1]:.0f}"
        # pressure extremes in view, and strongest cyclonic vorticity in the vortex box
        cells = [(S[i][j], la, lo) for i, la in enumerate(lats) for j, lo in enumerate(lons) if inview(la, lo)]
        near = [c_ for c_ in cells if bx["lat"][0] - 2.5 <= c_[1] <= bx["lat"][1] + 2.5 and bx["lon"][0] - 2.5 <= c_[2] <= bx["lon"][1] + 2.5]
        hi, lo_ = max(cells), min(near)
        zbest = None
        for i in range(1, len(lats) - 1):
            for j in range(1, len(lons) - 1):
                la, lo = lats[i], lons[j]
                if not (bx["lat"][0] <= la <= bx["lat"][1] and bx["lon"][0] <= lo <= bx["lon"][1]):
                    continue
                dv = (V[i][j + 1] - V[i][j - 1]) / (2 * 2.5 * 111e3 * math.cos(math.radians(la)))
                du = (U[i - 1][j] - U[i + 1][j]) / (2 * 2.5 * 111e3)
                z = (dv - du) * 1e5
                if zbest is None or z > zbest[0]:
                    zbest = (z, la, lo)
        mark = (f'<g class="s-hl s-h" transform="translate({px(hi[2]):.0f} {py(hi[1]):.0f})"><circle r="17"/><text y="6">H</text></g>'
                f'<g class="s-hl s-l" transform="translate({px(lo_[2]):.0f} {py(lo_[1]):.0f})"><circle r="17"/><text y="6">L</text></g>'
                f'<g class="s-vort" transform="translate({px(zbest[2]):.0f} {py(zbest[1]):.0f})"><circle r="11"/>'
                f'<path d="M0 -6 A6 6 0 1 0 6 0" /><polygon points="6,-3 10,2 2,2"/></g>')
        dt = datetime.date.fromisoformat(day)
        txt = (f'{dt.day} {MONTHS[dt.month - 1][0]} {dt.year}', f'{dt.day} {MONTHS[dt.month - 1][1]} {dt.year}')
        days_txt.append((txt, hi[0], lo_[0], zbest[0]))
        frames += (f'<g class="sframe{" on" if t == key_i else ""}" data-i="{t}"><path class="s-iso" d="{iso["minor"]}"/>'
                   f'<path class="s-iso major" d="{iso["major"]}"/>{labs}'
                   f'<path class="s-w s-w0" d="{arrows[0]}"/><path class="s-w s-w1" d="{arrows[1]}"/><path class="s-w s-w2" d="{arrows[2]}"/>{mark}</g>')

    def ph(t):
        (di, de), hi, lo_, z = days_txt[t]
        return (f'<span data-ph="{t}"{" class=on" if t == key_i else ""}>'
                f'{bi(di + ": tekanan tertinggi di bingkai " + f"{hi:.0f}" + " hPa (H), terendah di sekitar kotak " + f"{lo_:.0f}" + " hPa (L), selisih " + f"{hi - lo_:.0f}" + " hPa; vortisitas siklonik maks. " + f"{z:.1f}" + "×10⁻⁵ s⁻¹.", de + ": highest pressure in frame " + f"{hi:.0f}" + " hPa (H), lowest around the box " + f"{lo_:.0f}" + " hPa (L), difference " + f"{hi - lo_:.0f}" + " hPa; peak cyclonic vorticity " + f"{z:.1f}" + "×10⁻⁵ s⁻¹.")}</span>')
    phases = "".join(ph(t) for t in range(len(days_txt)))
    lab = lambda lon, lat, text, cls="": (f'<div class="dlabel {cls}" style="left:{px(lon) / W * 100:.2f}%;top:{py(lat) / H * 100:.2f}%">{bi(*text)}</div>')
    labels = "".join([lab(cfg["labels"][k]["lon"], cfg["labels"][k]["lat"], (cfg["labels"][k]["id"], cfg["labels"][k]["en"]), cls)
                      for k, cls in (("borneo", "b"), ("scs", "m-sea"), ("sumatra", "b"), ("java", "b"), ("china", "b"))]
                     + [lab((bx["lon"][0] + bx["lon"][1]) / 2, bx["lat"][1] + 1.4, UI["s_box"], "s-boxlab")])
    y0, y1 = d["dates"][0], d["dates"][-1]
    cap_id = (f"Peta cuaca harian dari NCEP/NCAR Reanalysis 1 (NOAA PSL), rata-rata harian {d['dates'][0]} sampai {d['dates'][-1]}, kisi 2,5°. "
              f"Garis kontur: tekanan permukaan laut tiap 2 hPa (angka pada kelipatan 4 hPa). Panah: angin 925 hPa (sekitar 750 m), makin gelap makin kencang. "
              f"H: tekanan tertinggi dalam bingkai; L: tekanan terendah di dalam atau sekitar (2,5°) kotak putus-putus. Lingkaran dengan panah melengkung: vortisitas siklonik terbesar di dalam kotak putus-putus "
              f"(kotak yang dipakai EUMeTrain untuk mendefinisikan pusaran Borneo), dihitung di sini dari angin kisi 2,5°. Peta ini menunjukkan keadaan atmosfer pada hari-hari itu; "
              f"kisi sekasar ini tidak memperlihatkan pusaran sebagai lingkaran tertutup yang tajam, dan penulis belum memeriksa pustaka bahwa pusaran Borneo dikenali pada periode ini.")
    cap_en = (f"Daily weather maps from the NCEP/NCAR Reanalysis 1 (NOAA PSL), daily means {y0} to {y1}, 2.5° grid. "
              f"Contours: sea-level pressure every 2 hPa (numbers on multiples of 4 hPa). Arrows: 925 hPa wind (about 750 m up), darker means stronger. "
              f"H: highest pressure in the frame; L: lowest pressure in or within 2.5° of the dashed box. The circle with a curved arrow marks the strongest cyclonic vorticity inside the dashed box "
              f"(the box EUMeTrain uses to define a Borneo vortex), computed here from the 2.5° wind grid. The maps show the state of the atmosphere on those days; "
              f"a grid this coarse does not show the vortex as a sharp closed circle, and the author has not checked the literature to confirm a Borneo vortex was identified in this period.")
    key = (f'<span><i class="sw" style="background:#9fb0c4"></i>{tt("s_k0")}</span><span><i class="sw" style="background:#4a7fc1"></i>{tt("s_k1")}</span>'
           f'<span><i class="sw" style="background:#12306b"></i>{tt("s_k2")}</span><span><i class="sw" style="background:#6b7b8e;height:2px"></i>{tt("s_kiso")}</span>')
    return f"""<figure class="diagram synoptic" data-kind="synoptic" data-n="{len(days_txt)}" data-key="{key_i}">
  <p class="dhint">{tt("s_hint")}</p>
  <div class="dscroll" tabindex="0" role="region" aria-label="{esc(UI['s_region'][0])}" data-focus="{(((bx["lon"][0] + bx["lon"][1]) / 2) - LON0) / (LON1 - LON0) * 100:.0f}">
  <div class="dstage dmap dsyn" style="aspect-ratio:1000/{H:.0f}">
    <svg class="dsvg" viewBox="0 0 {W:.0f} {H:.0f}" preserveAspectRatio="none" aria-hidden="true" focusable="false">
      <rect class="d-water" x="0" y="0" width="{W:.0f}" height="{H:.0f}"/>{land}{grat}{bvbox}{frames}</svg>
    {labels}
  </div>
  </div>
  <div class="dctl" hidden>
    <button type="button" class="dplay" aria-pressed="false"><span class="lp">{tt("d_play")}</span><span class="lq">{tt("d_pause")}</span></button>
    <input type="range" class="dscrub" min="0" max="{len(days_txt) - 1}" value="{key_i}" step="1" aria-label="{esc(UI['s_slider'][1])}">
  </div>
  <p class="dphase dsynphase">{phases}</p>
  <div class="dkey">{key}</div>
  <figcaption><p>{bi(cap_id, cap_en)}</p></figcaption>
</figure>"""


def cens_figure(e):
    """Cross-equatorial northerly surge: daily 925 hPa wind-and-pressure maps (NCEP/NCAR
    Reanalysis 1) with the CENS-index box marked, and under them the daily index over a
    winter with a marker that follows the map. One control drives both. Drawn here from
    data committed in atlas/diagrams/; the page never loads data at run time."""
    import math
    tt = globals()["t"]
    cfg = e["diagram"]
    d = json.loads((DIAGRAMS / f"{cfg['data']}.json").read_text())
    ix = json.loads((DIAGRAMS / f"{cfg['index']}.json").read_text())
    LON0, LON1, LAT1, LAT0 = cfg["view"]["lon"][0], cfg["view"]["lon"][1], cfg["view"]["lat"][0], cfg["view"]["lat"][1]
    W = 1000.0
    H = W * (LAT0 - LAT1) / (LON1 - LON0)
    px = lambda lon: (lon - LON0) / (LON1 - LON0) * W
    py = lambda lat: (LAT0 - lat) / (LAT0 - LAT1) * H
    lats, lons = d["lat"], d["lon"]
    F = 3
    ulat = [lats[0] + (lats[-1] - lats[0]) * r / ((len(lats) - 1) * F) for r in range((len(lats) - 1) * F + 1)]
    ulon = [lons[0] + (lons[-1] - lons[0]) * c / ((len(lons) - 1) * F) for c in range((len(lons) - 1) * F + 1)]
    gx = lambda c: px(ulon[0] + (ulon[-1] - ulon[0]) * c / (len(ulon) - 1))
    gy = lambda r: py(ulat[0] + (ulat[-1] - ulat[0]) * r / (len(ulat) - 1))
    inview = lambda la, lo: LAT1 <= la <= LAT0 and LON0 <= lo <= LON1
    land = _coast_paths(px, py, LON0, LON1, LAT1, LAT0)
    grat = ""
    for lo in range(int(math.ceil(LON0 / 5) * 5), int(LON1) + 1, 5):
        grat += f'<line class="s-grat" x1="{px(lo):.1f}" y1="0" x2="{px(lo):.1f}" y2="{H:.0f}"/><text class="s-gt" x="{px(lo) + 4:.1f}" y="{H - 8:.0f}">{lo}°E</text>'
    for la in range(int(math.ceil(LAT1 / 5) * 5), int(LAT0) + 1, 5):
        grat += (f'<line class="s-grat" x1="0" y1="{py(la):.1f}" x2="{W:.0f}" y2="{py(la):.1f}"/>'
                 f'<text class="s-gt" x="6" y="{py(la) - 4:.1f}">{abs(la)}°{"N" if la > 0 else "S" if la < 0 else ""}</text>')
    bx = cfg["box"]
    box = (f'<rect class="s-bv" x="{px(bx["lon"][0]):.1f}" y="{py(bx["lat"][1]):.1f}" width="{px(bx["lon"][1]) - px(bx["lon"][0]):.1f}" '
           f'height="{py(bx["lat"][0]) - py(bx["lat"][1]):.1f}"/>')

    idx_by_date = dict(zip(ix["dates"], ix["northerly_ms"]))
    notes = cfg.get("notes", {})
    fmt = lambda v, lang: f"{v:.1f}".replace(".", ",") if lang == "id" else f"{v:.1f}"
    key_i = cfg.get("key_day", 0)
    frames, phase_html = "", ""
    for t, day in enumerate(d["dates"]):
        S = d["slp_hpa"][t]
        U, V = d["u925_ms"][t], d["v925_ms"][t]
        SS = _upsample(S, F)
        iso = {"minor": "", "major": ""}
        labs = ""
        for lev in range(int(min(min(r) for r in S)) // 2 * 2, int(max(max(r) for r in S)) + 3, 2):
            lines = [ln for ln in _contours(SS, lev) if len(ln) > 3]
            if not lines:
                continue
            kind = "major" if lev % 4 == 0 else "minor"
            for ln in lines:
                iso[kind] += "M" + " L".join(f"{gx(c):.0f} {gy(r):.0f}" for c, r in ln)
            if kind == "major":
                ln = max(lines, key=len)
                cand = [(c, r) for c, r in ln[len(ln) // 3: 2 * len(ln) // 3 + 1] if 50 < gx(c) < W - 50 and 40 < gy(r) < H - 40]
                if cand:
                    c, r = cand[len(cand) // 2]
                    labs += f'<text class="s-il" x="{gx(c):.0f}" y="{gy(r) + 4:.0f}">{lev}</text>'
        # Dense display field: the 2.5-degree winds interpolated (bicubic) to 1.25 degrees for the
        # arrows, and to 0.625 degrees for the flow lines. Display only; no new information.
        UA, VA = _upsample(U, 2), _upsample(V, 2)
        arrows = {0: "", 1: "", 2: ""}
        nr, nc = len(UA), len(UA[0])
        for i in range(nr):
            la = lats[0] + (lats[-1] - lats[0]) * i / (nr - 1)
            for j in range(nc):
                lo = lons[0] + (lons[-1] - lons[0]) * j / (nc - 1)
                if not inview(la, lo):
                    continue
                u, v = UA[i][j], VA[i][j]
                sp = math.hypot(u, v)
                if sp < 0.5:
                    continue
                L = min(3.0 * sp, 44.0)
                ux, uy = u / sp, -v / sp
                x0, y0 = px(lo) - ux * L / 2, py(la) - uy * L / 2
                x1, y1 = x0 + ux * L, y0 + uy * L
                hh = 5.0
                a1 = (x1 - hh * (ux * .85 - uy * .5), y1 - hh * (uy * .85 + ux * .5))
                a2 = (x1 - hh * (ux * .85 + uy * .5), y1 - hh * (uy * .85 - ux * .5))
                cls = 0 if sp < 5 else 1 if sp < 10 else 2
                arrows[cls] += f"M{x0:.0f} {y0:.0f} L{x1:.0f} {y1:.0f} M{a1[0]:.0f} {a1[1]:.0f} L{x1:.0f} {y1:.0f} L{a2[0]:.0f} {a2[1]:.0f}"
        # flow lines: short streamlines of the same field, drawn as moving dashes
        UF, VF = _upsample(U, 4), _upsample(V, 4)
        fr, fc = len(UF), len(UF[0])

        def samp(la, lo):
            r = (la - lats[0]) / (lats[-1] - lats[0]) * (fr - 1)
            c = (lo - lons[0]) / (lons[-1] - lons[0]) * (fc - 1)
            if not (0 <= r <= fr - 1 and 0 <= c <= fc - 1):
                return None
            r0, c0 = min(int(r), fr - 2), min(int(c), fc - 2)
            fy, fx = r - r0, c - c0
            lerp2 = lambda G: (G[r0][c0] * (1 - fx) + G[r0][c0 + 1] * fx) * (1 - fy) + (G[r0 + 1][c0] * (1 - fx) + G[r0 + 1][c0 + 1] * fx) * fy
            return lerp2(UF), lerp2(VF)

        flow = {0: "", 1: "", 2: ""}
        step = cfg.get("flow_spacing", 1.8)
        la = LAT1 + step / 2
        k = 0
        while la < LAT0:
            lo = LON0 + step / 2 + (step / 2 if (k % 2) else 0)
            while lo < LON1:
                pts, sps = [(lo, la)], []
                cl, cb = lo, la
                for _ in range(8):
                    w = samp(cb, cl)
                    if not w:
                        break
                    sp = math.hypot(*w)
                    if sp < 1.2 or not inview(cb, cl):
                        break
                    sps.append(sp)
                    cl, cb = cl + 0.5 * w[0] / sp, cb + 0.5 * w[1] / sp
                    pts.append((cl, cb))
                if len(pts) >= 5:
                    m = sum(sps) / len(sps)
                    flow[0 if m < 5 else 1 if m < 10 else 2] += "M" + " L".join(f"{px(x):.0f} {py(y):.0f}" for x, y in pts)
                lo += step
            la += step
            k += 1
        frames += (f'<g class="sframe{" on" if t == key_i else ""}" data-i="{t}"><path class="s-iso" d="{iso["minor"]}"/>'
                   f'<path class="s-iso major" d="{iso["major"]}"/>{labs}'
                   f'<path class="s-flow s-f0" d="{flow[0]}"/><path class="s-flow s-f1" d="{flow[1]}"/><path class="s-flow s-f2" d="{flow[2]}"/>'
                   f'<path class="s-w s-w0" d="{arrows[0]}"/><path class="s-w s-w1" d="{arrows[1]}"/><path class="s-w s-w2" d="{arrows[2]}"/></g>')
        dt = datetime.date.fromisoformat(day)
        dtxt = (f'{dt.day} {MONTHS[dt.month - 1][0]} {dt.year}', f'{dt.day} {MONTHS[dt.month - 1][1]} {dt.year}')
        v_ = idx_by_date[day]
        thr = cfg.get("threshold", 5.0)
        side_id, side_en = ("di atas", "above") if v_ >= thr else ("di bawah", "below")
        note = notes.get(day)
        extra_id = f' {note["id"]}' if note else ""
        extra_en = f' {note["en"]}' if note else ""
        phase_html += (f'<span data-ph="{t}"{" class=on" if t == key_i else ""}>'
                       + bi(f"{dtxt[0]}: indeks CENS (perkiraan dari angin 925 hPa) {fmt(v_, 'id')} m/s, {side_id} garis {thr:g} m/s.{extra_id}",
                            f"{dtxt[1]}: CENS index (estimated from 925 hPa wind) {fmt(v_, 'en')} m/s, {side_en} the {thr:g} m/s line.{extra_en}")
                       + "</span>")
    lab = lambda lon, lat, text, cls="": (f'<div class="dlabel {cls}" style="left:{px(lon) / W * 100:.2f}%;top:{py(lat) / H * 100:.2f}%">{bi(*text)}</div>')
    labels = "".join([lab(cfg["labels"][k]["lon"], cfg["labels"][k]["lat"], (cfg["labels"][k]["id"], cfg["labels"][k]["en"]), cls)
                      for k, cls in (("borneo", "b"), ("scs", "m-sea"), ("sumatra", "b"), ("java", "b"), ("china", "b"))]
                     + [lab((bx["lon"][0] + bx["lon"][1]) / 2, bx["lat"][1] + 1.6, UI["cn_box"], "s-boxlab")])

    # ---- the index time series (own viewBox; text in SVG, so the box keeps a minimum width) ----
    CW, CH, ML, MR, MT, MB = 1000.0, 300.0, 62.0, 14.0, 22.0, 40.0
    vals, dates = ix["northerly_ms"], ix["dates"]
    n = len(vals)
    thr = cfg.get("threshold", 5.0)
    ymin = math.floor(min(vals + [0.0])) - 1
    ymax = max(math.ceil(max(vals)), math.ceil(thr) + 1) + 1
    cx = lambda i: ML + (CW - ML - MR) * i / (n - 1)
    cy = lambda v: MT + (CH - MT - MB) * (ymax - v) / (ymax - ymin)
    grid = ""
    for v in range(int(math.ceil(ymin / 2) * 2), ymax + 1, 2):
        grid += (f'<line class="c-grid{" zero" if v == 0 else ""}" x1="{ML:.0f}" x2="{CW - MR:.0f}" y1="{cy(v):.1f}" y2="{cy(v):.1f}"/>'
                 f'<text class="c-t" x="{ML - 8:.0f}" y="{cy(v) + 7:.1f}" text-anchor="end">{v}</text>')
    line = "M" + " L".join(f"{cx(i):.1f} {cy(v):.1f}" for i, v in enumerate(vals))
    area = f"M{cx(0):.1f} {cy(0):.1f} L" + " L".join(f"{cx(i):.1f} {cy(v):.1f}" for i, v in enumerate(vals)) + f" L{cx(n - 1):.1f} {cy(0):.1f} Z"
    ticks = ""
    mon = [("Jan", "Jan"), ("Feb", "Feb"), ("Mar", "Mar"), ("Apr", "Apr"), ("Mei", "May"), ("Jun", "Jun"), ("Jul", "Jul"), ("Agu", "Aug"),
           ("Sep", "Sep"), ("Okt", "Oct"), ("Nov", "Nov"), ("Des", "Dec")]
    for i, dd in enumerate(dates):
        dt = datetime.date.fromisoformat(dd)
        if dt.day == 1:
            ticks += (f'<line class="c-tick" x1="{cx(i):.1f}" x2="{cx(i):.1f}" y1="{CH - MB:.0f}" y2="{CH - MB + 7:.0f}"/>'
                      f'<text class="c-t" lang="id" x="{cx(i) + 5:.1f}" y="{CH - 12:.0f}">{mon[dt.month - 1][0]} {dt.year}</text>'
                      f'<text class="c-t" lang="en" x="{cx(i) + 5:.1f}" y="{CH - 12:.0f}">{mon[dt.month - 1][1]} {dt.year}</text>')
    pos = {dd: i for i, dd in enumerate(dates)}
    w0, w1 = pos[d["dates"][0]], pos[d["dates"][-1]]
    window = f'<rect class="c-win" x="{cx(w0):.1f}" y="{MT:.0f}" width="{cx(w1) - cx(w0):.1f}" height="{CH - MT - MB:.0f}"/>'
    thrline = (f'<line class="c-thr" x1="{ML:.0f}" x2="{CW - MR:.0f}" y1="{cy(thr):.1f}" y2="{cy(thr):.1f}"/>'
               f'<text class="c-t thr" x="{CW - MR - 4:.0f}" y="{cy(thr) - 6:.1f}" text-anchor="end">{thr:g} m/s</text>')
    marks = ""
    for t, day in enumerate(d["dates"]):
        i, v_ = pos[day], idx_by_date[day]
        tx = min(max(cx(i), ML + 30), CW - MR - 30)
        marks += (f'<g class="sframe cmark{" on" if t == key_i else ""}" data-i="{t}">'
                  f'<line class="c-cur" x1="{cx(i):.1f}" x2="{cx(i):.1f}" y1="{MT:.0f}" y2="{CH - MB:.0f}"/>'
                  f'<circle class="c-dot" cx="{cx(i):.1f}" cy="{cy(v_):.1f}" r="7"/>'
                  f'<text class="c-val" lang="id" x="{tx:.1f}" y="{MT - 6:.0f}" text-anchor="middle">{fmt(v_, "id")}</text>'
                  f'<text class="c-val" lang="en" x="{tx:.1f}" y="{MT - 6:.0f}" text-anchor="middle">{fmt(v_, "en")}</text></g>')
    chart = (f'<svg class="csvg" viewBox="0 0 {CW:.0f} {CH:.0f}" role="img" aria-label="{esc(UI["cn_chart"][0])}" focusable="false">'
             f'{grid}{window}<path class="c-area" d="{area}"/>{thrline}<path class="c-line" d="{line}"/>{ticks}{marks}</svg>')

    y0, y1 = d["dates"][0], d["dates"][-1]
    cap_id = (f"Atas: peta harian dari NCEP/NCAR Reanalysis 1 (NOAA PSL), rata-rata harian {y0} sampai {y1}, kisi 2,5°. Garis kontur: tekanan permukaan laut tiap 2 hPa "
              f"(angka pada kelipatan 4 hPa). Panah: angin 925 hPa (sekitar 750 m), makin gelap makin kencang; untuk tampilan, angin kisi 2,5° diinterpolasi (bikubik) ke kisi yang lebih rapat, sehingga tidak menambah informasi. Garis putus-putus yang bergerak menunjukkan arah aliran medan angin hari itu (garis arus pendek), bukan lintasan parsel udara dan bukan kecepatan sebenarnya. Kotak putus-putus: area indeks CENS "
              f"({bx['lon'][0]:g}–{bx['lon'][1]:g}°BT, {abs(bx['lat'][0]):g}°LS–ekuator). Bawah: indeks harian {ix['dates'][0]} sampai {ix['dates'][-1]}, "
              f"yaitu rata-rata angin utara 925 hPa di {ix['box']['grid_points']} titik kisi dalam kotak itu (positif = dari utara). Ini perkiraan sendiri dari reanalisis, "
              f"bukan indeks asli: Hattori dkk. (2011) mendefinisikannya dari angin permukaan laut QuikSCAT, sehingga angkanya tidak sama dan garis {thr:g} m/s "
              f"hanyalah acuan ambang mereka. Pita biru muda menandai hari-hari pada peta; angka di atas penanda adalah nilai hari itu.")
    cap_en = (f"Top: daily maps from the NCEP/NCAR Reanalysis 1 (NOAA PSL), daily means {y0} to {y1}, 2.5° grid. Contours: sea-level pressure every 2 hPa "
              f"(numbers on multiples of 4 hPa). Arrows: 925 hPa wind (about 750 m up), darker means stronger; for display, the 2.5° grid wind is interpolated (bicubic) to a denser grid, which adds no information. The moving dashes show the direction of that day's wind field (short streamlines), not air-parcel paths and not true speed. Dashed box: the CENS index area "
              f"({bx['lon'][0]:g}–{bx['lon'][1]:g}°E, {abs(bx['lat'][0]):g}°S to the equator). Bottom: the daily index {ix['dates'][0]} to {ix['dates'][-1]}, "
              f"the average northerly 925 hPa wind over the {ix['box']['grid_points']} grid points in that box (positive = from the north). This is our own estimate from "
              f"reanalysis, not the original index: Hattori et al. (2011) defined it from QuikSCAT sea-surface wind, so the values differ and the {thr:g} m/s line "
              f"is only their threshold for reference. The light-blue band marks the days on the maps; the number above the marker is that day's value.")
    key = (f'<span><i class="sw" style="background:#9fb0c4"></i>{tt("s_k0")}</span><span><i class="sw" style="background:#4a7fc1"></i>{tt("s_k1")}</span>'
           f'<span><i class="sw" style="background:#12306b"></i>{tt("s_k2")}</span><span><i class="sw" style="background:#6b7b8e;height:2px"></i>{tt("s_kiso")}</span>'
           f'<span><i class="sw flowsw"></i>{tt("cn_flow")}</span>')
    return f"""<figure class="diagram synoptic cens" data-kind="synoptic" data-n="{len(d["dates"])}" data-key="{key_i}">
  <p class="dhint">{tt("s_hint")}</p>
  <div class="dscroll" tabindex="0" role="region" aria-label="{esc(UI['s_region'][0])}" data-focus="{(((bx["lon"][0] + bx["lon"][1]) / 2) - LON0) / (LON1 - LON0) * 100:.0f}">
  <div class="dstage dmap dsyn" style="aspect-ratio:1000/{H:.0f}">
    <svg class="dsvg" viewBox="0 0 {W:.0f} {H:.0f}" preserveAspectRatio="none" aria-hidden="true" focusable="false">
      <rect class="d-water" x="0" y="0" width="{W:.0f}" height="{H:.0f}"/>{land}{grat}{box}{frames}</svg>
    {labels}
  </div>
  </div>
  <p class="cn-title">{tt("cn_chart")}</p>
  <p class="dhint">{tt("cn_hint")}</p>
  <div class="dscroll cn-chart" tabindex="0" role="region" aria-label="{esc(UI['cn_chart'][0])}" data-focus="{(cx(w0) + cx(w1)) / 2 / CW * 100:.0f}"><div class="cn-stage">{chart}</div></div>
  <div class="dctl" hidden>
    <button type="button" class="dplay" aria-pressed="false"><span class="lp">{tt("d_play")}</span><span class="lq">{tt("d_pause")}</span></button>
    <input type="range" class="dscrub" min="0" max="{len(d["dates"]) - 1}" value="{key_i}" step="1" aria-label="{esc(UI['s_slider'][1])}">
  </div>
  <p class="dphase dsynphase">{phase_html}</p>
  <div class="dkey">{key}</div>
  <figcaption><p>{bi(cap_id, cap_en)}</p></figcaption>
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
      {({"coldair": coldair_figure, "synoptic": synoptic_figure, "frost": frost_figure, "cens": cens_figure, "fogbasin": fogbasin_figure}.get(e["diagram"]["type"], foehn_figure)(e)) if e.get("diagram") else ""}
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
