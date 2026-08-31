/**
 * Connection and queue state, shown only when it matters.
 *
 * Silent when online with an empty queue — a permanent "you are connected"
 * badge is noise that trains people to ignore the bar entirely. It appears
 * when there is something a person should know: no signal, or work waiting to
 * go out.
 *
 * The tone is deliberately reassuring rather than alarming. Nothing is lost
 * when the network drops; that is the entire promise of the outbox, and the
 * copy should say so instead of implying failure.
 */

import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';

import { onOutboxChange } from '../lib/outbox';

export function OutboxBanner() {
  const { t } = useTranslation();
  const [pending, setPending] = useState(0);
  const [online, setOnline] = useState(navigator.onLine);

  useEffect(() => {
    const unsubscribe = onOutboxChange(setPending);
    const up = () => setOnline(true);
    const down = () => setOnline(false);
    window.addEventListener('online', up);
    window.addEventListener('offline', down);
    return () => {
      unsubscribe();
      window.removeEventListener('online', up);
      window.removeEventListener('offline', down);
    };
  }, []);

  if (online && pending === 0) return null;

  const offline = !online;
  const message = offline
    ? pending > 0
      ? t('outbox.offline', { count: pending })
      : t('outbox.offlineNoQueue')
    : t('outbox.syncing', { count: pending });

  return (
    <div
      role="status"
      aria-live="polite"
      className="px-4 py-1.5 text-center"
      style={{
        background: offline ? 'var(--amber-tint)' : 'var(--accent-quiet)',
        color: offline ? 'var(--amber)' : 'var(--ink)',
        fontSize: 'var(--text-xs)',
      }}
    >
      {message}
    </div>
  );
}
