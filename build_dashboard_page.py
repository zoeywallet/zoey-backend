logo_svg = open('/tmp/zw_logo.svg', encoding='utf-8').read()

HEAD = """<!doctype html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Dashboard — Zoey Wallet</title>
<meta name="robots" content="noindex">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,400;9..144,500;9..144,600&family=Inter:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500;600&display=swap" rel="stylesheet">
<style>
  :root{
    --white:#FFFFFF;
    --off-white:#F7F6F3;
    --ink:#0A0E14;
    --ink-soft: rgba(10,14,20,0.62);
    --ink-faint: rgba(10,14,20,0.40);
    --navy:#0B1220;
    --navy-deep:#05070C;
    --navy-surface:#111A2B;
    --cobalt:#3355FF;
    --cobalt-light:#5B7CFF;
    --green:#1A9A63;
    --red:#C23A3A;
    --border: rgba(10,14,20,0.11);
    --border-on-dark: rgba(247,246,243,0.13);
    --radius: 14px;
    --font-display: 'Fraunces', Georgia, serif;
    --font-body: 'Inter', 'Liberation Sans', sans-serif;
    --font-mono: 'IBM Plex Mono', 'Liberation Mono', monospace;
    --max: 1320px;
  }
  *{ margin:0; padding:0; box-sizing:border-box; }
  html{ scroll-behavior:smooth; }
  body{
    background: var(--off-white); color: var(--ink); font-family: var(--font-body);
    -webkit-font-smoothing:antialiased; overflow-x:hidden;
  }
  img,svg{ display:block; max-width:100%; }
  a{ color:inherit; text-decoration:none; }
  button{ font-family:inherit; cursor:pointer; }
  ul{ list-style:none; }
  @media (prefers-reduced-motion: reduce){
    *{ animation-duration:0.01ms !important; animation-iteration-count:1 !important; transition-duration:0.01ms !important; }
  }
  :focus-visible{ outline:2px solid var(--cobalt); outline-offset:3px; border-radius:4px; }

  .wrap{ max-width: var(--max); margin:0 auto; padding:0 48px; }
  .eyebrow{ font-family: var(--font-mono); font-size:12px; font-weight:500; letter-spacing:2px; text-transform:uppercase; color: var(--ink-faint); }

  .btn{ display:inline-flex; align-items:center; justify-content:center; gap:8px; font-family:var(--font-body); font-weight:600; font-size:14.5px; padding:13px 24px; border-radius:100px; border:1.5px solid transparent; transition: transform .15s ease, background .15s ease, border-color .15s ease; }
  .btn-primary{ background: var(--ink); color: var(--off-white); }
  .btn-primary:hover{ transform: translateY(-1px); background:#000; }
  .btn-outline{ border-color: var(--border); color: var(--ink); background:none; }
  .btn-outline:hover{ background: var(--ink); color: var(--off-white); border-color: var(--ink); }

  /* ============ TOP NAV ============ */
  header.dash-header{ position:fixed; top:0; left:0; right:0; z-index:100; background: rgba(247,246,243,0.86); backdrop-filter: blur(14px); -webkit-backdrop-filter: blur(14px); border-bottom:1px solid var(--border); }
  .dash-nav{ display:flex; align-items:center; justify-content:space-between; max-width: var(--max); margin:0 auto; padding:16px 48px; gap:24px; }
  .nav-logo svg{ height:22px; width:auto; }
  .dash-nav-links{ display:flex; align-items:center; gap:30px; flex:1 1 auto; justify-content:center; }
  .dash-nav-links a{ font-size:14px; font-weight:500; color: var(--ink-soft); transition: color .2s; white-space:nowrap; }
  .dash-nav-links a:hover{ color: var(--ink); }
  .dash-nav-links a.active{ color: var(--ink); position:relative; }
  .dash-nav-links a.active::after{ content:''; position:absolute; left:0; right:0; bottom:-19px; height:2px; background: var(--cobalt); }

  .dash-nav-actions{ position:relative; flex:0 0 auto; }
  .dash-profile-btn{
    display:flex; align-items:center; gap:9px; background:none; border:1px solid transparent;
    border-radius:100px; padding:5px 12px 5px 5px; transition: background .15s, border-color .15s;
  }
  .dash-profile-btn:hover{ background: rgba(10,14,20,0.04); border-color: var(--border); }
  .dash-avatar{
    width:30px; height:30px; border-radius:50%; background: var(--ink); color: var(--off-white);
    display:flex; align-items:center; justify-content:center; font-family:var(--font-mono); font-size:12px; font-weight:600;
    flex:0 0 auto;
  }
  .dash-profile-name{ font-size:13.5px; font-weight:600; color: var(--ink); }
  .dash-profile-chevron{ opacity:0.5; transition: transform .18s; }
  .dash-profile-btn[aria-expanded="true"] .dash-profile-chevron{ transform: rotate(180deg); }

  .dash-profile-menu{
    position:absolute; top:calc(100% + 10px); right:0; width:220px; background: var(--white);
    border:1px solid var(--border); border-radius:14px; box-shadow: 0 24px 48px -18px rgba(10,14,20,0.28);
    padding:8px; display:none; z-index:50;
  }
  .dash-profile-menu.open{ display:block; }
  .dash-profile-menu-header{ padding:10px 12px 12px; border-bottom:1px solid var(--border); margin-bottom:6px; }
  .dash-profile-menu-name{ font-size:13.5px; font-weight:600; color: var(--ink); }
  .dash-profile-menu-email{ font-size:12px; color: var(--ink-faint); margin-top:2px; word-break:break-all; }
  .dash-logout-btn{
    width:100%; text-align:left; padding:10px 12px; border-radius:8px; background:none; border:none;
    font-size:13.5px; font-weight:500; color: var(--red); transition: background .15s;
  }
  .dash-logout-btn:hover{ background: rgba(194,58,58,0.08); }

  .dash-nav-toggle{ display:none; background:none; border:1px solid var(--border); border-radius:8px; width:38px; height:38px; align-items:center; justify-content:center; color:var(--ink); }
  .dash-mobile-menu{ display:none; flex-direction:column; padding:10px 20px 16px; background: var(--off-white); border-top:1px solid var(--border); border-bottom:1px solid var(--border); }
  .dash-mobile-menu.open{ display:flex; }
  .dash-mobile-menu a, .dash-mobile-menu button{ padding:13px 4px; font-size:15px; text-align:left; color: var(--ink-soft); border-bottom:1px solid var(--border); background:none; border-left:none; border-right:none; border-top:none; }
  .dash-mobile-menu a.active{ color: var(--ink); font-weight:600; }
  .dash-mobile-menu button{ color: var(--red); font-weight:600; }
  .dash-mobile-menu :last-child{ border-bottom:none; }

  /* ============ MAIN ============ */
  .dash-main{ padding:112px 0 80px; min-height:100vh; }
  .dash-loading{ padding:120px 0; text-align:center; color: var(--ink-faint); font-family:var(--font-mono); font-size:13px; letter-spacing:1px; text-transform:uppercase; }

  .dash-intro{ margin-bottom:28px; }
  .dash-welcome{ margin-top:10px; font-family: var(--font-display); font-weight:500; letter-spacing:-0.01em; font-size:32px; color: var(--ink); }

  /* ---- dark portfolio card (reuses the homepage's signature visual
     language exactly, widened into a two-column layout) ---- */
  .dash-portfolio-card{
    background: var(--navy); border-radius:20px; padding:32px; color: var(--off-white);
    box-shadow: 0 40px 90px -30px rgba(10,14,20,0.35);
  }
  .pf-head{ display:flex; justify-content:space-between; align-items:flex-start; margin-bottom:26px; }
  .pf-label{ font-family:var(--font-mono); font-size:11.5px; letter-spacing:1.5px; color: rgba(247,246,243,0.45); margin-bottom:8px; }
  .pf-value{ font-family:var(--font-mono); font-size:40px; font-weight:600; }
  .pf-change{ font-family:var(--font-mono); font-size:14px; margin-top:8px; }
  .pf-change.up{ color: var(--green); } .pf-change.down{ color: var(--red); }
  .pf-badge{ display:flex; align-items:center; justify-content:center; width:32px; height:32px; border-radius:9px; background: rgba(51,85,255,0.14); flex:0 0 auto; }
  .pf-badge .badge-mark{ width:14px; height:auto; display:block; }

  .dash-portfolio-grid{ display:grid; grid-template-columns: 1.5fr 1fr; gap:36px; align-items:start; }
  .dash-chart-label{ font-family:var(--font-mono); font-size:10.5px; letter-spacing:1.2px; color: rgba(247,246,243,0.35); text-transform:uppercase; margin-bottom:10px; }
  .pf-chart svg{ width:100%; height:auto; }

  .pf-holdings{ display:flex; flex-direction:column; gap:0; }
  .pf-row{ display:flex; align-items:center; justify-content:space-between; padding:12px 0; border-top:1px solid var(--border-on-dark); }
  .pf-row:first-child{ border-top:none; }
  .pf-sym{ font-family:var(--font-mono); font-weight:600; font-size:14px; }
  .pf-name{ font-size:11px; color: rgba(247,246,243,0.4); margin-top:1px; }
  .pf-px{ font-family:var(--font-mono); font-size:14px; text-align:right; }
  .pf-chg{ font-family:var(--font-mono); font-size:11.5px; text-align:right; margin-top:2px; }
  .pf-chg.up{ color: var(--green); } .pf-chg.down{ color: var(--red); }

  /* ---- stablecoin funding card (light, separate section per spec) ---- */
  .dash-funding-card{
    margin-top:24px; background: var(--white); border:1px solid var(--border); border-radius:20px;
    padding:32px; box-shadow: 0 1px 2px rgba(10,14,20,0.03);
  }
  .dash-funding-head{ margin-bottom:22px; }
  .dash-funding-title{ margin-top:8px; font-family: var(--font-display); font-weight:500; font-size:22px; color: var(--ink); }
  .dash-funding-row{ display:flex; gap:14px; margin-bottom:22px; flex-wrap:wrap; }
  .dash-stable-pill{ flex:1 1 200px; background: var(--off-white); border:1px solid var(--border); border-radius:12px; padding:16px 18px; }
  .dash-stable-pill .lbl{ font-family:var(--font-mono); font-size:10.5px; color: var(--ink-faint); letter-spacing:1px; }
  .dash-stable-pill .val{ font-family:var(--font-mono); font-size:20px; font-weight:600; color: var(--ink); margin-top:6px; }
  .dash-funding-actions{ display:flex; gap:12px; flex-wrap:wrap; }
  .dash-funding-actions .btn{ flex:1 1 140px; }

  /* ---- toast ---- */
  .dash-toast{
    position:fixed; left:50%; bottom:28px; transform:translateX(-50%) translateY(16px); z-index:200;
    background: var(--ink); color: var(--off-white); font-family:var(--font-body); font-size:13.5px; font-weight:500;
    padding:12px 20px; border-radius:100px; box-shadow: 0 20px 40px -12px rgba(10,14,20,0.4);
    opacity:0; pointer-events:none; transition: opacity .25s, transform .25s;
  }
  .dash-toast.show{ opacity:1; transform:translateX(-50%) translateY(0); }

  @media (max-width: 980px){
    .dash-nav-links{ display:none; }
    .dash-nav-toggle{ display:flex; }
    .dash-nav{ padding:16px 24px; }
    .wrap{ padding:0 24px; }
    .dash-portfolio-grid{ grid-template-columns: 1fr; gap:26px; }
    .dash-portfolio-card{ padding:24px; }
    .dash-funding-card{ padding:24px; }
    .pf-value{ font-size:32px; }
  }
  @media (max-width: 560px){
    .dash-welcome{ font-size:26px; }
    .dash-profile-name{ display:none; }
    .dash-funding-actions .btn{ flex:1 1 100%; }
  }
</style>
</head>
<body>
"""

