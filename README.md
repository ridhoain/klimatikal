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
