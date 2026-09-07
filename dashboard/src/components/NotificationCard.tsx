/**
 * Turning notifications on, and explaining the one case where you cannot.
 *
 * WHY THIS IS NOT JUST A SWITCH
 *
 * On an iPhone in a Safari tab there is nothing to switch. The push APIs are
 * absent — not denied, absent — because iOS delivers Web Push only to a PWA
 * added to the Home Screen. A disabled toggle there tells somebody the feature
 * is broken; what they need is the two-step instruction that fixes it.
 *
 * That matters more here than in most apps. The whole point of the maintenance
 * area is that a stopped machine makes phones buzz, and a technician on an
 * iPhone who never adds the app to their Home Screen is never alerted, ever,
 * without anything appearing to go wrong.
 *
 * Only shown to people who would actually be notified. Somebody who only logs
 * production gets no pushes, so offering them the switch is asking a question
 * whose answer changes nothing.
 */

import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';

import * as push from '../lib/push';

export function NotificationCard() {
  const { t } = useTranslation();

  const [support, setSupport] = useState<push.PushSupport>('unsupported');
  const [available, setAvailable] = useState(false);
  const [on, setOn] = useState(false);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState('');

  useEffect(() => {
    setSupport(push.pushSupport());
    void import('../lib/api').then(({ pushStatus }) =>
      pushStatus()
        .then((s) => setAvailable(s.enabled))
        .catch(() => setAvailable(false)),
    );
    void push.isSubscribedHere().then(setOn);
  }, []);

  // The plant has not generated VAPID keys. Nothing to offer, and saying
  // "notifications are unavailable" to an operator who cannot act on it is
  // noise on a screen that should be short.
  if (!available) return null;

  async function toggle() {
    setBusy(true);
    setNote('');
    try {
      if (on) {
        await push.disablePush();
        setOn(false);
      } else {
        const ok = await push.enablePush();
        setOn(ok);
        // Declining is a normal answer. It gets a plain sentence, not an error.
        if (!ok) setNote(t('notify.declined'));
      }
    } catch {
      setNote(t('notify.failed'));
    } finally {
      setBusy(false);
    }
  }

  const card = {
    borderColor: 'var(--line)',
    background: 'var(--surface)',
  } as const;

  if (support === 'needs-home-screen') {
    return (
      <section className="arch mt-6 border px-4 py-3" style={card}>
        <h2 className="font-semibold" style={{ color: 'var(--ink)' }}>
          {t('notify.iosTitle')}
        </h2>
        <p className="mt-1" style={{ color: 'var(--ink-muted)', fontSize: 'var(--text-sm)' }}>
          {t('notify.iosBody')}
        </p>
        <ol
          className="mt-2 list-decimal space-y-1 pl-5"
          style={{ color: 'var(--ink)', fontSize: 'var(--text-sm)' }}
        >
          <li>{t('notify.iosStep1')}</li>
          <li>{t('notify.iosStep2')}</li>
          <li>{t('notify.iosStep3')}</li>
        </ol>
      </section>
    );
  }

  if (support === 'unsupported') return null;

  return (
    <section className="arch mt-6 border px-4 py-3" style={card}>
      <div className="flex items-baseline justify-between gap-3">
        <div>
          <h2 className="font-semibold" style={{ color: 'var(--ink)' }}>
            {t('notify.title')}
          </h2>
          <p className="mt-1" style={{ color: 'var(--ink-muted)', fontSize: 'var(--text-sm)' }}>
            {on ? t('notify.onBody') : t('notify.offBody')}
          </p>
        </div>
      </div>

      {support === 'denied' ? (
        // Only the person can undo this, in their phone's settings. A button
        // here would call requestPermission(), which returns "denied" without
        // showing anything — a button that visibly does nothing.
        <p className="mt-2" style={{ color: 'var(--rust)', fontSize: 'var(--text-sm)' }}>
          {t('notify.blocked')}
        </p>
      ) : (
        <button
          type="button"
          onClick={() => void toggle()}
          disabled={busy}
          aria-pressed={on}
          className="arch mt-3 w-full border py-3 font-medium disabled:opacity-60"
          style={{
            borderColor: on ? 'var(--line-strong)' : 'var(--accent)',
            background: on ? 'var(--surface)' : 'var(--accent-quiet)',
            color: 'var(--ink)',
          }}
        >
          {busy ? t('notify.working') : on ? t('notify.turnOff') : t('notify.turnOn')}
        </button>
      )}

      {note && (
        <p className="mt-2" style={{ color: 'var(--ink-muted)', fontSize: 'var(--text-sm)' }}>
          {note}
        </p>
      )}
    </section>
  );
}
