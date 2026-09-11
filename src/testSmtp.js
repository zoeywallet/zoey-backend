// Standalone Gmail connection test — verifies GMAIL_USER/GMAIL_APP_PASSWORD/
// NOTIFY_TO actually work, without going through a full lead submission.
// Usage: npm run test:smtp

const { loadEnv } = require('./loadEnv');
loadEnv();

const mailer = require('./mailer');

async function main() {
  if (!mailer.isConfigured()) {
    console.error('GMAIL_USER, GMAIL_APP_PASSWORD, and NOTIFY_TO must all be set in .env first.');
    process.exit(1);
  }

  console.log(`Sending a test notification to ${process.env.NOTIFY_TO}...`);
  const testLead = {
    id: 0,
    name: 'Test Lead',
    email: 'test-lead@example.com',
    country: 'Nigeria',
    phone_e164: '+2348000000000',
    interest: 'exploring',
    source: 'test:smtp script',
    submitted_at: new Date().toISOString(),
    duplicate_count: 0,
  };

  const result = await mailer.sendLeadNotification(testLead);
  if (result.status === 'sent') {
    console.log('Success — check the inbox at NOTIFY_TO.');
    process.exit(0);
  } else {
    console.error('Failed:', result.status, result.error || '');
    process.exit(1);
  }
}

main();
