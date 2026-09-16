/*
 * Zoey Wallet — Contact page script (contact.html)
 *
 * Frontend-only. Everything here either (a) reuses patterns/data that
 * already exist in index.html (the country dataset + phone-country
 * selector widget, the /api/leads submission contract) so the Contact
 * page behaves identically to the rest of the site, or (b) is new
 * behavior scoped entirely to this page (the FAQ accordion, the
 * "how can we help" cards -- those have no JS, pure CSS).
 *
 * Nothing here touches the backend, the database, or any existing route.
 * The only network call this file makes is a POST to the *existing*
 * POST /api/leads endpoint (see backend/schemas.py's LeadIn + api/index.py) --
 * the same endpoint index.html's signup modal already posts to via its
 * submitLead()/handleGoogleCredential() path. No new endpoint, no schema
 * change.
 */

(function () {
  'use strict';

  // ============================================================
  // Shared country dataset -- copied verbatim from index.html's
  // ZW_COUNTRIES (same 212 entries, same [isoCode, name, callingCode]
  // shape) so the phone-country selector on this page dials exactly the
  // same numbers index.html's signup modal does, and so the separate
  // "Country" field below can look up a calling code from the same
  // single source of truth rather than maintaining a second dataset.
  // ============================================================
  const ZW_COUNTRIES = [["AF","Afghanistan","93"],["AL","Albania","355"],["DZ","Algeria","213"],["AS","American Samoa","1684"],["AD","Andorra","376"],["AO","Angola","244"],["AI","Anguilla","1264"],["AG","Antigua and Barbuda","1268"],["AR","Argentina","54"],["AM","Armenia","374"],["AW","Aruba","297"],["AU","Australia","61"],["AT","Austria","43"],["AZ","Azerbaijan","994"],["BS","Bahamas","1242"],["BH","Bahrain","973"],["BD","Bangladesh","880"],["BB","Barbados","1246"],["BY","Belarus","375"],["BE","Belgium","32"],["BZ","Belize","501"],["BJ","Benin","229"],["BM","Bermuda","1441"],["BT","Bhutan","975"],["BO","Bolivia","591"],["BA","Bosnia and Herzegovina","387"],["BW","Botswana","267"],["BR","Brazil","55"],["VG","British Virgin Islands","1284"],["BN","Brunei","673"],["BG","Bulgaria","359"],["BF","Burkina Faso","226"],["BI","Burundi","257"],["KH","Cambodia","855"],["CM","Cameroon","237"],["CA","Canada","1"],["CV","Cape Verde","238"],["KY","Cayman Islands","1345"],["CF","Central African Republic","236"],["TD","Chad","235"],["CL","Chile","56"],["CN","China","86"],["CO","Colombia","57"],["KM","Comoros","269"],["CG","Congo","242"],["CD","Congo (DRC)","243"],["CR","Costa Rica","506"],["CI","Cote d'Ivoire","225"],["HR","Croatia","385"],["CU","Cuba","53"],["CW","Curacao","599"],["CY","Cyprus","357"],["CZ","Czech Republic","420"],["DK","Denmark","45"],["DJ","Djibouti","253"],["DM","Dominica","1767"],["DO","Dominican Republic","1809"],["EC","Ecuador","593"],["EG","Egypt","20"],["SV","El Salvador","503"],["GQ","Equatorial Guinea","240"],["ER","Eritrea","291"],["EE","Estonia","372"],["SZ","Eswatini","268"],["ET","Ethiopia","251"],["FJ","Fiji","679"],["FI","Finland","358"],["FR","France","33"],["GA","Gabon","241"],["GM","Gambia","220"],["GE","Georgia","995"],["DE","Germany","49"],["GH","Ghana","233"],["GI","Gibraltar","350"],["GR","Greece","30"],["GL","Greenland","299"],["GD","Grenada","1473"],["GU","Guam","1671"],["GT","Guatemala","502"],["GN","Guinea","224"],["GW","Guinea-Bissau","245"],["GY","Guyana","592"],["HT","Haiti","509"],["HN","Honduras","504"],["HK","Hong Kong","852"],["HU","Hungary","36"],["IS","Iceland","354"],["IN","India","91"],["ID","Indonesia","62"],["IR","Iran","98"],["IQ","Iraq","964"],["IE","Ireland","353"],["IL","Israel","972"],["IT","Italy","39"],["JM","Jamaica","1876"],["JP","Japan","81"],["JO","Jordan","962"],["KZ","Kazakhstan","7"],["KE","Kenya","254"],["KI","Kiribati","686"],["KW","Kuwait","965"],["KG","Kyrgyzstan","996"],["LA","Laos","856"],["LV","Latvia","371"],["LB","Lebanon","961"],["LS","Lesotho","266"],["LR","Liberia","231"],["LY","Libya","218"],["LI","Liechtenstein","423"],["LT","Lithuania","370"],["LU","Luxembourg","352"],["MO","Macau","853"],["MG","Madagascar","261"],["MW","Malawi","265"],["MY","Malaysia","60"],["MV","Maldives","960"],["ML","Mali","223"],["MT","Malta","356"],["MH","Marshall Islands","692"],["MR","Mauritania","222"],["MU","Mauritius","230"],["MX","Mexico","52"],["FM","Micronesia","691"],["MD","Moldova","373"],["MC","Monaco","377"],["MN","Mongolia","976"],["ME","Montenegro","382"],["MS","Montserrat","1664"],["MA","Morocco","212"],["MZ","Mozambique","258"],["MM","Myanmar","95"],["NA","Namibia","264"],["NR","Nauru","674"],["NP","Nepal","977"],["NL","Netherlands","31"],["NZ","New Zealand","64"],["NI","Nicaragua","505"],["NE","Niger","227"],["NG","Nigeria","234"],["KP","North Korea","850"],["MK","North Macedonia","389"],["NO","Norway","47"],["OM","Oman","968"],["PK","Pakistan","92"],["PW","Palau","680"],["PS","Palestine","970"],["PA","Panama","507"],["PG","Papua New Guinea","675"],["PY","Paraguay","595"],["PE","Peru","51"],["PH","Philippines","63"],["PL","Poland","48"],["PT","Portugal","351"],["PR","Puerto Rico","1787"],["QA","Qatar","974"],["RO","Romania","40"],["RU","Russia","7"],["RW","Rwanda","250"],["KN","Saint Kitts and Nevis","1869"],["LC","Saint Lucia","1758"],["VC","Saint Vincent and the Grenadines","1784"],["WS","Samoa","685"],["SM","San Marino","378"],["ST","Sao Tome and Principe","239"],["SA","Saudi Arabia","966"],["SN","Senegal","221"],["RS","Serbia","381"],["SC","Seychelles","248"],["SL","Sierra Leone","232"],["SG","Singapore","65"],["SK","Slovakia","421"],["SI","Slovenia","386"],["SB","Solomon Islands","677"],["SO","Somalia","252"],["ZA","South Africa","27"],["KR","South Korea","82"],["SS","South Sudan","211"],["ES","Spain","34"],["LK","Sri Lanka","94"],["SD","Sudan","249"],["SR","Suriname","597"],["SE","Sweden","46"],["CH","Switzerland","41"],["SY","Syria","963"],["TW","Taiwan","886"],["TJ","Tajikistan","992"],["TZ","Tanzania","255"],["TH","Thailand","66"],["TL","Timor-Leste","670"],["TG","Togo","228"],["TO","Tonga","676"],["TT","Trinidad and Tobago","1868"],["TN","Tunisia","216"],["TR","Turkey","90"],["TM","Turkmenistan","993"],["TC","Turks and Caicos Islands","1649"],["TV","Tuvalu","688"],["VI","U.S. Virgin Islands","1340"],["UG","Uganda","256"],["UA","Ukraine","380"],["AE","United Arab Emirates","971"],["GB","United Kingdom","44"],["US","United States","1"],["UY","Uruguay","598"],["UZ","Uzbekistan","998"],["VU","Vanuatu","678"],["VA","Vatican City","379"],["VE","Venezuela","58"],["VN","Vietnam","84"],["YE","Yemen","967"],["ZM","Zambia","260"],["ZW","Zimbabwe","263"]];

  // Same flag-image + fallback pattern as index.html's zwFlagHTML()/error
  // handler -- real per-country SVG art from flagcdn.com, keyed by the ISO
  // code already in ZW_COUNTRIES, with the image hidden (not a broken-image
  // glyph) if it fails to load.
  function zcFlagHTML(code, cls) {
    return '<img class="zc-flag-img ' + cls + '" src="https://flagcdn.com/' + code.toLowerCase() + '.svg" ' +
      'width="' + (cls === 'zc-country-option-flag' ? 20 : 18) + '" height="' + (cls === 'zc-country-option-flag' ? 15 : 13) + '" ' +
      'alt="" aria-hidden="true" loading="lazy">';
  }
  document.addEventListener('error', (e) => {
    const t = e.target;
    if (t && t.classList && t.classList.contains('zc-flag-img')) t.style.display = 'none';
  }, true);

  // ============================================================
  // Mobile menu (same pattern as index.html / legal.html)
  // ============================================================
  const navToggle = document.getElementById('navToggle');
  const mobileMenu = document.getElementById('mobileMenu');
  if (navToggle && mobileMenu) {
    navToggle.addEventListener('click', () => {
      const open = mobileMenu.classList.toggle('open');
      navToggle.setAttribute('aria-expanded', String(open));
      document.getElementById('toggleIcon').setAttribute('d', open ? 'M3 3 L15 15 M15 3 L3 15' : 'M2 5 H16 M2 9 H16 M2 13 H16');
    });
    mobileMenu.querySelectorAll('a').forEach(a => a.addEventListener('click', () => {
      mobileMenu.classList.remove('open');
      navToggle.setAttribute('aria-expanded', 'false');
      document.getElementById('toggleIcon').setAttribute('d', 'M2 5 H16 M2 9 H16 M2 13 H16');
    }));
  }

  // ---- Header height sync (drives scroll-margin-top on #faq etc.) ----
  function syncHeaderHeight() {
    const header = document.querySelector('header');
    if (header) document.documentElement.style.setProperty('--header-h', header.getBoundingClientRect().height + 'px');
  }
  syncHeaderHeight();
  window.addEventListener('resize', syncHeaderHeight);
  window.addEventListener('load', syncHeaderHeight);
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(syncHeaderHeight);

  // ---- Scroll reveal (same IntersectionObserver pattern as the rest of
  // the site) ----
  const io = new IntersectionObserver((entries) => {
    entries.forEach(e => { if (e.isIntersecting) { e.target.classList.add('in'); io.unobserve(e.target); } });
  }, { threshold: 0.12 });
  document.querySelectorAll('.reveal').forEach(el => io.observe(el));

  // ============================================================
  // Country <select> (the separate "Country" field, distinct from the
  // phone number's dial-code selector below) -- populated from the same
  // ZW_COUNTRIES dataset rather than a second, hand-maintained list.
  // ============================================================
  const countrySelect = document.getElementById('zcCountrySelect');
  if (countrySelect) {
    const frag = document.createDocumentFragment();
    const placeholder = document.createElement('option');
    placeholder.value = '';
    placeholder.textContent = 'Select your country';
    placeholder.disabled = true;
    placeholder.selected = true;
    frag.appendChild(placeholder);
    ZW_COUNTRIES.forEach(c => {
      const opt = document.createElement('option');
      opt.value = c[0];
      opt.textContent = c[1];
      frag.appendChild(opt);
    });
    countrySelect.appendChild(frag);
  }
  function countryNameAndDialFor(isoCode) {
    const match = ZW_COUNTRIES.find(c => c[0] === isoCode);
    return match ? { name: match[1], dial: match[2] } : { name: null, dial: null };
  }

  // ============================================================
  // Phone number country selector -- same widget/markup pattern as
  // index.html's signup modal (.zw-country-btn / .zw-country-dropdown /
  // .zw-country-panel / .zw-country-search / .zw-country-list), just
  // scoped to this page's own element ids (zc* instead of zw*) since this
  // is a standalone page rather than the homepage's modal.
  // ============================================================
  const countryBtn = document.getElementById('zcCountryBtn');
  const countryDropdown = document.getElementById('zcCountryDropdown');
  const countrySearch = document.getElementById('zcCountrySearch');
  const countryList = document.getElementById('zcCountryList');
  const countryFlagEl = document.getElementById('zcCountryFlag');
  const countryCodeEl = document.getElementById('zcCountryCode');
  const countryDialEl = document.getElementById('zcCountryDial');
  const phoneInput = document.getElementById('zcPhone');

  let selectedPhoneCountry = ZW_COUNTRIES.find(c => c[0] === 'NG') || ZW_COUNTRIES[0];

  function renderCountryList(filter) {
    const q = (filter || '').trim().toLowerCase();
    const items = ZW_COUNTRIES.filter(c => {
      if (!q) return true;
      return c[1].toLowerCase().includes(q) || c[2].includes(q.replace('+', ''));
    });
    countryList.innerHTML = '';
    if (!items.length) {
      const empty = document.createElement('div');
      empty.className = 'zc-country-empty';
      empty.textContent = 'No countries match your search.';
      countryList.appendChild(empty);
      return;
    }
    items.forEach(c => {
      const opt = document.createElement('div');
      opt.className = 'zc-country-option';
      opt.setAttribute('role', 'option');
      opt.innerHTML = zcFlagHTML(c[0], 'zc-country-option-flag') +
        '<span class="zc-country-option-code">' + c[0] + '</span>' +
        '<span class="zc-country-option-name">' + c[1] + '</span>' +
        '<span class="zc-country-option-dial">+' + c[2] + '</span>';
      opt.addEventListener('click', () => selectPhoneCountry(c));
      countryList.appendChild(opt);
    });
  }

  function selectPhoneCountry(c) {
    selectedPhoneCountry = c;
    if (countryFlagEl) countryFlagEl.src = 'https://flagcdn.com/' + c[0].toLowerCase() + '.svg';
    if (countryCodeEl) countryCodeEl.textContent = c[0];
    if (countryDialEl) countryDialEl.textContent = '+' + c[2];
    closeCountryDropdown();
    if (phoneInput) phoneInput.focus();
  }

  function openCountryDropdown() {
    if (!countryDropdown) return;
    countryDropdown.classList.add('open');
    countryBtn.setAttribute('aria-expanded', 'true');
    renderCountryList('');
    if (countrySearch) { countrySearch.value = ''; setTimeout(() => countrySearch.focus(), 50); }
  }
  function closeCountryDropdown() {
    if (!countryDropdown) return;
    countryDropdown.classList.remove('open');
    countryBtn.setAttribute('aria-expanded', 'false');
  }

  if (countryBtn) {
    countryBtn.addEventListener('click', () => {
      countryDropdown.classList.contains('open') ? closeCountryDropdown() : openCountryDropdown();
    });
    countrySearch.addEventListener('input', () => renderCountryList(countrySearch.value));
    document.addEventListener('click', (e) => {
      if (!countryDropdown.contains(e.target) && e.target !== countryBtn && !countryBtn.contains(e.target)) {
        closeCountryDropdown();
      }
    });
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && countryDropdown.classList.contains('open')) closeCountryDropdown();
    });
  }

  // ============================================================
  // Form validation + submission -> POST /api/leads
  //
  // This is the SAME endpoint (and the same request contract -- name,
  // email, phone_e164, interest, country, country_code, source,
  // submitted_at) that index.html's existing lead-capture flow already
  // posts to (see index.html's submitLead()/handleGoogleCredential()).
  // Nothing new is added to the backend, and nothing here can affect the
  // homepage's own lead/signup forms since this file only runs on
  // contact.html.
  //
  // The backend's Lead model (backend/models.py) has no field for a
  // free-text message -- only name/email/phone/interest/country/
  // country_code/source. Rather than inventing a schema change for this
  // frontend-only task, the "Tell us how we can help" textarea below is
  // collected for a good on-page experience but is NOT sent to /api/leads
  // (LeadIn's `extra="ignore"` would silently drop it anyway); the visible
  // fields that map to the existing Lead columns are what gets stored.
  // ============================================================
  const ZOEY_LEADS_API_BASE = ''; // same relative-path convention as index.html

  async function submitContactLead(payload) {
    let res, data;
    try {
      res = await fetch(`${ZOEY_LEADS_API_BASE}/api/leads`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      data = await res.json();
    } catch (err) {
      throw { fieldErrors: null, message: "We couldn't reach our servers. Please try again shortly." };
    }
    if (!res.ok || !data.ok) {
      if (res.status === 422 && data.errors) {
        throw { fieldErrors: data.errors, message: null };
      }
      if (res.status === 429) {
        throw { fieldErrors: null, message: 'Too many attempts. Please try again in a few minutes.' };
      }
      throw { fieldErrors: null, message: "We couldn't send your message right now. Please try again." };
    }
    return data;
  }

  function validName(v) { return v.trim().length >= 1 && /^[a-zA-ZÀ-ſ' -]+$/.test(v.trim()); }
  function validEmail(v) { return /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(v.trim()); }
  function validPhone(v) {
    const digits = v.replace(/\D/g, '');
    return digits.length >= 6 && digits.length <= 14;
  }
  function setFieldError(fieldEl, show) {
    if (fieldEl) fieldEl.classList.toggle('has-error', !!show);
  }

  const form = document.getElementById('zcForm');
  if (form) {
    const firstNameField = document.getElementById('zcFirstNameField');
    const lastNameField = document.getElementById('zcLastNameField');
    const emailField = document.getElementById('zcEmailField');
    const phoneField = document.getElementById('zcPhoneField');
    const countryField = document.getElementById('zcCountryField');

    const firstNameInput = document.getElementById('zcFirstName');
    const lastNameInput = document.getElementById('zcLastName');
    const emailInput = document.getElementById('zcEmail');
    const interestSelect = document.getElementById('zcInterest');
    const sourceSelect = document.getElementById('zcSource');
    const messageInput = document.getElementById('zcMessage');
    const submitBtn = document.getElementById('zcSubmitBtn');
    const formError = document.getElementById('zcFormError');
    const formState = document.getElementById('contactFormState');
    const successState = document.getElementById('zcSuccessState');

    [firstNameInput, lastNameInput, emailInput, phoneInput, countrySelect].forEach(inp => {
      if (!inp) return;
      inp.addEventListener('input', () => {
        const field = inp.closest('.zw-field');
        if (field && field.classList.contains('has-error')) field.classList.remove('has-error');
      });
      inp.addEventListener('change', () => {
        const field = inp.closest('.zw-field');
        if (field && field.classList.contains('has-error')) field.classList.remove('has-error');
      });
    });

    form.addEventListener('submit', function (e) {
      e.preventDefault();

      const firstNameOk = validName(firstNameInput.value);
      const lastNameOk = validName(lastNameInput.value);
      const emailOk = validEmail(emailInput.value);
      const phoneOk = validPhone(phoneInput.value);
      const countryOk = !!countrySelect.value;

      setFieldError(firstNameField, !firstNameOk);
      setFieldError(lastNameField, !lastNameOk);
      setFieldError(emailField, !emailOk);
      setFieldError(phoneField, !phoneOk);
      setFieldError(countryField, !countryOk);

      if (!firstNameOk) { firstNameInput.focus(); return; }
      if (!lastNameOk) { lastNameInput.focus(); return; }
      if (!emailOk) { emailInput.focus(); return; }
      if (!phoneOk) { phoneInput.focus(); return; }
      if (!countryOk) { countrySelect.focus(); return; }

      const digits = phoneInput.value.replace(/\D/g, '').replace(/^0+/, '');
      const chosenCountry = countryNameAndDialFor(countrySelect.value);

      const payload = {
        name: (firstNameInput.value.trim() + ' ' + lastNameInput.value.trim()).trim(),
        email: emailInput.value.trim().toLowerCase(),
        phone_e164: '+' + selectedPhoneCountry[2] + digits,
        interest: interestSelect.value || null,
        country: chosenCountry.name,
        country_code: chosenCountry.dial,
        source: 'contact_page' + (sourceSelect.value ? ':' + sourceSelect.value.toLowerCase().replace(/[^a-z0-9]+/g, '_') : ''),
        submitted_at: new Date().toISOString(),
      };

      submitBtn.classList.add('loading');
      submitBtn.disabled = true;
      formError.style.display = 'none';

      submitContactLead(payload).then(() => {
        submitBtn.classList.remove('loading');
        submitBtn.disabled = false;
        formState.style.display = 'none';
        successState.classList.add('show');
        successState.setAttribute('tabindex', '-1');
        successState.focus();
      }).catch((err) => {
        submitBtn.classList.remove('loading');
        submitBtn.disabled = false;
        if (err && err.fieldErrors) {
          if (err.fieldErrors.name) setFieldError(firstNameField, true);
          if (err.fieldErrors.email) setFieldError(emailField, true);
          if (err.fieldErrors.phone) setFieldError(phoneField, true);
          const firstMessage = err.message || Object.values(err.fieldErrors)[0];
          formError.textContent = firstMessage || "We couldn't send your message right now. Please try again.";
          formError.style.display = 'block';
        } else {
          formError.textContent = (err && err.message) || "We couldn't send your message right now. Please try again.";
          formError.style.display = 'block';
        }
      });
    });
  }

  // ============================================================
  // FAQ accordion -- accessible disclosure pattern: a <button
  // aria-expanded> per question, a role="region" panel per answer, only
  // the clicked row toggles (independent, not single-open-at-a-time,
  // since the spec doesn't ask for exclusivity and forcing others closed
  // is more surprising than helpful when someone's comparing answers).
  // ============================================================
  document.querySelectorAll('.zc-faq-row').forEach(row => {
    const trigger = row.querySelector('.zc-faq-trigger');
    const panel = row.querySelector('.zc-faq-panel');
    if (!trigger || !panel) return;
    trigger.addEventListener('click', () => {
      const isOpen = trigger.getAttribute('aria-expanded') === 'true';
      trigger.setAttribute('aria-expanded', String(!isOpen));
      panel.classList.toggle('open', !isOpen);
      row.classList.toggle('open', !isOpen);
    });
  });
})();
