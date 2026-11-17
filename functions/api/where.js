// Cloudflare Pages Function: GET /api/where
// Tells the page roughly where the visitor is, so the map can open there.
// Cloudflare already knows this from the request (IP geolocation, city level at
// best); nothing is looked up elsewhere, stored or logged, and the answer goes
// back only to the visitor who asked. The exact position is a separate thing:
// the locate button asks the browser, which asks the visitor.

const num = (v) => (v === undefined || v === null || v === "" || Number.isNaN(+v) ? null : +v);

export function onRequestGet({ request }) {
  const cf = request.cf || {};
  const body = { country: cf.country || null, lat: num(cf.latitude), lon: num(cf.longitude) };
  return new Response(JSON.stringify(body), {
    headers: { "content-type": "application/json", "cache-control": "private, no-store" },
  });
}
