/**
 * Raise a breakdown. The thirty-second path.
 *
 * Everything optional has been removed from the first screen. Machine, what
 * is wrong — submit. Section is inferred from the machine, shift and category
 * can be filled later by whoever works it, and priority is not asked at all
 * any more (V5 §5.8).
 *
 * The prototype asked for section, machine, location, category, priority,
 * description and name — seven fields, and the section had to be picked before
 * the machine list would populate. That is the 90-second flow the spec warns
 * turns into shouting across the floor instead.
 */

import { useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';


import { sectionColour } from '@greenlam/core';

import * as api from '../../lib/api';
import { Sheet } from '../Sheet';

export function RaiseSheet({
  onClose,
  onRaised,
  prefill,
}: {
  onClose: () => void;
  onRaised: (ticket: api.Ticket) => void;
  /** Set when the sheet was opened from a scan — the machine is already known. */
  prefill?: api.ScanResolution | null;
}) {
  const { t } = useTranslation();
  const [machines, setMachines] = useState<api.Machine[]>([]);
  const [sections, setSections] = useState<api.Section[]>([]);
  const [query, setQuery] = useState('');
  const [machineId, setMachineId] = useState<number | null>(prefill?.machine_id ?? null);
  // NOT asked for any more. The roadmap crosses urgency off the raise form,
  // and it was the wrong question anyway: a person standing next to a stopped
  // press is the worst-placed person in the plant to grade its severity, and
  // within a month everything is Critical.
  //
  // No priority here, and none sent. V5 §5.8 settled open question 5-A by
  // removing the field: nobody picks how urgent a breakdown is, the server
  // ranks it by how much the machine matters, and the criticality that gets
  // reported is measured from the finished repair.
  const [description, setDescription] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const searchRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    void Promise.all([api.listMachines(), api.listSections()]).then(([m, s]) => {
      setMachines(m);
      setSections(s);
    });
    searchRef.current?.focus();
  }, []);

  const sectionById = useMemo(
    () => new Map(sections.map((s) => [s.id, s])),
    [sections],
  );

  // One flat searchable list rather than section-then-machine. Typing "p4"
  // finds Press-4; nobody has to remember which section a machine lives in.
  const matches = useMemo(() => {
    const q = query.trim().toLowerCase().replace(/[\s-]/g, '');
    if (!q) return machines.slice(0, 8);
    return machines
      .filter((m) => m.code.toLowerCase().replace(/[\s-]/g, '').includes(q))
      .slice(0, 8);
  }, [machines, query]);

  const selected = machines.find((m) => m.id === machineId) ?? null;

  async function submit() {
    if (machineId === null) {
      setError(t('raise.errors.pickMachine'));
      return;
    }
    if (!description.trim()) {
      setError(t('raise.errors.describe'));
      return;
    }
    setBusy(true);
    setError('');
    try {
      onRaised(
        await api.raiseTicket({
          machine_id: machineId,
          description: description.trim(),
          // Recorded so the pilot review can compare scanned against typed —
          // "68% raised by scanning, 34s against 81s" is what gets a rollout
          // approved (§1.5).
          raised_via: prefill ? 'qr' : 'manual',
        }),
      );
    } catch {
      setError(t('raise.errors.failed'));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Sheet title={t('raise.title')} onClose={onClose}>
      <div className="space-y-5">
        <div>
          <label
            htmlFor="machine-search"
            className="mb-1 block font-medium"
            style={{ fontSize: 'var(--text-sm)', color: 'var(--ink)' }}
          >
            {t('raise.machine')}
          </label>

          {selected ? (
            <div
              className="arch flex items-center justify-between border px-3 py-3"
              style={{ borderColor: 'var(--accent)', background: 'var(--accent-quiet)' }}
            >
              <span className="font-semibold" style={{ color: 'var(--ink)' }}>
                {selected.code}
              </span>
              <button
                type="button"
                onClick={() => {
                  setMachineId(null);
                  setQuery('');
                }}
                className="px-2 py-1"
                style={{ fontSize: 'var(--text-sm)', color: 'var(--ink-muted)' }}
              >
                {t('raise.change')}
              </button>
            </div>
          ) : (
            <>
              <input
                id="machine-search"
                ref={searchRef}
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder={t('raise.machinePlaceholder')}
                autoComplete="off"
                autoCapitalize="characters"
                spellCheck={false}
                className="arch w-full border px-3 py-3"
                style={{
                  borderColor: 'var(--line-strong)',
                  background: 'var(--surface)',
                  color: 'var(--ink)',
                }}
              />
              <ul className="mt-2 grid grid-cols-2 gap-2">
                {matches.map((m) => {
                  const section = sectionById.get(m.section_id);
                  return (
                    <li key={m.id}>
                      <button
                        type="button"
                        onClick={() => setMachineId(m.id)}
                        className="feather arch w-full border py-3 pr-2 pl-2.5 text-left"
                        style={
                          {
                            borderColor: 'var(--line)',
                            background: 'var(--surface)',
                            '--feather': sectionColour(
                              section?.sort_order,
                              section?.name ?? '',
                            ),
                          } as React.CSSProperties
                        }
                      >
                        <span className="block font-semibold" style={{ color: 'var(--ink)' }}>
                          {m.code}
                        </span>
                        <span
                          className="block truncate"
                          style={{ fontSize: 'var(--text-xs)', color: 'var(--ink-muted)' }}
                        >
                          {section?.name ?? '—'}
                        </span>
                      </button>
                    </li>
                  );
                })}
              </ul>
              {matches.length === 0 && (
                <p
                  className="mt-2"
                  style={{ fontSize: 'var(--text-sm)', color: 'var(--ink-muted)' }}
                >
                  {t('raise.noMatch')}
                </p>
              )}
            </>
          )}
        </div>

        <div>
          <label
            htmlFor="what-happened"
            className="mb-1 block font-medium"
            style={{ fontSize: 'var(--text-sm)', color: 'var(--ink)' }}
          >
            {t('raise.what')}
          </label>
          <textarea
            id="what-happened"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            rows={3}
            placeholder={t('raise.whatPlaceholder')}
            className="arch w-full border px-3 py-3"
            style={{
              borderColor: 'var(--line-strong)',
              background: 'var(--surface)',
              color: 'var(--ink)',
            }}
          />
        </div>

        {error && (
          <p
            role="alert"
            className="arch px-3 py-2"
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
          type="button"
          onClick={() => void submit()}
          disabled={busy}
          className="arch w-full py-4 font-semibold disabled:opacity-60"
          style={{ background: 'var(--accent)', color: 'var(--accent-ink)' }}
        >
          {busy ? t('raise.submitting') : t('raise.submit')}
        </button>
      </div>
    </Sheet>
  );
}
