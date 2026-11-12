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
    if (reduce) { p = 0.9; render(); } else { render(); play(true); }
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
