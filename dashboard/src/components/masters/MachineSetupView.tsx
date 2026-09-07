/**
 * The three answers the plant owes the system.
 *
 * WHY THIS SCREEN EXISTS
 *
 * Three columns have been on the machines table since the beginning, holding
 * NULL, and every figure they unlock has been switched off with a message
 * saying so. `hourly_downtime_cost` was worse than unused — nothing in the
 * codebase read it at all. This is where they get filled in, and the moment
 * they are, the dashboard stops apologising and starts answering.
 *
 *   Hourly cost      -> a rupee figure for downtime
 *   Scheduled hours  -> real availability instead of calendar
 *   Criticality      -> differentiated response targets
 *
 * ALL OR NOTHING, AND THE PROGRESS BAR SAYS WHICH
 *
 * A cost total covering 9 of 42 machines looks complete and is silently low —
 * so the server withholds it entirely until every machine that went down has a
 * rate. That is the right call and a frustrating one if the screen does not
 * show how far off you are, hence the counters at the top.
 *
 * BULK FILL IS NOT A CONVENIENCE
 *
 * 42 machines times three fields is 126 boxes, and most of a plant shares one
 * schedule. Without "apply to all" this screen gets abandoned halfway, which
 * leaves the system in the exact partial state that shows nothing. The tedium
 * is the failure mode.
 *
 * SAVES ON BLUR, PER FIELD
 *
 * No Save button. Somebody working down a column of 33 rows should not have to
 * remember a final click, and a PATCH per field means a half-finished session
 * still keeps what was typed.
 */

