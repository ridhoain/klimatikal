/* /analysis/zom-central-java-aifs/ : map (canvas raster + SVG zones), zone time series and score charts.
   Data: zom-eval.json, zom-map.json, chirps-grid.json + chirps-grid.bin. No libraries (CSP: script-src 'self'). */
(function () {
  "use strict";
  var LANG = document.documentElement.lang === "en" ? "en" : "id";
  var BASE = "/analysis/zom-central-java-aifs/";
  var T = {
    id: { maesWhat: "Skill MAE vs klimatologi", accWhat: "Korelasi anomali", lead: "Lead (hari)", days: "hari", zone: "ZOM",
      obs: "CHIRPS (pengamatan)", fc: "AIFS (prakiraan)", clim: "Klimatologi 1991–2020", mm: "mm per dasarian", bias: "bias",
      date: "Dasarian", noFc: "tanpa prakiraan", err: "Data tidak dapat dimuat.",
      layers: { obs: "Pengamatan CHIRPS", clim: "Klimatologi 1991–2020", anom: "Anomali (pengamatan − klimatologi)", aifs: "Prakiraan AIFS", aerr: "Galat AIFS (AIFS − CHIRPS)", skill: "Skill per zona" }, noAifs: "tidak ada prakiraan AIFS untuk dasarian ini", lgAerr: "mm per dasarian: AIFS lebih kering ← → lebih basah",
      play: "Putar", pause: "Jeda", prev: "Dasarian sebelumnya", next: "Dasarian berikutnya", slider: "Dasarian yang ditampilkan di peta",
      hint: "Arahkan kursor ke peta untuk membaca nilai; klik sebuah zona untuk membuka validasinya.",
      pixel: { obs: "CHIRPS", clim: "klimatologi", anom: "anomali", aifs: "AIFS", aerr: "galat AIFS" }, zmean: "rata-rata zona", noZ: "tidak ada data zona untuk dasarian ini",
      lgObs: "mm per dasarian", lgAnom: "mm per dasarian: lebih kering ← → lebih basah", lgSkill: "skill MAE (0 = sama dengan klimatologi)", lgAcc: "korelasi anomali",
      sea: "Putih: laut atau tidak ada data", climFor: "rata-rata 1991–2020 untuk dasarian ini",
      area: "Luas", cells: "piksel CHIRPS", inJt: "di dalam Jawa Tengah",
      pooled: "Termasuk dalam rata-rata 10 ZOM pada hasil utama.",
      small: "Zona ini terlalu kecil untuk grid model (kurang dari 28 piksel CHIRPS, sekitar satu sel model 0,25°). Hasilnya tidak dipakai untuk kesimpulan.",
      partial: "Hanya sebagian zona ini berada di dalam Jawa Tengah (kurang dari 80%), sehingga dinilai terpisah dari rata-rata 10 ZOM.",
      metricAria: "Ukuran", leadAria: "Skill rata-rata 10 ZOM menurut lead, dengan selang kepercayaan 95%",
      tsAria: "Total curah hujan per dasarian: pengamatan CHIRPS, prakiraan AIFS dan klimatologi", skMetric: "Ukuran", skLead: "Lead", zoneSel: "Zona",
      scLead: "Lead", scSkill: "Skill MAE", scAcc: "Korelasi anomali", scBias: "Bias (mm)", tbl: "Tabel angka", mapAria: "Peta zona musim Jawa Tengah dengan curah hujan CHIRPS" },
    en: { maesWhat: "MAE skill vs climatology", accWhat: "Anomaly correlation", lead: "Lead (days)", days: "days", zone: "ZOM",
      obs: "CHIRPS (observed)", fc: "AIFS (forecast)", clim: "Climatology 1991–2020", mm: "mm per ten days", bias: "bias",
      date: "Period", noFc: "no forecast", err: "Could not load the data.",
      layers: { obs: "CHIRPS observed", clim: "Climatology 1991–2020", anom: "Anomaly (observed − climatology)", aifs: "AIFS forecast", aerr: "AIFS error (AIFS − CHIRPS)", skill: "Skill by zone" }, noAifs: "no AIFS forecast for this period", lgAerr: "mm per ten days: AIFS drier ← → AIFS wetter",
      play: "Play", pause: "Pause", prev: "Previous ten-day period", next: "Next ten-day period", slider: "Ten-day period shown on the map",
      hint: "Hover over the map to read values; click a zone to open its validation.",
      pixel: { obs: "CHIRPS", clim: "climatology", anom: "anomaly", aifs: "AIFS", aerr: "AIFS error" }, zmean: "zone mean", noZ: "no zone data for this period",
      lgObs: "mm per ten days", lgAnom: "mm per ten days: drier ← → wetter", lgSkill: "MAE skill (0 = same as climatology)", lgAcc: "anomaly correlation",
      sea: "White: sea or no data", climFor: "1991–2020 mean for this ten-day period",
      area: "Area", cells: "CHIRPS pixels", inJt: "inside Central Java",
      pooled: "Included in the 10-zone average in the headline results.",
      small: "This zone is too small for the model grid (fewer than 28 CHIRPS pixels, about one 0.25° model cell). Its result is not used for conclusions.",
      partial: "Only part of this zone lies inside Central Java (under 80%), so it is scored separately from the 10-zone average.",
      metricAria: "Measure", leadAria: "Average skill of 10 zones by lead, with 95% confidence intervals",
      tsAria: "Rainfall total per ten-day period: CHIRPS observation, AIFS forecast and climatology", skMetric: "Measure", skLead: "Lead", zoneSel: "Zone",
      scLead: "Lead", scSkill: "MAE skill", scAcc: "Anomaly corr.", scBias: "Bias (mm)", tbl: "Table of values", mapAria: "Map of Central Java seasonal zones with CHIRPS rainfall" }
  }[LANG];
  var MONTHS = LANG === "id" ? ["Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des"] : ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  var NS = "http://www.w3.org/2000/svg", LOC = LANG === "id" ? "id-ID" : "en-US";
  function $(id) { return document.getElementById(id); }
  function el(n, a, kids) {
    var e = document.createElementNS(NS, n);
    for (var k in (a || {})) e.setAttribute(k, a[k]);
    (kids || []).forEach(function (c) { e.appendChild(typeof c === "string" ? document.createTextNode(c) : c); });
    return e;
  }
  function h(tag, a, text) { var e = document.createElement(tag); for (var k in (a || {})) e.setAttribute(k, a[k]); if (text != null) e.textContent = text; return e; }
  function fmt(x, d) { var a = Math.abs(x).toFixed(d == null ? 2 : d); return (x < 0 && +a !== 0 ? "−" : "") + a; }
  function sgn(x, d) { return (x > 0 ? "+" : "") + fmt(x, d); }
  function pct(x) { return (Math.round(x * 100) + "%").replace("-", "−"); }
  function pctRange(t) { return pct(t[1]) + "–" + pct(t[2]); }
  function niceTicks(lo, hi, n) {
    var span = hi - lo, step = Math.pow(10, Math.floor(Math.log10(span / n))), err = (n / span) * step;
    step *= err <= .15 ? 10 : err <= .35 ? 5 : err <= .75 ? 2 : 1;
    var t = [], v = Math.ceil(lo / step) * step; for (; v <= hi + 1e-9; v += step) t.push(+v.toFixed(10)); return t;
  }
  function width(node) { return Math.max(260, Math.floor(node.getBoundingClientRect().width) || 600); }
  function num(x) { return x.toLocaleString(LOC); }

  // ---------- colours ----------
  function hex(c) { return [parseInt(c.slice(1, 3), 16), parseInt(c.slice(3, 5), 16), parseInt(c.slice(5, 7), 16)]; }
  function ramp(stops, v) {            // stops: [[value, "#rrggbb"], ...] ascending
    if (v <= stops[0][0]) return hex(stops[0][1]);
    for (var i = 1; i < stops.length; i++) if (v <= stops[i][0]) {
      var a = stops[i - 1], b = stops[i], f = (v - a[0]) / (b[0] - a[0]), ca = hex(a[1]), cb = hex(b[1]);
      return [0, 1, 2].map(function (k) { return Math.round(ca[k] + (cb[k] - ca[k]) * f); });
    }
    return hex(stops[stops.length - 1][1]);
  }
  var SEQ = [[0, "#efe9d4"], [20, "#cfe6cf"], [50, "#8fd0bd"], [100, "#42a5b8"], [160, "#2c6fb0"], [240, "#2b3a8f"], [320, "#1a0f55"]];
  var ANOM_SPAN = 100, NEU = "#e6e6e6";
  var DIVA = [[-ANOM_SPAN, "#b35806"], [0, NEU], [ANOM_SPAN, "#2166ac"]];
  function skillStops(s) { return [[-s, "#c2447a"], [0, NEU], [s, "#1b8a6b"]]; }
  var SKSPAN = { MAESS: 0.5, ACC: 0.8 };
  var LUT = []; for (var b0 = 0; b0 < 255; b0++) LUT.push(ramp(SEQ, Math.pow(b0 / 7, 2)));
  function css(c, a) { return "rgba(" + c[0] + "," + c[1] + "," + c[2] + "," + (a == null ? 1 : a) + ")"; }

  var D, M, G, bin, NT, CELL;
  var layer = "obs", t = 0, zone = "133", skLead = 0, skMetric = "MAESS", lmetric = "MAESS", playing = null;
  var canvas, ctx, img, svg, zonesG, labG, VW, VH, zpath = {}, zlab = [], hoverZ = null, hoverPix = null;
  var COS = Math.cos(7 * Math.PI / 180);

  // ---------- dekad labels ----------
  function lastDay(y, m) { return new Date(Date.UTC(y, m, 0)).getUTCDate(); }
  function dekadLabel(d, noYear) {
    var y = +d.slice(0, 4), m = +d.slice(5, 7), day = +d.slice(8, 10), end = day === 1 ? 10 : day === 11 ? 20 : lastDay(y, m);
    return day + "–" + end + " " + MONTHS[m - 1] + (noYear ? "" : " " + y);
  }

  // ---------- map ----------
  function px(lon) { return (lon - M.window[0]) * COS * 1000; }
  function py(lat) { return (M.window[3] - lat) * 1000; }
  function pathOf(rings) { return rings.map(function (r) { return "M" + r.map(function (p) { return px(p[0]).toFixed(1) + " " + py(p[1]).toFixed(1); }).join("L") + "Z"; }).join(""); }
  function centroid(ring) {
    var A = 0, cx = 0, cy = 0;
    for (var i = 0, n = ring.length - 1; i < n; i++) {
      var x0 = px(ring[i][0]), y0 = py(ring[i][1]), x1 = px(ring[i + 1][0]), y1 = py(ring[i + 1][1]), c = x0 * y1 - x1 * y0;
      A += c; cx += (x0 + x1) * c; cy += (y0 + y1) * c;
    }
    return A ? [cx / (3 * A), cy / (3 * A)] : [px(ring[0][0]), py(ring[0][1])];
  }
  function ringArea(r) { var a = 0; for (var i = 0; i < r.length - 1; i++) a += r[i][0] * r[i + 1][1] - r[i + 1][0] * r[i][1]; return Math.abs(a / 2); }

  function buildMap() {
    var box = $("mapbox"); box.textContent = "";
    var W0 = M.window[0], S0 = M.window[1], E0 = M.window[2], N0 = M.window[3];
    VW = Math.round((E0 - W0) * COS * 1000); VH = Math.round((N0 - S0) * 1000);
    canvas = h("canvas", { width: G.nx, height: G.ny, "aria-hidden": "true" }); ctx = canvas.getContext("2d"); img = ctx.createImageData(G.nx, G.ny);
    box.appendChild(canvas);
    svg = el("svg", { viewBox: "0 0 " + VW + " " + VH, preserveAspectRatio: "none", role: "img", "aria-label": T.mapAria });
    function poly(cls, lines) { return lines.map(function (l) { return el("path", { class: cls, d: "M" + l.map(function (p) { return px(p[0]).toFixed(1) + " " + py(p[1]).toFixed(1); }).join("L") }); }); }
    var sea = "M0 0H" + VW + "V" + VH + "H0Z" + M.land.map(function (r) { return "M" + r.map(function (q) { return px(q[0]).toFixed(1) + " " + py(q[1]).toFixed(1); }).join("L") + "Z"; }).join("");
    svg.appendChild(el("path", { class: "sea", d: sea, "fill-rule": "evenodd" }));
    poly("coast", M.coast).forEach(function (p) { svg.appendChild(p); });
    poly("border", M.borders).forEach(function (p) { svg.appendChild(p); });
    zonesG = el("g"); labG = el("g");
    M.zones.forEach(function (z) {
      var info = D.zones[z.id], p = el("path", { class: "zone" + (info.pooled ? "" : " small"), d: pathOf(z.rings), "data-z": z.id });
      zpath[z.id] = p; zonesG.appendChild(p);
      if (info.area_km2 >= 700 && z.rings.length) {
        var big = z.rings.slice().sort(function (a, b) { return ringArea(b) - ringArea(a); })[0], c = centroid(big);
        var tx = el("text", { class: "zlab", x: c[0].toFixed(0), y: c[1].toFixed(0) }, [z.id]); zlab.push(tx); labG.appendChild(tx);
      }
    });
    svg.appendChild(zonesG); svg.appendChild(labG); box.appendChild(svg);
    fitLabels();
    svg.addEventListener("pointermove", onMove);
    svg.addEventListener("pointerleave", function () { hoverZ = null; hoverPix = null; showHover(); });
    svg.addEventListener("click", function (ev) { var z = ev.target.getAttribute && ev.target.getAttribute("data-z"); if (z) selectZone(z); });
  }
  function fitLabels() {
    var w = $("mapbox").getBoundingClientRect().width || 600, k = VW / w;
    zlab.forEach(function (x) { x.style.fontSize = (11 * k).toFixed(1) + "px"; x.style.strokeWidth = (3 * k).toFixed(1) + "px"; });
  }
  function cellAt(ev) {
    var r = svg.getBoundingClientRect(), fx = (ev.clientX - r.left) / r.width, fy = (ev.clientY - r.top) / r.height;
    var ix = Math.floor(fx * G.nx), iy = Math.floor(fy * G.ny);
    return ix >= 0 && ix < G.nx && iy >= 0 && iy < G.ny ? iy * G.nx + ix : -1;
  }
  function onMove(ev) {
    var tg = ev.target, z = tg.getAttribute && tg.getAttribute("data-z"); hoverZ = z || null;
    hoverPix = tg.getAttribute && tg.getAttribute("class") === "sea" ? null : cellAt(ev); showHover();
  }
  var aif = null, aifLoading = false, aifAny = true, LEADL = { aifs: 1, aerr: 1, skill: 1 };
  function loadAifs() {
    if (aif || aifLoading) return; aifLoading = true;
    fetch(BASE + "aifs-grid.bin").then(function (r) { if (!r.ok) throw new Error(r.status); return r.arrayBuffer(); })
      .then(function (ab) { aif = new Uint8Array(ab); drawRaster(); timeLabel(); showHover(); })
      .catch(function () { aifLoading = false; $("map-hover").textContent = T.err; });
  }
  function mmOf(b) { return b === 255 ? null : Math.pow(b / 7, 2); }
  function pixelMM(i) {   // [observed, climatology, AIFS at the chosen lead] in mm, or null
    var bo = bin[t * CELL + i], bc = bin[(NT + G.doy[t]) * CELL + i], ba = aif ? aif[(skLead * NT + t) * CELL + i] : 255;
    return [mmOf(bo), mmOf(bc), mmOf(ba)];
  }
  function zoneText(z) {
    var S = D.series.zones[z];
    if (layer === "skill") {
      var v = D.zones[z].leads[skLead][skMetric];
      return v[0] == null ? "–" : (skMetric === "MAESS" ? T.maesWhat : T.accWhat) + " " + fmt(v[0]) + " [" + fmt(v[1]) + ", " + fmt(v[2]) + "] · " + T.skLead.toLowerCase() + " " + skLead;
    }
    var si = D.series.dekads.indexOf(G.dekads[t]);
    if (si < 0) return T.noZ;
    var o = S.obs[si], c = S.clim[si];
    if (layer === "aifs" || layer === "aerr") {
      var f = skLead === 0 ? S.aifs0[si] : skLead === 3 ? S.aifs3[si] : undefined;
      if (f === undefined) return "";
      if (f == null) return T.noAifs;
      return layer === "aifs" ? T.zmean + " " + fmt(f, 0) + " mm" : T.zmean + " " + sgn(f - o, 0) + " mm (" + fmt(f, 0) + " / " + fmt(o, 0) + ")";
    }
    return layer === "obs" ? T.zmean + " " + fmt(o, 0) + " mm" : layer === "clim" ? T.zmean + " " + fmt(c, 0) + " mm" : T.zmean + " " + sgn(o - c, 0) + " mm (" + fmt(o, 0) + " / " + fmt(c, 0) + ")";
  }
  function showHover() {
    var parts = [];
    if (hoverZ) { var zt = zoneText(hoverZ); parts.push("<b>" + T.zone + " " + hoverZ + "</b>" + (zt ? " · " + zt : "")); }
    if (layer !== "skill" && hoverPix != null && hoverPix >= 0) {
      var v = pixelMM(hoverPix), o = v[0], c = v[1], a = v[2];
      if (o != null) {
        if (layer === "obs") parts.push(T.pixel.obs + " <b>" + fmt(o, 0) + " mm</b>");
        else if (layer === "clim") parts.push(T.pixel.clim + " <b>" + fmt(c, 0) + " mm</b>");
        else if (layer === "anom") parts.push(T.pixel.anom + " <b>" + sgn(o - c, 0) + " mm</b> (" + fmt(o, 0) + " / " + fmt(c, 0) + ")");
        else if (a != null) parts.push(layer === "aifs" ? T.pixel.aifs + " <b>" + fmt(a, 0) + " mm</b> (CHIRPS " + fmt(o, 0) + ")" : T.pixel.aerr + " <b>" + sgn(a - o, 0) + " mm</b> (" + fmt(a, 0) + " / " + fmt(o, 0) + ")");
      }
    }
    $("map-hover").innerHTML = parts.length ? parts.join("<br>") : T.hint;
  }

  function drawRaster() {
    if (layer === "skill") { canvas.style.visibility = "hidden"; return; }
    canvas.style.visibility = "visible";
    if (LEADL[layer]) loadAifs();
    var d = img.data, o = t * CELL, c = (NT + G.doy[t]) * CELL, ao = (skLead * NT + t) * CELL; aifAny = false;
    for (var i = 0; i < CELL; i++) {
      var bo = bin[o + i], bc = bin[c + i], ba = aif ? aif[ao + i] : 255, rgb = null;
      if (ba !== 255) aifAny = true;
      if (layer === "obs") rgb = bo === 255 ? null : LUT[bo];
      else if (layer === "clim") rgb = bc === 255 ? null : LUT[bc];
      else if (layer === "aifs") rgb = ba === 255 ? null : LUT[ba];
      else if (layer === "aerr") { if (bo !== 255 && ba !== 255) rgb = ramp(DIVA, Math.pow(ba / 7, 2) - Math.pow(bo / 7, 2)); }
      else if (bo !== 255 && bc !== 255) rgb = ramp(DIVA, Math.pow(bo / 7, 2) - Math.pow(bc / 7, 2));
      var j = i * 4;
      if (rgb) { d[j] = rgb[0]; d[j + 1] = rgb[1]; d[j + 2] = rgb[2]; d[j + 3] = 255; } else d[j + 3] = 0;
    }
    ctx.putImageData(img, 0, 0);
  }
  function styleZones() {
    Object.keys(zpath).forEach(function (id) {
      var p = zpath[id];
      if (layer === "skill") {
        var v = D.zones[id].leads[skLead][skMetric][0];
        p.style.fill = v == null ? "rgba(128,128,128,.35)" : css(ramp(skillStops(SKSPAN[skMetric]), v), .94); p.setAttribute("class", p.getAttribute("class").replace(/ ?sk/g, "") + " sk");
      } else { p.style.fill = ""; p.setAttribute("class", p.getAttribute("class").replace(/ ?sk/g, "")); }
    });
    selectStyle();
  }
  function selectStyle() {
    Object.keys(zpath).forEach(function (id) { var p = zpath[id], on = / sel/.test(p.getAttribute("class")); if (on && id !== zone) p.setAttribute("class", p.getAttribute("class").replace(/ ?sel/g, "")); });
    var p = zpath[zone]; if (p && !/ sel/.test(p.getAttribute("class"))) p.setAttribute("class", p.getAttribute("class") + " sel");
    if (p) zonesG.appendChild(p);
  }

  function legend() {
    var host = $("legend"), grad, ticks, title, pos;
    if (layer === "obs" || layer === "clim" || layer === "aifs") {
      title = T.lgObs + (layer === "aifs" ? " · " + T.skLead.toLowerCase() + " " + skLead : ""); pos = function (v) { return Math.sqrt(v / 320); };
      grad = SEQ.map(function (s) { return s[1] + " " + (pos(s[0]) * 100).toFixed(1) + "%"; }).join(",");
      ticks = [0, 10, 25, 50, 100, 200, 300].map(function (v) { return [pos(v), String(v)]; });
    } else if (layer === "anom" || layer === "aerr") {
      title = layer === "aerr" ? T.lgAerr + " · " + T.skLead.toLowerCase() + " " + skLead : T.lgAnom; pos = function (v) { return (v + ANOM_SPAN) / (2 * ANOM_SPAN); };
      grad = DIVA.map(function (s) { return s[1] + " " + (pos(s[0]) * 100).toFixed(1) + "%"; }).join(",");
      ticks = [-100, -50, 0, 50, 100].map(function (v) { return [pos(v), v === 0 ? "0" : sgn(v, 0)]; });
    } else {
      var s = SKSPAN[skMetric]; title = (skMetric === "MAESS" ? T.lgSkill : T.lgAcc) + " · " + T.skLead.toLowerCase() + " " + skLead;
      pos = function (v) { return (v + s) / (2 * s); };
      grad = skillStops(s).map(function (x) { return x[1] + " " + (pos(x[0]) * 100).toFixed(1) + "%"; }).join(",");
      ticks = [-s, -s / 2, 0, s / 2, s].map(function (v) { return [pos(v), v === 0 ? "0" : sgn(v, 2)]; });
    }
    host.textContent = "";
    host.appendChild(h("p", { class: "lg-title" }, title));
    var g = h("div", { class: "lg-grad" }); g.style.background = "linear-gradient(to right," + grad + ")"; host.appendChild(g);
    var tk = h("div", { class: "lg-ticks", "aria-hidden": "true" });
    ticks.forEach(function (x) { var sp = h("span", {}, x[1]); sp.style.left = (x[0] * 100).toFixed(1) + "%"; tk.appendChild(sp); });
    host.appendChild(tk);
    if (layer !== "skill") host.appendChild(h("p", { class: "lg-sea" }, T.sea));
  }

  function timeLabel() {
    var d = G.dekads[t];
    $("t-out").textContent = layer === "clim" ? dekadLabel(d, true) + " · " + T.climFor : dekadLabel(d) + (LEADL[layer] && aif && !aifAny ? " · " + T.noAifs : "");
  }
  function setTime(i) {
    t = Math.max(0, Math.min(NT - 1, i)); $("t-range").value = t; timeLabel();
    if (layer !== "skill") drawRaster();
    timeLabel(); showHover(); tsCursor();
  }
  function setLayer(l) {
    layer = l; stop();
    Array.prototype.forEach.call($("layer-ctl").children, function (b) { b.setAttribute("aria-pressed", b.getAttribute("data-l") === l ? "true" : "false"); });
    $("timebar").hidden = l === "skill"; $("skill-ctl").hidden = !LEADL[l]; $("sk-metric").hidden = l !== "skill";
    drawRaster(); styleZones(); legend(); timeLabel(); showHover();
  }
  function play() {
    if (playing) { stop(); return; }
    $("t-play").textContent = "⏸"; $("t-play").setAttribute("aria-label", T.pause);
    playing = setInterval(function () { setTime(t >= NT - 1 ? 0 : t + 1); }, 650);
  }
  function stop() { if (playing) { clearInterval(playing); playing = null; } var b = $("t-play"); if (b) { b.textContent = "▶"; b.setAttribute("aria-label", T.play); } }

  // ---------- zone panel ----------
  function selectZone(z) {
    zone = String(z); $("zone-sel").value = zone; selectStyle(); zonePanel(); tsChart(); showHover();
  }
  function zonePanel() {
    var Z = D.zones[zone];
    $("zp-title").textContent = T.zone + " " + zone;
    $("zp-facts").textContent = T.area + " " + num(Z.area_km2) + " km² · " + Z.cells.toFixed(0) + " " + T.cells + " · " + Math.round(Z.frac_in_jateng * 100) + "% " + T.inJt;
    var w = $("zp-warn"); w.textContent = ""; w.className = "";
    var msg = Z.pooled ? T.pooled : Z.cells < 28 ? T.small : T.partial;
    if (Z.pooled) { w.className = "zfacts"; } else { w.className = "zwarn"; }
    w.textContent = msg;
    var rows = "<tr><th>" + T.scLead + "</th><th>" + T.scSkill + "</th><th>" + T.scAcc + "</th><th>" + T.scBias + "</th></tr>";
    for (var l = 0; l < 6; l++) {
      var L = Z.leads[l], f = function (v) { return v[0] == null ? "–" : fmt(v[0]) + " <small>[" + fmt(v[1]) + ", " + fmt(v[2]) + "]</small>"; };
      rows += "<tr><td>" + l + " " + T.days + "</td><td>" + f(L.MAESS) + "</td><td>" + f(L.ACC) + "</td><td>" + fmt(L.bias[0], 0) + "</td></tr>";
    }
    $("zp-scores").innerHTML = '<table class="sc">' + rows + "</table>";
  }

  // ---------- zone time series ----------
  var ts = null;
  function tsChart() {
    var host = $("fig-ts"), S = D.series.zones[zone], dek = D.series.dekads, n = dek.length, lead = $("ts-lead").value;
    host.textContent = "";
    var W = width(host), H = 260, m = { l: 44, r: 12, t: 30, b: 34 };
    var items = [["l-obs", T.obs], ["l-fc", T.fc + " · " + T.skLead.toLowerCase() + " " + lead], ["l-clim", T.clim]], pos = [], lx0 = m.l, row = 0;
    items.forEach(function (it) {
      var w = 28 + it[1].length * 6.2 + 14;
      if (lx0 + w - 14 > W - m.r && lx0 > m.l) { row++; lx0 = m.l; }
      pos.push([lx0, row]); lx0 += w;
    });
    m.t = 30 + row * 18; H += row * 18;
    var fc = S["aifs" + lead], all = S.obs.concat(S.clim, fc).filter(function (v) { return v != null; });
    var ymax = Math.max.apply(null, all) * 1.06, ticks = niceTicks(0, ymax, 5); ymax = Math.max(ymax, ticks[ticks.length - 1]);
    var t0 = Date.parse(dek[0]), t1 = Date.parse(dek[n - 1]);
    var x = function (i) { return m.l + (W - m.l - m.r) * (Date.parse(dek[i]) - t0) / (t1 - t0); };
    var y = function (v) { return m.t + (H - m.t - m.b) * (1 - v / ymax); };
    var s = el("svg", { viewBox: "0 0 " + W + " " + H, width: W, height: H, "aria-hidden": "true" });
    ticks.forEach(function (tk) {
      s.appendChild(el("line", { class: "grid", x1: m.l, x2: W - m.r, y1: y(tk), y2: y(tk) }));
      s.appendChild(el("text", { x: m.l - 8, y: y(tk) + 4, "text-anchor": "end" }, [String(tk)]));
    });
    var seen = {}, step = W < 520 ? 3 : 2;
    dek.forEach(function (d, i) {
      var mo = +d.slice(5, 7) - 1, key = d.slice(0, 7);
      if (d.slice(8, 10) === "01" && !seen[key] && mo % step === (step === 3 ? 2 : 0)) {
        seen[key] = 1; s.appendChild(el("line", { class: "grid", x1: x(i), x2: x(i), y1: m.t, y2: H - m.b }));
        s.appendChild(el("text", { x: x(i), y: H - m.b + 16, "text-anchor": "middle" }, [MONTHS[mo] + (mo === 0 || i === 0 ? " " + d.slice(2, 4) : "")]));
      }
    });
    function path(arr) {
      var d = "", pen = false;
      arr.forEach(function (v, i) { if (v == null) { pen = false; return; } d += (pen ? "L" : "M") + x(i).toFixed(1) + " " + y(v).toFixed(1); pen = true; });
      return d;
    }
    s.appendChild(el("path", { class: "l-clim", d: path(S.clim) }));
    s.appendChild(el("path", { class: "l-obs", d: path(S.obs) }));
    s.appendChild(el("path", { class: "l-fc", d: path(fc) }));
    var lg = el("g", { class: "legend" });
    items.forEach(function (it, k) {
      var lx = pos[k][0], ly = 12 + pos[k][1] * 18;
      lg.appendChild(el("line", { class: it[0], x1: lx, x2: lx + 22, y1: ly, y2: ly }));
      lg.appendChild(el("text", { x: lx + 28, y: ly + 4 }, [it[1]]));
    });
    s.appendChild(lg);
    var hov = el("line", { class: "hov", y1: m.t, y2: H - m.b, x1: -10, x2: -10 }), cur = el("line", { class: "cursor", y1: m.t, y2: H - m.b, x1: -10, x2: -10 });
    s.appendChild(hov); s.appendChild(cur); host.appendChild(s);
    host.setAttribute("aria-label", T.tsAria + " – " + T.zone + " " + zone);
    ts = { x: x, n: n, S: S, fc: fc, cur: cur, hov: hov, dek: dek };
    function nearest(ev) {
      var r = s.getBoundingClientRect(), p = (ev.clientX - r.left) * (W / r.width), best = 0, bd = 1e9;
      for (var i = 0; i < n; i++) { var dd = Math.abs(x(i) - p); if (dd < bd) { bd = dd; best = i; } }
      return best;
    }
    s.addEventListener("pointermove", function (ev) { var i = nearest(ev); hov.setAttribute("x1", x(i)); hov.setAttribute("x2", x(i)); tsReadout(i); });
    s.addEventListener("pointerleave", function () { hov.setAttribute("x1", -10); hov.setAttribute("x2", -10); tsReadout(null); });
    s.addEventListener("click", function (ev) { var gi = G.dekads.indexOf(dek[nearest(ev)]); if (gi >= 0) setTime(gi); });
    host.onkeydown = function (ev) {
      var si = dek.indexOf(G.dekads[t]), d = ev.key === "ArrowRight" ? 1 : ev.key === "ArrowLeft" ? -1 : 0;
      if (!d) return;
      var ni = si < 0 ? (d > 0 ? 0 : n - 1) : Math.max(0, Math.min(n - 1, si + d)); setTime(G.dekads.indexOf(dek[ni])); ev.preventDefault();
    };
    var rows = "<tr><th>" + T.date + "</th><th>CHIRPS</th><th>AIFS</th><th>" + T.clim.split(" ")[0] + "</th></tr>";
    for (var i = 0; i < n; i++) rows += "<tr><td>" + dek[i] + "</td><td>" + fmt(S.obs[i], 0) + "</td><td>" + (fc[i] == null ? "–" : fmt(fc[i], 0)) + "</td><td>" + fmt(S.clim[i], 0) + "</td></tr>";
    $("ts-table").innerHTML = '<div class="tbl-wrap"><table>' + rows + "</table></div>";
    tsCursor();
  }
  function tsReadout(i) {
    if (!ts) return;
    if (i == null) i = ts.dek.indexOf(G.dekads[t]);
    var o = $("ts-readout");
    if (i < 0) { o.textContent = dekadLabel(G.dekads[t]) + ": " + T.noZ; return; }
    var f = ts.fc[i], ob = ts.S.obs[i], c = ts.S.clim[i];
    o.innerHTML = T.date + " <b>" + dekadLabel(ts.dek[i]) + "</b><br>" + T.obs + " <b>" + fmt(ob, 0) + "</b> · " + T.fc + " <b>" + (f == null ? "–" : fmt(f, 0)) + "</b> · " + T.clim + " <b>" + fmt(c, 0) + "</b> " + T.mm;
  }
  function tsCursor() {
    if (!ts) return;
    var i = ts.dek.indexOf(G.dekads[t]), xx = i < 0 ? -10 : ts.x(i);
    ts.cur.setAttribute("x1", xx); ts.cur.setAttribute("x2", xx); tsReadout(null);
  }

  // ---------- pooled charts ----------
  var METRICS = { MAESS: { label: function () { return T.maesWhat; }, dom: [-0.4, 0.8] }, ACC: { label: function () { return T.accWhat; }, dom: [-0.2, 1] } };
  function leadChart() {
    var host = $("fig-lead"); host.textContent = "";
    var W = width(host), H = 300, m = { l: 52, r: 16, t: 30, b: 44 }, dom = METRICS[lmetric].dom;
    var L = D.skill.lead, series = D.skill[lmetric];
    var x = function (i) { return m.l + (W - m.l - m.r) * (i + .5) / L.length; };
    var y = function (v) { return m.t + (H - m.t - m.b) * (1 - (v - dom[0]) / (dom[1] - dom[0])); };
    var s = el("svg", { viewBox: "0 0 " + W + " " + H, width: W, height: H, "aria-hidden": "true" });
    niceTicks(dom[0], dom[1], 6).forEach(function (tk) {
      s.appendChild(el("line", { class: tk === 0 ? "zero" : "grid", x1: m.l, x2: W - m.r, y1: y(tk), y2: y(tk) }));
      s.appendChild(el("text", { x: m.l - 8, y: y(tk) + 4, "text-anchor": "end" }, [fmt(tk, 1)]));
    });
    L.forEach(function (l, i) {
      s.appendChild(el("text", { x: x(i), y: H - m.b + 18, "text-anchor": "middle" }, [String(l)]));
      var v = series[i];
      s.appendChild(el("g", {}, [el("line", { class: "ci", x1: x(i), x2: x(i), y1: y(v[2]), y2: y(v[1]) }),
        el("line", { class: "ci", x1: x(i) - 5, x2: x(i) + 5, y1: y(v[2]), y2: y(v[2]) }), el("line", { class: "ci", x1: x(i) - 5, x2: x(i) + 5, y1: y(v[1]), y2: y(v[1]) }),
        el("circle", { class: "dot", cx: x(i), cy: y(v[0]), r: 5.5 }, [el("title", {}, [T.lead + " " + l + ": " + fmt(v[0]) + " [" + fmt(v[1]) + ", " + fmt(v[2]) + "]"])])]));
      s.appendChild(el("text", { class: "ttl", x: x(i) + 10, y: y(v[0]) + 4 }, [fmt(v[0])]));
    });
    s.appendChild(el("text", { x: m.l + (W - m.l - m.r) / 2, y: H - 6, "text-anchor": "middle" }, [T.lead]));
    s.appendChild(el("text", { class: "ttl", x: 6, y: 12 }, [METRICS[lmetric].label()]));
    host.setAttribute("aria-label", T.leadAria + " (" + METRICS[lmetric].label() + ")");
    host.appendChild(s);
  }

  function summary() {
    var k = D.skill, w = D.season.wet, d = D.season.dry;
    var vv = { l0: pct(k.MAESS[0][0]), l0ci: pctRange(k.MAESS[0]), l5: pct(k.MAESS[5][0]), l5ci: pctRange(k.MAESS[5]), dry: pct(d.MAESS[0]), dryci: pctRange(d.MAESS), wet: pct(w.MAESS[0]), wetci: pctRange(w.MAESS) };
    Array.prototype.forEach.call(document.querySelectorAll("[data-v]"), function (n) { n.textContent = vv[n.getAttribute("data-v")]; });
    var id = "Pada lead 2 hari, keunggulan terhadap klimatologi di musim kemarau (Jun–Sep, " + d.n + " dasarian) sebesar " + pct(d.MAESS[0]) + " (selang 95%: " + pctRange(d.MAESS) + "; korelasi anomali " + fmt(d.ACC[0]) + "). Di musim hujan (Des–Mar, " + w.n + " dasarian) keunggulannya hanya " + pct(w.MAESS[0]) + " dan selangnya mencakup nol (" + pctRange(w.MAESS) + "; korelasi anomali " + fmt(w.ACC[0]) + "). Artinya, pada data ini belum terbukti model mengalahkan klimatologi justru ketika hujan paling penting. Sampel musim hujan sangat kecil (kurang dari dua musim), jadi ini peringatan, bukan temuan pasti.";
    var en = "At a 2-day lead, the advantage over climatology in the dry season (Jun–Sep, " + d.n + " periods) is " + pct(d.MAESS[0]) + " (95% interval " + pctRange(d.MAESS) + "; anomaly correlation " + fmt(d.ACC[0]) + "). In the wet season (Dec–Mar, " + w.n + " periods) it is only " + pct(w.MAESS[0]) + " and the interval includes zero (" + pctRange(w.MAESS) + "; anomaly correlation " + fmt(w.ACC[0]) + "). So, in this data, the model has not been shown to beat climatology exactly when rain matters most. The wet-season sample is very small (under two seasons), so treat this as a warning, not a firm finding.";
    var V = D.versions, vs = V.v11_season, a10 = V.v10["0"], a11 = V.v11["0"];
    id += " Hanya dengan versi 1.1.0 (lead 2): musim kemarau " + pct(vs.dry.MAESS[0]) + " (" + pctRange(vs.dry.MAESS) + ", n = " + vs.dry.n + "), musim hujan " + pct(vs.wet.MAESS[0]) + " (" + pctRange(vs.wet.MAESS) + ", n = " + vs.wet.n + ").";
    en += " With version 1.1.0 only (lead 2): dry season " + pct(vs.dry.MAESS[0]) + " (" + pctRange(vs.dry.MAESS) + ", n = " + vs.dry.n + "), wet season " + pct(vs.wet.MAESS[0]) + " (" + pctRange(vs.wet.MAESS) + ", n = " + vs.wet.n + ").";
    $("season-text").textContent = LANG === "id" ? id : en;
    var vid = "Selama periode ini ECMWF mengganti AIFS Single: versi 1.1.0 dirilis pada 27 Agustus 2025 untuk memperbaiki masalah prakiraan curah hujan pada versi awal (arXiv:2509.18994). Kami memisahkan hasilnya menurut tanggal prakiraan dibuat. Sebelum tanggal itu (" + a10.n + " dasarian, lead 0) bias rata-rata " + fmt(a10.bias[0], 0) + " mm per dasarian, yaitu terlalu kering; sesudahnya (" + a11.n + " dasarian) " + fmt(a11.bias[0], 0) + " mm. Skill terhadap klimatologi serupa pada kedua versi (lead 0: " + pct(a10.MAESS[0]) + " dan " + pct(a11.MAESS[0]) + "; selang " + pctRange(a10.MAESS) + " dan " + pctRange(a11.MAESS) + "). Hasil utama di atas menggabungkan keduanya.";
    var ven = "During this period ECMWF replaced AIFS Single: version 1.1.0 was released on 27 August 2025 to correct a precipitation forecast issue in the first version (arXiv:2509.18994). We split the results by the date the forecast was made. Before that date (" + a10.n + " periods, lead 0) the average bias was " + fmt(a10.bias[0], 0) + " mm per ten days, i.e. too dry; afterwards (" + a11.n + " periods) it was " + fmt(a11.bias[0], 0) + " mm. Skill against climatology is similar for both versions (lead 0: " + pct(a10.MAESS[0]) + " and " + pct(a11.MAESS[0]) + "; intervals " + pctRange(a10.MAESS) + " and " + pctRange(a11.MAESS) + "). The headline results above pool both.";
    $("version-text").textContent = LANG === "id" ? vid : ven;
  }

  // ---------- init ----------
  function btnGroup(host, items, current, onPick, labelFn) {
    host.textContent = "";
    items.forEach(function (k) {
      var b = h("button", { type: "button", "aria-pressed": k === current ? "true" : "false", "data-l": k }, labelFn(k));
      b.onclick = function () { Array.prototype.forEach.call(host.children, function (c) { c.setAttribute("aria-pressed", c === b ? "true" : "false"); }); onPick(k); };
      host.appendChild(b);
    });
  }
  function init() {
    CELL = G.nx * G.ny; NT = G.dekads.length;
    buildMap();
    btnGroup($("layer-ctl"), ["obs", "clim", "anom", "aifs", "aerr", "skill"], layer, setLayer, function (k) { return T.layers[k]; });
    var rg = $("t-range"); rg.min = 0; rg.max = NT - 1; rg.step = 1; rg.setAttribute("aria-label", T.slider);
    rg.oninput = function () { stop(); setTime(+rg.value); };
    $("t-prev").setAttribute("aria-label", T.prev); $("t-next").setAttribute("aria-label", T.next); $("t-play").setAttribute("aria-label", T.play);
    $("t-prev").onclick = function () { stop(); setTime(t - 1); }; $("t-next").onclick = function () { stop(); setTime(t + 1); }; $("t-play").onclick = play;
    var sl = $("sk-lead"); D.skill.lead.forEach(function (l) { sl.appendChild(h("option", { value: l }, l + " " + T.days)); }); sl.value = "0";
    sl.onchange = function () { skLead = +sl.value; drawRaster(); styleZones(); legend(); timeLabel(); showHover(); };
    btnGroup($("sk-metric"), ["MAESS", "ACC"], skMetric, function (k) { skMetric = k; styleZones(); legend(); showHover(); }, function (k) { return METRICS[k].label(); });
    var zs = $("zone-sel"); Object.keys(D.zones).sort(function (a, b) { return a - b; }).forEach(function (z) { zs.appendChild(h("option", { value: z }, T.zone + " " + z + " (" + num(D.zones[z].area_km2) + " km²)")); });
    zs.onchange = function () { selectZone(zs.value); };
    $("ts-lead").onchange = tsChart;
    btnGroup($("metric-ctl"), ["MAESS", "ACC"], lmetric, function (k) { lmetric = k; leadChart(); }, function (k) { return METRICS[k].label(); });
    $("metric-ctl").setAttribute("aria-label", T.metricAria);
    t = NT - 1; $("t-range").value = t;
    summary(); leadChart(); zonePanel(); selectZone(zone);
    setLayer("obs"); setTime(t);
    var rt; window.addEventListener("resize", function () { clearTimeout(rt); rt = setTimeout(function () { fitLabels(); leadChart(); tsChart(); }, 120); });
  }

  function json(u) { return fetch(BASE + u).then(function (r) { if (!r.ok) throw new Error(u + " " + r.status); return r.json(); }); }
  Promise.all([json("zom-eval.json"), json("zom-map.json"), json("chirps-grid.json"), fetch(BASE + "chirps-grid.bin").then(function (r) { if (!r.ok) throw new Error(r.status); return r.arrayBuffer(); })])
    .then(function (a) { D = a[0]; M = a[1]; G = a[2]; bin = new Uint8Array(a[3]); init(); })
    .catch(function (e) { if (window.console) console.error(e); var f = $("map-hover"); if (f) f.textContent = T.err; });
})();
