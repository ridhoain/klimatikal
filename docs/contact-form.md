# Contact form: setup

The form on `/contact-us/` posts to `functions/api/contact.js` (a Cloudflare Pages
Function). It checks Cloudflare Turnstile, validates the fields, and sends the message
through Resend to the owner's mailbox, with the visitor's address in Reply-To.

It does nothing until these are set. Never paste secret keys into chat or commit them.

1. **Resend** (resend.com, free: 100 emails/day). Domains -> Add Domain -> `klimatikal.com`.
   Add the DNS records it lists in Cloudflare DNS (they sit on a `send` subdomain and do
   not touch Zoho mail), then Verify. API Keys -> create one with "Sending access".
2. **Turnstile** (Cloudflare dashboard -> Turnstile -> Add widget). Hostnames:
   `klimatikal.com` and `www.klimatikal.com`. Mode: Managed. You get a **site key**
   (public) and a **secret key** (private).
3. **Pages settings** (Workers & Pages -> klimatikal -> Settings -> Variables and
   secrets, Production):
   - `RESEND_API_KEY` (secret), `TURNSTILE_SECRET` (secret)
   - `CONTACT_TO` = `ar@klimatikal.com`
   - `CONTACT_FROM` = `Klimatikal contact <contact@klimatikal.com>`
   Add the same under Preview if you want to try a branch preview.
4. Put the Turnstile **site key** in `web/contact-us/index.html`, replacing
   `__TURNSTILE_SITE_KEY__`, then push.

Test: send yourself a message from the live page; it should arrive within a minute,
and Reply should go to the address typed in the form.
