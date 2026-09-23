// Vercel runtime rebuild diagnostic
// Zoey Wallet lead-capture backend.
//
//   Website lead form  →  POST /api/leads  →  SQLite (leads.db)  →  Gmail
//
// Built entirely on Node's built-in modules (http, sqlite, crypto, fs) —
// see README.md for why (short version: this sandbox's npm registry access
// was blocked by org policy while building this; the only real dependency,
// nodemailer, was vendored from its GitHub source). On your own host you
// can `npm install nodemailer` normally; nothing else to install.
//
// This same process serves the static site AND the API on one origin, so
// the frontend's fetch('/api/leads') call needs no CORS configuration at
// all in the common case (see .env.example for the cross-origin option).

const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const { URL } = require('node:url');

const { loadEnv } = require('./loadEnv');
loadEnv();

const logger = require('./logger');
const db = require('./db');
const mailer = require('./mailer');
const { validateLeadPayload, validEmail } = require('./validate');
const { checkRateLimit } = require('./rateLimit');
const { isAdminAuthorized } = require('./adminAuth');
const { renderAdminDashboard } = require('./render/adminDashboard');
const { leadsToCsv } = require('./csv');
const { retryOneLead, retryAllFailedNotifications } = require('./retryFailedNotifications');
const { hashPassword, verifyPassword } = require('./auth/password');
const session = require('./auth/session');
const { getDashboardData } = require('./dashboardData');

const PORT = Number(process.env.PORT || 3001);
const PUBLIC_DIR = process.env.PUBLIC_DIR || path.join(__dirname, '..', 'public');
const RATE_LIMIT_MAX = Number(process.env.RATE_LIMIT_MAX || 5);
const RATE_LIMIT_WINDOW_MIN = Number(process.env.RATE_LIMIT_WINDOW_MIN || 10);
const LOGIN_RATE_LIMIT_MAX = Number(process.env.LOGIN_RATE_LIMIT_MAX || 8);
const LOGIN_RATE_LIMIT_WINDOW_MIN = Number(process.env.LOGIN_RATE_LIMIT_WINDOW_MIN || 15);
const RETRY_INTERVAL_MIN = Number(process.env.RETRY_INTERVAL_MIN || 15);
const IP_HASH_SALT = process.env.IP_HASH_SALT || 'zoey-wallet-default-salt-change-me';
const TRUST_PROXY = process.env.TRUST_PROXY === 'true';

if (!process.env.ADMIN_KEY) {
  logger.warn('ADMIN_KEY is not set — the /admin dashboard and lead-export endpoints will refuse all requests until it is configured.');
}
if (!mailer.isConfigured()) {
  logger.warn('Gmail is not configured (GMAIL_USER / GMAIL_APP_PASSWORD / NOTIFY_TO) — leads will still be saved, but no notification email will be sent until these are set.');
}
console.log('[DB DIAGNOSTIC]', {
  listUsersType: typeof db.listUsers,
  dbKeys: Object.keys(db),
  dbModulePath: require.resolve('./db'),
});

if (db.listUsers().length === 0) {
  logger.warn('No user accounts exist yet — /login will reject everything until one is created. Run: npm run create-user -- <email> <password> ["Full Name"]');
}

// ---------------------------------------------------------------------
// small helpers
// ---------------------------------------------------------------------

function sendJson(res, status, body) {
  const payload = JSON.stringify(body);
  res.writeHead(status, {
    'Content-Type': 'application/json; charset=utf-8',
    'Content-Length': Buffer.byteLength(payload),
    'Cache-Control': 'no-store',
  });
  res.end(payload);
}

function getClientIp(req) {
  if (TRUST_PROXY) {
    const xff = req.headers['x-forwarded-for'];
    if (xff) return String(xff).split(',')[0].trim();
  }
  return req.socket.remoteAddress || 'unknown';
}

function hashIp(ip) {
  return crypto.createHash('sha256').update(IP_HASH_SALT + ip).digest('hex').slice(0, 24);
}

async function readJsonBody(req, { maxBytes = 32 * 1024 } = {}) {
  return new Promise((resolve, reject) => {
    let size = 0;
    const chunks = [];
    req.on('data', (chunk) => {
      size += chunk.length;
      if (size > maxBytes) {
        reject(Object.assign(new Error('Payload too large'), { statusCode: 413 }));
        req.destroy();
        return;
      }
      chunks.push(chunk);
    });
    req.on('end', () => {
      if (chunks.length === 0) return resolve({});
      try {
        resolve(JSON.parse(Buffer.concat(chunks).toString('utf8')));
      } catch (err) {
        reject(Object.assign(new Error('Invalid JSON body'), { statusCode: 400 }));
      }
    });
    req.on('error', reject);
  });
}

