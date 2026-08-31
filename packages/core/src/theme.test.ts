import { describe, expect, it } from 'vitest';

import {
  coerceThemePreference,
  isThemePreference,
  nextThemePreference,
  resolveTheme,
} from './theme';

describe('coerceThemePreference', () => {
  it('passes through the three valid values', () => {
    expect(coerceThemePreference('light')).toBe('light');
    expect(coerceThemePreference('dark')).toBe('dark');
    expect(coerceThemePreference('system')).toBe('system');
  });

  // The whole reason this function exists. localStorage is writable by any
  // script on the origin, so its contents are untrusted input.
  it.each([
    '<script>alert(1)</script>',
    '"><img src=x onerror=alert(1)>',
    'dark; background:url(evil)',
    'DARK',
    '',
    null,
    undefined,
    42,
    {},
    ['dark'],
  ])('collapses %p to the fallback', (hostile) => {
    expect(coerceThemePreference(hostile)).toBe('system');
  });

  it('honours an explicit fallback', () => {
    expect(coerceThemePreference('nonsense', 'light')).toBe('light');
  });
});

describe('isThemePreference', () => {
  it('is case-sensitive', () => {
    expect(isThemePreference('dark')).toBe(true);
    expect(isThemePreference('Dark')).toBe(false);
  });
});

describe('resolveTheme', () => {
  it('follows the system only when the preference is system', () => {
    expect(resolveTheme('system', true)).toBe('dark');
    expect(resolveTheme('system', false)).toBe('light');
  });

  it('ignores the system when the user has chosen', () => {
    expect(resolveTheme('light', true)).toBe('light');
    expect(resolveTheme('dark', false)).toBe('dark');
  });
});

describe('nextThemePreference', () => {
  it('cycles light → dark → system → light', () => {
    expect(nextThemePreference('light')).toBe('dark');
    expect(nextThemePreference('dark')).toBe('system');
    expect(nextThemePreference('system')).toBe('light');
  });

  it('returns to the start after three taps', () => {
    let t: ReturnType<typeof nextThemePreference> = 'light';
    for (let i = 0; i < 3; i++) t = nextThemePreference(t);
    expect(t).toBe('light');
  });
});
