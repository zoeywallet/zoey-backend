// Protects the admin endpoints (lead listing, CSV export, notification
// resend) with a single shared secret key (ADMIN_KEY env var), compared in
// constant time to avoid leaking timing information. This is intentionally
// simple — not a full auth/user system — because the requirement is just
// "don't expose the lead database publicly," not "build a login system."

const crypto = require('node:crypto');

function timingSafeEqual(a, b) {
  const bufA = Buffer.from(String(a));
  const bufB = Buffer.from(String(b));
  if (bufA.length !== bufB.length) {
    // Still run a comparison of equal length to avoid a fast length-based
    // timing signal, then report unequal.
    crypto.timingSafeEqual(bufA, bufA);
    return false;
  }
  return crypto.timingSafeEqual(bufA, bufB);
}

function extractProvidedKey(req, url) {
  const header = req.headers['x-admin-key'];
  if (header) return Array.isArray(header) ? header[0] : header;

  const auth = req.headers['authorization'];
  if (auth && auth.startsWith('Bearer ')) return auth.slice(7);

  const queryKey = url.searchParams.get('key');
  if (queryKey) return queryKey;

  return null;
}

/** Returns true if the request is authorized to hit an admin route. */
function isAdminAuthorized(req, url) {
  const configuredKey = process.env.ADMIN_KEY;
  if (!configuredKey) return false; // fail closed if nothing is configured

  const provided = extractProvidedKey(req, url);
  if (!provided) return false;

  return timingSafeEqual(provided, configuredKey);
}

module.exports = { isAdminAuthorized };
