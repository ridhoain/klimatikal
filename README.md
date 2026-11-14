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
