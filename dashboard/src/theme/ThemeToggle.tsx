/**
 * Three-way theme control.
 *
 * Built as a `radiogroup` rather than a single cycling button. A cycling button
 * is smaller, but it never tells you what the other options are, and a screen
 * reader user has to activate it three times to find out. Three radios announce
 * the full set and the current choice in one pass, and arrow keys move between
 * them for free.
 *
 * The moving pill is a `transform` on a single absolutely-positioned element —
 * no layout animation, nothing that triggers reflow, and it disappears entirely
 * under `prefers-reduced-motion`. On the mid-range Android phones this runs on,
 * that restraint is the difference between smooth and janky.
 */

import type { ReactElement } from 'react';
import { useTranslation } from 'react-i18next';

import { THEME_PREFERENCES, type ThemePreference } from '@greenlam/core';

import { useTheme } from './ThemeProvider';

// React 19 removed the global JSX namespace; ReactElement is the replacement.
const ICONS: Record<ThemePreference, ReactElement> = {
  light: (
    <>
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
    </>
  ),
  dark: <path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z" />,
  // A phone outline: 'system' means "whatever this device is set to", and a
  // device is the clearest way to draw that.
  system: (
    <>
      <rect x="7" y="2.5" width="10" height="19" rx="2" />
      <path d="M11 18.5h2" />
    </>
  ),
};

export function ThemeToggle() {
  const { t } = useTranslation();
  const { preference, setPreference } = useTheme();
  const activeIndex = THEME_PREFERENCES.indexOf(preference);

  return (
    <div
      role="radiogroup"
      aria-label={t('theme.label')}
      className="relative inline-flex items-center rounded-full border p-0.5"
      style={{ borderColor: 'var(--line)', background: 'var(--surface-muted)' }}
    >
      {/* The indicator. transform only — never width or left. */}
      <span
        aria-hidden="true"
        className="absolute top-0.5 bottom-0.5 left-0.5 rounded-full motion-safe:transition-transform motion-safe:duration-200 motion-safe:ease-out"
        style={{
          width: 'calc((100% - 0.25rem) / 3)',
          background: 'var(--surface)',
          boxShadow: 'var(--shadow)',
          transform: `translateX(${activeIndex * 100}%)`,
        }}
      />

      {THEME_PREFERENCES.map((option) => {
        const isActive = option === preference;
        return (
          <button
            key={option}
            type="button"
            role="radio"
            aria-checked={isActive}
            // Announces the option, not the icon. "Dark", not "moon".
            aria-label={t(`theme.${option}`)}
            title={t(`theme.${option}`)}
            tabIndex={isActive ? 0 : -1}
            onClick={() => setPreference(option)}
            onKeyDown={(event) => {
              // Arrow keys move within a radiogroup, per the ARIA pattern.
              if (event.key !== 'ArrowRight' && event.key !== 'ArrowLeft') return;
              event.preventDefault();
              const delta = event.key === 'ArrowRight' ? 1 : -1;
              const count = THEME_PREFERENCES.length;
              const next =
                THEME_PREFERENCES[(activeIndex + delta + count) % count];
              if (next) setPreference(next);
            }}
            className="relative z-10 flex h-10 w-11 items-center justify-center rounded-full"
            style={{ color: isActive ? 'var(--primary)' : 'var(--ink-muted)' }}
          >
            <svg
              width="18"
              height="18"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.75"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden="true"
            >
              {ICONS[option]}
            </svg>
          </button>
        );
      })}
    </div>
  );
}
