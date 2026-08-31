/**
 * Locale parity check.
 *
 * Three failures that a translation ships with silently, and that a human
 * reviewer will not catch by reading two JSON files side by side:
 *
 *   1. A MISSING KEY falls back to English. On a Hindi floor tablet that is one
 *      English sentence in the middle of a Hindi screen — it looks like a bug
 *      to the operator and it never gets reported, because nobody thinks the
 *      language of a button is their problem to raise.
 *
 *   2. A DROPPED PLACEHOLDER is worse than a missing key. `{{count}}` left out
 *      of a translated string does not error; it just renders a sentence with
 *      the number removed. "machines are running with no write-up" — how many?
 *      The string still reads as fluent Hindi, so it survives review.
 *
 *   3. A MISSING PLURAL FORM. i18next resolves `key_one` / `key_other`, and a
 *      locale that defines only the base key gets the singular for 7 items.
 *
 * Run in CI. A translation regression should fail the build, not the plant.
 */

import { readFileSync, readdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const localeDir = join(here, '..', 'dashboard', 'src', 'i18n', 'locales');
const REFERENCE = 'en';

function flatten(object, prefix = '') {
  const out = new Map();
  for (const [key, value] of Object.entries(object)) {
    const path = prefix ? `${prefix}.${key}` : key;
    if (value && typeof value === 'object' && !Array.isArray(value)) {
      for (const [k, v] of flatten(value, path)) out.set(k, v);
    } else {
      out.set(path, String(value));
    }
  }
  return out;
}

/** Every `{{token}}` in a string, as a sorted, comparable signature. */
function placeholders(text) {
  return [...text.matchAll(/\{\{\s*([\w.-]+)\s*\}\}/g)]
    .map((m) => m[1])
    .sort()
    .join(',');
}

const load = (locale) =>
  flatten(JSON.parse(readFileSync(join(localeDir, `${locale}.json`), 'utf8')));

const locales = readdirSync(localeDir)
  .filter((f) => f.endsWith('.json'))
  .map((f) => f.replace(/\.json$/, ''))
  .filter((l) => l !== REFERENCE);

const reference = load(REFERENCE);
let failures = 0;

for (const locale of locales) {
  const translated = load(locale);
  const problems = [];

  for (const [key, englishValue] of reference) {
    if (!translated.has(key)) {
      problems.push(`  missing key        ${key}`);
      continue;
    }
    const want = placeholders(englishValue);
    const got = placeholders(translated.get(key));
    if (want !== got) {
      problems.push(
        `  placeholder drift  ${key}\n      en: {${want || '—'}}\n      ${locale}: {${got || '—'}}`,
      );
    }
  }

  for (const key of translated.keys()) {
    // An extra key is dead weight, not a failure — but it is usually a typo in
    // a key name, which means the real key is also missing above.
    if (!reference.has(key)) problems.push(`  extra key          ${key}`);
  }

  if (problems.length === 0) {
    console.log(`${locale}: ${translated.size} keys, parity with ${REFERENCE}`);
  } else {
    failures += problems.length;
    console.error(`${locale}: ${problems.length} problem(s)`);
    console.error(problems.join('\n'));
  }
}

if (failures > 0) {
  console.error(`\n${failures} locale problem(s). Fix before shipping.`);
  process.exit(1);
}
console.log(`\nAll ${locales.length + 1} locales agree.`);
