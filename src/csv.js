// Tiny CSV writer (no dependency). Handles quoting per RFC 4180: any field
// containing a comma, quote, or newline gets wrapped in quotes with
// internal quotes doubled.

function csvField(value) {
  const str = value === null || value === undefined ? '' : String(value);
  if (/[",\n\r]/.test(str)) {
    return `"${str.replace(/"/g, '""')}"`;
  }
  return str;
}

function leadsToCsv(leads) {
  const headers = [
    'id', 'name', 'email', 'phone_e164', 'country', 'country_code',
    'interest', 'source', 'submitted_at', 'created_at', 'duplicate_count',
    'notification_status', 'notification_sent_at',
  ];
  const lines = [headers.join(',')];
  for (const l of leads) {
    lines.push(headers.map((h) => csvField(l[h])).join(','));
  }
  return lines.join('\r\n') + '\r\n';
}

module.exports = { leadsToCsv };
