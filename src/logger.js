// Minimal structured logger. Writes JSON lines to logs/app.log (rotated
// daily by filename) and mirrors human-readable output to the console.
// No external dependency — this is intentionally simple; swap in a real
// logging service (e.g. by piping stdout) in production if you want more.

const fs = require('node:fs');
const path = require('node:path');

const LOG_DIR = process.env.LOG_DIR || path.join(__dirname, '..', 'logs');

try {
  fs.mkdirSync(LOG_DIR, { recursive: true });
} catch (err) {
  // If we can't create the log directory, fall back to console-only logging
  // rather than crashing the server over a non-essential concern.
  console.error('[logger] could not create log directory, logging to console only:', err.message);
}

function logFilePath(date = new Date()) {
  const day = date.toISOString().slice(0, 10); // YYYY-MM-DD
  return path.join(LOG_DIR, `app-${day}.log`);
}

function write(level, message, meta) {
  const entry = {
    ts: new Date().toISOString(),
    level,
    message,
    ...(meta ? { meta } : {}),
  };
  const line = JSON.stringify(entry);

  const consoleFn = level === 'error' ? console.error : level === 'warn' ? console.warn : console.log;
  consoleFn(`[${entry.ts}] [${level.toUpperCase()}] ${message}`, meta ? meta : '');

  try {
    fs.appendFileSync(logFilePath(), line + '\n');
  } catch (err) {
    console.error('[logger] failed to write log file:', err.message);
  }
}

module.exports = {
  info: (message, meta) => write('info', message, meta),
  warn: (message, meta) => write('warn', message, meta),
  error: (message, meta) => write('error', message, meta),
};
