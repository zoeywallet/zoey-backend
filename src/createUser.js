// Creates (or updates the password of) a Zoey Wallet dashboard login
// account. There's no self-serve sign-up flow yet (out of scope for the
// login/dashboard build — the homepage's existing "Sign Up" button is left
// pointing at the lead-capture flow, per the brief), so this is how you
// provision accounts for now: a CLI script, run server-side, never a public
// endpoint.
//
// Usage:
//   node src/createUser.js <email> <password> ["Full Name"]
//   npm run create-user -- <email> <password> ["Full Name"]
//
// Re-running with an existing email updates that account's password
// instead of erroring, so this also doubles as a manual "reset password."

const { loadEnv } = require('./loadEnv');
loadEnv();

const db = require('./db');
const { hashPassword } = require('./auth/password');
const { validEmail } = require('./validate');

function main() {
  const [, , emailArg, passwordArg, nameArg] = process.argv;

  if (!emailArg || !passwordArg) {
    console.error('Usage: node src/createUser.js <email> <password> ["Full Name"]');
    process.exit(1);
  }

  const email = emailArg.trim();
  if (!validEmail(email)) {
    console.error(`"${email}" doesn't look like a valid email address.`);
    process.exit(1);
  }

  if (passwordArg.length < 8) {
    console.error('Password must be at least 8 characters.');
    process.exit(1);
  }

  const name = (nameArg && nameArg.trim()) || email.split('@')[0];
  const passwordHash = hashPassword(passwordArg);

  const existing = db.findUserByEmail(email);
  if (existing) {
    db.updateUserPassword(existing.id, passwordHash);
    console.log(`Updated password for existing account: ${email} (id ${existing.id})`);
  } else {
    const user = db.createUser({ email, name, passwordHash });
    console.log(`Created account: ${user.email} (id ${user.id}, name "${user.name}")`);
  }
}

main();
