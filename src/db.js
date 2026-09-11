// Lead database. Uses Node's built-in node:sqlite module (stable-ish as of
// Node 22.5+; still flagged "experimental" by Node itself, but it's a thin
// wrapper around SQLite's C library and behaves predictably) — no external
// dependency, no native module to compile, just a file on disk.
//
// Every successful form submission lands in the `leads` table. Email is
// UNIQUE: a resubmission from the same address updates the existing row
// (latest info wins) instead of creating a duplicate, and is tracked via
// duplicate_count. See upsertLead() for the exact policy.

const path = require('node:path');
const fs = require('node:fs');
const { DatabaseSync } = require('node:sqlite');
const logger = require('./logger');

const DB_PATH = process.env.LEADS_DB_PATH || path.join(__dirname, '..', 'data', 'leads.db');

fs.mkdirSync(path.dirname(DB_PATH), { recursive: true });

const db = new DatabaseSync(DB_PATH);

db.exec(`
  CREATE TABLE IF NOT EXISTS leads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT NOT NULL,
    phone_e164 TEXT,
    country TEXT,
    country_code TEXT,
    interest TEXT,
    source TEXT,
    submitted_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    ip_hash TEXT,
    duplicate_count INTEGER NOT NULL DEFAULT 0,
    notification_status TEXT NOT NULL DEFAULT 'pending',
    notification_attempts INTEGER NOT NULL DEFAULT 0,
    notification_last_error TEXT,
    notification_sent_at TEXT,
    UNIQUE(email)
  );

  CREATE INDEX IF NOT EXISTS idx_leads_notification_status ON leads(notification_status);
  CREATE INDEX IF NOT EXISTS idx_leads_created_at ON leads(created_at);

  CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
  );

  CREATE TABLE IF NOT EXISTS sessions (
    token TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
  );

  CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON sessions(user_id);
  CREATE INDEX IF NOT EXISTS idx_sessions_expires_at ON sessions(expires_at);
`);

logger.info('Database ready', { path: DB_PATH });

const NOTIFIABLE_RETRY_STATES = new Set(['pending', 'failed', 'skipped_no_credentials']);

/**
 * Insert a new lead, or — if the email already exists — update the existing
 * row with the latest submitted info and bump duplicate_count.
 *
 * Returns { lead, isNew, shouldNotify }:
 *   - isNew: true if this email had never been seen before.
 *   - shouldNotify: true if we should attempt a Gmail notification for this
 *     submission (always true for a new lead; also true for a resubmission
 *     whose previous notification never actually succeeded, so retrying is
 *     both correct and low-noise — it does not re-notify about a lead we
 *     already successfully told the admin about).
 */
function upsertLead(fields) {
  const now = new Date().toISOString();
  const email = fields.email.toLowerCase().trim();

  const existing = db.prepare('SELECT * FROM leads WHERE email = ?').get(email);

  if (!existing) {
    const insert = db.prepare(`
      INSERT INTO leads (
        name, email, phone_e164, country, country_code, interest, source,
        submitted_at, created_at, updated_at, ip_hash,
        duplicate_count, notification_status, notification_attempts
      ) VALUES (
        ?, ?, ?, ?, ?, ?, ?,
        ?, ?, ?, ?,
        0, 'pending', 0
      )
    `);
    const info = insert.run(
      fields.name,
      email,
      fields.phone_e164 ?? null,
      fields.country ?? null,
      fields.country_code ?? null,
      fields.interest ?? null,
      fields.source ?? null,
      fields.submitted_at ?? now,
      now,
      now,
      fields.ip_hash ?? null
    );
    const lead = db.prepare('SELECT * FROM leads WHERE id = ?').get(info.lastInsertRowid);
    return { lead, isNew: true, shouldNotify: true };
  }

  // Existing lead: refresh the mutable fields with whatever was just
  // submitted (people often re-submit with corrected info), track that a
  // duplicate happened, but never overwrite a notification we already sent.
  const update = db.prepare(`
    UPDATE leads SET
      name = ?, phone_e164 = ?, country = ?, country_code = ?,
      interest = ?, source = ?, submitted_at = ?, updated_at = ?,
      ip_hash = COALESCE(?, ip_hash),
      duplicate_count = duplicate_count + 1
    WHERE id = ?
  `);
  update.run(
    fields.name,
    fields.phone_e164 ?? existing.phone_e164,
    fields.country ?? existing.country,
    fields.country_code ?? existing.country_code,
    fields.interest ?? existing.interest,
    fields.source ?? existing.source,
    fields.submitted_at ?? now,
    now,
    fields.ip_hash ?? null,
    existing.id
  );

  const lead = db.prepare('SELECT * FROM leads WHERE id = ?').get(existing.id);
  const shouldNotify = NOTIFIABLE_RETRY_STATES.has(existing.notification_status);
  return { lead, isNew: false, shouldNotify };
}

