/**
 * Download the nightly workbook.
 *
 * WHY THIS EXISTS WHEN THE FILE IS ALSO SYNCED ELSEWHERE
 *
 * The same workbook is meant to land in a shared drive and arrive by email.
 * This is the third route, and the one with no dependencies: no cloud account,
 * no mailbox, no IT ticket. Somebody in a meeting who needs the numbers now
 * gets them now.
 *
 * THE AGE IS SHOWN BEFORE THE CLICK, NOT AFTER
 *
 * A dashboard that silently hands over a workbook built nine days ago is worse
 * than one that says so — the person carries it into a meeting believing it is
 * current. So the button always states when the file was built, and says
 * plainly when nothing has been built at all, which is a different problem
 * with a different fix.
 */

import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';

import * as api from '../../lib/api';

export function WorkbookDownload() {
  const { t, i18n } = useTranslation();
  const [status, setStatus] = useState<api.ExportStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const refresh = useCallback(() => {
    void api
      .exportStatus()
      .then(setStatus)
      .catch(() => setStatus(null));
  }, []);

  useEffect(refresh, [refresh]);

  async function download() {
    setBusy(true);
    setError('');
    try {
      await api.downloadWorkbook();
      refresh();
    } catch (e) {
      setError(e instanceof api.ApiError ? e.message : t('workbook.failed'));
    } finally {
      setBusy(false);
    }
  }

  // Absent status means the endpoint is unreachable — not that the file is
  // missing. Rendering nothing beats rendering a wrong claim about the file.
  if (status === null) return null;

  const when =
    status.built_at &&
    new Date(status.built_at).toLocaleString(i18n.language, {
      dateStyle: 'medium',
      timeStyle: 'short',
    });

  return (
    <section
      aria-labelledby="workbook"
      className="arch border px-4 py-3.5"
      style={{
        borderColor: status.stale ? 'var(--amber)' : 'var(--line)',
        borderLeftWidth: '4px',
        borderLeftColor: status.available
          ? status.stale
            ? 'var(--amber)'
            : 'var(--viz-1)'
          : 'var(--line-strong)',
        background: 'var(--surface)',
      }}
    >
      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
        <div className="min-w-0">
          <p id="workbook" className="font-semibold" style={{ color: 'var(--ink)' }}>
            {t('workbook.title')}
          </p>
          <p style={{ fontSize: 'var(--text-sm)', color: 'var(--ink-muted)' }}>
            {!status.available
              ? t('workbook.none')
              : status.stale
                ? t('workbook.stale', { when, hours: Math.round(status.hours_ago ?? 0) })
                : t('workbook.fresh', { when, size: status.size_kb ?? 0 })}
          </p>
        </div>

        <button
          type="button"
          onClick={() => void download()}
          disabled={!status.available || busy}
          className="arch flex min-h-[44px] shrink-0 items-center gap-2 px-4 font-semibold disabled:opacity-45"
          style={{ background: 'var(--accent)', color: 'var(--accent-ink)' }}
        >
          <svg
            width="17"
            height="17"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2.1"
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden="true"
          >
            <path d="M12 3v12M7 11l5 5 5-5M4 20h16" />
          </svg>
          {busy ? t('workbook.preparing') : t('workbook.download')}
        </button>
      </div>

      {error && (
        <p
          role="alert"
          className="mt-2"
          style={{ fontSize: 'var(--text-sm)', color: 'var(--rust)' }}
        >
          {error}
        </p>
      )}

      <p className="mt-2" style={{ fontSize: 'var(--text-xs)', color: 'var(--ink-muted)' }}>
        {t('workbook.note')}
      </p>
    </section>
  );
}
