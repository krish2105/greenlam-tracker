/**
 * Compute the CSP hash for the inline theme bootstrap in dashboard/index.html,
 * and write it into render.yaml.
 *
 * Why this exists: the theme has to be applied before first paint, which needs
 * an inline script. Allowing that with `'unsafe-inline'` would open the door to
 * every injected script on the page — the exact thing CSP is for. A SHA-256
 * hash allowlists this one script and nothing else, so an attacker who manages
 * to inject a <script> tag still gets blocked.
 *
 * The trade-off is that the hash must be regenerated whenever the bootstrap
 * changes, even by one byte. That is the point: the CSP tracks the script
 * rather than blessing inline script in general.
 *
 *     npm run csp:hash        # update render.yaml
 *     npm run csp:hash -- --check   # fail if stale (used in CI)
 */

import { createHash } from 'node:crypto';
import { readFileSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const repoRoot = join(dirname(fileURLToPath(import.meta.url)), '..');
const htmlPath = join(repoRoot, 'dashboard/index.html');
const renderPath = join(repoRoot, 'render.yaml');

const html = readFileSync(htmlPath, 'utf8');

// Inline scripts only — anything with a src= is covered by 'self'.
const inlineScripts = [
  ...html.matchAll(/<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/gi),
].map((match) => match[1]);

if (inlineScripts.length === 0) {
  console.error('No inline script found in dashboard/index.html.');
  process.exit(1);
}
if (inlineScripts.length > 1) {
  console.error(
    `Found ${inlineScripts.length} inline scripts. Only the theme bootstrap ` +
      'should be inline — move the rest into src/ so they are covered by ' +
      "'self'.",
  );
  process.exit(1);
}

// The browser hashes the element's exact text content, byte for byte.
const hash = createHash('sha256').update(inlineScripts[0], 'utf8').digest('base64');
const directive = `'sha256-${hash}'`;

const renderYaml = readFileSync(renderPath, 'utf8');
const existing = renderYaml.match(/'sha256-[A-Za-z0-9+/=]+'|'sha256-PLACEHOLDER[^']*'/);

if (process.argv.includes('--check')) {
  if (existing?.[0] === directive) {
    console.log(`CSP hash is current: ${directive}`);
    process.exit(0);
  }
  console.error(
    `CSP hash is stale.\n  render.yaml has: ${existing?.[0] ?? '(none)'}\n` +
      `  index.html needs: ${directive}\n\nRun: npm run csp:hash`,
  );
  process.exit(1);
}

if (!existing) {
  console.error(
    "No sha256 placeholder found in render.yaml. Expected a script-src entry " +
      "containing 'sha256-...'.",
  );
  process.exit(1);
}

writeFileSync(renderPath, renderYaml.replace(existing[0], directive), 'utf8');
console.log(`Wrote ${directive} into render.yaml`);
