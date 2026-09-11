import re

logo_svg = open('/tmp/zw_logo.svg', encoding='utf-8').read()

HEAD = """<!doctype html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Log In — Zoey Wallet</title>
<meta name="description" content="Log in to your Zoey Wallet account.">
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
  }
  *{ margin:0; padding:0; box-sizing:border-box; }
  html{ height:100%; }
  body{
    height:100%; background: var(--off-white); color: var(--ink); font-family: var(--font-body);
    -webkit-font-smoothing:antialiased; overflow-x:hidden;
  }
  img,svg{ display:block; max-width:100%; }
  a{ color:inherit; text-decoration:none; }
  button{ font-family:inherit; cursor:pointer; }
  input{ font-family:inherit; }
  @media (prefers-reduced-motion: reduce){
    *{ animation-duration:0.01ms !important; animation-iteration-count:1 !important; transition-duration:0.01ms !important; }
  }
  :focus-visible{ outline:2px solid var(--cobalt); outline-offset:3px; border-radius:4px; }

  .eyebrow{ font-family: var(--font-mono); font-size:12px; font-weight:500; letter-spacing:2px; text-transform:uppercase; color: var(--ink-faint); }
  .eyebrow.on-dark{ color: rgba(247,246,243,0.45); }
  .lede{ color: var(--ink-soft); font-size:15px; line-height:1.6; font-family: var(--font-body); font-weight:400; }

  /* ---- shared form controls (same visual language as the site's
     "Get started" modal, so this page reads as the same product) ---- */
  .zw-field{ display:flex; flex-direction:column; gap:7px; }
  .zw-label{ font-family: var(--font-body); font-size:12.5px; font-weight:600; color: var(--ink-soft); }
  .zw-input{
    height:48px; padding:0 15px; border-radius:12px; border:1px solid var(--border);
    background: var(--off-white); font-family: var(--font-body); font-size:14.5px; color: var(--ink);
    width:100%; box-sizing:border-box; transition: border-color .18s, box-shadow .18s, background .18s;
  }
  .zw-input::placeholder{ color: var(--ink-faint); }
  .zw-input:focus{
    outline:none; border-color: var(--cobalt); background: var(--white);
    box-shadow: 0 0 0 3px rgba(53,85,255,0.14);
  }
  .zw-field.has-error .zw-input{ border-color: var(--red); }
  .zw-field-error{ display:none; font-family: var(--font-body); font-size:12px; color: var(--red); }
  .zw-field.has-error .zw-field-error{ display:block; }
  /* auth-error: reddens the input to echo the form-level "Incorrect email or
     password" banner, without showing a field-specific message that would
     misleadingly claim the field itself is malformed/empty. */
  .zw-field.auth-error .zw-input{ border-color: var(--red); }

  .zw-submit-btn{
    position:relative; width:100%; margin-top:6px; height:50px; border-radius:12px; border:none;
    background: var(--ink); color: var(--off-white); font-family: var(--font-body); font-size:15px; font-weight:600;
    cursor:pointer; transition: background .2s, transform .2s, opacity .2s;
  }
  .zw-submit-btn:hover{ background:#000; transform: translateY(-1px); }
  .zw-submit-btn:disabled{ opacity:0.6; cursor:not-allowed; transform:none; }
  .zw-submit-btn .zw-spinner{
    display:none; width:16px; height:16px; border-radius:50%;
    border:2px solid rgba(247,246,243,0.35); border-top-color: var(--off-white);
    animation: zwSpin .7s linear infinite; margin-right:8px; vertical-align:-3px;
  }
  .zw-submit-btn.loading .zw-spinner{ display:inline-block; }
  .zw-submit-btn.loading .zw-submit-label{ opacity:0.85; }
  .zw-submit-btn.success{ background: var(--green); }
  @keyframes zwSpin{ to{ transform:rotate(360deg); } }

  .zw-form-error{
    margin:-4px 0 0; font-family:var(--font-body); font-size:12.5px; color:var(--red);
    text-align:center; display:none;
  }
  .zw-form-error.show{ display:block; }

  /* ============ PAGE LAYOUT ============ */
  .login-shell{ min-height:100vh; display:grid; grid-template-columns: minmax(0,560px) 1fr; }

  .login-form-col{
    display:flex; align-items:center; justify-content:center;
    padding:48px 40px; background: var(--off-white);
  }
  .login-card{ width:100%; max-width:380px; }
  .login-card-logo{ margin-bottom:40px; }
  .login-card-logo svg{ height:24px; width:auto; }
  .login-title{
    margin-top:14px; font-family: var(--font-display); font-weight:500; letter-spacing:-0.01em;
    font-size:34px; color: var(--ink);
  }
  .login-sub{ margin-top:10px; margin-bottom:32px; }

  .login-form{ display:flex; flex-direction:column; gap:18px; }

  .login-password-wrap{ position:relative; }
  .login-password-wrap .zw-input{ padding-right:44px; }
  .login-password-toggle{
    position:absolute; right:6px; top:50%; transform:translateY(-50%);
    width:34px; height:34px; display:flex; align-items:center; justify-content:center;
    background:none; border:none; border-radius:8px; color: var(--ink-faint);
    transition: color .15s, background .15s;
  }
  .login-password-toggle:hover{ color: var(--ink); background: rgba(10,14,20,0.05); }
  .login-password-toggle svg{ width:18px; height:18px; }
  .login-password-toggle .eye-off{ display:none; }
  .login-password-toggle.showing .eye{ display:none; }
  .login-password-toggle.showing .eye-off{ display:block; }

  .login-row{ display:flex; align-items:center; justify-content:space-between; margin-top:-4px; }
  .login-remember{ display:flex; align-items:center; gap:8px; font-size:13.5px; color: var(--ink-soft); cursor:pointer; }
  .login-remember input{ accent-color: var(--cobalt); width:15px; height:15px; }
  .login-forgot{ font-size:13.5px; font-weight:500; color: var(--ink-soft); transition: color .15s; }
  .login-forgot:hover{ color: var(--cobalt); }
  .login-forgot-note{
    display:none; margin-top:-6px; font-size:12.5px; color: var(--ink-faint); text-align:right;
  }
  .login-forgot-note.show{ display:block; }

  .login-signup-note{
    margin-top:26px; font-family: var(--font-body); font-size:13.5px; color: var(--ink-soft); text-align:center;
  }
  .login-signup-note a{ color: var(--ink); font-weight:600; text-decoration:underline; }

  /* success state (shown after a valid submit, in place of the form) */
  .login-success{ display:none; text-align:center; padding:20px 0; }
  .login-success.show{ display:block; }
  .login-success-icon{
    width:52px; height:52px; border-radius:50%; background: rgba(26,154,99,0.12);
    display:flex; align-items:center; justify-content:center; margin:0 auto 18px; color: var(--green);
  }
  .login-success-title{ font-family: var(--font-display); font-size:22px; color: var(--ink); }
  .login-success-copy{ margin-top:8px; font-size:14px; color: var(--ink-soft); }

  /* ---- visual column ---- */
  .login-visual-col{
    position:relative; overflow:hidden; background: var(--navy);
    display:flex; align-items:center; justify-content:center; padding:60px;
  }
  .login-visual-grid{
    position:absolute; inset:0; opacity:0.06; mix-blend-mode:screen; pointer-events:none;
    background-image:
      repeating-linear-gradient(90deg, rgba(247,246,243,0.6) 0 1px, transparent 1px 120px),
      repeating-linear-gradient(0deg, rgba(247,246,243,0.6) 0 1px, transparent 1px 120px);
  }
  .login-visual-glow{
    position:absolute; inset:-20%; pointer-events:none; filter: blur(60px);
    background:
      radial-gradient(38% 42% at 22% 18%, rgba(83,120,255,0.30), transparent 70%),
      radial-gradient(42% 46% at 82% 78%, rgba(60,96,255,0.26), transparent 70%),
      radial-gradient(30% 34% at 70% 15%, rgba(110,150,255,0.16), transparent 70%);
  }
  .login-visual-content{ position:relative; width:100%; max-width:400px; }
  .login-visual-content > .eyebrow{ margin-bottom:18px; }
  .login-visual-headline{
    font-family: var(--font-display); font-weight:500; font-size:26px; line-height:1.25;
    color: var(--off-white); margin-bottom:28px; max-width:360px;
  }

  /* reuse of the homepage's signature portfolio-card component, static
     (no hover tilt) so it reads as a calm, editorial illustration rather
     than an interactive control on an auth page. */
  .portfolio-card{
    background: var(--navy-surface); border-radius:20px; padding:26px; color: var(--off-white);
    box-shadow: 0 40px 90px -24px rgba(0,0,0,0.55), 0 0 1px rgba(255,255,255,0.06);
    border:1px solid var(--border-on-dark);
  }
  .pf-head{ display:flex; justify-content:space-between; align-items:flex-start; margin-bottom:20px; }
  .pf-label{ font-family:var(--font-mono); font-size:11px; letter-spacing:1.5px; color: rgba(247,246,243,0.45); margin-bottom:8px; }
  .pf-value{ font-family:var(--font-mono); font-size:32px; font-weight:600; }
  .pf-change{ font-family:var(--font-mono); font-size:13px; margin-top:6px; color: var(--green); }
  .pf-badge{ display:flex; align-items:center; justify-content:center; width:28px; height:28px; border-radius:8px; background: rgba(51,85,255,0.14); }
  .pf-badge .badge-mark{ width:12px; height:auto; display:block; }
  .pf-holdings{ display:flex; flex-direction:column; gap:0; }
  .pf-row{ display:flex; align-items:center; justify-content:space-between; padding:10px 0; border-top:1px solid var(--border-on-dark); }
  .pf-row:first-child{ border-top:none; }
  .pf-sym{ font-family:var(--font-mono); font-weight:600; font-size:13.5px; }
  .pf-name{ font-size:10.5px; color: rgba(247,246,243,0.4); margin-top:1px; }
  .pf-px{ font-family:var(--font-mono); font-size:13.5px; text-align:right; }
  .pf-chg{ font-family:var(--font-mono); font-size:11px; text-align:right; margin-top:2px; }
  .pf-chg.up{ color: var(--green); } .pf-chg.down{ color: var(--red); }

  .login-visual-stats{
    display:flex; gap:22px; margin-top:26px; font-family: var(--font-mono); font-size:11px;
    color: rgba(247,246,243,0.45); letter-spacing:0.4px;
  }
  .login-visual-stats b{ color: rgba(247,246,243,0.85); font-weight:600; }

  @media (max-width: 1200px){
    .login-shell{ grid-template-columns: minmax(0,500px) minmax(240px, 1fr); }
    .login-visual-col{ padding:40px; }
    .login-visual-content{ max-width:280px; }
    .login-visual-headline{ font-size:20px; margin-bottom:22px; }
    .login-visual-stats{ display:none; }
    .portfolio-card{ padding:20px; }
    .pf-value{ font-size:26px; }
  }
  @media (max-width: 760px){
    .login-shell{ grid-template-columns: 1fr; }
    .login-visual-col{ display:none; }
    .login-form-col{ padding:40px 24px; min-height:100vh; }
  }
  @media (max-width: 420px){
    .login-title{ font-size:28px; }
  }
</style>
</head>
<body>
"""

