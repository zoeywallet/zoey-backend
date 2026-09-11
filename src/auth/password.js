// Password hashing using Node's built-in crypto.scrypt — no external
// dependency (bcrypt/argon2 would need a native module or npm install,
// neither of which this project depends on elsewhere). scrypt is a
// well-regarded, memory-hard KDF and is what Node itself recommends for
// this exact purpose.
//
// Stored format: "scrypt:<N>:<r>:<p>:<saltHex>:<hashHex>" — the cost
// parameters travel with the hash so they can be tuned in the future
// without breaking existing accounts' ability to log in.

const crypto = require('node:crypto');

const SCRYPT_N = 16384; // CPU/memory cost — Node's own recommended default
const SCRYPT_R = 8;
const SCRYPT_P = 1;
const KEY_LENGTH = 64;
const SALT_BYTES = 16;

function scrypt(password, salt, N, r, p) {
  return crypto.scryptSync(password, salt, KEY_LENGTH, { N, r, p, maxmem: 128 * N * r * 2 });
}

function hashPassword(password) {
  const salt = crypto.randomBytes(SALT_BYTES);
  const hash = scrypt(password, salt, SCRYPT_N, SCRYPT_R, SCRYPT_P);
  return `scrypt:${SCRYPT_N}:${SCRYPT_R}:${SCRYPT_P}:${salt.toString('hex')}:${hash.toString('hex')}`;
}

function verifyPassword(password, stored) {
  if (typeof stored !== 'string') return false;
  const parts = stored.split(':');
  if (parts.length !== 6 || parts[0] !== 'scrypt') return false;

  const [, nStr, rStr, pStr, saltHex, hashHex] = parts;
  const N = Number(nStr);
  const r = Number(rStr);
  const p = Number(pStr);
  const salt = Buffer.from(saltHex, 'hex');
  const expected = Buffer.from(hashHex, 'hex');

  let actual;
  try {
    actual = scrypt(password, salt, N, r, p);
  } catch {
    return false;
  }

  if (actual.length !== expected.length) return false;
  return crypto.timingSafeEqual(actual, expected);
}

module.exports = { hashPassword, verifyPassword };
