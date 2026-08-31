/**
 * Three-way language control, matching the theme toggle exactly.
 *
 * Deliberately the same `radiogroup` shape rather than a `<select>`: the three
 * options are always visible, so an operator who does not read the current
 * language can still see that a language they DO read is available. A select
 * collapsed to "English" is unreadable to precisely the person who needs it,
 * which is the whole failure this control exists to prevent.
 *
 * Each option is labelled in its own language and script — "English", "हिंदी",
 * "Hinglish" — never translated into the currently active one. A Hindi speaker
 * looking for Hindi should be scanning for हिंदी, not for the Devanagari word
 * that English uses for it.
 *
 * SCRIPT, NOT FLAGS
 * No flags. Hindi is not a country, several countries share a language, and
 * flag icons in language pickers are a well-known way to insult a user. Two
 * or three letters of the actual script is both more accurate and more legible
 * at 18px than any icon would be.
 */

import { useTranslation } from 'react-i18next';

import { LOCALES } from '@greenlam/core';

import { changeLanguage } from './index';

/** What each option prints on its own button, in its own script. */
const GLYPH: Record<string, string> = {
  en: 'EN',
  hi: 'हिं',
  'hi-Latn': 'HI',
};

export function LanguageToggle() {
  const { t, i18n } = useTranslation();
  const current = LOCALES.includes(i18n.language as (typeof LOCALES)[number])
    ? i18n.language
    : LOCALES[0];
  const activeIndex = LOCALES.indexOf(current as (typeof LOCALES)[number]);

  const select = (locale: string) => {
    void changeLanguage(locale);
  };

  return (
    <div
      role="radiogroup"
      aria-label={t('language.label')}
      className="relative inline-flex items-center rounded-full border p-0.5"
      style={{ borderColor: 'var(--line)', background: 'var(--surface-muted)' }}
    >
      <span
        aria-hidden="true"
        className="absolute top-0.5 bottom-0.5 left-0.5 rounded-full motion-safe:transition-transform motion-safe:duration-200 motion-safe:ease-out"
        style={{
          width: `calc((100% - 0.25rem) / ${LOCALES.length})`,
          background: 'var(--surface)',
          boxShadow: 'var(--shadow)',
          transform: `translateX(${activeIndex * 100}%)`,
        }}
      />

      {LOCALES.map((locale) => {
        const isActive = locale === current;
        return (
          <button
            key={locale}
            type="button"
            role="radio"
            aria-checked={isActive}
            // The full language name, in its own language — so a screen reader
            // set to Hindi announces "हिंदी" rather than a transliteration.
            aria-label={t(`language.${locale}`)}
            title={t(`language.${locale}`)}
            lang={locale}
            tabIndex={isActive ? 0 : -1}
            onClick={() => select(locale)}
            onKeyDown={(event) => {
              if (event.key !== 'ArrowRight' && event.key !== 'ArrowLeft') return;
              event.preventDefault();
              const delta = event.key === 'ArrowRight' ? 1 : -1;
              const next =
                LOCALES[(activeIndex + delta + LOCALES.length) % LOCALES.length];
              if (next) select(next);
            }}
            className="relative z-10 flex h-10 w-11 items-center justify-center rounded-full font-semibold"
            style={{
              fontSize: 'var(--text-sm)',
              color: isActive ? 'var(--primary)' : 'var(--ink-muted)',
            }}
          >
            <span aria-hidden="true">{GLYPH[locale] ?? locale}</span>
          </button>
        );
      })}
    </div>
  );
}
