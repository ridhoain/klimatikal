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

## Publishing

Commit the JSON, any photo, and the rebuilt `web/atlas-cuaca/` folder (the
index plus one folder per phenomenon), then push; Cloudflare Pages deploys it.
Old links of the form `/atlas-cuaca/#<id>` still work: they jump to that
phenomenon's own page.