function applyCors(req, res) {
  const allowedOrigin = process.env.ALLOWED_ORIGIN;
  if (!allowedOrigin) return; // same-origin deployment — nothing to do
  res.setHeader('Access-Control-Allow-Origin', allowedOrigin);
  res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');
  res.setHeader('Vary', 'Origin');
}

const STATIC_CONTENT_TYPES = {
  '.html': 'text/html; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.ico': 'image/x-icon',
};

function serveStatic(res, filePath) {
  fs.readFile(filePath, (err, data) => {
    if (err) {
      sendJson(res, 404, { ok: false, message: 'Not found.' });
      return;
    }
    const ext = path.extname(filePath).toLowerCase();
    res.writeHead(200, {
      'Content-Type': STATIC_CONTENT_TYPES[ext] || 'application/octet-stream',
      'Content-Length': data.length,
    });
    res.end(data);
  });
}

// ---------------------------------------------------------------------
// route handlers
// ---------------------------------------------------------------------

// Sends the notification and persists its outcome, without the caller
// (the request handler) ever awaiting it. mailer.sendLeadNotification()
// itself never throws, but this is guarded anyway — nothing in here may
// ever surface as an unhandled rejection.
function sendLeadNotificationInBackground(lead) {
  mailer
    .sendLeadNotification(lead)
    .then((result) => {
      db.recordNotificationResult(lead.id, result.status === 'sent'
        ? { status: 'sent' }
        : { status: result.status, error: result.error });
      if (result.status === 'failed') {
        logger.error('Lead saved but notification email failed — will retry automatically.', {
          leadId: lead.id,
          error: result.error,
        });
      }
    })
    .catch((err) => {
      db.recordNotificationResult(lead.id, { status: 'failed', error: err.message });
      logger.error('Unexpected error while sending lead notification', { leadId: lead.id, error: err.message });
    });
}

async function handleCreateLead(req, res) {
  const clientIp = getClientIp(req);
  const rl = checkRateLimit(`lead:${hashIp(clientIp)}`, {
    max: RATE_LIMIT_MAX,
    windowMs: RATE_LIMIT_WINDOW_MIN * 60 * 1000,
  });
  if (!rl.allowed) {
    res.setHeader('Retry-After', String(rl.retryAfterSeconds));
    logger.warn('Rate limit hit on /api/leads', { ipHash: hashIp(clientIp) });
    return sendJson(res, 429, { ok: false, message: 'Too many attempts. Please try again in a few minutes.' });
  }

  let body;
  try {
    body = await readJsonBody(req);
  } catch (err) {
    return sendJson(res, err.statusCode || 400, { ok: false, message: 'Malformed request.' });
  }

  const validation = validateLeadPayload(body);
  if (!validation.ok) {
    if (validation.errors) {
      return sendJson(res, 422, { ok: false, errors: validation.errors });
    }
    return sendJson(res, 400, { ok: false, message: validation.message || 'Invalid submission.' });
  }

  let upsertResult;
  try {
    upsertResult = db.upsertLead({ ...validation.sanitized, ip_hash: hashIp(clientIp) });
  } catch (err) {
    // The lead is NOT considered submitted if this fails — no success
    // response, nothing silently dropped.
    logger.error('Failed to persist lead to database', { error: err.message });
    return sendJson(res, 500, { ok: false, message: 'Something went wrong. Please try again.' });
  }

  const { lead, isNew, shouldNotify } = upsertResult;
  logger.info(isNew ? 'New lead captured' : 'Duplicate lead resubmission recorded', {
    leadId: lead.id,
    email: lead.email,
    duplicateCount: lead.duplicate_count,
  });

  // The database write already succeeded, so the visitor's submission is
  // successful right now, full stop — email delivery is a background
  // concern from here. We deliberately do NOT await the send before
  // responding: Gmail (or the network path to it) being slow or briefly
  // unreachable must never make a visitor sit on a spinning "Create
  // account" button. The send still happens — just after the response —
  // and its outcome is persisted either way, with the automatic retry
  // sweep and the admin "Resend" button as the safety net if it fails.
  if (shouldNotify) {
    sendLeadNotificationInBackground(lead);
  }

  return sendJson(res, 200, {
    ok: true,
    status: isNew ? 'created' : 'duplicate',
    message: "You're on the list.",
    lead: { id: lead.id, name: lead.name, email: lead.email },
  });
}

// ---------------------------------------------------------------------
// auth (login / dashboard) route handlers
// ---------------------------------------------------------------------

function publicUser(user) {
  return { id: user.id, name: user.name, email: user.email };
}

