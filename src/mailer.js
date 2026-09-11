// Sends the "New Zoey Wallet Lead" notification via Gmail, using an App
// Password over SMTP (smtp.gmail.com:465). Credentials come ONLY from
// environment variables (GMAIL_USER, GMAIL_APP_PASSWORD, NOTIFY_TO) — never
// hardcoded, never sent to the frontend.
//
// If credentials aren't configured, sendLeadNotification() logs a clear
// warning and returns a "skipped" result instead of throwing — this lets
// the rest of the app (DB writes, API responses) be developed and tested
// before Gmail is wired up, without crashing lead submissions.

const nodemailer = require('nodemailer');
const logger = require('./logger');
const { buildLeadEmail } = require('./render/emailTemplate');

function isConfigured() {
  return Boolean(process.env.GMAIL_USER && process.env.GMAIL_APP_PASSWORD && process.env.NOTIFY_TO);
}

const CONNECT_TIMEOUT_MS = Number(process.env.SMTP_TIMEOUT_MS || 10000);

let cachedTransporter = null;
function getTransporter() {
  if (cachedTransporter) return cachedTransporter;
  cachedTransporter = nodemailer.createTransport({
    host: 'smtp.gmail.com',
    port: 465,
    secure: true, // implicit TLS
    auth: {
      user: process.env.GMAIL_USER,
      // Gmail App Passwords are shown with spaces in the Google Account UI
      // (e.g. "abcd efgh ijkl mnop") but must be used without them.
      pass: process.env.GMAIL_APP_PASSWORD.replace(/\s+/g, ''),
    },
    // Fail fast rather than hanging: a network that silently drops outbound
    // SMTP (some sandboxes/PaaS platforms do) would otherwise leave a
    // connection attempt hanging for nodemailer's 2-minute default, which
    // is far too long to let anything wait on — see sendLeadNotification(),
    // which never lets a caller block on this anyway.
    connectionTimeout: CONNECT_TIMEOUT_MS,
    greetingTimeout: CONNECT_TIMEOUT_MS,
    socketTimeout: CONNECT_TIMEOUT_MS,
  });
  return cachedTransporter;
}

/**
 * Sends the lead-notification email for a given lead row.
 * Returns { status: 'sent' } | { status: 'skipped_no_credentials' } | { status: 'failed', error }.
 * Never throws — callers should check the returned status rather than
 * wrapping this in try/catch for control flow (though it's still safe to).
 */
async function sendLeadNotification(lead) {
  if (!isConfigured()) {
    logger.warn('Gmail is not configured (GMAIL_USER/GMAIL_APP_PASSWORD/NOTIFY_TO) — skipping notification email.', {
      leadId: lead.id,
    });
    return { status: 'skipped_no_credentials' };
  }

  const dashboardUrl = process.env.APP_BASE_URL ? `${process.env.APP_BASE_URL.replace(/\/$/, '')}/admin` : null;
  const { subject, text, html } = buildLeadEmail(lead, { dashboardUrl });

  try {
    const transporter = getTransporter();
    await transporter.sendMail({
      from: `"Zoey Wallet Leads" <${process.env.GMAIL_USER}>`,
      to: process.env.NOTIFY_TO,
      subject,
      text,
      html,
    });
    logger.info('Lead notification email sent', { leadId: lead.id, to: process.env.NOTIFY_TO });
    return { status: 'sent' };
  } catch (err) {
    logger.error('Lead notification email failed to send', { leadId: lead.id, error: err.message });
    return { status: 'failed', error: err.message };
  }
}

module.exports = { sendLeadNotification, isConfigured };
