/**
 * i18next. Three locales, all real.
 *
 * The scaffolding was built in Phase 1 rather than Phase 7 deliberately —
 * retrofitting internationalisation across a finished app means touching every
 * hardcoded string in every component and discovering all the layout breakage
 * at once (addendum §2.2). That bet has now paid: adding Hindi was two JSON
 * files and a switcher, with no component changes at all.
 *
 * WHY THREE, AND WHY hi-Latn IS NOT A NOVELTY
 * `hi` is Devanagari. `hi-Latn` is the same Hindi written in Latin script with
 * the technical vocabulary left in English — "Hydraulic pressure gir raha hai".
 * That is not a compromise, it is how an Indian plant floor actually talks and
 * types, and a large share of operators read Latin script faster than
 * Devanagari even when Hindi is their first language, because that is the
 * script their phone keyboard trained them on. Offering only en and hi would
 * force those people into English — the outcome i18n exists to prevent.
 *
 * WHY ALL THREE ARE BUNDLED EAGERLY
 * Measured, not guessed: hi.json is 7.9 KB gzipped and hi-Latn.json 6.6 KB, so
 * carrying both costs 14.5 KB on a 158 KB entry bundle — about 9%.
 *
 * Lazy-loading them would save that and buy an outage. An operator who switches
 * to Hindi while offline would fire a request that cannot be served and fall
 * back to English, silently, on the screen they just told us they cannot read.
 * In an offline-first app the interface language must not depend on the network
 * any more than the machine list does, and 14.5 KB is the right price for
 * deleting that failure mode rather than documenting it.
 *
 * Revisit if a fourth and fifth locale land — at five languages the sum stops
 * being a rounding error and per-locale chunks, warmed by the service worker at
 * install time, become the better trade.
 */

import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';

import { DEFAULT_LOCALE, LOCALES, isLocale } from '@greenlam/core';

import en from './locales/en.json';
import hi from './locales/hi.json';
import hiLatn from './locales/hi-Latn.json';

export const LANGUAGE_STORAGE_KEY = 'gmt.language';

/** Same allowlist discipline as the theme: storage is untrusted input. */
export function readStoredLocale(): string {
  try {
    const stored = localStorage.getItem(LANGUAGE_STORAGE_KEY);
    return isLocale(stored) ? stored : DEFAULT_LOCALE;
  } catch {
    return DEFAULT_LOCALE;
  }
}

export function persistLocale(locale: string): void {
  if (!isLocale(locale)) return;
  try {
    localStorage.setItem(LANGUAGE_STORAGE_KEY, locale);
  } catch {
    /* storage unavailable — the in-memory choice still applies */
  }
}

void i18n.use(initReactI18next).init({
  resources: {
    en: { translation: en },
    hi: { translation: hi },
    'hi-Latn': { translation: hiLatn },
  },
  // Exact match only. Without this, i18next would strip 'hi-Latn' down to its
  // base language and serve Devanagari to someone who explicitly asked for
  // Latin script — the two are different scripts, not dialects.
  nonExplicitSupportedLngs: false,
  load: 'currentOnly',
  lng: readStoredLocale(),
  fallbackLng: DEFAULT_LOCALE,
  supportedLngs: [...LOCALES],
  interpolation: {
    // React escapes for us. Double-escaping mangles Devanagari and any
    // technician's free text that happens to contain a quote.
    escapeValue: false,
  },
  returnNull: false,
});

export async function changeLanguage(locale: string): Promise<void> {
  if (!isLocale(locale)) return;
  persistLocale(locale);
  await i18n.changeLanguage(locale);
  document.documentElement.lang = locale;
}

document.documentElement.lang = i18n.language;

export default i18n;
