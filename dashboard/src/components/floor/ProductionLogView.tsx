/**
 * What has already been logged today (V5 §6.4).
 *
 * WHY IT EXISTS
 *
 * The question it answers is asked at every handover: "has the last shift's
 * output gone in yet, or am I about to enter it twice?" Without a list, the
 * only way to find out is to enter it and see what the totals do.
 *
 * It is also the only place a production entry can be corrected. A ticket is
 * reachable from the breakdown board; an entry, once saved, had nowhere to be
 * opened from at all — so a mistyped sheet count was permanent in practice
 * however correctable it was in the API.
 *
 * Deliberately not a report. Today by default, one line per entry, the fields
 * somebody would recognise their own entry by. The analysis lives on the
 * dashboard, which this is not.
 */

import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';

import * as api from '../../lib/api';
import { CorrectProductionSheet } from './CorrectProductionSheet';

export function ProductionLogView() {
  const { t } = useTranslation();
  const [rows, setRows] = useState<api.ProductionRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [days, setDays] = useState(1);
  const [correcting, setCorrecting] = useState<api.ProductionRow | null>(null);

  const load = useCallback(() => {
    void api
      .listProduction(days)
      .then(setRows)
      .catch(() => setRows([]))
      .finally(() => setLoading(false));
  }, [days]);

  useEffect(load, [load]);

  const cell = { fontSize: 'var(--text-sm)', color: 'var(--ink)' } as const;

  return (
    <section className="mt-8">
      <div className="flex items-baseline justify-between">
        <h2 className="font-semibold" style={{ fontSize: 'var(--text-lg)', color: 'var(--ink)' }}>
          {t('productionLog.title')}
        </h2>
        <button
          type="button"
          onClick={() => setDays((d) => (d === 1 ? 7 : 1))}
          className="px-2 py-1"
          style={{ fontSize: 'var(--text-sm)', color: 'var(--ink-muted)' }}
        >
          {days === 1 ? t('productionLog.showWeek') : t('productionLog.showToday')}
        </button>
      </div>

      {loading ? (
        <p className="py-6" style={{ color: 'var(--ink-muted)' }}>{t('masters.loading')}</p>
      ) : rows.length === 0 ? (
        <p className="py-6" style={{ color: 'var(--ink-muted)' }}>{t('productionLog.empty')}</p>
      ) : (
        <ul className="mt-3 space-y-2">
          {rows.map((r) => (
            <li
              key={r.id}
              className="arch border px-3 py-3"
              style={{ borderColor: 'var(--line)', background: 'var(--surface)' }}
            >
              <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
                <span className="font-semibold" style={{ color: 'var(--ink)' }}>
                  {r.machine_code}
                </span>
                {r.load_no && <span className="plate">{r.load_no}</span>}
                {/* V5 §7: the mark travels with the record everywhere it is
                    shown, so a count nobody expected to move is never read as
                    the one that was logged at the time. */}
                {r.last_edited_at && (
                  <span
                    className="plate"
                    title={t('ticket.editedBy', { name: r.last_edited_by_name ?? '—' })}
                    style={{ borderColor: 'var(--rust)', color: 'var(--rust)' }}
                  >
                    {t('ticket.edited')}
                  </span>
                )}
                <span className="ml-auto tabular" style={cell}>
                  {t('productionLog.counts', {
                    produced: r.produced_qty,
                    rejected: r.rejected_qty,
                  })}
                </span>
              </div>
              <p className="mt-1" style={{ color: 'var(--ink-muted)', fontSize: 'var(--text-sm)' }}>
                {[r.log_date, r.shift_name, r.logged_by_name, r.reject_reason]
                  .filter(Boolean)
                  .join(' · ')}
              </p>
              <button
                type="button"
                onClick={() => setCorrecting(r)}
                className="mt-2 px-2 py-1"
                style={{ fontSize: 'var(--text-sm)', color: 'var(--ink-muted)' }}
              >
                {t('productionLog.correct')}
              </button>
            </li>
          ))}
        </ul>
      )}

      {correcting && (
        <CorrectProductionSheet
          row={correcting}
          onClose={() => setCorrecting(null)}
          onCorrected={() => {
            setCorrecting(null);
            load();
          }}
        />
      )}
    </section>
  );
}
