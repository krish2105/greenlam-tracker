/**
 * App shell, session state, and role-aware routing.
 *
 * One PWA, two surfaces. Which one you land on is decided by
 * `homeRouteFor(role)` in packages/core: floor roles go to the floor, corporate
 * roles go to the board. A CXO opening a ticket queue would be a sign the
 * information architecture is wrong, so they simply never get sent there.
 *
 * Client-side gating hides controls. The API enforces the same rules
 * independently — every check here has a server-side twin.
 */

import { Suspense, lazy, useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Navigate, Route, Routes, useLocation, useNavigate } from 'react-router-dom';

import { can, homeRouteFor, isPendingApproval, type ThemePreference } from '@greenlam/core';

import { AppHeader } from './components/AppHeader';
import { NoAccess } from './components/NoAccess';
import { OutboxBanner } from './components/OutboxBanner';
import { ArchMark } from './components/ArchMark';
import { FloorHome } from './components/floor/FloorHome';
import { FloorView } from './components/floor/FloorView';
import { ProductionView } from './components/floor/ProductionView';

// The board carries Motion, the display face, four charts and the plant map.
// Lazy so an operator's phone never downloads any of it.
const BoardView = lazy(() =>
  import('./components/board/BoardView').then((m) => ({ default: m.BoardView })),
);
// Same reasoning as the board. Import is a manager-and-above screen that pulls
// in a preview table and a drop zone; an operator's phone should never spend a
// byte on it.
const ImportView = lazy(() =>
  import('./components/imports/ImportView').then((m) => ({ default: m.ImportView })),
);
// Dashboard-only and lazy for a reason of its own: this one carries a ZIP
// reader and an XML parser for files people bring with them, and the floor
// never opens one.
const AdHocView = lazy(() =>
  import('./components/board/AdHocView').then((m) => ({ default: m.AdHocView })),
);
// Also dashboard-only, also lazy. The floor never edits a vocabulary.
const AccessView = lazy(() =>
  import('./components/access/AccessView').then((m) => ({ default: m.AccessView })),
);
const MastersView = lazy(() =>
  import('./components/masters/MastersView').then((m) => ({ default: m.MastersView })),
);
const MachineSetupView = lazy(() =>
  import('./components/masters/MachineSetupView').then((m) => ({
    default: m.MachineSetupView,
  })),
);
import { MachineMaster } from './components/MachineMaster';
import { SignIn } from './components/SignIn';
import * as api from './lib/api';
import { clearOutbox, startOutbox } from './lib/outbox';
import { resetSectionNames } from './lib/masterNames';
import { ThemeProvider, clearStoredPreference } from './theme/ThemeProvider';

export default function App() {
  const [user, setUser] = useState<api.ApiUser | null>(null);
  const [restoring, setRestoring] = useState(true);

  useEffect(() => {
    let cancelled = false;
    void api.refresh().then((restored) => {
      if (!cancelled) {
        setUser(restored);
        setRestoring(false);
      }
    });
    return () => {
      cancelled = true;
    };
  }, []);

  const persistTheme = useCallback(
    (preference: ThemePreference) => {
      if (!user) return;
      void api.savePreferences({ preferred_theme: preference }).catch(() => {});
    },
    [user],
  );

  // Drain triggers: app foreground, `online`, and a timer while open. There is
  // deliberately no background timer — iOS has no Background Sync API.
  useEffect(() => startOutbox(), []);

  const handleSignOut = useCallback(async () => {
    await api.logout().catch(() => {});
    // A shared floor tablet must not carry one person's queued work into the
    // next person's session.
    await clearOutbox().catch(() => {});
    // Shared floor tablets: the next person must not inherit this one's theme.
    clearStoredPreference();
    // Nor their plant's section names — the next sign-in may be a different
    // plant, and a stale lookup would translate its sections into another
    // plant's vocabulary.
    resetSectionNames();
    setUser(null);
  }, []);

  return (
    <ThemeProvider userPreference={user?.preferred_theme} onPersist={persistTheme}>
      {restoring ? (
        <Splash />
      ) : user ? (
        <SignedIn user={user} onSignOut={handleSignOut} />
      ) : (
        <SignIn onSignedIn={setUser} />
      )}
    </ThemeProvider>
  );
}

function Splash() {
  const { t } = useTranslation();
  return (
    <div
      className="flex min-h-dvh flex-col items-center justify-center gap-3"
      role="status"
      aria-live="polite"
    >
      <ArchMark size={40} />
      <p style={{ color: 'var(--ink-muted)' }}>{t('masters.loading')}</p>
    </div>
  );
}

