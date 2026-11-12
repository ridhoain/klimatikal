// Cloudflare Pages Function: POST /api/contact
// Checks the visitor with Turnstile, validates the fields, and sends the message
// to the site owner through Resend. The visitor's address goes in Reply-To, so
// replying in Zoho answers them directly.
//
// Settings (Cloudflare Pages -> Settings -> Variables and secrets):
//   RESEND_API_KEY    secret   Resend API key
//   TURNSTILE_SECRET  secret   Turnstile secret key
//   CONTACT_TO        text     where messages go (ar@klimatikal.com)
//   CONTACT_FROM      text     sender on a Resend-verified domain, e.g.
//                              Klimatikal contact <contact@klimatikal.com>

const json = (body, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json", "cache-control": "no-store" } });

const clean = (s, max) => String(s ?? "").replace(/\r/g, "").trim().slice(0, max);
const oneLine = (s, max) => clean(s, max).replace(/\s*\n\s*/g, " ");
const EMAIL = /^[^\s@<>"]+@[^\s@<>"]+\.[^\s@<>"]{2,}$/;

export async function onRequestPost({ request, env }) {
  if (!env.RESEND_API_KEY || !env.TURNSTILE_SECRET || !env.CONTACT_TO || !env.CONTACT_FROM) {
    return json({ ok: false, error: "The contact form is not configured yet." }, 503);
  }

  let data;
  try {
    const type = request.headers.get("content-type") || "";
    data = type.includes("application/json") ? await request.json() : Object.fromEntries(await request.formData());
  } catch {
    return json({ ok: false, error: "Could not read the form." }, 400);
  }

  // honeypot: real visitors never see or fill this field
  if (clean(data.website, 200)) return json({ ok: true });

  const email = oneLine(data.email, 200);
  const subject = oneLine(data.subject, 150);
  const message = clean(data.message, 5000);
  if (!EMAIL.test(email)) return json({ ok: false, error: "Please enter a valid email address.", field: "email" }, 400);
  if (!subject) return json({ ok: false, error: "Please enter a subject.", field: "subject" }, 400);
  if (message.length < 10) return json({ ok: false, error: "Please write a message of at least 10 characters.", field: "message" }, 400);

  const token = clean(data["cf-turnstile-response"] || data.turnstile, 4096);
  if (!token) return json({ ok: false, error: "Please complete the human check." }, 400);
  const form = new FormData();
  form.append("secret", env.TURNSTILE_SECRET);
  form.append("response", token);
  const ip = request.headers.get("CF-Connecting-IP");
  if (ip) form.append("remoteip", ip);
  let human = false;
  try {
    const r = await fetch("https://challenges.cloudflare.com/turnstile/v0/siteverify", { method: "POST", body: form });
    human = (await r.json()).success === true;
  } catch {}
  if (!human) return json({ ok: false, error: "The human check failed. Please try again." }, 400);

  const text = `From: ${email}\nSubject: ${subject}\n\n${message}\n\n--\nSent from the contact form at klimatikal.com`;
  const res = await fetch("https://api.resend.com/emails", {
    method: "POST",
    headers: { authorization: `Bearer ${env.RESEND_API_KEY}`, "content-type": "application/json" },
    body: JSON.stringify({
      from: env.CONTACT_FROM,
      to: [env.CONTACT_TO],
      reply_to: email,
      subject: `[Klimatikal contact] ${subject}`,
      text,
    }),
  });
  if (!res.ok) return json({ ok: false, error: "The message could not be sent. Please email us directly." }, 502);
  return json({ ok: true });
}

export const onRequest = () => json({ ok: false, error: "Use POST." }, 405);