async function handleLogin(req, res) {
  const clientIp = getClientIp(req);
  const rl = checkRateLimit(`login:${hashIp(clientIp)}`, {
    max: LOGIN_RATE_LIMIT_MAX,
    windowMs: LOGIN_RATE_LIMIT_WINDOW_MIN * 60 * 1000,
  });
  if (!rl.allowed) {
    res.setHeader('Retry-After', String(rl.retryAfterSeconds));
    logger.warn('Rate limit hit on /api/auth/login', { ipHash: hashIp(clientIp) });
    return sendJson(res, 429, { ok: false, message: 'Too many attempts. Please try again in a few minutes.' });
  }

  let body;
  try {
    body = await readJsonBody(req);
  } catch (err) {
    return sendJson(res, err.statusCode || 400, { ok: false, message: 'Malformed request.' });
  }

  const email = typeof body.email === 'string' ? body.email.trim() : '';
  const password = typeof body.password === 'string' ? body.password : '';

  if (!validEmail(email) || !password) {
    return sendJson(res, 422, { ok: false, message: 'Enter a valid email and password.' });
  }

  const user = db.findUserByEmail(email);
  // Deliberately identical error for "no such user" and "wrong password" —
  // never let a login form reveal which one was wrong.
  if (!user || !verifyPassword(password, user.password_hash)) {
    logger.warn('Failed login attempt', { ipHash: hashIp(clientIp), email: email.toLowerCase() });
    return sendJson(res, 401, { ok: false, message: 'Incorrect email or password.' });
  }

  const { token, expiresAt } = session.createSessionForUser(user.id);
  // "Remember me" controls the COOKIE's lifetime, not the server-side
  // session's — that always expires at SESSION_TTL_HOURS either way.
  // Unchecked, the cookie carries no Max-Age at all, so the browser drops
  // it when the browser itself closes even though the session would still
  // be valid server-side until then.
  const remember = body.remember !== false;
  const maxAgeSeconds = remember
    ? Math.round((new Date(expiresAt).getTime() - Date.now()) / 1000)
    : undefined;
  session.setSessionCookie(req, res, token, maxAgeSeconds);

  logger.info('User logged in', { userId: user.id });
  return sendJson(res, 200, { ok: true, user: publicUser(user) });
}

function handleLogout(req, res) {
  session.destroySession(req);
  session.clearSessionCookie(req, res);
  return sendJson(res, 200, { ok: true });
}

function handleMe(req, res) {
  const user = session.getRequestUser(req);
  if (!user) {
    return sendJson(res, 401, { ok: false, message: 'Not authenticated.' });
  }
  return sendJson(res, 200, { ok: true, user: publicUser(user) });
}

function handleDashboardData(req, res) {
  const user = session.getRequestUser(req);
  if (!user) {
    return sendJson(res, 401, { ok: false, message: 'Not authenticated.' });
  }
  return sendJson(res, 200, { ok: true, data: getDashboardData(user) });
}

function handleAdminDashboard(req, res, url) {
  if (!isAdminAuthorized(req, url)) {
    return sendJson(res, 401, { ok: false, message: 'Unauthorized.' });
  }
  const leads = db.listLeads({ limit: 1000 });
  const html = renderAdminDashboard(leads, { key: url.searchParams.get('key') || req.headers['x-admin-key'], totalCount: db.countLeads() });
  res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8', 'Cache-Control': 'no-store' });
  res.end(html);
}

function handleListLeadsJson(req, res, url) {
  if (!isAdminAuthorized(req, url)) {
    return sendJson(res, 401, { ok: false, message: 'Unauthorized.' });
  }
  const leads = db.listLeads({ limit: 1000 });
  return sendJson(res, 200, { ok: true, count: leads.length, total: db.countLeads(), leads });
}

function handleExportCsv(req, res, url) {
  if (!isAdminAuthorized(req, url)) {
    return sendJson(res, 401, { ok: false, message: 'Unauthorized.' });
  }
  const leads = db.listLeads({ limit: 100000 });
  const csv = leadsToCsv(leads);
  res.writeHead(200, {
    'Content-Type': 'text/csv; charset=utf-8',
    'Content-Disposition': `attachment; filename="zoey-leads-${new Date().toISOString().slice(0, 10)}.csv"`,
    'Cache-Control': 'no-store',
  });
  res.end(csv);
}

async function handleResendNotification(req, res, url, leadId) {
  if (!isAdminAuthorized(req, url)) {
    return sendJson(res, 401, { ok: false, message: 'Unauthorized.' });
  }
  const lead = db.getLeadById(leadId);
  if (!lead) {
    return sendJson(res, 404, { ok: false, message: 'Lead not found.' });
  }
  const result = await retryOneLead(lead);

  // The admin dashboard's resend button is a plain HTML form POST (no JS),
  // so redirect back to the dashboard with the same key rather than
  // returning raw JSON to a full-page navigation.
  const accept = req.headers['accept'] || '';
  if (accept.includes('application/json')) {
    return sendJson(res, 200, { ok: true, result });
  }
  const key = url.searchParams.get('key') || '';
  res.writeHead(303, { Location: `/admin?key=${encodeURIComponent(key)}` });
  res.end();
}

