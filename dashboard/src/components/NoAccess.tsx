/**
 * The screen for an account that can sign in and do nothing (V5 §3).
 *
 * WHY THIS EXISTS RATHER THAN A FAILED LOGIN
 *
 * A new signup could have been refused at the door until an admin approved it.
 * That would be indistinguishable from a wrong PIN, so the person would try
 * again, and again, until the graduated lockout in `security.py` caught them —
 * and then somebody would have to unlock an account that was never at fault.
 *
 * Signing in and being told plainly what is happening is the only version that
 * does not generate a support call on day one.
 *
 * It also serves the other empty account: one whose access was deliberately
 * revoked. The two need different words — one is waiting for a decision, the
 * other has had one — and `approved_at` is what tells them apart.
 */

import { useTranslation } from 'react-i18next';

import { ArchMark } from './ArchMark';

export function NoAccess({ name, pending }: { name: string; pending: boolean }) {
  const { t } = useTranslation();

  return (
    <div className="mx-auto flex max-w-md flex-col items-center px-4 py-16 text-center">
      <ArchMark size={56} />
      <h1
        className="mt-6 font-semibold"
        style={{ fontSize: 'var(--text-xl)', color: 'var(--ink)' }}
      >
        {pending ? t('noAccess.pendingTitle', { name }) : t('noAccess.revokedTitle')}
      </h1>
      <p className="mt-3" style={{ color: 'var(--ink-muted)' }}>
        {pending ? t('noAccess.pendingBody') : t('noAccess.revokedBody')}
      </p>
      {/* No retry button. There is nothing this person can do from here, and a
          button that only ever reloads the same screen reads as a fault. */}
      <p className="mt-6" style={{ color: 'var(--ink-muted)', fontSize: 'var(--text-sm)' }}>
        {t('noAccess.hint')}
      </p>
    </div>
  );
}
