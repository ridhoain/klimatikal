(function () {
  var form = document.getElementById("contact"), status = document.getElementById("c-status");
  if (!form) return;
  var btn = form.querySelector("button[type=submit]");
  function say(msg, bad) { status.textContent = msg; status.className = "cstatus " + (bad ? "bad" : "ok"); }
  form.addEventListener("submit", function (e) {
    e.preventDefault();
    var d = new FormData(form), body = {};
    d.forEach(function (v, k) { body[k] = v; });
    if (!body.email || !/^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(body.email)) { say("Please enter a valid email address.", true); return; }
    if (!body.subject.trim()) { say("Please enter a subject.", true); return; }
    if (body.message.trim().length < 10) { say("Please write a message of at least 10 characters.", true); return; }
    btn.disabled = true; say("Sending…", false);
    fetch("/api/contact", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) })
      .then(function (r) { return r.json().catch(function () { return { ok: false, error: "Something went wrong." }; }); })
      .then(function (j) {
        if (j.ok) { form.reset(); say("Thank you. We have received your request and will reply to the email you gave.", false); }
        else { say(j.error || "Something went wrong.", true); if (window.turnstile) try { window.turnstile.reset(); } catch (x) {} }
      })
      .catch(function () { say("Could not reach the server. Please try again in a moment.", true); })
      .then(function () { btn.disabled = false; });
  });
})();