// ---------------------------------------------------------------------
// router
// ---------------------------------------------------------------------

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, `http://${req.headers.host || 'localhost'}`);
  applyCors(req, res);

  if (req.method === 'OPTIONS') {
    res.writeHead(204);
    return res.end();
  }

  try {
    if (req.method === 'GET' && url.pathname === '/healthz') {
      return sendJson(res, 200, { ok: true, uptimeSeconds: Math.round(process.uptime()) });
    }

    if (req.method === 'POST' && url.pathname === '/api/leads') {
      return await handleCreateLead(req, res);
    }

    const resendMatch = url.pathname.match(/^\/api\/leads\/(\d+)\/resend-notification$/);
    if (req.method === 'POST' && resendMatch) {
      return await handleResendNotification(req, res, url, Number(resendMatch[1]));
    }

    if (req.method === 'GET' && url.pathname === '/api/leads') {
      return handleListLeadsJson(req, res, url);
    }

    if (req.method === 'GET' && url.pathname === '/api/leads/export.csv') {
      return handleExportCsv(req, res, url);
    }

    if (req.method === 'GET' && url.pathname === '/admin') {
      return handleAdminDashboard(req, res, url);
    }

    if (req.method === 'POST' && url.pathname === '/api/auth/login') {
      return await handleLogin(req, res);
    }

    if (req.method === 'POST' && url.pathname === '/api/auth/logout') {
      return handleLogout(req, res);
    }

    if (req.method === 'GET' && url.pathname === '/api/auth/me') {
      return handleMe(req, res);
    }

    if (req.method === 'GET' && url.pathname === '/api/dashboard') {
      return handleDashboardData(req, res);
    }

    // /login and /dashboard are gated in both directions: an authenticated
    // visitor never sees the login page (redirected straight to the
    // dashboard), and an unauthenticated visitor never sees the dashboard
    // (redirected straight to login) — enforced here, server-side, not by
    // client-side JS that a visitor could simply skip.
    if (req.method === 'GET' && url.pathname === '/login') {
      const user = session.getRequestUser(req);
      if (user) {
        res.writeHead(302, { Location: '/dashboard' });
        return res.end();
      }
      return serveStatic(res, path.join(PUBLIC_DIR, 'login.html'));
    }

    if (req.method === 'GET' && url.pathname === '/dashboard') {
      const user = session.getRequestUser(req);
      if (!user) {
        res.writeHead(302, { Location: '/login' });
        return res.end();
      }
      return serveStatic(res, path.join(PUBLIC_DIR, 'dashboard.html'));
    }

    if (req.method === 'GET') {
      // Static site. Everything else falls through to index.html so
      // in-page anchors (e.g. /#about) and any direct path just render
      // the one-page site, matching how it behaved as a plain static file.
      const candidate = url.pathname === '/' ? 'index.html' : url.pathname.replace(/^\//, '');
      const safePath = path.normalize(path.join(PUBLIC_DIR, candidate));
      if (!safePath.startsWith(PUBLIC_DIR)) {
        return sendJson(res, 400, { ok: false, message: 'Invalid path.' });
      }
      if (fs.existsSync(safePath) && fs.statSync(safePath).isFile()) {
        return serveStatic(res, safePath);
      }
      return serveStatic(res, path.join(PUBLIC_DIR, 'index.html'));
    }

    return sendJson(res, 404, { ok: false, message: 'Not found.' });
  } catch (err) {
    logger.error('Unhandled request error', { error: err.message, path: url.pathname });
    if (!res.headersSent) {
      sendJson(res, 500, { ok: false, message: 'Something went wrong. Please try again.' });
    }
  }
});

server.listen(PORT, () => {
  logger.info(`Zoey backend listening on port ${PORT}`, {
    adminConfigured: Boolean(process.env.ADMIN_KEY),
    gmailConfigured: mailer.isConfigured(),
  });
});

// Background retry sweep for notifications that failed or were skipped
// (e.g. Gmail wasn't configured yet at submission time). Runs on an
// interval inside this same process — no external job scheduler needed.
if (RETRY_INTERVAL_MIN > 0) {
  setInterval(() => {
    retryAllFailedNotifications().catch((err) => {
      logger.error('Background retry sweep crashed', { error: err.message });
    });
  }, RETRY_INTERVAL_MIN * 60 * 1000).unref();
}

// Periodic cleanup of expired login sessions — nothing relies on this for
// correctness (getUserBySessionToken already excludes expired rows), it
// just keeps the sessions table from growing forever.
db.deleteExpiredSessions();
setInterval(() => {
  const removed = db.deleteExpiredSessions();
  if (removed > 0) logger.info('Cleaned up expired sessions', { removed });
}, 60 * 60 * 1000).unref();

module.exports = { server };
