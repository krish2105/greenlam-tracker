/**
 * The filters the three dashboards sit on (V5 §11.1).
 *
 * WHY THIS IS ONE BAR AND NOT NINE REPORTS
 *
 * The spec is explicit about the alternative: "rather than building a separate
 * fixed report for every combination you might want — day-wise, time-wise, one
 * machine, all machines of a type, HPL-only, Maintenance-only, combined". That
 * list has no end. Somebody always wants morning shift on Press 4 last week,
 * and then the same thing for the impregnators, and each one arrives as a
 * ticket. Independent filters that combine freely answer all of them at once.
 *
 * WHAT EACH CONTROL IS ACTUALLY FOR
 *
 *   Machine type   every unit in a category at once — all twelve impregnators
 *   Machine        one named unit, when the argument is about Press 4
 *   Shift          Shift 1 vs Shift 2, the comparison managers make weekly
 *   Time of day    morning against night, which is *not* the same question:
 *                  shifts move with the roster, hours do not
 *   Load No.       one load, every stage it passed through (§6.2A)
 *
 * WHY LOAD NO. IS NOT ALWAYS SHOWN
 *
 * It only exists on production rows. On the maintenance view it would be a
 * control that empties the screen and explains nothing — a breakdown is raised
 * against a machine, never against a load.
 *
 * WHY THE HOUR WINDOW IS A PAIR OF PICKERS AND NOT A SLIDER
 *
 * This is read on a laptop, but it is also read on a phone in a corridor
 * between meetings. A two-handled range slider on a touch screen is a fiddly
 * way to say "22:00 to 06:00", and it cannot be operated from a keyboard
 * without inventing key handling. Two selects say the same thing and are
 * accessible for free.
 */

import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';

import { localName } from '@greenlam/core';

import * as api from '../../lib/api';

/** Which of the three dashboards is on screen. V5 §11.1 calls this "Module". */
export type BoardModule = 'maintenance' | 'production' | 'combined';

const HOURS = Array.from({ length: 24 }, (_, h) => h);

function hourLabel(h: number): string {
  return `${String(h).padStart(2, '0')}:00`;
}

