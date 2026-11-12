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