function recordNotificationResult(id, { status, error, attempted = true }) {
  const now = new Date().toISOString();
  if (status === 'sent') {
    db.prepare(`
      UPDATE leads SET
        notification_status = 'sent',
        notification_attempts = notification_attempts + ?,
        notification_last_error = NULL,
        notification_sent_at = ?,
        updated_at = ?
      WHERE id = ?
    `).run(attempted ? 1 : 0, now, now, id);
  } else {
    db.prepare(`
      UPDATE leads SET
        notification_status = ?,
        notification_attempts = notification_attempts + ?,
        notification_last_error = ?,
        updated_at = ?
      WHERE id = ?
    `).run(status, attempted ? 1 : 0, error ? String(error).slice(0, 2000) : null, now, id);
  }
}

function getLeadById(id) {
  return db.prepare('SELECT * FROM leads WHERE id = ?').get(id);
}

function listLeads({ limit = 500, offset = 0 } = {}) {
  return db
    .prepare('SELECT * FROM leads ORDER BY created_at DESC LIMIT ? OFFSET ?')
    .all(limit, offset);
}

function countLeads() {
  const row = db.prepare('SELECT COUNT(*) AS n FROM leads').get();
  return row.n;
}

function listFailedNotifications({ maxAttempts = 5 } = {}) {
  return db
    .prepare(`
      SELECT * FROM leads
      WHERE notification_status IN ('pending', 'failed', 'skipped_no_credentials')
        AND notification_attempts < ?
      ORDER BY created_at ASC
    `)
    .all(maxAttempts);
}

// ---------------------------------------------------------------------
// Users & sessions (login / dashboard auth)
// ---------------------------------------------------------------------

function createUser({ email, name, passwordHash }) {
  const now = new Date().toISOString();
  const insert = db.prepare(`
    INSERT INTO users (email, name, password_hash, created_at, updated_at)
    VALUES (?, ?, ?, ?, ?)
  `);
  const info = insert.run(email.toLowerCase().trim(), name, passwordHash, now, now);
  return db.prepare('SELECT * FROM users WHERE id = ?').get(info.lastInsertRowid);
}

function updateUserPassword(userId, passwordHash) {
  db.prepare('UPDATE users SET password_hash = ?, updated_at = ? WHERE id = ?').run(
    passwordHash,
    new Date().toISOString(),
    userId
  );
}

function findUserByEmail(email) {
  return db.prepare('SELECT * FROM users WHERE email = ?').get(String(email).toLowerCase().trim());
}

function getUserById(id) {
  return db.prepare('SELECT * FROM users WHERE id = ?').get(id);
}

function listUsers() {
  return db.prepare('SELECT id, email, name, created_at FROM users ORDER BY created_at DESC').all();
}

function createSession({ token, userId, expiresAt }) {
  const now = new Date().toISOString();
  db.prepare(`
    INSERT INTO sessions (token, user_id, created_at, expires_at)
    VALUES (?, ?, ?, ?)
  `).run(token, userId, now, expiresAt);
}

/** Returns the user row for a valid, non-expired session token, or null. */
function getUserBySessionToken(token) {
  if (!token) return null;
  const row = db
    .prepare(`
      SELECT users.* FROM sessions
      JOIN users ON users.id = sessions.user_id
      WHERE sessions.token = ? AND sessions.expires_at > ?
    `)
    .get(token, new Date().toISOString());
  return row || null;
}

function deleteSession(token) {
  db.prepare('DELETE FROM sessions WHERE token = ?').run(token);
}

function deleteExpiredSessions() {
  const info = db.prepare('DELETE FROM sessions WHERE expires_at <= ?').run(new Date().toISOString());
  return info.changes;
}

module.exports = {
  db,
  upsertLead,
  recordNotificationResult,
  getLeadById,
  listLeads,
  countLeads,
  listFailedNotifications,
  createUser,
  updateUserPassword,
  findUserByEmail,
  getUserById,
  listUsers,
  createSession,
  getUserBySessionToken,
  deleteSession,
  deleteExpiredSessions,
};