export function FilterBar({
  module,
  filters,
  onChange,
}: {
  module: BoardModule;
  filters: api.BoardFilters;
  onChange: (next: api.BoardFilters) => void;
}) {
  const { t, i18n } = useTranslation();

  const [sections, setSections] = useState<api.Section[]>([]);
  const [machines, setMachines] = useState<api.Machine[]>([]);
  const [shifts, setShifts] = useState<api.Shift[]>([]);
  // Typing a load number should not fire a request per keystroke against a
  // free-tier instance. Held locally, applied on submit.
  const [loadDraft, setLoadDraft] = useState(filters.load_no ?? '');

  useEffect(() => {
    void Promise.all([
      api.listSections().catch(() => []),
      api.listMachines().catch(() => []),
      api.listShifts().catch(() => []),
    ]).then(([s, m, sh]) => {
      setSections(s);
      setMachines(m);
      setShifts(sh);
    });
  }, []);

  useEffect(() => {
    setLoadDraft(filters.load_no ?? '');
  }, [filters.load_no]);

  function set(patch: Partial<api.BoardFilters>) {
    onChange({ ...filters, ...patch });
  }

  // Picking a machine type and then a machine from a different type is a
  // contradiction that returns nothing and looks like a bug. Narrowing the
  // machine list is the cheaper fix than explaining the empty result.
  const machineOptions = filters.section_id
    ? machines.filter((m) => m.section_id === filters.section_id)
    : machines;

  const active =
    (filters.section_id ? 1 : 0) +
    (filters.machine_id ? 1 : 0) +
    (filters.shift_id ? 1 : 0) +
    (filters.hour_from != null ? 1 : 0) +
    (filters.load_no ? 1 : 0);

  const field = {
    fontSize: 'var(--text-sm)',
    borderColor: 'var(--line-strong)',
    background: 'var(--surface)',
    color: 'var(--ink)',
  } as const;

  return (
    <section
      aria-label={t('filters.title')}
      className="arch border px-3 py-3"
      style={{ borderColor: 'var(--line)', background: 'var(--surface-muted)' }}
    >
      <div className="flex flex-wrap items-end gap-3">
        <Field id="f-section" label={t('filters.machineType')}>
          <select
            id="f-section"
            value={filters.section_id ?? ''}
            onChange={(e) =>
              set({
                section_id: e.target.value ? Number(e.target.value) : null,
                // The old machine almost certainly belongs to another type.
                machine_id: null,
              })
            }
            className="arch border px-2.5 py-2"
            style={field}
          >
            <option value="">{t('filters.allTypes')}</option>
            {sections.map((s) => (
              <option key={s.id} value={s.id}>
                {localName(s, i18n.language)}
              </option>
            ))}
          </select>
        </Field>

        <Field id="f-machine" label={t('filters.machine')}>
          <select
            id="f-machine"
            value={filters.machine_id ?? ''}
            onChange={(e) => set({ machine_id: e.target.value ? Number(e.target.value) : null })}
            className="arch border px-2.5 py-2"
            style={field}
          >
            <option value="">{t('filters.allMachines')}</option>
            {machineOptions.map((m) => (
              <option key={m.id} value={m.id}>
                {m.code}
              </option>
            ))}
          </select>
        </Field>

        {shifts.length > 0 && (
          <Field id="f-shift" label={t('filters.shift')}>
            <select
              id="f-shift"
              value={filters.shift_id ?? ''}
              onChange={(e) => set({ shift_id: e.target.value ? Number(e.target.value) : null })}
              className="arch border px-2.5 py-2"
              style={field}
            >
              <option value="">{t('filters.allShifts')}</option>
              {shifts.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </select>
          </Field>
        )}

        {/* Hours apply to when a breakdown was *raised*, so they are a
            maintenance question. Production is logged per shift for a whole
            day and carries no clock time to filter on. */}
        {module !== 'production' && (
          <Field id="f-hour-from" label={t('filters.timeOfDay')}>
            <div className="flex items-center gap-1.5">
              <select
                id="f-hour-from"
                value={filters.hour_from ?? ''}
                onChange={(e) =>
                  set(
                    e.target.value
                      ? {
                          hour_from: Number(e.target.value),
                          // A window needs both ends. Defaulting the second to
                          // the end of the day beats a control that silently
                          // does nothing until you touch it twice.
                          hour_to: filters.hour_to ?? 23,
                        }
                      : { hour_from: null, hour_to: null },
                  )
                }
                className="arch border px-2.5 py-2"
                style={field}
              >
                <option value="">{t('filters.anyTime')}</option>
                {HOURS.map((h) => (
                  <option key={h} value={h}>
                    {hourLabel(h)}
                  </option>
                ))}
              </select>
              <span aria-hidden="true" style={{ color: 'var(--ink-muted)' }}>
                –
              </span>
              <label htmlFor="f-hour-to" className="sr-only">
                {t('filters.timeOfDayEnd')}
              </label>
              <select
                id="f-hour-to"
                value={filters.hour_to ?? ''}
                disabled={filters.hour_from == null}
                onChange={(e) => set({ hour_to: e.target.value ? Number(e.target.value) : null })}
                className="arch border px-2.5 py-2 disabled:opacity-50"
                style={field}
              >
                {HOURS.map((h) => (
                  <option key={h} value={h}>
                    {hourLabel(h)}
                  </option>
                ))}
              </select>
            </div>
          </Field>
        )}

        {module !== 'maintenance' && (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              set({ load_no: loadDraft.trim() || null });
            }}
          >
            <Field id="f-load" label={t('filters.loadNo')}>
              <div className="flex gap-1.5">
                <input
                  id="f-load"
                  value={loadDraft}
                  onChange={(e) => setLoadDraft(e.target.value)}
                  onBlur={() => set({ load_no: loadDraft.trim() || null })}
                  placeholder={t('filters.loadNoPlaceholder')}
                  autoComplete="off"
                  className="arch w-32 border px-2.5 py-2"
                  style={field}
                />
                <button
                  type="submit"
                  className="arch border px-3 py-2 font-medium"
                  style={{ ...field, borderColor: 'var(--accent)' }}
                >
                  {t('filters.apply')}
                </button>
              </div>
            </Field>
          </form>
        )}

        {active > 0 && (
          <button
            type="button"
            onClick={() => {
              setLoadDraft('');
              onChange({});
            }}
            className="arch px-3 py-2 font-medium underline-offset-2 hover:underline"
            style={{ fontSize: 'var(--text-sm)', color: 'var(--accent)' }}
          >
            {t('filters.clear', { count: active })}
          </button>
        )}
      </div>

      {/* Every number above and below this bar is now a subset. Saying so is
          the difference between a filtered board and a board that looks like
          the plant had a quiet month. */}
      {active > 0 && (
        <p className="mt-2" style={{ fontSize: 'var(--text-xs)', color: 'var(--ink-muted)' }}>
          {t('filters.narrowed')}
        </p>
      )}
    </section>
  );
}

function Field({
  id,
  label,
  children,
}: {
  id: string;
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <label
        htmlFor={id}
        className="mb-1 block font-medium"
        style={{ fontSize: 'var(--text-xs)', color: 'var(--ink-muted)' }}
      >
        {label}
      </label>
      {children}
    </div>
  );
}
