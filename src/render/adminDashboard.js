// Server-rendered admin dashboard: a single plain HTML page listing all
// leads, with an export link and per-row "resend notification" buttons for
// leads whose email failed or was skipped. No client-side framework, no
// build step — just a table. Protected by ADMIN_KEY (see adminAuth.js).

function escapeHtml(str) {
  return String(str ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

const STATUS_STYLES = {
  sent: 'background:#E4F7EF;color:#0F7A4C;',
  pending: 'background:#FFF3D6;color:#9A6B00;',
  failed: 'background:#FDE6E6;color:#B3261E;',
  skipped_no_credentials: 'background:#EDEBE5;color:#6B6656;',
};

function renderAdminDashboard(leads, { key, totalCount }) {
  const rows = leads
    .map((l) => {
      const badgeStyle = STATUS_STYLES[l.notification_status] || STATUS_STYLES.pending;
      const canResend = l.notification_status !== 'sent';
      return `
        <tr>
          <td>${l.id}</td>
          <td>${escapeHtml(l.name)}</td>
          <td><a href="mailto:${escapeHtml(l.email)}">${escapeHtml(l.email)}</a></td>
          <td>${escapeHtml(l.phone_e164 || '—')}</td>
          <td>${escapeHtml(l.country || '—')}</td>
          <td>${escapeHtml(l.interest || '—')}</td>
          <td>${escapeHtml(l.source || '—')}</td>
          <td>${l.duplicate_count > 0 ? `<span title="Submitted ${l.duplicate_count + 1} times">×${l.duplicate_count + 1}</span>` : '1'}</td>
          <td><span class="badge" style="${badgeStyle}">${escapeHtml(l.notification_status)}</span></td>
          <td>${escapeHtml(new Date(l.created_at).toLocaleString('en-US', { dateStyle: 'medium', timeStyle: 'short' }))}</td>
          <td>
            ${canResend
              ? `<form method="post" action="/api/leads/${l.id}/resend-notification?key=${encodeURIComponent(key)}" style="margin:0;">
                   <button type="submit" class="btn-sm">Resend</button>
                 </form>`
              : '—'}
          </td>
        </tr>`;
    })
    .join('');

  return `<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Zoey Wallet — Leads</title>
  <style>
    :root { color-scheme: light; }
    body { margin:0; padding:0; background:#F0EEE9; font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif; color:#141313; }
    header { background:#0B0F1A; padding:20px 28px; }
    header .brand { font-size:13px; font-weight:700; letter-spacing:.08em; text-transform:uppercase; color:#F7F6F3; }
    header .sub { font-size:11px; letter-spacing:.06em; text-transform:uppercase; color:#7C8AFF; margin-top:2px; }
    main { max-width:1200px; margin:0 auto; padding:28px 20px 60px; }
    .toolbar { display:flex; align-items:center; justify-content:space-between; margin-bottom:18px; flex-wrap:wrap; gap:10px; }
    .count { font-size:14px; color:#6B6656; }
    .export-link { display:inline-block; padding:9px 18px; background:#141313; color:#F7F6F3; text-decoration:none; font-size:13px; font-weight:600; border-radius:100px; }
    table { width:100%; border-collapse:collapse; background:#FFFFFF; border-radius:12px; overflow:hidden; box-shadow:0 1px 2px rgba(0,0,0,0.04); }
    th, td { padding:10px 12px; text-align:left; font-size:13px; border-bottom:1px solid #EDEBE5; white-space:nowrap; }
    th { background:#FAF9F6; font-size:11px; font-weight:700; letter-spacing:.04em; text-transform:uppercase; color:#8A8578; }
    tr:last-child td { border-bottom:none; }
    .badge { display:inline-block; padding:3px 9px; border-radius:100px; font-size:11px; font-weight:600; text-transform:uppercase; letter-spacing:.03em; }
    .btn-sm { padding:6px 12px; font-size:12px; font-weight:600; border-radius:100px; border:1px solid #D8D5CC; background:#FFF; cursor:pointer; }
    .btn-sm:hover { background:#F0EEE9; }
    .empty { padding:60px 20px; text-align:center; color:#8A8578; }
    .table-wrap { overflow-x:auto; border-radius:12px; }
  </style>
</head>
<body>
  <header>
    <div class="brand">Zoey Wallet</div>
    <div class="sub">Leads — Admin</div>
  </header>
  <main>
    <div class="toolbar">
      <div class="count">${totalCount} lead${totalCount === 1 ? '' : 's'} total${leads.length < totalCount ? ` — showing ${leads.length}` : ''}</div>
      <a class="export-link" href="/api/leads/export.csv?key=${encodeURIComponent(key)}">Export CSV</a>
    </div>
    ${leads.length === 0
      ? '<div class="empty">No leads yet. They\'ll show up here as soon as someone submits the form.</div>'
      : `<div class="table-wrap"><table>
          <thead>
            <tr>
              <th>ID</th><th>Name</th><th>Email</th><th>Phone</th><th>Country</th>
              <th>Interest</th><th>Source</th><th>Submits</th><th>Notification</th><th>Created</th><th></th>
            </tr>
          </thead>
          <tbody>${rows}</tbody>
        </table></div>`}
  </main>
</body>
</html>`;
}

module.exports = { renderAdminDashboard };
