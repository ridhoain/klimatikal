#!/usr/bin/env python3
"""Build separate Indonesian and English pages from the bilingual sources.

    python3 i18n/build.py            # from klimatikal/

Sources in i18n/src/ hold both languages in one file, as paired elements:
    <span lang="id">…</span><span lang="en">…</span>
For each source page this writes
    web/<path>/index.html        Indonesian (default, keeps the existing URL)
    web/en/<path>/index.html     English
and each page declares its own <html lang>, canonical URL and hreflang
alternates. Edit the files in i18n/src/ (and i18n/meta.en.json), never the
generated pages. Also rewrites web/sitemap.xml.
"""
import hashlib, json, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC, WEB = ROOT / "i18n" / "src", ROOT / "web"
SITE = "https://klimatikal.com"
LANGS = ("id", "en")
LOCALE = {"id": "id_ID", "en": "en_US"}
META_EN = json.loads((ROOT / "i18n" / "meta.en.json").read_text("utf-8"))
# Elements that carry a lang pair in the sources.
PAIRED = re.compile(r'<(/?)(span|button|text)\b([^>]*)>')


def url_of(rel: str, lang: str) -> str:
    return ("/en" if lang == "en" else "") + "/" + rel.replace("index.html", "")


def strip_other(html: str, keep: str) -> str:
    """Drop every paired element whose lang is the other language (nesting-safe)."""
    drop = "en" if keep == "id" else "id"
    out, pos, stack, skip = [], 0, [], None
    for m in PAIRED.finditer(html):
        closing, tag, attrs = m.group(1), m.group(2), m.group(3)
        if not closing and not attrs.rstrip().endswith("/"):
            if skip is None:
                if re.search(r'\blang="%s"' % drop, attrs):
                    out.append(html[pos:m.start()]); skip = [tag, 1]
            elif tag == skip[0]:
                skip[1] += 1
        elif closing and skip is not None and tag == skip[0]:
            skip[1] -= 1
            if skip[1] == 0:
                pos, skip = m.end(), None
    if skip is not None:
        sys.exit("unbalanced <%s lang=%s> element" % (skip[0], drop))
    out.append(html[pos:])
    return "".join(out)


def set_meta(html: str, lang: str, rel: str) -> str:
    url = SITE + url_of(rel, lang)
    if lang == "en":
        m = META_EN.get(rel.replace("index.html", ""), {})
        if "title" in m:
            html = re.sub(r"<title>[^<]*</title>", "<title>%s</title>" % m["title"], html, 1)
            html = re.sub(r'(<meta property="og:title" content=")[^"]*', r"\g<1>" + m["title"], html, 1)
        if "description" in m:
            html = re.sub(r'(<meta name="description" content=")[^"]*', r"\g<1>" + m["description"], html, 1)
            html = re.sub(r'(<meta property="og:description" content=")[^"]*', r"\g<1>" + m["description"], html, 1)
        else:
            print("  ! no English description for", rel)
        # Links to other atlas pages stay inside the English tree.
        html = re.sub(r'href="/atlas-cuaca/([^"]*/)?"', lambda x: 'href="/en/atlas-cuaca/%s"' % (x.group(1) or ""), html)
        html = html.replace('"item": "%s/atlas-cuaca/' % SITE, '"item": "%s/en/atlas-cuaca/' % SITE)
    html = re.sub(r'(<link rel="canonical" href=")[^"]*', r"\g<1>" + url, html, 1)
    html = re.sub(r'(<meta property="og:url" content=")[^"]*', r"\g<1>" + url, html, 1)
    alt = "".join('<link rel="alternate" hreflang="%s" href="%s%s">\n' % (l, SITE, url_of(rel, l)) for l in LANGS)
    alt += '<link rel="alternate" hreflang="x-default" href="%s%s">\n' % (SITE, url_of(rel, "id"))
    html = re.sub(r'(<link rel="canonical"[^>]*>\n)', lambda x: x.group(1) + alt, html, 1)
    loc = '<meta property="og:locale" content="%s">\n' % LOCALE[lang]
    loc += '<meta property="og:locale:alternate" content="%s">\n' % LOCALE["en" if lang == "id" else "id"]
    return re.sub(r'(<meta property="og:type"[^>]*>\n)', lambda x: x.group(1) + loc, html, 1)


def switcher(rel: str, lang: str) -> str:
    links = "".join(
        '<a href="%s" hreflang="%s"%s>%s</a>' % (url_of(rel, l), l, ' aria-current="true"' if l == lang else "", l.upper())
        for l in LANGS)
    return '<span class="lang" role="group" aria-label="Language">%s</span>' % links


def build_page(path: Path) -> list:
    rel = path.relative_to(SRC).as_posix()
    source = path.read_text("utf-8")
    atlas_js = WEB / "atlas-cuaca" / "atlas.js"
    ver = hashlib.md5(atlas_js.read_bytes()).hexdigest()[:10]
    written = []
    for lang in LANGS:
        html = strip_other(source, lang)
        html = re.sub(r'<html lang="[a-z]+"[^>]*>', '<html lang="%s" data-lang="%s">' % (lang, lang), html, 1)
        # Language is fixed by the URL now: drop the pick-on-first-paint script.
        html = re.sub(r"<script>\s*/\* Language is chosen before first paint.*?</script>\n?", "", html, 1, re.S)
        html = re.sub(r"(/atlas-cuaca/atlas\.js\?v=)[0-9a-f]+", r"\g<1>" + ver, html)
        html = set_meta(html, lang, rel)
        # After set_meta, which rewrites atlas links in the English tree.
        html = re.sub(r'<span class="lang"[^>]*>.*?</span>', lambda _: switcher(rel, lang), html, 1, re.S)
        out = WEB / url_of(rel, lang).lstrip("/") / "index.html"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(html, "utf-8")
        written.append(url_of(rel, lang))
    return written


def sitemap(bilingual: set) -> None:
    urls = []
    for p in sorted(WEB.rglob("index.html")):
        rel = p.relative_to(WEB).as_posix()
        if rel.split("/")[0] in ("data", "en", "radar", "brand", "geo"):
            continue
        urls.append("/" + rel.replace("index.html", ""))
    body = []
    for u in urls:
        rel = u.lstrip("/")
        entries = [(u, None)]
        if u in bilingual:
            entries = [(u, "id"), ("/en" + u, "en")]
        for loc, lang in entries:
            x = "  <url>\n    <loc>%s%s</loc>\n" % (SITE, loc)
            if lang:
                for l in LANGS:
                    x += '    <xhtml:link rel="alternate" hreflang="%s" href="%s%s"/>\n' % (l, SITE, ("/en" if l == "en" else "") + u)
                x += '    <xhtml:link rel="alternate" hreflang="x-default" href="%s%s"/>\n' % (SITE, u)
            body.append(x + "  </url>\n")
    xml = ('<?xml version="1.0" encoding="UTF-8"?>\n'
           '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" xmlns:xhtml="http://www.w3.org/1999/xhtml">\n'
           + "".join(body) + "</urlset>\n")
    (WEB / "sitemap.xml").write_text(xml, "utf-8")


if __name__ == "__main__":
    bilingual = set()
    for page in sorted(SRC.rglob("index.html")):
        for u in build_page(page):
            print("wrote", u)
        bilingual.add(url_of(page.relative_to(SRC).as_posix(), "id"))
    sitemap(bilingual)
    print("wrote /sitemap.xml")
