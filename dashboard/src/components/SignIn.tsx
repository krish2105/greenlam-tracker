/**
 * PIN sign-in.
 *
 * Written for someone standing next to a stopped machine: two fields, a numeric
 * keypad, and errors that say what to do rather than what went wrong.
 *
 * The lockout messages are surfaced honestly. Telling someone "try again in 8
 * seconds" is far better than a flat rejection they will retry immediately —
 * and knowing a supervisor can unlock them is the difference between waiting
 * and going back to shouting across the floor.
 */

import type { TFunction } from 'i18next';
import { useState, type FormEvent } from 'react';
import { useTranslation } from 'react-i18next';

import * as api from '../lib/api';
import { LanguageToggle } from '../i18n/LanguageToggle';
import { ThemeToggle } from '../theme/ThemeToggle';

const DEVICE_KEY = 'gmt.device';

/** Stable per-install id, used to tie a session to a device. Not a secret. */
function deviceUid(): string {
  try {
    let existing = localStorage.getItem(DEVICE_KEY);
    if (!existing) {
      existing = crypto.randomUUID();
      localStorage.setItem(DEVICE_KEY, existing);
    }
    return existing;
  } catch {
    return 'unknown-device';
  }
}

export function SignIn({ onSignedIn }: { onSignedIn: (user: api.ApiUser) => void }) {
  const { t } = useTranslation();
  const [employeeId, setEmployeeId] = useState('');
  const [pin, setPin] = useState('');
  const [showPin, setShowPin] = useState(false);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  // The same form, in two modes. Signing up asks for one more field and posts
  // somewhere else; everything around it — the ID, the PIN, the show/hide, the
  // error handling — is identical, and building it twice would mean two places
  // for the PIN rules to drift apart.
  const [signingUp, setSigningUp] = useState(false);
  const [name, setName] = useState('');

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (!employeeId.trim() || !pin) {
      setError(t('signIn.errors.missingFields'));
      return;
    }
    if (!/^\d{6}$/.test(pin)) {
      setError(t('signIn.errors.badPinFormat'));
      return;
    }

    if (signingUp && !name.trim()) {
      setError(t('signIn.errors.missingName'));
      return;
    }

    setBusy(true);
    setError('');
    try {
      if (signingUp) {
        await api.signup({ employee_id: employeeId.trim(), name: name.trim(), pin });
      }
      // Signed in either way. A new account holds nothing and lands on the
      // waiting screen — which is a far better answer than "account created,
      // now sign in", which is one more chance to mistype the PIN they just
      // chose.
      onSignedIn(await api.login(employeeId.trim(), pin, deviceUid()));
    } catch (err) {
      setError(messageFor(err, t));
      setPin('');
    } finally {
      setBusy(false);
    }
  }

  const inputStyle = {
    borderColor: 'var(--line-strong)',
    background: 'var(--surface)',
    color: 'var(--ink)',
  };

  return (
    <div className="flex min-h-dvh flex-col">
      {/* Available before sign-in on purpose: someone on a night shift should
          not have to authenticate before they can turn the brightness down. */}
      <div className="flex justify-end p-3">
        <LanguageToggle />
        <ThemeToggle />
      </div>

      <div className="flex flex-1 items-start justify-center px-4 pb-10">
        <div className="w-full max-w-sm">
          {/* The mark leads, centred, with room around it. This is the only
              screen in the product that gets to be decorative — everything
              after sign-in is somebody standing next to a stopped machine. */}
          <div className="flex flex-col items-center pt-2 text-center">
            {/* The real logo, not the drawn mark. This is the one screen with
                room for the full lockup, and the one screen where a person is
                deciding whether they are in the right place — so it should be
                Greenlam's own artwork, wordmark and all.

                The ARCH only, not the full lockup. The "Greenlam" wordmark is
                dark green on white - on this canvas it sinks into the
                background and reads as a smudge. The arch carries its own
                light-green field, so it holds on either theme, and the name is
                set in type below where it can take the theme's ink colour.

                The drawn mark still runs everywhere else: this is a 305px
                raster, and at the 28px of the nav bar a downscaled raster is
                mush where the vector stays sharp. */}
            <img
              src="/greenlam-mark.png"
              alt=""
              width={104}
              height={104}
              className="brand-logo"
            />
            <h1
              className="mt-4 font-semibold"
              style={{ fontSize: 'var(--text-2xl)', color: 'var(--ink)', letterSpacing: '-0.02em' }}
            >
              {t('app.name')}
            </h1>
            <p
              className="mt-1"
              style={{ color: 'var(--ink-muted)', fontSize: 'var(--text-sm)' }}
            >
              {t('app.tagline')}
            </p>
            {/* A hairline in the brand spectrum. The fan again, flattened —
                one idea, stated twice, quietly the second time. */}
            <span aria-hidden="true" className="brand-rule mt-5" />
          </div>

          <form onSubmit={handleSubmit} className="mt-6 space-y-4" noValidate>
            <div>
              <label
                htmlFor="employeeId"
                className="mb-1 block font-medium"
                style={{ fontSize: 'var(--text-sm)', color: 'var(--ink)' }}
              >
                {t('signIn.employeeId')}
              </label>
              <input
                id="employeeId"
                value={employeeId}
                onChange={(e) => setEmployeeId(e.target.value)}
                autoComplete="username"
                autoCapitalize="characters"
                spellCheck={false}
                enterKeyHint="next"
                aria-describedby="employeeIdHint"
                className="w-full rounded-lg border px-3 py-3"
                style={inputStyle}
              />
              <p
                id="employeeIdHint"
                className="mt-1"
                style={{ fontSize: 'var(--text-xs)', color: 'var(--ink-muted)' }}
              >
                {t('signIn.employeeIdHint')}
              </p>
            </div>

            {signingUp && (
              <div>
                <label
                  htmlFor="signup-name"
                  className="mb-1 block font-medium"
                  style={{ fontSize: 'var(--text-sm)', color: 'var(--ink)' }}
                >
                  {t('signIn.name')}
                </label>
                <input
                  id="signup-name"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  autoComplete="name"
                  className="w-full rounded-lg border px-3 py-3"
                  style={inputStyle}
                />
                <p
                  className="mt-1"
                  style={{ fontSize: 'var(--text-xs)', color: 'var(--ink-muted)' }}
                >
                  {t('signIn.nameHint')}
                </p>
              </div>
            )}

            <div>
              <label
                htmlFor="pin"
                className="mb-1 block font-medium"
                style={{ fontSize: 'var(--text-sm)', color: 'var(--ink)' }}
              >
                {t('signIn.pin')}
              </label>
              <div className="relative">
                <input
                  id="pin"
                  // `type` flips rather than using a masked text field, so
                  // password managers still recognise it and browsers do not
                  // offer to save a plaintext value.
                  type={showPin ? 'text' : 'password'}
                  value={pin}
                  onChange={(e) =>
                    setPin(e.target.value.replace(/\D/g, '').slice(0, 6))
                  }
                  // Numeric keypad on a phone. `inputMode` rather than
                  // type="number", which brings spinners and a stray minus sign.
                  inputMode="numeric"
                  autoComplete="current-password"
                  enterKeyHint="go"
                  maxLength={6}
                  aria-describedby="pinHint"
                  className="tabular w-full rounded-lg border py-3 pr-24 pl-3 tracking-[0.4em]"
                  style={inputStyle}
                />
                <button
                  type="button"
                  onClick={() => setShowPin((v) => !v)}
                  className="absolute top-1/2 right-1 -translate-y-1/2 rounded px-3 py-2"
                  style={{ color: 'var(--ink-muted)', fontSize: 'var(--text-xs)' }}
                >
                  {showPin ? t('signIn.hidePin') : t('signIn.showPin')}
                </button>
              </div>
              <p
                id="pinHint"
                className="mt-1"
                style={{ fontSize: 'var(--text-xs)', color: 'var(--ink-muted)' }}
              >
                {t('signIn.pinHint')}
              </p>
            </div>

            {error && (
              // role="alert" so a screen reader announces it without the user
              // having to hunt for what changed.
              <p
                role="alert"
                className="rounded-lg px-3 py-2"
                style={{
                  background: 'var(--rust-tint)',
                  color: 'var(--rust)',
                  fontSize: 'var(--text-sm)',
                }}
              >
                {error}
              </p>
            )}

            <button
              type="submit"
              disabled={busy}
              className="w-full rounded-lg py-3 font-medium disabled:opacity-60"
              style={{ background: 'var(--primary)', color: 'var(--primary-ink)' }}
            >
              {busy
                ? t('signIn.submitting')
                : signingUp
                  ? t('signIn.signUpSubmit')
                  : t('signIn.submit')}
            </button>

            <button
              type="button"
              onClick={() => {
                setSigningUp((v) => !v);
                setError('');
              }}
              className="w-full py-2"
              style={{ fontSize: 'var(--text-sm)', color: 'var(--ink-muted)' }}
            >
              {signingUp ? t('signIn.haveAccount') : t('signIn.needAccount')}
            </button>
          </form>
        </div>
      </div>
    </div>
  );
}

function messageFor(err: unknown, t: TFunction): string {
  if (!(err instanceof api.ApiError)) return t('signIn.errors.unknown');
  switch (err.status) {
    case 0:
      return t('signIn.errors.offline');
    case 401:
      return t('signIn.errors.rejected');
    case 409:
      return t('signIn.errors.idTaken');
    case 422:
      return t('signIn.errors.weakPin');
    case 423:
      return t('signIn.errors.lockedHard');
    case 429:
      return t('signIn.errors.lockedSoft', { seconds: err.retryAfter ?? 60 });
    default:
      return t('signIn.errors.unknown');
  }
}
