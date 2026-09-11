// Minimal .env loader (no external dependency). Parses KEY=VALUE lines from
// a .env file in the project root and applies them to process.env, without
// overwriting variables that are already set in the real environment (so
// real hosting-platform env vars always win over the local .env file).

const fs = require('node:fs');
const path = require('node:path');

function loadEnv(envPath = path.join(__dirname, '..', '.env')) {
  let raw;
  try {
    raw = fs.readFileSync(envPath, 'utf8');
  } catch (err) {
    return; // no .env file present — fine, rely on real env vars only
  }

  for (const rawLine of raw.split('\n')) {
    const line = rawLine.trim();
    if (!line || line.startsWith('#')) continue;

    const eq = line.indexOf('=');
    if (eq === -1) continue;

    const key = line.slice(0, eq).trim();
    let value = line.slice(eq + 1).trim();

    // Strip matching surrounding quotes, if present.
    if (
      (value.startsWith('"') && value.endsWith('"')) ||
      (value.startsWith("'") && value.endsWith("'"))
    ) {
      value = value.slice(1, -1);
    }

    if (!(key in process.env)) {
      process.env[key] = value;
    }
  }
}

module.exports = { loadEnv };