function SignedIn({
  user,
  onSignOut,
}: {
  user: api.ApiUser;
  onSignOut: () => void;
}) {
  const navigate = useNavigate();
  const location = useLocation();

  // Six combinable areas (V5 §3). The floor shows for anyone who can act on
  // it; the board is a separate grant, and holding it does not imply the floor
  // — a plant head reads every number and acknowledges nothing.
  const showFloor = can(user.areas, 'raiseTicket') || can(user.areas, 'logProduction');
  const showBoard = can(user.areas, 'viewDashboard');
  const home = homeRouteFor(user.areas);

  // Send people to the surface built for their job rather than dropping
  // everyone on the same landing page.
  useEffect(() => {
    if (location.pathname === '/') navigate(home, { replace: true });
  }, [location.pathname, home, navigate]);

  // Holding nothing is a real state, not an error. Every screen behind this
  // would 403, and showing them to somebody who cannot use them is how a new
  // person concludes the app is broken rather than that they are waiting.
  if (user.areas.length === 0) {
    return (
      <div className="flex min-h-dvh flex-col">
        <AppHeader
          user={user}
          showFloor={false}
          showBoard={false}
          showImport={false}
          showAccess={false}
          onSignOut={onSignOut}
        />
        <main id="main" className="flex-1">
          <NoAccess name={user.name} pending={isPendingApproval(user)} />
        </main>
      </div>
    );
  }

  return (
    <div className="flex min-h-dvh flex-col">
      <AppHeader
        user={user}
        showFloor={showFloor}
        showBoard={showBoard}
        showImport={can(user.areas, 'editMasters')}
        showAccess={can(user.areas, 'approveUsers')}
        onSignOut={onSignOut}
      />
      <OutboxBanner />

      <main
        id="main"
        className={`mx-auto w-full flex-1 px-4 py-4 ${
          location.pathname.startsWith('/board') ? 'max-w-6xl' : 'max-w-2xl'
        }`}
      >
        <Routes>
          {/* The floor opens on a choice, not a screen. Maintenance and
              production are done by different people at different moments, and
              one combined screen showed a press operator eight paper fields he
              could never fill. */}
          <Route path="/floor" element={<FloorHome user={user} />} />
          <Route
            path="/floor/maintenance"
            element={
              <FloorView
                user={user}
                canRaise={can(user.areas, 'raiseTicket')}
                canSeeTeam={can(user.areas, 'viewDashboard')}
              />
            }
          />
          <Route path="/floor/production" element={<ProductionView />} />
          <Route path="/floor/machines" element={<MachineMaster />} />
          {/* Importing rewrites shared history for the whole plant, so it sits
              behind the same capability that guards the masters it depends on.
              Someone without it gets sent home rather than shown a locked door. */}
          <Route
            path="/setup"
            element={
              can(user.areas, 'editMasters') ? (
                <Suspense fallback={<Splash />}>
                  <MachineSetupView />
                </Suspense>
              ) : (
                <Navigate to={home} replace />
              )
            }
          />
          {/* Approving accounts and granting areas. Its own capability rather
              than riding on `editMasters`: deciding who gets in is a different
              decision from renaming a machine, even though the same people do
              both today. */}
          <Route
            path="/access"
            element={
              can(user.areas, 'approveUsers') ? (
                <Suspense fallback={<Splash />}>
                  <AccessView />
                </Suspense>
              ) : (
                <Navigate to={home} replace />
              )
            }
          />
          <Route
            path="/masters"
            element={
              can(user.areas, 'editMasters') ? (
                <Suspense fallback={<Splash />}>
                  <MastersView />
                </Suspense>
              ) : (
                <Navigate to={home} replace />
              )
            }
          />
          <Route
            path="/import"
            element={
              can(user.areas, 'editMasters') ? (
                <Suspense fallback={<Splash />}>
                  <ImportView />
                </Suspense>
              ) : (
                <Navigate to={home} replace />
              )
            }
          />
          <Route
            path="/board"
            element={
              !showBoard ? (
                <Navigate to="/floor" replace />
              ) : (
              <Suspense fallback={<Splash />}>
                <BoardView canDrill />
              </Suspense>
              )
            }
          />
          {/* Charting a file somebody brought (V5 §11). Guarded by Dashboard,
              NOT by editMasters like /import — this changes nothing, and
              putting the two on one screen would be a misread button between
              "look at my file" and "overwrite the plant's". */}
          <Route
            path="/analyse"
            element={
              showBoard ? (
                <Suspense fallback={<Splash />}>
                  <AdHocView />
                </Suspense>
              ) : (
                <Navigate to={home} replace />
              )
            }
          />
          <Route path="*" element={<Navigate to={home} replace />} />
        </Routes>
      </main>
    </div>
  );
}
