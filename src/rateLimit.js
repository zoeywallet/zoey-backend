// Minimal in-memory sliding-window rate limiter, keyed by a hashed IP.
// No external dependency, no shared store — fine for a single-process
// deployment. If you ever run multiple instances behind a load balancer,
// move this state to the database or a shared cache instead.

const buckets = new Map(); // key -> array of timestamps (ms)

function checkRateLimit(key, { max, windowMs }) {
  const now = Date.now();
  const timestamps = (buckets.get(key) || []).filter((t) => now - t < windowMs);

  if (timestamps.length >= max) {
    buckets.set(key, timestamps);
    const retryAfterMs = windowMs - (now - timestamps[0]);
    return { allowed: false, retryAfterSeconds: Math.ceil(retryAfterMs / 1000) };
  }

  timestamps.push(now);
  buckets.set(key, timestamps);
  return { allowed: true };
}

// Periodically sweep stale entries so this map doesn't grow forever.
setInterval(() => {
  const now = Date.now();
  const maxWindowMs = 60 * 60 * 1000; // nothing here should ever need more than 1h
  for (const [key, timestamps] of buckets) {
    const fresh = timestamps.filter((t) => now - t < maxWindowMs);
    if (fresh.length === 0) buckets.delete(key);
    else buckets.set(key, fresh);
  }
}, 10 * 60 * 1000).unref();

module.exports = { checkRateLimit };
