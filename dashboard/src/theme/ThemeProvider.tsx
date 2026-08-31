/**
 * Theme state, persistence and DOM application.
 *
 * The bootstrap in index.html has already painted the correct theme before
 * React mounted. This provider takes over from there and adds the four things
 * a bootstrap script cannot do: react to a system change, stay in step across
 * tabs, follow the signed-in user, and write the preference back.
 *
 * Security notes, since a theme toggle is a surprisingly good place to get
 * this wrong:
 *
 *   - Every value that reaches the DOM goes through `coerceThemePreference`
 *     first. Nothing read from storage or the network is assigned to an
 *     attribute directly.
 *   - The preference is cleared from the device on sign-out, so the next
 *     person on a shared floor tablet does not inherit the last one's setting.
 *   - Storage access is wrapped. Safari private mode throws on localStorage,
 *     and a theme is never worth a crash.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react';

import {
  coerceThemePreference,
  nextThemePreference,
  resolveTheme,
  THEME_CANVAS,
  THEME_STORAGE_KEY,
  type ResolvedTheme,
  type ThemePreference,
} from '@greenlam/core';

interface ThemeContextValue {
  /** What the user chose: 'light', 'dark' or 'system'. */
  preference: ThemePreference;
  /** What is actually painted right now. */
  resolved: ResolvedTheme;
  setPreference: (next: ThemePreference) => void;
  /** light → dark → system → light */
  cycle: () => void;
}

const ThemeContext = createContext<ThemeContextValue | null>(null);

const DARK_QUERY = '(prefers-color-scheme: dark)';

function readStoredPreference(): ThemePreference {
  try {
    return coerceThemePreference(localStorage.getItem(THEME_STORAGE_KEY));
  } catch {
    return 'system';
  }
}

/** Distinguishes "no choice made on this device" from "chose system". */
function hasStoredPreference(): boolean {
  try {
    return localStorage.getItem(THEME_STORAGE_KEY) !== null;
  } catch {
    return false;
  }
}

function writeStoredPreference(preference: ThemePreference): void {
  try {
    localStorage.setItem(THEME_STORAGE_KEY, preference);
  } catch {
    /* private mode, quota, or storage disabled — the session still works */
  }
}

export function clearStoredPreference(): void {
  try {
    localStorage.removeItem(THEME_STORAGE_KEY);
  } catch {
    /* nothing to clear */
  }
}

function systemPrefersDark(): boolean {
  return typeof window !== 'undefined' && window.matchMedia(DARK_QUERY).matches;
}

/** Only ever called with a value that has already been coerced. */
function applyToDocument(resolved: ResolvedTheme): void {
  const root = document.documentElement;
  root.setAttribute('data-theme', resolved);
  // Tells the browser to paint native controls, scrollbars and form widgets to
  // match. Without it, dark mode has white scrollbars and light dropdowns.
  root.style.colorScheme = resolved;

  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) meta.setAttribute('content', THEME_CANVAS[resolved]);
}

interface ThemeProviderProps {
  children: ReactNode;
  /**
   * The signed-in user's saved preference, if any. Applied once on sign-in so
   * a technician's choice follows them onto whichever shared tablet they pick
   * up. Pass `undefined` while signed out.
   */
  userPreference?: ThemePreference;
  /** Persist to the server. Failure is non-fatal: the local choice still holds. */
  onPersist?: (preference: ThemePreference) => void;
}

export function ThemeProvider({
  children,
  userPreference,
  onPersist,
}: ThemeProviderProps) {
  const [preference, setPreferenceState] =
    useState<ThemePreference>(readStoredPreference);
  const [prefersDark, setPrefersDark] = useState(systemPrefersDark);

  // Follow the OS while the preference is 'system'. Without this the theme
  // only updates on reload, which looks broken on a phone with a sunset
  // schedule.
  useEffect(() => {
    const media = window.matchMedia(DARK_QUERY);
    const onChange = (event: MediaQueryListEvent) => setPrefersDark(event.matches);
    media.addEventListener('change', onChange);
    return () => media.removeEventListener('change', onChange);
  }, []);

  // Keep tabs in step. A supervisor with the board open on one tab and a
  // ticket on another should not see two different themes.
  useEffect(() => {
    const onStorage = (event: StorageEvent) => {
      if (event.key !== THEME_STORAGE_KEY) return;
      setPreferenceState(coerceThemePreference(event.newValue));
    };
    window.addEventListener('storage', onStorage);
    return () => window.removeEventListener('storage', onStorage);
  }, []);

  // Adopt the server-side preference on sign-in — but only when this device
  // has no choice of its own.
  //
  // The two cases this has to get right:
  //   - A shared floor tablet. Storage was cleared at the previous sign-out,
  //     so the next person's saved theme applies. That is the feature.
  //   - Someone who just tapped the toggle on the sign-in screen, then signed
  //     in. Their tap stands. Overriding a choice made ten seconds ago reads
  //     as the control being broken.
  //
  // Coerced regardless, because the value arrived over the network.
  useEffect(() => {
    if (userPreference === undefined) return;
    if (hasStoredPreference()) return;
    const safe = coerceThemePreference(userPreference);
    setPreferenceState(safe);
    writeStoredPreference(safe);
  }, [userPreference]);

  const resolved = useMemo(
    () => resolveTheme(preference, prefersDark),
    [preference, prefersDark],
  );

  useEffect(() => {
    applyToDocument(resolved);
  }, [resolved]);

  const setPreference = useCallback(
    (next: ThemePreference) => {
      const safe = coerceThemePreference(next);
      setPreferenceState(safe);
      writeStoredPreference(safe);
      onPersist?.(safe);
    },
    [onPersist],
  );

  const cycle = useCallback(() => {
    setPreference(nextThemePreference(preference));
  }, [preference, setPreference]);

  const value = useMemo(
    () => ({ preference, resolved, setPreference, cycle }),
    [preference, resolved, setPreference, cycle],
  );

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme(): ThemeContextValue {
  const context = useContext(ThemeContext);
  if (context === null) {
    throw new Error('useTheme must be used inside a ThemeProvider');
  }
  return context;
}
