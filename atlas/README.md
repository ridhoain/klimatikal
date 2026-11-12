# Atlas Cuaca Indonesia

Source for `klimatikal.com/atlas-cuaca/`. One JSON file per phenomenon in
`atlas/phenomena/`; the page is generated from them.

```bash
python3 atlas/build_atlas.py     # rebuilds web/atlas-cuaca/index.html (stdlib only)
```

## Adding a phenomenon

Copy `phenomena/angin-bahorok.json`, rename it to the new slug, and edit. The
file name must equal `id` (it becomes the card's link: `/atlas-cuaca/#slug`).

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
| `scientific` | `{ "id": "...", "en": "..." }`, short |
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
- **While any entry is `draft`, the page is `noindex`** and shows a Draft
  badge and the curator notes. Set `status` to `reviewed` once the text,
  sources and photo have been checked. When none are drafts, the page is
  indexable.

## Publishing

Commit the JSON, the photo and the rebuilt `web/atlas-cuaca/index.html`, then
push; Cloudflare Pages deploys it.
