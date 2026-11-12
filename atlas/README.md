# Atlas Cuaca Indonesia

Source for `klimatikal.com/atlas-cuaca/`. One JSON file per phenomenon in
`atlas/phenomena/`; the pages are generated from them.

```bash
python3 atlas/build_atlas.py                 # the build that gets deployed (stdlib only)
python3 atlas/build_atlas.py --with-drafts   # a preview that also lists drafts in the index
```

It produces:

- `/atlas-cuaca/`: the index, with compact cards you can filter and search,
  and a map of every pin;
- `/atlas-cuaca/<id>/`: one full page per phenomenon (scientific text, local
  knowledge, sources, location map, link to the weather map).

## Adding a phenomenon

Copy `phenomena/angin-bahorok.json`, rename it to the new slug, and edit. The
file name must equal `id`, and it is the page address: `id` `angin-bahorok`
becomes `/atlas-cuaca/angin-bahorok/`. Use lowercase letters, digits and hyphens.

| Field | Notes |
|---|---|
| `id` | slug, same as the file name |
| `status` | `draft` or `reviewed` |
| `name_id`, `name_en` | required |
| `name_local` | local-language name, or `null` |
| `scale` | `local` or `regional` |
| `documentation` | `well` or `poor` |
| `place` | `{ "id": "...", "en": "..." }` |
| `lat`, `lon` | the pin; decimal degrees |
| `scientific` | `{ "id": "...", "en": "..." }`, the main text |
| `summary` | optional `{ "id": "...", "en": "..." }` for the index card; if left out, the first sentence of `scientific` is used |
| `caveat` | optional `{ "id": "...", "en": "..." }`: a public note under the science text, for where sources disagree or something is unsettled |
| `diagram` | optional; see "Terrain diagrams" below |
| `local_knowledge` | `{ "id": "...", "en": "..." }` or `null` |
| `photo` | `null`, or `{ "file", "alt", "credit", "licence" }` |
| `sources` | list of `{ "text", "url" }` (`url` optional) |
| `curator_notes` | what is still to check; shown only on drafts |

## Rules the build enforces

- **A photo needs a credit and a licence.** The file goes in
  `web/atlas-cuaca/photos/` (about 1600 px wide, JPEG or WebP, under ~300 KB).
  Use only photos you own or that have a licence that allows it.
- **Local and indigenous knowledge needs a named source** (a person or a
  publication). Leave it `null` rather than paraphrase from memory.
- **Drafts are private previews.** A `draft` entry still gets its page, so you
  can read it at its address, but that page is `noindex` and the entry is left
  out of the public index and map. Set `status` to `reviewed` once the text,
  sources and photo have been checked, and it is listed and indexable. One
  draft never hides the rest of the atlas.
- **Removing an entry removes its page** on the next build.

## Terrain diagrams

A foehn entry can carry a cross-section drawn from **real elevation data**, with
the airflow, cloud and rain laid over it as an illustration of the mechanism
(never as a measurement). Bahorok has one.

1. Sample a terrain line, once. It is saved in `atlas/diagrams/` and committed,
   so the site build never touches the network:

   ```bash
   python3 atlas/diagrams/fetch_transect.py --name bahorok-transect \
       --lat 3.60 --lon 98.10 --azimuth 45 --from-km -200 --to-km 120
   ```

   The line passes through (lat, lon) at 0 km and runs along `azimuth` (degrees
   clockwise from north). Elevations are NASA's SRTM 30 m model (public domain)
   via the OpenTopoData public API: gentle use only, about 4 requests. Choose
   the azimuth across the range, and check the printed profile before using it.

2. Add to the entry's JSON:

   ```json
   "diagram": {
     "type": "foehn",
     "transect": "bahorok-transect",
     "view_km": [-120, 90],
     "labels": {
       "sea_left":  { "id": "...", "en": "..." },
       "sea_right": { "id": "...", "en": "..." },
       "range":     { "id": "...", "en": "..." },
       "plain":     { "id": "...", "en": "..." },
       "site":      { "id": "...", "en": "...", "km": 0 }
     }
   }
   ```

   `view_km` is the stretch of the line to draw; `site.km` is where the entry's
   place lies on it. Check the labels against the profile (is the left end
   really sea?). The crest is the highest point in view. The caption, the
   vertical exaggeration and the highest elevation are worked out for you.

Things to remember: it is one line through a complex range, not the whole range;
the vertical scale is exaggerated (stated in the caption); and the diagram
shows the mechanism only. It names no wind direction or monsoon: it labels the
windward and lee sides by role, which is what a foehn on that side implies.
On narrow screens the figure scrolls sideways inside its own box.

### Cold-air diagram (`"type": "coldair"`)

Musim Bediding uses a three-scene variant on one terrain line (air from height,
air along the warm surface, clear-versus-cloudy night cooling). Config needs
`transect`, `view_km` and `labels` `sea_left`, `sea_right`, `range` only. Scenes 1
and 2 come from Suaydhi (2022); scene 3 is from Wikipedia/BMKG staff and says so
in its caption. An optional `diagram.map` (`wind`, `starts`) adds a fourth scene: a map of 10-day backward streamlines through the long-term mean August wind (`atlas/diagrams/fetch_wind.py` fetches NCEP/NCAR data once; it is rate-limited, so run it gently). With JavaScript the scenes are tabs; without it they are stacked.

### Weather-map sequence (`"type": "synoptic"`)

Borneo Vortex uses a real-data map: sea-level pressure isobars, 925 hPa wind arrows,
H/L markers and peak cyclonic vorticity, one frame per day. `atlas/diagrams/fetch_daily.py`
downloads NCEP/NCAR Reanalysis 1 daily means once (gentle: it is rate-limited); the
page is drawn at build time from that committed JSON. Config: `data`, `view`, `bv_box`,
`labels`, `key_day`. A 2.5-degree grid shows broad flow, not a sharp vortex, and the
caption says so. A date must be backed by a source before it is called a vortex event.

### Frost slices (`"type": "frost"`)

Bun Upas uses a self-contained schematic: four slices of grass and air (dusk,
clear night, before dawn, cloudy night for comparison). Config is just
`"diagram": {"type": "frost"}`; no terrain or data file. Arrows drift by CSS only
(stopped under `prefers-reduced-motion`), it needs no JavaScript, and the caption
states that it is not to scale and shows no temperatures. The wording lives in
`build_atlas.py` (`frost_figure`, `FROST_UI`), so reuse it only for radiation frost.

## Publishing

**Rebuild after editing `atlas.css`, `atlas.js` or `about.css`.** The generated
pages carry a short hash of those files in their URLs (`atlas.css?v=7bd819005e`).
Cloudflare caches stylesheets and scripts for four hours, while pages are always
fresh, so without the hash a returning visitor could get the new page with an old
stylesheet (a new component would render unstyled). The hand-written About and
Contact pages do not use hashed URLs; if you change `about.css`, they can show the
old styles for up to four hours.

Commit the JSON, any photo, and the rebuilt `web/atlas-cuaca/` folder (the
index plus one folder per phenomenon), then push; Cloudflare Pages deploys it.
Old links of the form `/atlas-cuaca/#<id>` still work: they jump to that
phenomenon's own page.
