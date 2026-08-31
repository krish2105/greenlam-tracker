/**
 * Theme resolution. Pure functions, no DOM, no React — the Expo port reuses
 * this file verbatim.
 *
 * The security-relevant piece is `coerceThemePreference`. A theme preference
 * arrives from two places we do not fully control: `localStorage`, which any
 * script on the origin can write, and the API, which reflects what a user
 * saved. Neither value is ever allowed to reach the DOM directly. It is mapped
 * through this allowlist first, and anything unrecognised collapses to
 * `'system'`. That is what keeps a stored string from becoming an attribute
 * value, a class name, or worse, an injected style.
 */

export const THEME_PREFERENCES = ['light', 'dark', 'system'] as const;
export type ThemePreference = (typeof THEME_PREFERENCES)[number];

/** What actually gets painted. 'system' has been resolved away by this point. */
export type ResolvedTheme = 'light' | 'dark';

export const THEME_STORAGE_KEY = 'gmt.theme';

export function isThemePreference(value: unknown): value is ThemePreference {
  return (
    typeof value === 'string' &&
    (THEME_PREFERENCES as readonly string[]).includes(value)
  );
}

/**
 * The only sanctioned way to turn untrusted input into a theme.
 *
 * Never do `el.dataset.theme = localStorage.getItem('gmt.theme')`. Always
 * `el.dataset.theme = coerceThemePreference(localStorage.getItem(...))`.
 */
export function coerceThemePreference(
  value: unknown,
  fallback: ThemePreference = 'system',
): ThemePreference {
  return isThemePreference(value) ? value : fallback;
}

export function resolveTheme(
  preference: ThemePreference,
  systemPrefersDark: boolean,
): ResolvedTheme {
  if (preference === 'system') return systemPrefersDark ? 'dark' : 'light';
  return preference;
}

/**
 * Cycle order for the toggle: light → dark → system → light.
 *
 * System sits last on purpose. Someone tapping the control is expressing an
 * opinion, so the two explicit choices come first and 'follow my phone' is
 * where you land when you want to stop deciding.
 */
const CYCLE: Record<ThemePreference, ThemePreference> = {
  light: 'dark',
  dark: 'system',
  system: 'light',
};

export function nextThemePreference(current: ThemePreference): ThemePreference {
  return CYCLE[current];
}

/**
 * The colour painted behind the page before CSS parses, and what goes in
 * <meta name="theme-color"> so Android's address bar matches.
 *
 * Kept here rather than read from CSS variables because the bootstrap script
 * needs it before any stylesheet has loaded.
 */
export const THEME_CANVAS: Record<ResolvedTheme, string> = {
  light: '#F7F6F2',
  dark: '#131611',
};
