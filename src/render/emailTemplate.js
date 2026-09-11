// Builds the "New Zoey Wallet Lead" notification email — both a plain-text
// and an HTML version (email clients vary wildly in HTML support, so a
// text fallback matters). Branding is simple, table-based, inline-styled
// HTML — the safest thing across Gmail, Outlook, Apple Mail, etc.

const INTEREST_LABELS = {
  us_stocks: 'Investing in US stocks',
  global_equities: 'Global equities',
  stablecoin_access: 'Stablecoin → stock access',
  exploring: 'Just exploring',
};

function escapeHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function formatTimestamp(iso) {
  try {
    const d = new Date(iso);
    return d.toLocaleString('en-US', {
      dateStyle: 'medium',
      timeStyle: 'short',
      timeZone: 'UTC',
    }) + ' UTC';
  } catch {
    return iso;
  }
}

function buildLeadEmail(lead, { dashboardUrl } = {}) {
  const interestLabel = lead.interest ? (INTEREST_LABELS[lead.interest] || lead.interest) : 'Not specified';
  const country = lead.country || 'Not specified';
  const phone = lead.phone_e164 || 'Not provided';
  const submitted = formatTimestamp(lead.submitted_at || lead.created_at);
  const isReturning = lead.duplicate_count > 0;

  const subject = `New Zoey Wallet Lead — ${lead.name}`;

  const textLines = [
    'NEW ZOEY WALLET LEAD',
    '',
    'A new lead has submitted the Zoey Wallet form.',
    '',
    `Name: ${lead.name}`,
    `Email: ${lead.email}`,
    `Country: ${country}`,
    `Interest: ${interestLabel}`,
    `Phone: ${phone}`,
    `Source: ${lead.source || 'Not specified'}`,
    `Submitted: ${submitted}`,
  ];
  if (isReturning) {
    textLines.push('', `Note: this email has submitted the form ${lead.duplicate_count + 1} time(s).`);
  }
  if (dashboardUrl) {
    textLines.push('', `View all leads: ${dashboardUrl}`);
  }
  const text = textLines.join('\n');

  const rows = [
    ['Name', lead.name],
    ['Email', lead.email],
    ['Country', country],
    ['Interest', interestLabel],
    ['Phone', phone],
    ['Source', lead.source || 'Not specified'],
    ['Submitted', submitted],
  ];

  const rowsHtml = rows
    .map(
      ([label, value]) => `
        <tr>
          <td style="padding:10px 16px;border-bottom:1px solid #E7E5E0;font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;font-size:12px;font-weight:600;letter-spacing:.04em;text-transform:uppercase;color:#8A8578;white-space:nowrap;vertical-align:top;">${escapeHtml(label)}</td>
          <td style="padding:10px 16px;border-bottom:1px solid #E7E5E0;font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;font-size:14px;color:#141313;">${escapeHtml(value)}</td>
        </tr>`
    )
    .join('');

  const returningNoticeHtml = isReturning
    ? `<tr><td colspan="2" style="padding:10px 16px;font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;font-size:12.5px;color:#8A8578;">This email has submitted the form ${lead.duplicate_count + 1} time(s).</td></tr>`
    : '';

  const dashboardHtml = dashboardUrl
    ? `<tr><td colspan="2" style="padding:18px 16px 4px;text-align:center;">
         <a href="${escapeHtml(dashboardUrl)}" style="display:inline-block;padding:11px 22px;background:#141313;color:#F7F6F3;text-decoration:none;font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;font-size:13px;font-weight:600;border-radius:100px;">View all leads</a>
       </td></tr>`
    : '';

  const html = `<!doctype html>
<html>
  <head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"></head>
  <body style="margin:0;padding:0;background:#F0EEE9;">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#F0EEE9;padding:32px 16px;">
      <tr>
        <td align="center">
          <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:520px;background:#FFFFFF;border-radius:16px;overflow:hidden;border:1px solid #E7E5E0;">
            <tr>
              <td style="background:#0B0F1A;padding:24px 28px;">
                <span style="font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;font-size:13px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:#F7F6F3;">Zoey Wallet</span>
                <div style="font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;font-size:11px;letter-spacing:.06em;text-transform:uppercase;color:#7C8AFF;margin-top:2px;">Infrastructure</div>
              </td>
            </tr>
            <tr>
              <td style="padding:26px 28px 6px;">
                <div style="font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;font-size:11px;font-weight:600;letter-spacing:.08em;text-transform:uppercase;color:#5B7CFF;">New Lead</div>
                <div style="font-family:Georgia,'Times New Roman',serif;font-size:22px;color:#141313;margin-top:6px;">${escapeHtml(lead.name)}</div>
              </td>
            </tr>
            <tr>
              <td style="padding:10px 12px 4px;">
                <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
                  ${rowsHtml}
                  ${returningNoticeHtml}
                </table>
              </td>
            </tr>
            ${dashboardHtml}
            <tr>
              <td style="padding:22px 28px 26px;">
                <div style="font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;font-size:11.5px;color:#B3AFA3;text-align:center;">Automated notification from the Zoey Wallet lead-capture system.</div>
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
  </body>
</html>`;

  return { subject, text, html };
}

module.exports = { buildLeadEmail };
