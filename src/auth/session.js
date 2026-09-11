// Opaque session tokens, stored server-side (see the `sessions` table in
// db.js) and handed to the browser only as an httpOnly cookie — the token
// itself is meaningless without a DB lookup, and JavaScript on the page can
// never read it (no localStorage/JWT-in-JS involved).

const crypto = require('node:crypto');
const db = require('../db');

const COOKIE_NAME = 'zw_session';
const SESSION_TTL_HOURS = Number(process.env.SESSION_TTL_HOURS || 24 * 7); // 7 days

function generateToken() {
  return crypto.randomBytes(32).toString('hex');
}

function createSessionForUser(userId) {
  const token = generateToken();
  const expiresAt = new Date(Date.now() + SESSION_TTL_HOURS * 60 * 60 * 1000).toISOString();
  db.createSession({ token, userId, expiresAt });
  return { token, expiresAt };
}

// ---- Cookie parsing/serialization (no external dependency) ----

function parseCookies(cookieHeader) {
  const out = {};
  if (!cookieHeader) return out;
  for (const part of cookieHeader.split(';')) {
    const eq = part.indexOf('=');
    if (eq === -1) continue;
    const key = part.slice(0, eq).trim();
    const value = part.slice(eq + 1).trim();
    if (key) out[key] = decodeURIComponent(value);
  }
  return out;
}

function serializeCookie(name, value, { maxAgeSeconds, secure } = {}) {
  const parts = [`${name}=${encodeURIComponent(value)}`, 'Path=/', 'HttpOnly', 'SameSite=Lax'];
  if (typeof maxAgeSeconds === 'number') parts.push(`Max-Age=${maxAgeSeconds}`);
  if (secure) parts.push('Secure');
  return parts.join('; ');
}

function isRequestSecure(req) {
  if (process.env.COOKIE_SECURE === 'true') return true;
  if (process.env.COOKIE_SECURE === 'false') return false;
  // Best-effort auto-detect: true if TLS-terminated directly, or a trusted
  // proxy said so (only trusted when TRUST_PROXY=true, same flag the rate
  // limiter's IP detection uses).
  if (req.socket.encrypted) return true;
  if (process.env.TRUST_PROXY === 'true' && req.headers['x-forwarded-proto'] === 'https') return true;
  return false;
}

function setSessionCookie(req, res, token, maxAgeSeconds) {
  res.setHeader('Set-Cookie', serializeCookie(COOKIE_NAME, token, {
    maxAgeSeconds,
    secure: isRequestSecure(req),
  }));
}

function clearSessionCookie(req, res) {
  res.setHeader('Set-Cookie', serializeCookie(COOKIE_NAME, '', {
    maxAgeSeconds: 0,
    secure: isRequestSecure(req),
  }));
}

function getSessionTokenFromRequest(req) {
  const cookies = parseCookies(req.headers['cookie']);
  return cookies[COOKIE_NAME] || null;
}

/** Returns the authenticated user for this request, or null. */
function getRequestUser(req) {
  const token = getSessionTokenFromRequest(req);
  if (!token) return null;
  return db.getUserBySessionToken(token);
}

function destroySession(req) {
  const token = getSessionTokenFromRequest(req);
  if (token) db.deleteSession(token);
}

module.exports = {
  COOKIE_NAME,
  SESSION_TTL_HOURS,
  createSessionForUser,
  setSessionCookie,
  clearSessionCookie,
  getSessionTokenFromRequest,
  getRequestUser,
  destroySession,
};
