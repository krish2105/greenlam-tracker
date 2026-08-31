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
import { BrandLockup } from './BrandLockup';
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

    setBusy(true);
    setError('');
    try {
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
            <BrandLockup size={92} />
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
              {busy ? t('signIn.submitting') : t('signIn.submit')}
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
    case 423:
      return t('signIn.errors.lockedHard');
    case 429:
      return t('signIn.errors.lockedSoft', { seconds: err.retryAfter ?? 60 });
    default:
      return t('signIn.errors.unknown');
  }
}
