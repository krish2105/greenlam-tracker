/**
 * The machine master, grouped by section.
 *
 * In Phase 3 this list gets cached into Dexie on sign-in, which is what makes
 * QR scanning resolve with no network at all (addendum §1.3). For now it is a
 * plain fetch — but it is the screen that proves auth, tenant scoping and
 * masters CRUD all work end to end.
 *
 * Each machine renders as a plate: mono code and the short label code that is
 * physically printed on the sticker, so what is on screen matches what is on
 * the machine.
 */

import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';

import * as api from '../lib/api';

export function MachineMaster() {
  const { t } = useTranslation();
  const [sections, setSections] = useState<api.Section[]>([]);
  const [machines, setMachines] = useState<api.Machine[]>([]);
  const [state, setState] = useState<'loading' | 'ready' | 'failed'>('loading');
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setState('loading');
    Promise.all([api.listSections(), api.listMachines()])
      .then(([s, m]) => {
        if (cancelled) return;
        setSections(s);
        setMachines(m);
        setState('ready');
      })
      .catch(() => {
        if (!cancelled) setState('failed');
      });
    return () => {
      cancelled = true;
    };
  }, [attempt]);

  if (state === 'loading') {
    return (
      <p role="status" aria-live="polite" style={{ color: 'var(--ink-muted)' }}>
        {t('masters.loading')}
      </p>
    );
  }

  if (state === 'failed') {
    return (
      // An error state names a recovery path. "Could not load" on its own
      // leaves someone stuck.
      <div role="alert">
        <p style={{ color: 'var(--ink)' }}>{t('masters.loadFailed')}</p>
        <button
          type="button"
          onClick={() => setAttempt((n) => n + 1)}
          className="mt-2 rounded-lg border px-4 py-2"
          style={{ borderColor: 'var(--line-strong)', color: 'var(--ink)' }}
        >
          {t('masters.retry')}
        </button>
      </div>
    );
  }

  if (machines.length === 0) {
    return (
      <div>
        <h1 className="font-semibold" style={{ fontSize: 'var(--text-xl)' }}>
          {t('masters.title')}
        </h1>
        <p className="mt-2" style={{ color: 'var(--ink-muted)' }}>
          {t('masters.empty')}
        </p>
      </div>
    );
  }

  return (
    <div>
      <h1
        className="font-semibold"
        style={{ fontSize: 'var(--text-xl)', color: 'var(--ink)' }}
      >
        {t('masters.title')}
      </h1>
      <p
        className="mt-0.5"
        style={{ color: 'var(--ink-muted)', fontSize: 'var(--text-sm)' }}
      >
        {t('masters.subtitle')}
      </p>

      <div className="mt-5 space-y-6">
        {sections.map((section) => {
          const inSection = machines.filter((m) => m.section_id === section.id);
          if (inSection.length === 0) return null;
          return (
            <section key={section.id} aria-labelledby={`section-${section.id}`}>
              <h2
                id={`section-${section.id}`}
                className="register-rule pb-1 font-semibold"
                style={{ fontSize: 'var(--text-sm)', color: 'var(--ink)' }}
              >
                {section.name}{' '}
                <span style={{ color: 'var(--ink-muted)', fontWeight: 400 }}>
                  · {inSection.length}
                </span>
              </h2>
              <ul className="mt-2 grid gap-2 sm:grid-cols-2">
                {inSection.map((machine) => (
                  <li
                    key={machine.id}
                    className="flex items-center justify-between gap-3 rounded-xl border px-3 py-2.5"
                    style={{
                      borderColor: 'var(--line)',
                      background: 'var(--surface)',
                    }}
                  >
                    <div className="min-w-0">
                      <p
                        className="truncate font-medium"
                        style={{ color: 'var(--ink)' }}
                      >
                        {machine.name}
                      </p>
                      <p
                        style={{
                          color: 'var(--ink-muted)',
                          fontSize: 'var(--text-xs)',
                        }}
                      >
                        {machine.hourly_downtime_cost === null
                          ? t('masters.noCost')
                          : t('masters.costPerHour', {
                              amount: machine.hourly_downtime_cost.toLocaleString(
                                'en-IN',
                                { style: 'currency', currency: 'INR' },
                              ),
                            })}
                      </p>
                    </div>
                    {/* What is stamped on the sticker, in the same voice. */}
                    <span className="plate shrink-0">{machine.qr_short_code}</span>
                  </li>
                ))}
              </ul>
            </section>
          );
        })}
      </div>
    </div>
  );
}