LOGO_SMALL = logo_svg  # same SVG, sized via CSS on the wrapper

BODY = f"""
<div class="login-shell">
  <div class="login-form-col">
    <div class="login-card">
      <a href="/" class="login-card-logo">{LOGO_SMALL}</a>

      <div class="eyebrow">WELCOME BACK</div>
      <h1 class="login-title">Log in</h1>
      <p class="lede login-sub">Access your Zoey Wallet account.</p>

      <div id="loginFormState">
        <form class="login-form" id="loginForm" novalidate>
          <div class="zw-field" id="loginEmailField">
            <label class="zw-label" for="loginEmail">Email address</label>
            <input class="zw-input" type="email" id="loginEmail" name="email" placeholder="you@example.com" autocomplete="email" required>
            <div class="zw-field-error">Enter a valid email address.</div>
          </div>

          <div class="zw-field" id="loginPasswordField">
            <label class="zw-label" for="loginPassword">Password</label>
            <div class="login-password-wrap">
              <input class="zw-input" type="password" id="loginPassword" name="password" placeholder="Your password" autocomplete="current-password" required>
              <button type="button" class="login-password-toggle" id="loginPasswordToggle" aria-label="Show password">
                <svg class="eye" viewBox="0 0 20 20" fill="none"><path d="M1.5 10S4.5 4 10 4s8.5 6 8.5 6-3 6-8.5 6-8.5-6-8.5-6Z" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round"/><circle cx="10" cy="10" r="2.4" stroke="currentColor" stroke-width="1.4"/></svg>
                <svg class="eye-off" viewBox="0 0 20 20" fill="none"><path d="M2.5 2.5l15 15M8.3 8.4a2.4 2.4 0 0 0 3.3 3.3M5.9 5.6C3.4 7 1.5 10 1.5 10s3 6 8.5 6c1.5 0 2.8-.4 3.9-1M16 14.3c1.6-1.4 2.5-3.3 2.5-4.3 0 0-3-6-8.5-6-.9 0-1.7.1-2.5.4" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/></svg>
              </button>
            </div>
            <div class="zw-field-error">Enter your password.</div>
          </div>

          <div class="login-row">
            <label class="login-remember"><input type="checkbox" id="loginRemember" checked><span>Remember me</span></label>
            <a href="#" class="login-forgot" id="loginForgotLink">Forgot password?</a>
          </div>
          <p class="login-forgot-note" id="loginForgotNote">Password reset isn't available yet &mdash; contact support to regain access.</p>

          <p class="zw-form-error" id="loginFormError"></p>

          <button type="submit" class="zw-submit-btn" id="loginSubmitBtn">
            <span class="zw-spinner"></span><span class="zw-submit-label">Log In</span>
          </button>
        </form>

        <p class="login-signup-note">Don't have an account? <a href="/#cta">Sign Up</a></p>
      </div>

      <div class="login-success" id="loginSuccessState">
        <div class="login-success-icon">
          <svg width="20" height="20" viewBox="0 0 22 22" fill="none"><path d="M4 11.5L9 16.5L18 6.5" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>
        </div>
        <div class="login-success-title">You're in.</div>
        <p class="login-success-copy">Taking you to your dashboard&hellip;</p>
      </div>
    </div>
  </div>

  <div class="login-visual-col" aria-hidden="true">
    <div class="login-visual-grid"></div>
    <div class="login-visual-glow"></div>
    <div class="login-visual-content">
      <div class="eyebrow on-dark">GLOBAL EQUITIES INFRASTRUCTURE</div>
      <div class="login-visual-headline">Stablecoin-native access to the world's markets, in one account.</div>

      <div class="portfolio-card">
        <div class="pf-head">
          <div>
            <div class="pf-label">PORTFOLIO VALUE</div>
            <div class="pf-value">$12,450.82</div>
            <div class="pf-change">+$184.20 &middot; +1.51% today</div>
          </div>
          <div class="pf-badge"><svg class="badge-mark" viewBox="165 84 1359 1671" xmlns="http://www.w3.org/2000/svg"><defs><linearGradient id="loginBadgeGrad" x1="0%" y1="0%" x2="100%" y2="0%"><stop offset="0%" stop-color="#8C9AFF"/><stop offset="55%" stop-color="#6E7EFF"/><stop offset="100%" stop-color="#4A55FF"/></linearGradient></defs><g fill="url(#loginBadgeGrad)"><path d="M 166,1024 L 172,1026 L 182,1020 L 195,1019 L 285,983 L 296,982 L 405,941 L 459,925 L 669,848 L 725,832 L 894,769 L 930,760 L 1103,698 L 1117,696 L 1204,662 L 1264,646 L 1316,626 L 1357,618 L 1502,562 L 1516,560 L 1524,550 L 1449,521 L 1394,505 L 1236,448 L 1223,447 L 1217,442 L 1182,433 L 1097,400 L 1053,388 L 1010,370 L 851,319 L 804,299 L 656,248 L 562,219 L 411,163 L 395,161 L 329,135 L 169,84 L 165,89 Z"/><path d="M 1520,1752 L 1520,811 L 1517,807 L 1412,847 L 1396,849 L 1354,867 L 1208,914 L 1183,926 L 1105,949 L 1096,955 L 914,1019 L 896,1022 L 788,1062 L 776,1063 L 605,1127 L 409,1192 L 301,1233 L 262,1243 L 197,1269 L 183,1271 L 172,1278 L 177,1285 L 244,1306 L 290,1326 L 303,1327 L 330,1339 L 344,1341 L 390,1361 L 403,1362 L 509,1403 L 709,1469 L 756,1489 L 1012,1576 L 1162,1632 L 1176,1634 L 1203,1646 L 1218,1648 L 1325,1688 L 1382,1705 L 1410,1718 L 1502,1748 L 1510,1754 Z"/></g></svg></div>
        </div>
        <div class="pf-holdings">
          <div class="pf-row"><div><div class="pf-sym">NVDA</div><div class="pf-name">NVIDIA Corp.</div></div><div><div class="pf-px">$201.30</div><div class="pf-chg up">+2.05%</div></div></div>
          <div class="pf-row"><div><div class="pf-sym">TSLA</div><div class="pf-name">Tesla Inc.</div></div><div><div class="pf-px">$256.90</div><div class="pf-chg up">+1.48%</div></div></div>
          <div class="pf-row"><div><div class="pf-sym">PLTR</div><div class="pf-name">Palantir Tech.</div></div><div><div class="pf-px">$168.44</div><div class="pf-chg down">&minus;0.62%</div></div></div>
        </div>
      </div>

      <div class="login-visual-stats">
        <div><b>4,000+</b> global equities</div>
        <div><b>$1</b> minimum</div>
        <div><b>USDT/USDC</b> funding rails</div>
      </div>
    </div>
  </div>
</div>

<script>
(function(){{
  const form = document.getElementById('loginForm');
  const emailInput = document.getElementById('loginEmail');
  const passwordInput = document.getElementById('loginPassword');
  const emailField = document.getElementById('loginEmailField');
  const passwordField = document.getElementById('loginPasswordField');
  const submitBtn = document.getElementById('loginSubmitBtn');
  const formError = document.getElementById('loginFormError');
  const formState = document.getElementById('loginFormState');
  const successState = document.getElementById('loginSuccessState');
  const rememberInput = document.getElementById('loginRemember');
  const toggleBtn = document.getElementById('loginPasswordToggle');
  const forgotLink = document.getElementById('loginForgotLink');
  const forgotNote = document.getElementById('loginForgotNote');

  function validEmail(v){{ return /^[^\\s@]+@[^\\s@]+\\.[^\\s@]{{2,}}$/.test(v.trim()); }}

  [emailInput, passwordInput].forEach(inp => {{
    inp.addEventListener('input', () => {{
      const field = inp.closest('.zw-field');
      if (field.classList.contains('has-error')) field.classList.remove('has-error');
      if (field.classList.contains('auth-error')) field.classList.remove('auth-error');
      formError.classList.remove('show');
    }});
  }});

  toggleBtn.addEventListener('click', () => {{
    const showing = toggleBtn.classList.toggle('showing');
    passwordInput.type = showing ? 'text' : 'password';
    toggleBtn.setAttribute('aria-label', showing ? 'Hide password' : 'Show password');
  }});

  forgotLink.addEventListener('click', (e) => {{
    e.preventDefault();
    forgotNote.classList.add('show');
  }});

  form.addEventListener('submit', function(e){{
    e.preventDefault();

    const emailOk = validEmail(emailInput.value);
    const passwordOk = passwordInput.value.length > 0;

    emailField.classList.toggle('has-error', !emailOk);
    passwordField.classList.toggle('has-error', !passwordOk);

    if (!emailOk) {{ emailInput.focus(); return; }}
    if (!passwordOk) {{ passwordInput.focus(); return; }}

    submitBtn.classList.add('loading');
    submitBtn.disabled = true;
    formError.classList.remove('show');

    fetch('/api/auth/login', {{
      method: 'POST',
      headers: {{ 'Content-Type': 'application/json' }},
      body: JSON.stringify({{
        email: emailInput.value.trim(),
        password: passwordInput.value,
        remember: rememberInput.checked,
      }}),
    }})
      .then(async (res) => {{
        const data = await res.json().catch(() => ({{}}));
        if (!res.ok || !data.ok) {{
          const message = res.status === 429
            ? 'Too many attempts. Please try again in a few minutes.'
            : (data.message || 'Something went wrong. Please try again.');
          throw new Error(message);
        }}
        return data;
      }})
      .then(() => {{
        submitBtn.classList.remove('loading');
        submitBtn.classList.add('success');
        submitBtn.querySelector('.zw-submit-label').textContent = 'Success';
        formState.style.display = 'none';
        successState.classList.add('show');
        setTimeout(() => {{ window.location.href = '/dashboard'; }}, 500);
      }})
      .catch((err) => {{
        submitBtn.classList.remove('loading');
        submitBtn.disabled = false;
        emailField.classList.add('auth-error');
        passwordField.classList.add('auth-error');
        formError.textContent = err.message;
        formError.classList.add('show');
      }});
  }});
}})();
</script>
</body>
</html>
"""

open('public/login.html', 'w', encoding='utf-8').write(HEAD + BODY)
print("wrote public/login.html, bytes:", len(HEAD + BODY))
