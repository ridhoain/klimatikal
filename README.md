# Klimatikal

A weather map built from ECMWF open data, served as static files. No tile
server, no runtime backend: a scheduled job turns GRIB into PNG textures that
carry real values, and the browser colours them on the GPU.

```
pipeline/   fetch, decode, encode, upload  (runs 4x a day, nothing serves from it)
web/        the map page                   (static, deployed to Cloudflare Pages)
```

## Try it locally in five minutes

No accounts, no network access to ECMWF needed for this first pass.

```bash
cd pipeline
pip install numpy pillow                       # the full list is requirements.txt
python test_encoding.py                        # round-trip test + real file sizes
python build_run.py --dry-run --offline --steps 0,3,6,9,12 --dest ../web/data

cd ../web
python3 -m http.server 8000
# open http://localhost:8000/?data=./data
```

You should get a map with moving wind particles, a working time slider, and a
value readout on hover. The fields are synthetic in `--offline` mode; they are
shaped like weather but they are not weather.

## Against real data

```bash
pip install -r pipeline/requirements.txt
python pipeline/build_run.py --dry-run --steps 0,3,6 --dest ./out
```

This downloads from ECMWF. Before trusting it, check that every parameter in
`ALL_PARAMS` is actually published in the open-data subset for the cycle you
are pulling: the list is set in `encoding.py` and the live index is at
<https://data.ecmwf.int/forecasts/>.

## Publishing

```bash
export R2_ACCOUNT_ID=... R2_ACCESS_KEY_ID=... R2_SECRET_ACCESS_KEY=... R2_BUCKET=klimatikal-data
python pipeline/build_run.py
```

Every file of the run is uploaded before `latest.json` is written, so a crash
at any earlier point leaves the previous run live.

## Presets

A preset is one information goal as a stack of layers drawn bottom to top, the
`PRESETS` table in `web/index.html`. Each entry is a `fill` (a colour field, its
colours in `RAMPS`), a `contour` (isolines of a layer) or `particles` (the wind
streaks); `main` is the layer the key, hover value and coast colours follow, and
`notes` are the key lines for layers with no colour bar. Picking a plain layer
button clears the preset and the page behaves as before. A preset is offered only
when the run holds every layer it needs, so an older run still loads. The choice
is in the URL as `#preset=<id>`.

| id | question | stack |
|---|---|---|
| `heat` | How hot does it feel outdoors? | UTCI (sun / shade toggle); hatched where wet-bulb is 31 °C or more (Stull; not WBGT); dotted where the estimated UV index is 11 or more (extreme; cloud-adjusted from the forecast radiation, haze and smoke not modelled); cloud haze (less sun); wind |
| `synoptic` | What is the big-picture pattern? | precipitation rate (mm/h, from the 3-hour totals) on a white map (same colours as the Precipitation layer, continuous colour bar), sea-level pressure isobars (blue low, red high) with values on the lines and H / L at the centres, 850 hPa wind |

| `astro` | Where is the sky good tonight? | total cloud cover (overcast is the strong blue, clear sky fades to black at 0 %); light glow from VIIRS night lights (Light pollution button); OVATION aurora probability (Aurora button); an always-on mask that whites out the part of the map still in daylight (lighter veil for twilight); Day/Night lines with an 18° astronomical-night line and the Moon's rise/set line and phase icon |

