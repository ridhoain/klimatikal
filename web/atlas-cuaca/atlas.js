/* Atlas cuaca: language switch, filters and search.
   The cards are plain HTML and read fine without this; the script only adds
   interaction. The initial language is set by a tiny inline script in <head>. */
(function () {
  // Old links to /atlas-cuaca/#some-id (from when every phenomenon was a full
  // card on this page) now go to that phenomenon's own page.
  if (document.body.getAttribute("data-page") === "index" && location.hash.length > 1) {
    var hit = document.getElementById(decodeURIComponent(location.hash.slice(1)));
    if (hit && hit.classList.contains("card")) { location.replace("/atlas-cuaca/" + hit.id + "/"); return; }
  }

  var root = document.documentElement;

  // A sideways-scrolling diagram opens with its crest in view, not its left edge.
  Array.prototype.forEach.call(document.querySelectorAll(".dscroll[data-focus]"), function (box) {
    var pct = parseFloat(box.getAttribute("data-focus")) / 100;
    box.scrollLeft = Math.max(0, box.scrollWidth * pct - box.clientWidth / 2);
  });

  // ---- foehn diagram animation -------------------------------------------
  // Parcels of air travel along the three flow lines; cloud and rain appear as
  // the front passes them. Illustrative only. Without this script (or with
  // reduced motion) the figure is the complete static picture.
  Array.prototype.forEach.call(document.querySelectorAll("figure.diagram"), function (fig) {
    var svg = fig.querySelector(".dsvg"), ctl = fig.querySelector(".dctl"), layer = svg && svg.querySelector(".d-parcels");
    var paths = fig.querySelectorAll(".d-air[data-lane]");
    if (!layer || !ctl || !paths.length || !svg.getBoundingClientRect) return;
    var NS = "http://www.w3.org/2000/svg", W = 1000;
    var stops = fig.getAttribute("data-stops").split(";").map(function (s) {
      var a = s.split(":"); return { x: +a[0], c: a[1].split(",").map(Number) };
    });
    var ph = fig.getAttribute("data-phases").split(",").map(Number); // windward start, crest, lee end (svg x)
    function colour(x) {
      for (var i = 0; i < stops.length - 1; i++) {
        var a = stops[i], b = stops[i + 1];
        if (x >= a.x && x <= b.x) {
          var f = b.x === a.x ? 0 : (x - a.x) / (b.x - a.x);
          return "rgb(" + a.c.map(function (v, k) { return Math.round(v + (b.c[k] - v) * f); }).join(",") + ")";
        }
      }
      var e = x < stops[0].x ? stops[0].c : stops[stops.length - 1].c;
      return "rgb(" + e.join(",") + ")";
    }
    // sample each line once: a point for every 2 svg units of x
    var lanes = Array.prototype.map.call(paths, function (pa) {
      var len = pa.getTotalLength(), pts = [], x, last = -1;
      for (var d = 0; d <= len; d += 2) { var q = pa.getPointAtLength(d); pts.push([q.x, q.y]); }
      return pts;
    });
    var TRAIL = 5, GAP = 0.05, parcels = [];
    lanes.forEach(function (pts, li) {
      for (var i = 0; i < TRAIL; i++) {
        var c = document.createElementNS(NS, "circle");
        c.setAttribute("class", "d-parcel"); c.setAttribute("r", String(6 - i * 0.6));
        c.style.display = "none"; layer.appendChild(c);
        parcels.push({ el: c, pts: pts, i: i });
      }
    });
    var clouds = fig.querySelectorAll(".d-cloud, .d-cloud-edge"), rain = fig.querySelectorAll(".d-rain");
    function at(pts, x) { // point of a lane at svg x (lanes run left to right)
      var lo = 0, hi = pts.length - 1;
      while (lo < hi) { var m = (lo + hi) >> 1; if (pts[m][0] < x) lo = m + 1; else hi = m; }
      return pts[lo];
    }
    var p = 0, playing = false, last = 0, DUR = 16000;
    var btn = ctl.querySelector(".dplay"), scrub = ctl.querySelector(".dscrub");
    var phases = ctl.querySelectorAll(".dphase span");
    function render() {
      var front = p * (W + 60) - 30; // runs a little past both edges
      parcels.forEach(function (o) {
        var x = front - o.i * GAP * W;
        if (x < 0 || x > W) { o.el.style.display = "none"; return; }
        var q = at(o.pts, x);
        o.el.style.display = ""; o.el.setAttribute("cx", q[0]); o.el.setAttribute("cy", q[1]);
        o.el.setAttribute("fill", colour(q[0])); o.el.style.opacity = String(1 - o.i * 0.17);
      });
      var fade = p > 0.94 ? (1 - p) / 0.06 : 1;
      Array.prototype.forEach.call(clouds, function (c) {
        c.style.opacity = String(Math.max(0, Math.min(1, (front - +c.getAttribute("data-x")) / 70)) * fade);
      });
      Array.prototype.forEach.call(rain, function (c) {
        c.style.opacity = String(Math.max(0, Math.min(1, (front - 40 - +c.getAttribute("data-x")) / 60)) * fade);
      });
      var k = front < ph[0] ? 0 : front < ph[1] ? 1 : front < ph[2] ? 2 : 3;
      if (k === 3 && front < ph[2] + 1) k = 2;
      Array.prototype.forEach.call(phases, function (s) { s.classList.toggle("on", +s.getAttribute("data-ph") === k); });
      scrub.value = String(Math.round(p * 1000));
    }
    function tick(now) {
      if (!playing) return;
      if (fig.hidden) { playing = false; btn.setAttribute("aria-pressed", "false"); return; }
      p += (now - last) / DUR; last = now;
      if (p >= 1) p = 0;
      render(); requestAnimationFrame(tick);
    }
    function play(on) {
      playing = on; btn.setAttribute("aria-pressed", String(on));
      if (on) { last = performance.now(); requestAnimationFrame(tick); }
    }
    btn.addEventListener("click", function () { play(!playing); });
    scrub.addEventListener("input", function () { play(false); p = scrub.value / 1000; render(); });
    ctl.hidden = false; fig.classList.add("animated");
    var reduce = window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches;
    fig.addEventListener("dshow", function () {
      p = 0; if (reduce) { p = 0.9; render(); } else { render(); play(true); }
    });
    if (reduce) { p = 0.9; render(); } else { render(); if (!fig.hidden) play(true); }
  });

  // ---- Musim Bediding: tabs, and the night-cooling scene --------------------
  Array.prototype.forEach.call(document.querySelectorAll(".dscenes"), function (box) {
    var tabs = box.querySelector(".dtabs"), figs = box.querySelectorAll(".dscene");
    if (!tabs) return;
    tabs.hidden = false; box.classList.add("tabbed");
    function show(i) {
      Array.prototype.forEach.call(figs, function (f) {
        var on = f.getAttribute("data-scene") === i;
        if (on && f.hidden) { f.hidden = false; f.dispatchEvent(new Event("dshow")); }
        else if (!on) f.hidden = true;
      });
      Array.prototype.forEach.call(tabs.querySelectorAll("button"), function (b) {
        b.setAttribute("aria-selected", String(b.getAttribute("data-scene") === i));
      });
    }
    Array.prototype.forEach.call(figs, function (f, k) { f.hidden = k !== 0; });
    Array.prototype.forEach.call(tabs.querySelectorAll("button"), function (b) {
      b.addEventListener("click", function () { show(b.getAttribute("data-scene")); });
    });
  });
  Array.prototype.forEach.call(document.querySelectorAll('figure.diagram[data-kind="night"]'), function (fig) {
    var ctl = fig.querySelector(".dctl"), btn = ctl.querySelector(".dplay"), scrub = ctl.querySelector(".dscrub");
    var sky = fig.querySelector(".d-sky"), heat = fig.querySelectorAll(".d-heat"), chill = fig.querySelectorAll(".d-chill");
    var phases = ctl.querySelectorAll(".dphase span");
    var DAY = [240, 160, 122], NIGHT = [29, 95, 209], TOP = {clear: 1, cloud: 0.3};
    var p = 0, playing = false, last = 0, DUR = 18000, CYC = 4;
    function mix(f) { return "rgb(" + DAY.map(function (v, i) { return Math.round(v + (NIGHT[i] - v) * f); }).join(",") + ")"; }
    function render() {
      var night = Math.max(0, Math.min(1, (p - 0.15) / 0.35)); // 0 by day, 1 once night has settled
      sky.style.opacity = String(night * 0.55);
      Array.prototype.forEach.call(chill, function (c) {
        c.style.fill = mix(night * TOP[c.getAttribute("data-side")]); c.style.opacity = String(0.5 + night * 0.15);
      });
      Array.prototype.forEach.call(heat, function (h) {
        var f = (p * CYC + +h.getAttribute("data-ph")) % 1, y0 = +h.getAttribute("data-y0"), y1 = +h.getAttribute("data-y1");
        var clear = h.getAttribute("data-side") === "clear", y, o;
        if (clear) { y = y0 + (y1 - y0) * f; o = 1 - f * f; } else { var g = f < 0.5 ? f * 2 : 2 - f * 2; y = y0 + (y1 - y0) * g; o = 1 - 0.45 * g; }
        h.setAttribute("cy", y); h.style.opacity = String(o * night);
      });
      var k = p < 0.15 ? 0 : p < 0.5 ? 1 : 2;
      Array.prototype.forEach.call(phases, function (s) { s.classList.toggle("on", +s.getAttribute("data-ph") === k); });
      scrub.value = String(Math.round(p * 1000));
    }
    function tick(now) {
      if (!playing) return;
      if (fig.hidden) { playing = false; btn.setAttribute("aria-pressed", "false"); return; }
      p += (now - last) / DUR; last = now; if (p >= 1) p = 0.15;
      render(); requestAnimationFrame(tick);
    }
    function play(on) { playing = on; btn.setAttribute("aria-pressed", String(on)); if (on) { last = performance.now(); requestAnimationFrame(tick); } }
    btn.addEventListener("click", function () { play(!playing); });
    scrub.addEventListener("input", function () { play(false); p = scrub.value / 1000; render(); });
    var reduce = window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches;
    ctl.hidden = false; fig.classList.add("animated");
    fig.addEventListener("dshow", function () { p = 0; if (reduce) { p = 0.8; render(); } else { render(); play(true); } });
    if (reduce) { p = 0.8; render(); } else { render(); if (!fig.hidden) play(true); }
  });
  Array.prototype.forEach.call(document.querySelectorAll('figure.diagram[data-kind="map"]'), function (fig) {
    var NS = "http://www.w3.org/2000/svg", ctl = fig.querySelector(".dctl"), btn = ctl.querySelector(".dplay"), scrub = ctl.querySelector(".dscrub");
    var layer = fig.querySelector(".d-parcels"), paths = fig.querySelectorAll(".m-traj"), phases = ctl.querySelectorAll(".dphase span");
    var TRAIL = 6, GAP = 0.035, parcels = [];
    Array.prototype.forEach.call(paths, function (pa) {
      var len = pa.getTotalLength();
      for (var i = 0; i < TRAIL; i++) {
        var c = document.createElementNS(NS, "circle");
        c.setAttribute("class", "d-parcel"); c.setAttribute("r", String(5.5 - i * 0.6)); c.setAttribute("fill", "#1d5fd1");
        c.style.display = "none"; layer.appendChild(c); parcels.push({ el: c, path: pa, len: len, i: i });
      }
    });
    var p = 0, playing = false, last = 0, DUR = 14000;
    function render() {
      var front = p * (1 + TRAIL * GAP);
      parcels.forEach(function (o) {
        var f = front - o.i * GAP;
        if (f < 0 || f > 1) { o.el.style.display = "none"; return; }
        var q = o.path.getPointAtLength(f * o.len);
        o.el.style.display = ""; o.el.setAttribute("cx", q.x); o.el.setAttribute("cy", q.y); o.el.style.opacity = String(1 - o.i * 0.15);
      });
      var k = p < 0.12 ? 0 : p < 0.8 ? 1 : 2;
      Array.prototype.forEach.call(phases, function (s) { s.classList.toggle("on", +s.getAttribute("data-ph") === k); });
      scrub.value = String(Math.round(p * 1000));
    }
    function tick(now) {
      if (!playing) return;
      if (fig.hidden) { playing = false; btn.setAttribute("aria-pressed", "false"); return; }
      p += (now - last) / DUR; last = now; if (p >= 1) p = 0;
      render(); requestAnimationFrame(tick);
    }
    function play(on) { playing = on; btn.setAttribute("aria-pressed", String(on)); if (on) { last = performance.now(); requestAnimationFrame(tick); } }
    btn.addEventListener("click", function () { play(!playing); });
    scrub.addEventListener("input", function () { play(false); p = scrub.value / 1000; render(); });
    var reduce = window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches;
    ctl.hidden = false; fig.classList.add("animated");
    fig.addEventListener("dshow", function () { p = 0; if (reduce) { p = 1; render(); } else { render(); play(true); } });
    if (reduce) { p = 1; render(); } else { render(); if (!fig.hidden) play(true); }
  });
  /* One day over the caldera: the slider position t runs 0..K-1 through the keyframes; sky, sun,
     moon, stars, light tint, arrows and the fog layers are interpolated between the two nearest. */
  Array.prototype.forEach.call(document.querySelectorAll('figure.fogday'), function (fig) {
    var keys; try { keys = JSON.parse(fig.getAttribute("data-keys")); } catch (e) { return; }
    var K = keys.length, ctl = fig.querySelector(".dctl"), btn = ctl.querySelector(".dplay"), scrub = ctl.querySelector(".dscrub");
    var svg = fig.querySelector(".fd-svg"), W = svg.viewBox.baseVal.width, H = svg.viewBox.baseVal.height;
    var top = fig.querySelector(".fd-stop-top"), bot = fig.querySelector(".fd-stop-bot"), tintEl = fig.querySelector(".fd-tint");
    var sun = fig.querySelector(".fd-sun"), glow = fig.querySelector(".fd-glow"), moon = fig.querySelector(".fd-moon");
    var stars = fig.querySelector(".fd-stars"), arrows = fig.querySelector(".fd-arrows"), clocks = fig.querySelectorAll(".fd-time");
    var fogs = Array.prototype.slice.call(fig.querySelectorAll(".fd-fog")), items = fig.querySelectorAll(".fd-list li");
    var t = (+fig.getAttribute("data-start") || 0), raf = null, last = 0;
    function mix(a, b, f) { return a + (b - a) * f; }
    function mixv(a, b, f) { return a.map(function (v, i) { return mix(v, b[i], f); }); }
    function rgb(c) { return "rgb(" + Math.round(c[0]) + "," + Math.round(c[1]) + "," + Math.round(c[2]) + ")"; }
    function render() {
      var i = Math.min(K - 2, Math.floor(t)), f = t - i, a = keys[i], b = keys[i + 1];
      top.setAttribute("stop-color", rgb(mixv(a.top, b.top, f)));
      bot.setAttribute("stop-color", rgb(mixv(a.bot, b.bot, f)));
      var m = mixv(a.tint, b.tint, f);
      tintEl.setAttribute("values", m[0] + " 0 0 0 0  0 " + m[1] + " 0 0 0  0 0 " + m[2] + " 0 0  0 0 0 1 0");
      var s = mixv(a.sun, b.sun, f), mo = mixv(a.moon, b.moon, f);
      sun.setAttribute("cx", s[0] * W); sun.setAttribute("cy", s[1] * H); sun.style.opacity = s[2];
      glow.setAttribute("cx", s[0] * W); glow.setAttribute("cy", s[1] * H); glow.style.opacity = mix(a.glow, b.glow, f);
      moon.setAttribute("cx", mo[0] * W); moon.setAttribute("cy", mo[1] * H); moon.style.opacity = mo[2];
      stars.style.opacity = mix(a.stars, b.stars, f); arrows.style.opacity = mix(a.arrows, b.arrows, f);
      fogs.forEach(function (g) { g.style.opacity = Math.max(0, 1 - Math.abs(t - (+g.getAttribute("data-k")))); });
      var mins = Math.round(mix(a.min, b.min, f)) % 1440;
      var txt = (mins < 600 ? "0" : "") + Math.floor(mins / 60) + ":" + (mins % 60 < 10 ? "0" : "") + (mins % 60);
      Array.prototype.forEach.call(clocks, function (c) { c.textContent = txt; });
      var near = Math.round(t);
      Array.prototype.forEach.call(items, function (li, k) { li.classList.toggle("on", k === near); });
      scrub.value = String(Math.round(t * 100));
    }
    function stop() { if (raf) { cancelAnimationFrame(raf); raf = null; } btn.setAttribute("aria-pressed", "false"); }
    function tick(ts) {
      if (fig.closest("[hidden]")) { stop(); return; }
      var dt = last ? Math.min(0.35, (ts - last) / 1000) : 0; last = ts;
      t += dt * (K - 1) / 18;               /* the whole day in about 18 s */
      if (t >= K - 1) { t = K - 1; render(); stop(); return; }
      render(); raf = requestAnimationFrame(tick);
    }
    function start() { if (t >= K - 1) t = 0; last = 0; btn.setAttribute("aria-pressed", "true"); raf = requestAnimationFrame(tick); }
    btn.addEventListener("click", function () { if (raf) stop(); else start(); });
    scrub.addEventListener("input", function () { stop(); t = +scrub.value / 100; render(); });
    Array.prototype.forEach.call(items, function (li, k) { li.addEventListener("click", function () { stop(); t = k; render(); }); });
    ctl.hidden = false; fig.classList.add("animated"); render();
  });
  Array.prototype.forEach.call(document.querySelectorAll('figure.diagram[data-kind="synoptic"]'), function (fig) {
    var ctl = fig.querySelector(".dctl"), btn = ctl.querySelector(".dplay"), scrub = ctl.querySelector(".dscrub");
    var frames = fig.querySelectorAll(".sframe"), phases = fig.querySelectorAll(".dsynphase span");
    var n = +fig.getAttribute("data-n"), cur = +fig.getAttribute("data-key"), timer = null;
    function show(i) {
      cur = i;
      Array.prototype.forEach.call(frames, function (f) { f.classList.toggle("on", +f.getAttribute("data-i") === i); });
      Array.prototype.forEach.call(phases, function (s) { s.classList.toggle("on", +s.getAttribute("data-ph") === i); });
      scrub.value = String(i);
    }
    function stop() { if (timer) { clearInterval(timer); timer = null; } btn.setAttribute("aria-pressed", "false"); }
    function start() {
      btn.setAttribute("aria-pressed", "true");
      timer = setInterval(function () {
        if (fig.closest("[hidden]")) { stop(); return; }
        show((cur + 1) % n);
      }, 2400);
    }
    btn.addEventListener("click", function () { if (timer) stop(); else start(); });
    scrub.addEventListener("input", function () { stop(); show(+scrub.value); });
    ctl.hidden = false; fig.classList.add("animated");
    var reduce = window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (!reduce) { show(0); start(); }
  });
  var cards = Array.prototype.slice.call(document.querySelectorAll(".card"));
  var state = { scale: "all", doc: "all", q: "" };

  // ---- language ----------------------------------------------------------
  function setLang(l) {
    root.setAttribute("data-lang", l);
    root.lang = l;
    try { localStorage.setItem("kl-lang", l); } catch (e) {}
    Array.prototype.forEach.call(document.querySelectorAll("[data-set-lang]"), function (b) {
      b.setAttribute("aria-pressed", String(b.getAttribute("data-set-lang") === l));
    });
    var q = document.getElementById("q");
    if (q) { q.placeholder = q.getAttribute("data-ph-" + l) || q.placeholder; q.setAttribute("aria-label", q.placeholder); }
  }
  Array.prototype.forEach.call(document.querySelectorAll("[data-set-lang]"), function (b) {
    b.addEventListener("click", function () { setLang(b.getAttribute("data-set-lang")); });
  });
  setLang(root.getAttribute("data-lang") || "id");

  // ---- filters -----------------------------------------------------------
  function apply() {
    var shown = 0;
    cards.forEach(function (c) {
      var ok = (state.scale === "all" || c.dataset.scale === state.scale) &&
               (state.doc === "all" || c.dataset.doc === state.doc) &&
               (!state.q || c.dataset.search.indexOf(state.q) !== -1);
      c.hidden = !ok;
      if (ok) shown++;
      var pin = document.querySelector('.pin-link[data-id="' + c.id + '"]');
      if (pin) pin.classList.toggle("dim", !ok);
    });
    var s = document.querySelector("[data-shown]");
    if (s) s.textContent = String(shown);
    var none = document.querySelector(".none");
    if (none) none.hidden = shown !== 0;
  }

  Array.prototype.forEach.call(document.querySelectorAll(".controls button[data-group]"), function (b) {
    b.addEventListener("click", function () {
      var g = b.getAttribute("data-group");
      state[g] = b.getAttribute("data-value");
      Array.prototype.forEach.call(document.querySelectorAll('.controls button[data-group="' + g + '"]'), function (x) {
        x.setAttribute("aria-pressed", String(x === b));
      });
      apply();
    });
  });
  var q = document.getElementById("q");
  if (q) q.addEventListener("input", function () { state.q = q.value.trim().toLowerCase(); apply(); });
})();
