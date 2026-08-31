/**
 * Every machine, both halves of its story on one row.
 *
 * THE QUESTION THIS ANSWERS
 *
 * A machine can top the board for two completely different reasons: it stops
 * a lot, or it makes scrap. The fix, the owner and the budget are different in
 * each case — a bearing programme versus a process change — and until this
 * table existed a reader had to hold numbers from four separate charts in
 * their head to tell them apart.
 *
 * IMPREGNATORS GET DIFFERENT COLUMNS, NOT EMPTY ONES
 *
 * They do not press sheets, so they have no reject rate. Showing 0% would read
 * as perfect. Their quality signal is the spec window instead, so the row
 * switches to RC, VC and how often that line ran out of spec.
 *
 * SORTED BY DOWNTIME, WITH SCRAP VISIBLE BESIDE IT
 *
 * Not by a blended "score". Any single ranking of two different failure modes
 * hides the thing the reader came for, and invites an argument about the
 * weighting instead of about the machine.
 */

import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';

import * as api from '../../lib/api';
import { useSectionName } from '../../lib/masterNames';
import { SEQ_COLOURS, formatHours, rampColour } from '../charts/primitives';

type Mode = 'press' | 'impregnation';

export function MachinePerformancePanel({
  days,
  basis,
}: {
  days: number;
  basis: string | undefined;
}) {
  const { t } = useTranslation();
  const sectionName = useSectionName();
  const [rows, setRows] = useState<api.MachinePerformanceRow[]>([]);
  const [quality, setQuality] = useState<api.RollQuality | null>(null);
  const [mode, setMode] = useState<Mode>('press');

  useEffect(() => {
    void api.machinePerformance(days).then(setRows).catch(() => setRows([]));
    void api.rollQuality(days).then(setQuality).catch(() => setQuality(null));
  }, [days]);

  const shown = useMemo(
    () =>
      rows.filter((r) => (mode === 'impregnation' ? r.rolls > 0 : r.produced > 0 || r.rolls === 0)),
    [rows, mode],
  );

  if (rows.length === 0) return null;

  const worstDown = Math.max(...shown.map((r) => r.downtime_minutes), 1);
  const worstReject = Math.max(...shown.map((r) => r.reject_percent ?? 0), 0.1);

  return (
    <section aria-labelledby="machine-perf" className="space-y-4">
      <h2
        id="machine-perf"
        className="register-rule flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1 pb-1 font-semibold"
        style={{ fontSize: 'var(--text-sm)', color: 'var(--ink)' }}
      >
        <span>{t('perf.title')}</span>
        {/* Two views rather than one table with half its columns blank. */}
        <span
          role="radiogroup"
          aria-label={t('perf.title')}
          className="inline-flex rounded-full border p-0.5"
          style={{ borderColor: 'var(--line)', background: 'var(--surface-muted)' }}
        >
          {(['press', 'impregnation'] as Mode[]).map((m) => (
            <button
              key={m}
              type="button"
              role="radio"
              aria-checked={mode === m}
              onClick={() => setMode(m)}
              className="rounded-full px-3 py-1 font-medium"
              style={{
                fontSize: 'var(--text-xs)',
                background: mode === m ? 'var(--surface)' : 'transparent',
                color: mode === m ? 'var(--ink)' : 'var(--ink-muted)',
                boxShadow: mode === m ? 'var(--shadow)' : undefined,
              }}
            >
              {t(`perf.${m}`)}
            </button>
          ))}
        </span>
      </h2>

      {/* The finding, when there is enough data to stand behind it. */}
      {mode === 'impregnation' && quality && quality.linked_runs > 0 && (
        <div
          className="arch lift border px-4 py-3.5"
          style={{
            borderColor: quality.enough_data ? 'var(--amber)' : 'var(--line)',
            borderLeftWidth: '4px',
            background: 'var(--surface)',
          }}
        >
          <p className="font-semibold" style={{ color: 'var(--ink)' }}>
            {t('perf.rollFinding')}
          </p>
          {quality.in_spec_reject_percent !== null &&
          quality.out_of_spec_reject_percent !== null ? (
            <>
              <p className="tabular mt-1" style={{ color: 'var(--ink)' }}>
                {t('perf.rollComparison', {
                  inSpec: quality.in_spec_reject_percent,
                  outSpec: quality.out_of_spec_reject_percent,
                  lift: quality.lift_percent ?? 0,
                })}
              </p>
              <p
                className="mt-1.5"
                style={{ fontSize: 'var(--text-xs)', color: 'var(--ink-muted)' }}
              >
                {/* Say plainly when the sample is too thin. A two-roll
                    coincidence must not become a slide. */}
                {quality.enough_data
                  ? t('perf.rollCaveat', { runs: quality.linked_runs })
                  : t('perf.rollThin')}
              </p>
            </>
          ) : (
            <p className="mt-1" style={{ color: 'var(--ink-muted)' }}>
              {t('perf.rollNoLink')}
            </p>
          )}
        </div>
      )}

      <div className="scroll overflow-x-auto">
        <table className="w-full" style={{ fontSize: 'var(--text-sm)', minWidth: '38rem' }}>
          <thead>
            <tr style={{ color: 'var(--ink-muted)' }}>
              <th scope="col" className="py-1.5 pr-3 text-left">
                {t('chart.machine')}
              </th>
              <th scope="col" className="py-1.5 pr-3 text-right">
                {t('chart.downtime')}
              </th>
              <th scope="col" className="py-1.5 pr-3 text-right">
                {t('perf.breakdowns')}
              </th>
              <th scope="col" className="py-1.5 pr-3 text-right">
                MTBF
              </th>
              {mode === 'press' ? (
                <>
                  <th scope="col" className="py-1.5 pr-3 text-right">
                    {t('production.produced')}
                  </th>
                  <th scope="col" className="py-1.5 text-right">
                    {t('production.rejectRate')}
                  </th>
                </>
              ) : (
                <>
                  <th scope="col" className="py-1.5 pr-3 text-right">
                    {t('perf.rolls')}
                  </th>
                  <th scope="col" className="py-1.5 pr-3 text-right">
                    {t('perf.avgVc')}
                  </th>
                  <th scope="col" className="py-1.5 text-right">
                    {t('perf.offSpec')}
                  </th>
                </>
              )}
            </tr>
          </thead>
          <tbody>
            {shown.map((r, i) => (
              <tr key={r.machine_id} style={{ borderTop: '1px solid var(--line)' }}>
                <td className="py-2 pr-3">
                  <span className="font-medium" style={{ color: 'var(--ink)' }}>
                    {r.machine_code}
                  </span>
                  <span
                    className="ml-2"
                    style={{ fontSize: 'var(--text-xs)', color: 'var(--ink-muted)' }}
                  >
                    {sectionName(r.section_name)}
                  </span>
                </td>
                <td className="py-2 pr-3 text-right">
                  <span className="tabular" style={{ color: 'var(--ink)' }}>
                    {formatHours(r.downtime_minutes)}
                  </span>
                  {/* A bar in the cell, so the spread reads without arithmetic. */}
                  <span
                    aria-hidden="true"
                    className="mt-1 block h-1 rounded-full"
                    style={{
                      background: 'var(--viz-track)',
                    }}
                  >
                    <span
                      className="block h-full rounded-full"
                      style={{
                        width: `${Math.max(2, (r.downtime_minutes / worstDown) * 100)}%`,
                        background: rampColour(SEQ_COLOURS, Math.min(4, i)),
                      }}
                    />
                  </span>
                </td>
                <td className="tabular py-2 pr-3 text-right" style={{ color: 'var(--ink-muted)' }}>
                  {r.breakdowns}
                </td>
                <td className="tabular py-2 pr-3 text-right" style={{ color: 'var(--ink-muted)' }}>
                  {r.mtbf_hours ? `${r.mtbf_hours}h` : '—'}
                </td>
                {mode === 'press' ? (
                  <>
                    <td
                      className="tabular py-2 pr-3 text-right"
                      style={{ color: 'var(--ink-muted)' }}
                    >
                      {r.produced ? r.produced.toLocaleString('en-IN') : '—'}
                    </td>
                    <td className="tabular py-2 text-right">
                      {r.reject_percent === null ? (
                        <span style={{ color: 'var(--ink-muted)' }}>—</span>
                      ) : (
                        <span
                          style={{
                            color:
                              r.reject_percent >= worstReject * 0.95
                                ? 'var(--clay-2)'
                                : 'var(--ink)',
                            fontWeight: r.reject_percent >= worstReject * 0.95 ? 600 : 400,
                          }}
                        >
                          {r.reject_percent}%
                        </span>
                      )}
                    </td>
                  </>
                ) : (
                  <>
                    <td
                      className="tabular py-2 pr-3 text-right"
                      style={{ color: 'var(--ink-muted)' }}
                    >
                      {r.rolls}
                    </td>
                    <td className="tabular py-2 pr-3 text-right" style={{ color: 'var(--ink)' }}>
                      {r.avg_vc ?? '—'}
                    </td>
                    <td className="tabular py-2 text-right">
                      <span
                        style={{
                          color: r.out_of_spec_rolls > 0 ? 'var(--clay-2)' : 'var(--ink-muted)',
                          fontWeight: r.out_of_spec_rolls > 0 ? 600 : 400,
                        }}
                      >
                        {r.out_of_spec_rolls}
                      </span>
                      {r.rolls > 0 && r.out_of_spec_rolls > 0 && (
                        <span
                          className="ml-1"
                          style={{ fontSize: 'var(--text-xs)', color: 'var(--ink-muted)' }}
                        >
                          ({Math.round((100 * r.out_of_spec_rolls) / r.rolls)}%)
                        </span>
                      )}
                    </td>
                  </>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <p style={{ fontSize: 'var(--text-xs)', color: 'var(--ink-muted)' }}>
        {t(basis === 'scheduled' ? 'perf.scheduledNote' : 'perf.calendarNote')}
      </p>

      {/* Colour is never the only cue: the worst reject rate is bold as well as
          clay, and the out-of-spec count carries its own percentage. */}
      <span className="sr-only">{t('perf.srSummary', { count: shown.length })}</span>
    </section>
  );
}