**Stargazing (`astro`).** It needs only the `cloud` layer from the run; the two overlays are separate files and a button appears only when its file loads. The preset forces the Day/Night lines on while it is selected (`astro: true`), adding the violet 18° line, the Moon line (ticks on the side where the Moon is down) and a 16-phase Moon icon at the sub-lunar point; the Moon is computed in the browser (`moonAt`, Meeus' abbreviated series, about half a degree, no pipeline data). Each overlay has a colour legend, and hovering the aurora opens a pop-up with its chance and where to look, and hovering a day/night, twilight or Moon line explains it in a sentence. Hover reads "Astronomical night · sun −58° · Moon down, 11% lit", plus aurora % and the light-glow class where those are on.

- *Aurora*: `pipeline/aurora.py` reads NOAA SWPC's OVATION grid and Kp every 15 minutes (`.github/workflows/aurora.yml`) and writes `aurora/ovation.png` (360 x 181, value 0 to 100 in R) and `aurora/aurora.json` (JSON last). OVATION is a nowcast for about the next hour, so the page shows it only within 3 hours of its `forecast_time` (`ASTRO.auroraWindowH`); outside that the button is dimmed. Tests: `python -m pytest pipeline/test_aurora.py`.
- *Light pollution*: `pipeline/darksky.py` turns an annual night-lights GeoTIFF into `darksky/lights.png` (0.1°, value in R) and `darksky/darksky.json` (`units` says how to decode it). The default source (`--kind harmonized`) is the Li et al. harmonized DMSP + VIIRS series, 1992 to 2024, CC BY 4.0, no login, about 30 MB a year from <https://doi.org/10.6084/m9.figshare.9828827> (`Harmonized_DN_NTL_<year>_simVIIRS.tif`). It is a 0 to 63 index on the old DMSP scale, not radiance, with city cores saturated at 63, and covers 75 N to 65 S; the page therefore names classes (Dark, Faint glow, Moderate, Bright, Very bright, City centre) and quotes no number. `--kind vnl` still reads the EOG VNL v2.2 radiance composite (log scale, `units: "nw"`, never run on a real file). It is static: rerun when a new year is published, then upload `darksky/`.

        python pipeline/darksky.py --src Harmonized_DN_NTL_2024_simVIIRS.tif --year 2024 --dest ../web/data

  Run on the 2024 file it takes 6 s and 1.3 GB and writes a 0.56 MB image. The glow is spread with a 0.25° Gaussian, so this is a **light-pollution proxy, not sky brightness or a Bortle class**: it understates the glow of a big city far away. `--synthetic` makes a made-up field for testing (flagged `"synthetic": true`; never publish it). A Falchi-style propagation model would be the upgrade.
- Both overlays are drawn under the weather layer as MapLibre image sources (a PNG data URL from a canvas, projected to Web Mercator), so cloud veils them. A canvas source lost the transparency, hence the data URL.
- Tests: `python -m pytest pipeline/test_darksky.py` (block reduction, spread, both encodings, the harmonized reader on a synthetic raster).

The heat preset reads `utci_sun` / `utci_shade`, computed in `pipeline/thermal.py` (ERA5-HEAT-style mean radiant temperature from the accumulated `ssrd`, `ssr`, `strd`, `str`, then pythermalcomfort's UTCI). Checked against ERA5-HEAT for one day (see `docs/utci-validation.md`): daytime UTCI in sun is about +0.8 °C warm, RMSE 1.4 °C; shade mode has no reference. Step 0 has no radiation window and carries no sun term. `wetbulb` and `uvi` come from the same module. UV is clear-sky UVI (12.5 mu0^2.42 (O3/300)^-1.23, ozone fixed at 255 DU) times the ratio of forecast to Haurwitz clear-sky radiation; `UVI_SCALE` and `CLOUD_K` in `thermal.py` are the tuning knobs, and it has not yet been compared with BMKG or satellite UV. A run without the UTCI layers falls back to the older `heatlegacy` preset (NWS heat index).

Two pipeline consequences. `heatindex` is derived in `encoding.py` from the 2 m
temperature and dewpoint (`2d`), so the map and the hover value read the same
bytes; it is the shade, light-wind NWS index, and full sun adds several degrees.
`msl` is 16-bit, because isobars drawn from 8-bit pressure come out as thick
bands in the tropics (a dozen distinct levels over 20 x 30 degrees). The
synoptic preset also uses 850 hPa wind (`wind850`); the pressure-level wind is a second request per step
(`levtype=pl`). The contour numbers and the H / L markers are not drawn by the
shader: the page traces the same pressure field on the CPU (`traceContours`,
`findExtrema` in `web/index.html`) and gives MapLibre lines and points to label.
An H / L is the biggest or smallest value within 4 degrees and at least 1.5 hPa
off the surrounding ring; over high ground sea-level pressure is a reduction to
a surface below the terrain, so centres there are not physical.

The Day/Night button (time bar, next to Local / UTC; `#night=1`) shows where it is day and night, as
lines only so no weather colour is tinted: a solid terminator with ticks on the
dark side, dashed civil (6°) and nautical (12°) twilight lines, and a sun at the
point where it is overhead. It is computed in the browser from the date of the
time being shown (no pipeline data), follows the time slider, and adds
"Day / Twilight / Night · sun elevation" to the hover box.

Mean sea level pressure over high ground (Tibet, the Andes, Greenland,
Antarctica) is the surface pressure reduced through kilometres of rock, which
turns terrain roughness into pressure noise. The pipeline therefore blends `msl`
into a heavily smoothed copy (2.5 degrees) where the surface pressure is below
930 hPa, fully below 830 hPa, using `sp` of the first step so it does not
flicker (`smooth_over_terrain` in `encoding.py`, revision 7). Lowlands are
untouched. The browser also blurs the isobar field by 3 grid cells (`ISO_BLUR`).

Wind streaks in Synoptic overview are coloured by the sea-level pressure under their head (`tint` on the particles item), with the isobar colours, so a streak shows which isobar it is on; they are one pixel wide inside a light edge so the colour holds on dark and light cloud. Isobars themselves are plain coloured lines.

A preset with `lightBase` (Synoptic overview) switches the map to white: black coast with a soft shadow, dark place names with white outlines, dark wind streaks, and darker isobar colours so they read on white. Other presets keep the dark map.

The wind icon at the end of the layer bar turns the wind streaks on or off for any layer (`#wind=0` when off).

The contour shader interpolates pressure by hand on exact texel centres and takes the line width from the change per grid cell; the hardware filter's 8-bit weights broke flat-field isobars into dashes when zoomed in.

Fronts (Synoptic overview, `fronts: true`): `pipeline/fronts.py` finds them in the 850 hPa wet-bulb temperature (thermal front parameter, Hewson 1998), one GeoJSON per step at `runs/<run>/fronts/fNNN.json` (`fronts: true` in the manifest). The wind across the front decides cold (triangles) or warm (semicircles); a slow front close to a deep low is drawn occluded (both symbols, alternating), which is an approximation. Each line is stored with the side the front moves towards on its left, so the map's line-placed symbols point the right way. Thresholds (2 K per 100 km, about 700 km long, poleward of 10 degrees) are at the top of `fronts.py`. Runs built before revision 8 have none and just show no fronts. The same file carries two kinds of plain black line, with no symbols: the monsoon trough (long faint dashes; where the smoothed 850 hPa westerlies turn to easterlies with latitude, within 20 degrees of the equator) and pressure troughs (short dashes; the axis of strongest upward curvature of the smoothed sea-level pressure, 15 to 70 degrees latitude, off high ground). The front icon beside the cyclone button turns them on or off (`#fronts=0`), and hovering a line explains that kind of front. The symbols are sized to match the thin isobars.

Lows (Synoptic overview, `lows: true`): `pipeline/lows.py` takes the minima of the smoothed sea-level pressure (reusing `find_lows` from `fronts.py`, 25 to 85 degrees latitude), refines each centre on the 0.25 degree grid and joins them from step to step by nearest neighbour (at most 110 km/h plus 150 km of slack, one missed step allowed). A track that never gets to 1000 hPa or lasts under 3 steps is dropped. One file per run, `runs/<run>/lows.json` (`lows: true` in the manifest, revision 11): `{tracks: [{id, min_hpa, min_step, pts: [[step, lon, lat, hpa], ...]}]}`, deepest first. The Lows button (off by default, `#lows=1`) draws a dot with the central pressure at the current step, the path so far solid and the forecast path dashed; clicking a dot gives its deepest pressure and time. The lows carry no names. `web/named-storms.json` is kept by hand (no scraping: the names are copied from the Met Office, Met Éireann and KNMI announcements, which also carry the season's list of 21 names): when a storm is named, add `{"name": "Chloe", "by": "Met Office", "time": "2026-11-25T06:00:00Z", "lon": -12.5, "lat": 55.0}` to `storms`, the centre's position at that time from their warning. The page gives the name to the track that passes closest to that point (within 110 km/h of travel since then plus 300 km) and shows "Storm Chloe" with the pressure; no rebuild is needed, only a push of that file. Until a storm is named, `storms` is empty and every low is unnamed.

Presets are listed in the order given by their `order` (Synoptic overview first).

A preset can also carry `hazard`: warning triangles where its field reaches a
named level of the ramp's `marks` (Heat stress: Danger, 41 °C; purple triangle
from Extreme danger, 54 °C). The browser bins the visible cells into blocks of
about 44 screen pixels, joins hot blocks that are close, and draws one triangle
per joined area with its peak value, so areas merge as you zoom out and split as
you zoom in. The legend marks, the hover danger text and the triangles all come
from the same `marks`. Heat index is reached only through the Heat stress
preset (it has no layer button of its own).

The legend is one column. A preset's plain-language reading (`explain`) stays
hidden until the "i" on the legend is pressed (remembered per browser), a
preset's colour keys for layers without a bar (`keys`) get a
box of their own, and a ramp with `marks` (the heat index) draws its named
thresholds across the bar.

These are REVISIONs 4 to 6, so already-published runs rebuild once.

    cd pipeline && python3 build_run.py --dry-run --steps 0,3,6,9,12 --dest ../web/data/preset-test
    # then open http://localhost:8000/?data=./data/preset-test#preset=heat

## The one rule

`encoding.py`, the GLSL in `web/index.html`, and `decodeOnCPU()` in the same
file all implement the same decode. Change one and you must change all three,
then rerun `test_encoding.py`. The map showing one number while the readout
shows another is the failure this prevents.

## Licence and attribution

Forecast data is ECMWF open data under CC BY 4.0. The required attribution
travels in each run's `manifest.json` and the page renders it from there, so
it cannot drift out of sync with the data.

## Satellite layer (Himawari-9 infrared)

`pipeline/himawari.py` builds the newest complete 10-minute full-disk scan of
band 13 (10.4 µm) from the public NOAA copy of JMA's Himawari-9 data
(`s3://noaa-himawari9`, anonymous), reprojects it to Web Mercator over
80–165°E, 25°S–25°N, and publishes `sat/ir/<time>.webp` plus `sat/manifest.json`
(manifest last) to the same R2 bucket as the forecast. `.github/workflows/satellite.yml`
runs it every 10 minutes. Its dependencies (satpy) are in
`requirements-himawari.txt`, separate from the forecast job's. The colour table
travels in the manifest, so the legend is drawn from the numbers that coloured
the image. Credit: Himawari-9 (JMA), via NOAA Open Data.

    python3 himawari.py --dry-run --dest ../web/data    # local test, no R2

### Global mosaic (Himawari-9 + GOES-West + GOES-East)

`pipeline/satglobal.py` merges band 13 from Himawari-9, GOES-18 and GOES-19
(all public NOAA buckets) into one Web Mercator mosaic, 60°S–60°N, cut into four
longitude tiles, and publishes `sat/ir_g/…webp` plus `sat/global.json`
(`.github/workflows/satellite-global.yml`, every 10 minutes, dependencies in
`requirements-satglobal.txt`). Each pixel comes from the satellite looking most
nearly straight down on it. Roughly 0°E–65°E (Africa, Europe, the western Indian
Ocean) has no coverage until Meteosat is added (EUMETSAT account and licence
check needed). The site reads `sat/global.json` first and falls back to
`sat/manifest.json`, so `satellite.yml` can be retired once the mosaic is proven.

    python3 satglobal.py --dry-run --dest ../web/data  # local test, no R2

## Tropical systems (JTWC)

`pipeline/jtwc.py` reads the Joint Typhoon Warning Center's public text products
(the ABPW10 and ABIO10 outlooks, formation alerts, and tropical cyclone
warnings) and publishes one small file, `tropical/tropical.json`, every 30
minutes (`.github/workflows/tropical.yml`; only `boto3` is needed). The page
draws invests as rings coloured by development chance and warned cyclones as
discs coloured by intensity, with past track (solid) and JTWC forecast track
(dashed); a click opens the details. The Storms button in the layer bar (or
`#storms=0`) hides it.

JTWC publishes no past track, so each run adds the newest position to the
previous file's. If JTWC is unreachable the job exits without touching the
last good file. Parser tests use saved real text in `pipeline/fixtures/jtwc/`:
`python3 -m pytest pipeline/test_jtwc.py`. JTWC products are US Government
works; the credit line names JTWC while the layer is on.

### Atlantic and eastern Pacific (NHC), with post-tropical cyclones

`pipeline/nhc.py` (same workflow, own step, so one source failing does not stop the other) reads the National Hurricane Center's `CurrentStorms.json` and, for each storm, the forecast positions from its linked forecast/advisory bulletin. It publishes `tropical/nhc.json` in the same shape as `tropical.json`, with `"src": "NHC"`; the page loads both files and merges them, so either can be missing. Storms of class `PTC` (post-tropical cyclone or remnants, the stage where a hurricane becomes an extratropical low and NHC is still issuing advisories) are flagged `"pt": true`, and their forecast points `"xt": true`; their pop-up says so and points to the Lows layer for the model's own track. `CurrentStorms.json` is empty when nothing is active (as when this was written), so the tests use a real archived bulletin (Post-Tropical Cyclone Lee, 2023-09-17) with the JSON wrapper rebuilt from NHC's documented format: `python3 -m pytest pipeline/test_nhc.py`. NHC products are US Government works; NOAA/NWS names and logos are not to be used without permission, so the credit line names the National Hurricane Center only as the data source. Not yet checked against a live active storm; the JSON field names follow NHC's 2019 reference (`latitude_numeric`, `movementSpeed` in mph) and the reader also accepts the camelCase variants.
