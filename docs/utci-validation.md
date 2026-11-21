# UTCI validation against ERA5-HEAT

One day (5 Nov 2026), Indonesia (8N to 11S, 95E to 141E), 0.25 degree, 21 hourly
steps (03 to 23 UTC), about 300,000 grid-hours. Reference: ERA5-HEAT
`derived-utci-historical` v1.1, intermediate (ERA5T) release. Inputs for our code
are the ERA5 fields behind it (`2t`, `2d`, `10u`, `10v`, `ssrd`, `ssr`, `strd`,
`str`), so only the Tmrt and UTCI step is tested, not the IFS forecast.
Scripts: `pipeline/validation/`.

| configuration | daytime UTCI bias | RMSE | within 1 degC | within 2 degC |
|---|---|---|---|---|
| 1 h window, ERA5's measured direct beam (`fdir`) | +0.24 | 1.13 | 76% | 92% |
| 1 h window, Erbs split | +0.64 | 1.40 | 66% | 87% |
| **3 h window, Erbs split (what the pipeline does)** | **+0.82** | **1.43** | **61%** | **86%** |

Daytime = window-mean cos(zenith) above 0.3. At night the error is 0.9 degC RMSE
in every configuration: that is the floor from regridding and ERA5T versus
ERA5, not a defect in Tmrt.

Reading:
- The Tmrt geometry and the UTCI call are sound: with the measured direct beam,
  daytime Tmrt bias is 0.01 K (RMSE 0.9 K).
- The open data has no direct-beam field, so the Erbs split is the cost of using it:
  Tmrt runs 1.8 K warm on 1 h windows and 2.6 K on 3 h windows; in UTCI that is
  +0.6 to +0.8 degC bias, p95 error 3.0 degC.
- The bias is largest late morning to early afternoon local time (about +1.0 degC at 03 to 06 UTC)
  and near zero after 11 UTC.
- Comparing a step's value with the ERA5-HEAT value at the step end (instead of the
  3 h mean) gives bias +1.0, RMSE 1.7: the forecast steps are 3 h means, so that is not a fair test.

Limits: a single day, one season, ERA5T reference. Shade mode has no reference
(ERA5-HEAT has only a sun-exposed UTCI). Worth repeating on a monsoon-season day
and on a clear-sky day before tuning anything.
