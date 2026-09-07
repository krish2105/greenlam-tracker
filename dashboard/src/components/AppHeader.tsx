import { useLayoutEffect, useRef, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { NavLink } from 'react-router-dom';

import type { ApiUser } from '../lib/api';
import { LanguageToggle } from '../i18n/LanguageToggle';
import { ThemeToggle } from '../theme/ThemeToggle';
import { ArchMark } from './ArchMark';

interface AppHeaderProps {
  user: ApiUser;
  showFloor: boolean;
  showBoard: boolean;
  /** Manager and above. Importing rewrites history for the whole plant. */
  showImport: boolean;
  showAccess: boolean;
  onSignOut: () => void;
}

/**
 * Two rows, at every width.
 *
 * Row one is the mark and identity. On a shared floor tablet, "who am I signed
 * in as" is the most consequential thing in the chrome — a breakdown logged
 * under the wrong name corrupts the accountability the system exists for — so
 * it gets its own line rather than being truncated to "Signed in as Priy…" at
 * 375px. Row two carries the tabs and controls, which survive being compact.
 */
export function AppHeader({
  user,
  showFloor,
  showBoard,
  showImport,
  showAccess,
  onSignOut,
}: AppHeaderProps) {
  const { t } = useTranslation();
  const ref = useRef<HTMLElement | null>(null);

  /*
   * Publish the header's measured height as `--header-h`.
   *
   * Anything else that wants to stick below the header needs this number, and
   * hard-coding it in each of those places guarantees they drift the first time
   * a longer name or a second nav item wraps the header to a taller row. One
   * measured variable; every consumer stays correct for free.
   */
  useLayoutEffect(() => {
    const node = ref.current;
    if (!node || typeof ResizeObserver === 'undefined') return;
    const publish = () =>
      document.documentElement.style.setProperty(
        '--header-h',
        `${node.getBoundingClientRect().height}px`,
      );
    publish();
    const observer = new ResizeObserver(publish);
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  return (
    <header
      ref={ref}
      className="register-rule sticky top-0 z-20"
      style={{ background: 'var(--surface)' }}
    >
      {/* The mark and the product name. Nothing about who is signed in.
          This used to print "Vikram Shetty · Plant head" underneath, on every
          screen, for everyone. Two reasons it is gone:

          1. It was the loudest personal detail in the interface, permanently
             on display on shared floor tablets that pass between shifts.
          2. With two access levels, the role label said nothing a person did
             not already know from which tabs they could see.

          Identity has not disappeared — it is on the sign-out control, which
          is where somebody looks when the question is "am I still signed in as
          the last shift". */}
      <div className="mx-auto flex w-full max-w-6xl items-center gap-2.5 px-4 pt-2.5">
        <ArchMark />
        <p className="min-w-0 truncate font-semibold" style={{ color: 'var(--ink)' }}>
          {t('app.name')}
        </p>
      </div>

      <div className="mx-auto flex w-full max-w-6xl items-center gap-2 px-3 pt-1 pb-1">
        <nav aria-label={t('app.name')} className="flex flex-1 gap-1">
          {showFloor && <HeaderLink to="/floor">{t('nav.floor')}</HeaderLink>}
          {showBoard && <HeaderLink to="/board">{t('nav.board')}</HeaderLink>}
          {showImport && <HeaderLink to="/import">{t('imports.nav')}</HeaderLink>}
          {showImport && <HeaderLink to="/masters">{t('masters.nav')}</HeaderLink>}
          {showImport && <HeaderLink to="/setup">{t('setup.nav')}</HeaderLink>}
          {showAccess && <HeaderLink to="/access">{t('access.nav')}</HeaderLink>}
        </nav>

        <LanguageToggle />
        <ThemeToggle />

        {/* Icon-only under 640px: three toggle segments plus two tabs plus a
            text button does not fit 375px, and clipping "Sign out" on a shared
            tablet is the worst of the available compromises. The label is
            still announced and the target stays 44px. */}
        <button
          type="button"
          onClick={onSignOut}
          // Identity moved here from the masthead. A person checking whether
          // the last shift is still signed in looks at the sign-out control,
          // and it is only read on purpose rather than displayed permanently.
          aria-label={t('common.signOutAs', { name: user.name })}
          title={t('common.signOutAs', { name: user.name })}
          className="arch flex h-11 shrink-0 items-center justify-center border px-3"
          style={{
            borderColor: 'var(--line)',
            color: 'var(--ink-muted)',
            fontSize: 'var(--text-sm)',
          }}
        >
          <span className="hidden sm:inline">{t('nav.signOut')}</span>
          <svg
            className="sm:hidden"
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
            <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9" />
          </svg>
        </button>
      </div>
    </header>
  );
}

function HeaderLink({ to, children }: { to: string; children: ReactNode }) {
  return (
    <NavLink
      to={to}
      // Active state is weight plus a rule, never colour alone — colour-only
      // state fails for a colour-blind user and washes out in a sunlit hall.
      className={({ isActive }) =>
        `rounded-t px-3 py-2 ${isActive ? 'font-semibold' : ''}`
      }
      style={({ isActive }) => ({
        color: isActive ? 'var(--ink)' : 'var(--ink-muted)',
        boxShadow: isActive ? 'inset 0 -2px 0 var(--accent)' : 'none',
        fontSize: 'var(--text-sm)',
      })}
    >
      {children}
    </NavLink>
  );
}