BODY = f"""
<header class="dash-header">
  <nav class="dash-nav">
    <a href="/dashboard" class="nav-logo">{logo_svg}</a>
    <div class="dash-nav-links">
      <a href="/dashboard" class="active">Overview</a>
      <a href="#" data-soon="Markets">Markets</a>
      <a href="#" data-soon="Portfolio">Portfolio</a>
      <a href="#" data-soon="Transactions">Transactions</a>
      <a href="#" data-soon="Watchlist">Watchlist</a>
      <a href="#" data-soon="Settings">Settings</a>
    </div>
    <div class="dash-nav-actions">
      <button class="dash-profile-btn" id="dashProfileBtn" aria-haspopup="true" aria-expanded="false">
        <span class="dash-avatar" id="dashAvatar">Z</span>
        <span class="dash-profile-name" id="dashProfileName">&hellip;</span>
        <svg class="dash-profile-chevron" width="10" height="6" viewBox="0 0 10 6" fill="none"><path d="M1 1L5 5L9 1" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/></svg>
      </button>
      <div class="dash-profile-menu" id="dashProfileMenu">
        <div class="dash-profile-menu-header">
          <div class="dash-profile-menu-name" id="dashMenuName">&nbsp;</div>
          <div class="dash-profile-menu-email" id="dashMenuEmail">&nbsp;</div>
        </div>
        <button class="dash-logout-btn" id="dashLogoutBtn">Log out</button>
      </div>
    </div>
    <button class="dash-nav-toggle" id="dashNavToggle" aria-label="Open menu" aria-expanded="false">
      <svg viewBox="0 0 18 18" width="18" height="18" fill="none"><path d="M2 5 H16 M2 9 H16 M2 13 H16" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>
    </button>
  </nav>
  <div class="dash-mobile-menu" id="dashMobileMenu">
    <a href="/dashboard" class="active">Overview</a>
    <a href="#" data-soon="Markets">Markets</a>
    <a href="#" data-soon="Portfolio">Portfolio</a>
    <a href="#" data-soon="Transactions">Transactions</a>
    <a href="#" data-soon="Watchlist">Watchlist</a>
    <a href="#" data-soon="Settings">Settings</a>
    <button id="dashLogoutBtnMobile">Log out</button>
  </div>
</header>

<main class="dash-main">
  <div class="wrap">
    <div class="dash-loading" id="dashLoading">Loading your dashboard&hellip;</div>

    <div id="dashContent" style="display:none;">
      <div class="dash-intro">
        <div class="eyebrow">OVERVIEW</div>
        <h1 class="dash-welcome" id="dashWelcome">Welcome back.</h1>
      </div>

      <div class="dash-portfolio-card">
        <div class="pf-head">
          <div>
            <div class="pf-label">PORTFOLIO VALUE</div>
            <div class="pf-value" id="dashPfValue">$0.00</div>
            <div class="pf-change" id="dashPfChange">&nbsp;</div>
          </div>
          <div class="pf-badge"><svg class="badge-mark" viewBox="165 84 1359 1671" xmlns="http://www.w3.org/2000/svg"><defs><linearGradient id="dashBadgeGrad" x1="0%" y1="0%" x2="100%" y2="0%"><stop offset="0%" stop-color="#8C9AFF"/><stop offset="55%" stop-color="#6E7EFF"/><stop offset="100%" stop-color="#4A55FF"/></linearGradient></defs><g fill="url(#dashBadgeGrad)"><path d="M 166,1024 L 172,1026 L 182,1020 L 195,1019 L 285,983 L 296,982 L 405,941 L 459,925 L 669,848 L 725,832 L 894,769 L 930,760 L 1103,698 L 1117,696 L 1204,662 L 1264,646 L 1316,626 L 1357,618 L 1502,562 L 1516,560 L 1524,550 L 1449,521 L 1394,505 L 1236,448 L 1223,447 L 1217,442 L 1182,433 L 1097,400 L 1053,388 L 1010,370 L 851,319 L 804,299 L 656,248 L 562,219 L 411,163 L 395,161 L 329,135 L 169,84 L 165,89 Z"/><path d="M 1520,1752 L 1520,811 L 1517,807 L 1412,847 L 1396,849 L 1354,867 L 1208,914 L 1183,926 L 1105,949 L 1096,955 L 914,1019 L 896,1022 L 788,1062 L 776,1063 L 605,1127 L 409,1192 L 301,1233 L 262,1243 L 197,1269 L 183,1271 L 172,1278 L 177,1285 L 244,1306 L 290,1326 L 303,1327 L 330,1339 L 344,1341 L 390,1361 L 403,1362 L 509,1403 L 709,1469 L 756,1489 L 1012,1576 L 1162,1632 L 1176,1634 L 1203,1646 L 1218,1648 L 1325,1688 L 1382,1705 L 1410,1718 L 1502,1748 L 1510,1754 Z"/></g></svg></div>
        </div>

        <div class="dash-portfolio-grid">
          <div>
            <div class="dash-chart-label">PORTFOLIO PERFORMANCE</div>
            <div class="pf-chart">
              <svg id="dashChartSvg" viewBox="0 0 560 160" width="100%" height="160" preserveAspectRatio="none">
                <defs><linearGradient id="dashAreaGrad" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="#3355FF" stop-opacity="0.35"/><stop offset="100%" stop-color="#3355FF" stop-opacity="0"/></linearGradient></defs>
                <path id="dashAreaPath" d="" fill="url(#dashAreaGrad)"/>
                <path id="dashLinePath" d="" fill="none" stroke="#5B7CFF" stroke-width="2.4" stroke-linecap="round"/>
              </svg>
            </div>
          </div>
          <div class="pf-holdings" id="dashHoldings"></div>
        </div>
      </div>

      <div class="dash-funding-card">
        <div class="dash-funding-head">
          <div class="eyebrow">STABLECOIN FUNDING</div>
          <h2 class="dash-funding-title">Fund your account</h2>
        </div>
        <div class="dash-funding-row">
          <div class="dash-stable-pill"><div class="lbl">USDT BALANCE</div><div class="val" id="dashUsdt">0.00</div></div>
          <div class="dash-stable-pill"><div class="lbl">USDC BALANCE</div><div class="val" id="dashUsdc">0.00</div></div>
        </div>
        <div class="dash-funding-actions">
          <button class="btn btn-primary" data-soon="Deposit">Deposit</button>
          <button class="btn btn-outline" data-soon="Buy">Buy</button>
          <button class="btn btn-outline" data-soon="Sell">Sell</button>
        </div>
      </div>
    </div>
  </div>
</main>

<div class="dash-toast" id="dashToast"></div>

<script>
(function(){{
  const loading = document.getElementById('dashLoading');
  const content = document.getElementById('dashContent');
  const toast = document.getElementById('dashToast');
  let toastTimer = null;

  function showToast(msg){{
    toast.textContent = msg;
    toast.classList.add('show');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => toast.classList.remove('show'), 2200);
  }}

  document.querySelectorAll('[data-soon]').forEach(el => {{
    el.addEventListener('click', (e) => {{
      e.preventDefault();
      showToast(el.getAttribute('data-soon') + ' is coming soon.');
    }});
  }});

  // ---- profile menu ----
  const profileBtn = document.getElementById('dashProfileBtn');
  const profileMenu = document.getElementById('dashProfileMenu');
  profileBtn.addEventListener('click', () => {{
    const open = profileMenu.classList.toggle('open');
    profileBtn.setAttribute('aria-expanded', String(open));
  }});
  document.addEventListener('click', (e) => {{
    if (!profileMenu.contains(e.target) && e.target !== profileBtn && !profileBtn.contains(e.target)){{
      profileMenu.classList.remove('open');
      profileBtn.setAttribute('aria-expanded', 'false');
    }}
  }});

  // ---- mobile nav ----
  const navToggle = document.getElementById('dashNavToggle');
  const mobileMenu = document.getElementById('dashMobileMenu');
  navToggle.addEventListener('click', () => {{
    const open = mobileMenu.classList.toggle('open');
    navToggle.setAttribute('aria-expanded', String(open));
  }});

  // ---- logout ----
  async function logout(){{
    try {{ await fetch('/api/auth/logout', {{ method: 'POST' }}); }} catch (e) {{}}
    window.location.href = '/login';
  }}
  document.getElementById('dashLogoutBtn').addEventListener('click', logout);
  document.getElementById('dashLogoutBtnMobile').addEventListener('click', logout);

  // ---- number formatting + count-up ----
  const money = (n) => '$' + n.toLocaleString('en-US', {{ minimumFractionDigits: 2, maximumFractionDigits: 2 }});
  const plain = (n) => n.toLocaleString('en-US', {{ minimumFractionDigits: 2, maximumFractionDigits: 2 }});

  function animateValue(el, to, formatFn, duration){{
    const start = performance.now();
    function tick(now){{
      const t = Math.min(1, (now - start) / duration);
      const eased = 1 - Math.pow(1 - t, 3);
      el.textContent = formatFn(to * eased);
      if (t < 1) requestAnimationFrame(tick);
    }}
    requestAnimationFrame(tick);
  }}

  function buildChart(points){{
    const w = 560, h = 160, pad = 6;
    const min = Math.min(...points), max = Math.max(...points);
    const range = (max - min) || 1;
    const stepX = (w - pad * 2) / (points.length - 1);
    const coords = points.map((p, i) => {{
      const x = pad + i * stepX;
      const y = h - pad - ((p - min) / range) * (h - pad * 2);
      return [x, y];
    }});
    const line = coords.map((c, i) => (i === 0 ? 'M' : 'L') + c[0].toFixed(1) + ',' + c[1].toFixed(1)).join(' ');
    const area = line + ` L${{coords[coords.length - 1][0].toFixed(1)}},${{h}} L${{coords[0][0].toFixed(1)}},${{h}} Z`;
    document.getElementById('dashLinePath').setAttribute('d', line);
    document.getElementById('dashAreaPath').setAttribute('d', area);
  }}

  // ---- load dashboard ----
  async function init(){{
    let meRes, dashRes;
    try {{
      [meRes, dashRes] = await Promise.all([
        fetch('/api/auth/me'),
        fetch('/api/dashboard'),
      ]);
    }} catch (err) {{
      window.location.href = '/login';
      return;
    }}

    if (meRes.status === 401 || dashRes.status === 401) {{
      window.location.href = '/login';
      return;
    }}

    const meData = await meRes.json();
    const dashData = await dashRes.json();
    if (!meData.ok || !dashData.ok) {{
      window.location.href = '/login';
      return;
    }}

    const user = meData.user;
    const data = dashData.data;

    document.getElementById('dashProfileName').textContent = user.name;
    document.getElementById('dashMenuName').textContent = user.name;
    document.getElementById('dashMenuEmail').textContent = user.email;
    document.getElementById('dashAvatar').textContent = (user.name || '?').trim().charAt(0).toUpperCase();
    document.getElementById('dashWelcome').textContent = 'Welcome back, ' + user.name.split(' ')[0] + '.';

    const changeEl = document.getElementById('dashPfChange');
    const up = data.todayChangeAbs >= 0;
    changeEl.className = 'pf-change ' + (up ? 'up' : 'down');
    changeEl.textContent = (up ? '+' : '−') + '$' + Math.abs(data.todayChangeAbs).toFixed(2) + ' \\u00b7 ' + (up ? '+' : '−') + Math.abs(data.todayChangePct).toFixed(2) + '% today';

    animateValue(document.getElementById('dashPfValue'), data.portfolioValue, money, 900);
    animateValue(document.getElementById('dashUsdt'), data.stablecoins.USDT, plain, 700);
    animateValue(document.getElementById('dashUsdc'), data.stablecoins.USDC, plain, 700);

    const holdingsEl = document.getElementById('dashHoldings');
    holdingsEl.innerHTML = data.holdings.map(h => {{
      const hUp = h.changePct >= 0;
      return `<div class="pf-row">
        <div><div class="pf-sym">${{h.symbol}}</div><div class="pf-name">${{h.name}}</div></div>
        <div><div class="pf-px">$${{h.price.toFixed(2)}}</div><div class="pf-chg ${{hUp ? 'up' : 'down'}}">${{hUp ? '+' : '−'}}${{Math.abs(h.changePct).toFixed(2)}}%</div></div>
      </div>`;
    }}).join('');

    buildChart(data.chartPoints);

    loading.style.display = 'none';
    content.style.display = 'block';
  }}

  init();
}})();
</script>
</body>
</html>
"""

open('public/dashboard.html', 'w', encoding='utf-8').write(HEAD + BODY)
print("wrote public/dashboard.html, bytes:", len(HEAD + BODY))
