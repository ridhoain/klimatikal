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
| `heat` | Is it dangerous to work outdoors? | NWS heat index, cloud haze (less sun), wind |
| `synoptic` | What is the big-picture pattern? | precipitation rate (mm/h, from the 3-hour totals) on a white map (same colours as the Precipitation layer, continuous colour bar), sea-level pressure isobars (blue low, red high) with values on the lines and H / L at the centres, 850 hPa wind |

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
