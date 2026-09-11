// Server-side validation for lead submissions. Deliberately mirrors the
// frontend's own validation (see the zw-form JS in the site's <script>
// block: validName/validEmail/validPhone) so a legitimate submission is
// never rejected here after passing there — but this is the copy that
// actually matters, since the browser's checks can always be bypassed.

const KNOWN_INTERESTS = new Set([
  'us_stocks',
  'global_equities',
  'stablecoin_access',
  'exploring',
]);

const KNOWN_SOURCES = new Set([
  'website_get_started_modal',
  'website_google_signup',
]);

function isNonEmptyString(v) {
  return typeof v === 'string' && v.trim().length > 0;
}

function validName(v) {
  if (typeof v !== 'string') return false;
  const trimmed = v.trim();
  return trimmed.length >= 2 && trimmed.length <= 120 && /^[a-zA-ZÀ-ſ' -]+$/.test(trimmed);
}

// Intentionally simple (matches the frontend's own check) rather than a
// exhaustive RFC 5322 regex — those tend to reject valid addresses more
// often than they catch invalid ones. Length caps guard against abuse.
function validEmail(v) {
  if (typeof v !== 'string') return false;
  const trimmed = v.trim();
  return trimmed.length <= 254 && /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(trimmed);
}

// Expects E.164-ish: a leading + followed by 7-15 digits (matches the
// frontend's 6-14 national-number-digit check once the 1-3 digit country
// dial code is prepended).
function validPhone(v) {
  if (typeof v !== 'string') return false;
  return /^\+[1-9]\d{6,14}$/.test(v.trim());
}

/**
 * Validates and sanitizes a raw lead submission body.
 * Returns { ok: true, sanitized } or { ok: false, errors, message }.
 * `errors` uses the same shape the frontend already expects on a 422:
 * { name?: true, email?: true, phone?: true }.
 */
function validateLeadPayload(body) {
  if (!body || typeof body !== 'object') {
    return { ok: false, errors: null, message: 'Malformed request body.' };
  }

  const errors = {};

  if (!validName(body.name)) errors.name = true;
  if (!validEmail(body.email)) errors.email = true;

  const source = isNonEmptyString(body.source) && KNOWN_SOURCES.has(body.source.trim())
    ? body.source.trim()
    : 'website_get_started_modal';

  // Phone is required for the standard email sign-up flow, but the Google
  // sign-up flow never collects one — don't punish that legitimate case.
  const phoneProvided = body.phone_e164 !== null && body.phone_e164 !== undefined && body.phone_e164 !== '';
  if (phoneProvided) {
    if (!validPhone(body.phone_e164)) errors.phone = true;
  } else if (source !== 'website_google_signup') {
    errors.phone = true;
  }

  if (Object.keys(errors).length > 0) {
    return { ok: false, errors, message: null };
  }

  const interest = isNonEmptyString(body.interest) && KNOWN_INTERESTS.has(body.interest.trim())
    ? body.interest.trim()
    : null;

  let submittedAt = null;
  if (isNonEmptyString(body.submitted_at)) {
    const d = new Date(body.submitted_at);
    if (!Number.isNaN(d.getTime())) submittedAt = d.toISOString();
  }

  const sanitized = {
    name: body.name.trim().slice(0, 120),
    email: body.email.trim().toLowerCase().slice(0, 254),
    phone_e164: phoneProvided ? body.phone_e164.trim().slice(0, 20) : null,
    country: isNonEmptyString(body.country) ? body.country.trim().slice(0, 100) : null,
    country_code: isNonEmptyString(body.country_code) ? body.country_code.trim().slice(0, 5).toUpperCase() : null,
    interest,
    source,
    submitted_at: submittedAt,
  };

  return { ok: true, sanitized };
}

module.exports = { validateLeadPayload, validName, validEmail, validPhone };