import { useCallback, useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';

import * as api from '../../lib/api';
import { useSectionName } from '../../lib/masterNames';

type Field = 'hourly_downtime_cost' | 'scheduled_hours_per_day' | 'criticality';

const CRITICALITY = ['A', 'B', 'C'] as const;

export function MachineSetupView() {
  const { t } = useTranslation();
  const sectionName = useSectionName();
  const [rows, setRows] = useState<api.MachineSetup[]>([]);
  const [saving, setSaving] = useState<string | null>(null);
  const [error, setError] = useState('');
  const [bulk, setBulk] = useState({ cost: '', hours: '' });

  const load = useCallback(() => {
    void api
      .machineSetup()
      .then(setRows)
      .catch(() => setRows([]));
  }, []);

  useEffect(load, [load]);

  const progress = useMemo(
    () => ({
      priced: rows.filter((r) => r.hourly_downtime_cost !== null).length,
      scheduled: rows.filter((r) => r.scheduled_hours_per_day !== null).length,
      total: rows.length,
    }),
    [rows],
  );

  async function save(id: number, field: Field, raw: string) {
    const key = `${id}:${field}`;
    setSaving(key);
    setError('');
    try {
      const value =
        field === 'criticality' ? raw || null : raw.trim() === '' ? null : Number(raw);
      const updated = await api.updateMachineSetup(id, { [field]: value });
      setRows((prev) => prev.map((r) => (r.id === id ? updated : r)));
    } catch (e) {
      setError(e instanceof api.ApiError ? e.message : t('setup.saveFailed'));
      // Put the row back to what the server actually holds, so a rejected
      // value does not sit on screen looking accepted.
      load();
    } finally {
      setSaving(null);
    }
  }

  async function applyToAll(field: Field, raw: string) {
    if (!raw.trim()) return;
    setError('');
    // Sequential, not Promise.all. Thirty-three parallel PATCHes on a free
    // instance is how you turn a convenience into a timeout.
    for (const row of rows) {
      try {
        await api.updateMachineSetup(row.id, { [field]: Number(raw) });
      } catch {
        /* keep going — one rejected row must not abandon the other 32 */
      }
    }
    load();
  }

  const cell = {
    borderColor: 'var(--line-strong)',
    background: 'var(--surface)',
    color: 'var(--ink)',
  } as const;

  const Bar = ({ done, total, label }: { done: number; total: number; label: string }) => (
    <div>
      <p className="flex items-baseline justify-between gap-2">
        <span style={{ fontSize: 'var(--text-sm)', color: 'var(--ink)' }}>{label}</span>
        <span className="tabular" style={{ fontSize: 'var(--text-sm)', color: 'var(--ink-muted)' }}>
          {done} / {total}
        </span>
      </p>
      <span
        aria-hidden="true"
        className="mt-1 block h-1.5 w-full overflow-hidden rounded-full"
        style={{ background: 'var(--viz-track)' }}
      >
        <span
          className="block h-full rounded-full"
          style={{
            width: `${total ? (100 * done) / total : 0}%`,
            background: done === total && total > 0 ? 'var(--viz-1)' : 'var(--amber)',
            transition: 'width 200ms ease-out',
          }}
        />
      </span>
    </div>
  );

  return (
    <div className="space-y-6 pb-12">
      <header>
        <h1 className="font-semibold" style={{ fontSize: 'var(--text-xl)', color: 'var(--ink)' }}>
          {t('setup.title')}
        </h1>
        <p className="mt-1" style={{ color: 'var(--ink-muted)' }}>
          {t('setup.subtitle')}
        </p>
      </header>

      {/* How far from switching the held-back numbers on. */}
      <section
        className="arch grid gap-4 border px-4 py-3.5 sm:grid-cols-2"
        style={{ borderColor: 'var(--line)', background: 'var(--surface)' }}
      >
        <Bar done={progress.priced} total={progress.total} label={t('setup.pricedLabel')} />
        <Bar
          done={progress.scheduled}
          total={progress.total}
          label={t('setup.scheduledLabel')}
        />
        <p
          className="sm:col-span-2"
          style={{ fontSize: 'var(--text-xs)', color: 'var(--ink-muted)' }}
        >
          {t('setup.allOrNothing')}
        </p>
      </section>

      {/* Bulk fill. Most of a plant shares one schedule, and 99 boxes is how
          this screen gets abandoned halfway — which leaves exactly the partial
          state that shows nothing. */}
      <section
        aria-labelledby="bulk"
        className="arch border px-4 py-3.5"
        style={{ borderColor: 'var(--line)', background: 'var(--surface)' }}
      >
        <h2
          id="bulk"
          className="font-semibold"
          style={{ fontSize: 'var(--text-sm)', color: 'var(--ink)' }}
        >
          {t('setup.bulkTitle')}
        </h2>
        <div className="mt-3 grid gap-3 sm:grid-cols-2">
          {(
            [
              ['cost', 'hourly_downtime_cost', t('setup.cost')],
              ['hours', 'scheduled_hours_per_day', t('setup.hours')],
            ] as const
          ).map(([key, field, label]) => (
            <div key={key} className="flex items-end gap-2">
              <div className="flex-1">
                <label
                  htmlFor={`bulk-${key}`}
                  className="mb-1 block font-medium"
                  style={{ fontSize: 'var(--text-sm)', color: 'var(--ink)' }}
                >
                  {label}
                </label>
                <input
                  id={`bulk-${key}`}
                  type="text"
                  inputMode="decimal"
                  value={bulk[key]}
                  onChange={(e) => setBulk((p) => ({ ...p, [key]: e.target.value }))}
                  className="arch w-full border px-3 py-2.5"
                  style={cell}
                />
              </div>
              <button
                type="button"
                onClick={() => void applyToAll(field, bulk[key])}
                disabled={!bulk[key].trim()}
                className="arch min-h-[42px] border px-3 font-medium disabled:opacity-40"
                style={{
                  fontSize: 'var(--text-sm)',
                  borderColor: 'var(--line-strong)',
                  color: 'var(--ink)',
                }}
              >
                {t('setup.applyAll')}
              </button>
            </div>
          ))}
        </div>
        <p className="mt-2" style={{ fontSize: 'var(--text-xs)', color: 'var(--ink-muted)' }}>
          {t('setup.bulkNote')}
        </p>
      </section>

      {error && (
        <p
          role="alert"
          className="arch px-3 py-2"
          style={{ background: 'var(--rust-tint)', color: 'var(--rust)' }}
        >
          {error}
        </p>
      )}

      <div className="overflow-x-auto">
        <table className="w-full" style={{ fontSize: 'var(--text-sm)', minWidth: '40rem' }}>
          <caption className="sr-only">{t('setup.title')}</caption>
          <thead>
            <tr style={{ color: 'var(--ink-muted)' }}>
              <th scope="col" className="py-1.5 pr-3 text-left">
                {t('chart.machine')}
              </th>
              <th scope="col" className="py-1.5 pr-3 text-left">
                {t('setup.cost')}
              </th>
              <th scope="col" className="py-1.5 pr-3 text-left">
                {t('setup.hours')}
              </th>
              <th scope="col" className="py-1.5 text-left">
                {t('setup.criticality')}
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.id} style={{ borderTop: '1px solid var(--line)' }}>
                <td className="py-2 pr-3">
                  <span className="font-medium" style={{ color: 'var(--ink)' }}>
                    {row.code}
                  </span>
                  <span
                    className="ml-2"
                    style={{ fontSize: 'var(--text-xs)', color: 'var(--ink-muted)' }}
                  >
                    {sectionName(row.section_name)}
                  </span>
                </td>
                <td className="py-1.5 pr-3">
                  <input
                    type="text"
                    inputMode="decimal"
                    aria-label={`${t('setup.cost')} — ${row.code}`}
                    defaultValue={row.hourly_downtime_cost ?? ''}
                    onBlur={(e) =>
                      void save(row.id, 'hourly_downtime_cost', e.target.value)
                    }
                    className="arch w-28 border px-2 py-1.5"
                    style={{
                      ...cell,
                      borderColor:
                        saving === `${row.id}:hourly_downtime_cost`
                          ? 'var(--accent)'
                          : cell.borderColor,
                    }}
                  />
                </td>
                <td className="py-1.5 pr-3">
                  <input
                    type="text"
                    inputMode="decimal"
                    aria-label={`${t('setup.hours')} — ${row.code}`}
                    defaultValue={row.scheduled_hours_per_day ?? ''}
                    onBlur={(e) =>
                      void save(row.id, 'scheduled_hours_per_day', e.target.value)
                    }
                    className="arch w-20 border px-2 py-1.5"
                    style={cell}
                  />
                </td>
                <td className="py-1.5">
                  <select
                    aria-label={`${t('setup.criticality')} — ${row.code}`}
                    value={row.criticality}
                    onChange={(e) => void save(row.id, 'criticality', e.target.value)}
                    className="arch border px-2 py-1.5"
                    style={cell}
                  >
                    {CRITICALITY.map((c) => (
                      <option key={c} value={c}>
                        {t(`setup.crit${c}`)}
                      </option>
                    ))}
                  </select>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <p style={{ fontSize: 'var(--text-xs)', color: 'var(--ink-muted)' }}>
        {t('setup.savedNote')}
      </p>
    </div>
  );
}
