// Retries the Gmail notification for any lead whose notification never
// successfully went out (status pending/failed/skipped_no_credentials),
// up to RETRY_MAX_ATTEMPTS attempts each. Three ways this runs:
//   1. A background interval inside the running server (see server.js).
//   2. On demand, per-lead, from the admin dashboard's "Resend" button.
//   3. Standalone via `npm run retry-failed` — handy as a cron job hitting
//      a long-running deployment, or a one-off manual retry.

const db = require('./db');
const mailer = require('./mailer');
const logger = require('./logger');

async function retryOneLead(lead) {
  const result = await mailer.sendLeadNotification(lead);
  db.recordNotificationResult(lead.id, result.status === 'sent'
    ? { status: 'sent' }
    : { status: result.status, error: result.error });
  return result;
}

async function retryAllFailedNotifications() {
  const maxAttempts = Number(process.env.RETRY_MAX_ATTEMPTS || 5);
  const candidates = db.listFailedNotifications({ maxAttempts });

  if (candidates.length === 0) {
    logger.info('Retry sweep: nothing to retry.');
    return { attempted: 0, sent: 0, failed: 0 };
  }

  logger.info(`Retry sweep: attempting ${candidates.length} lead(s).`);
  let sent = 0;
  let failed = 0;
  for (const lead of candidates) {
    const result = await retryOneLead(lead);
    if (result.status === 'sent') sent += 1;
    else failed += 1;
  }
  logger.info('Retry sweep complete.', { attempted: candidates.length, sent, failed });
  return { attempted: candidates.length, sent, failed };
}

// Allow `node src/retryFailedNotifications.js` / `npm run retry-failed` to
// run this as a standalone one-off script.
if (require.main === module) {
  const { loadEnv } = require('./loadEnv');
  loadEnv();
  retryAllFailedNotifications()
    .then((summary) => {
      console.log('Done:', summary);
      process.exit(0);
    })
    .catch((err) => {
      console.error('Retry sweep crashed:', err);
      process.exit(1);
    });
}

module.exports = { retryAllFailedNotifications, retryOneLead };
