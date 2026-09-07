/**
 * The approval queue, and who holds what (V5 §3).
 *
 * WHY THE QUEUE AND THE ROSTER ARE ONE SCREEN
 *
 * They are the same decision made at two different moments. Approving somebody
 * is choosing their areas; changing them later is choosing again. Splitting
 * them would mean building the same six checkboxes twice and then keeping the
 * two copies in step.
 *
 * The queue sits on top because it is the only time-sensitive half — somebody
 * signed up this morning and cannot do their job until this is done.
 *
 * REVOKING IS SAVING AN EMPTY LIST
 *
 * There is no separate revoke button. Access is whatever the boxes say, and
 * unticking all six is what "no longer works here" looks like. One code path
 * instead of two, and the consequence is visible while you are choosing it
 * rather than behind a confirmation after the fact.
 */

import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';

import { AREAS } from '@greenlam/core';

import * as api from '../../lib/api';

export function AccessView() {
  const { t } = useTranslation();

  const [pending, setPending] = useState<api.PendingUser[]>([]);
  const [people, setPeople] = useState<api.ApiUser[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const load = useCallback(() => {
    setError('');
    void Promise.all([api.pendingUsers().catch(() => []), api.listUsers().catch(() => [])])
      .then(([q, u]) => {
        setPending(q);
        setPeople(u);
      })
      .finally(() => setLoading(false));
  }, []);

  useEffect(load, [load]);

  if (loading) {
    return <p style={{ color: 'var(--ink-muted)' }}>{t('masters.loading')}</p>;
  }

  return (
    <div className="pb-16">
      <h1 className="font-semibold" style={{ fontSize: 'var(--text-xl)', color: 'var(--ink)' }}>
        {t('access.title')}
      </h1>
      <p className="mt-1" style={{ color: 'var(--ink-muted)', fontSize: 'var(--text-sm)' }}>
        {t('access.subtitle')}
      </p>

      {error && (
        <p
          role="alert"
          className="arch mt-4 px-3 py-2"
          style={{ background: 'var(--rust-tint)', color: 'var(--rust)' }}
        >
          {error}
        </p>
      )}

      <section className="mt-6">
        <h2 className="register-rule pb-1 font-semibold" style={{ color: 'var(--ink)' }}>
          {t('access.waiting', { count: pending.length })}
        </h2>
        {pending.length === 0 ? (
          <p className="mt-3" style={{ color: 'var(--ink-muted)' }}>
            {t('access.noneWaiting')}
          </p>
        ) : (
          <ul className="mt-3 space-y-3">
            {pending.map((p) => (
              <PersonCard
                key={p.id}
                title={p.name}
                subtitle={t('access.signedUp', {
                  id: p.employee_id,
                  when: new Date(p.signed_up_at).toLocaleDateString(),
                })}
                initial={[]}
                saveLabel={t('access.approve')}
                onSave={(areas) => api.approveUser(p.id, areas)}
                onSaved={load}
                onError={setError}
              />
            ))}
          </ul>
        )}
      </section>

      <section className="mt-8">
        <h2 className="register-rule pb-1 font-semibold" style={{ color: 'var(--ink)' }}>
          {t('access.everyone')}
        </h2>
        <ul className="mt-3 space-y-3">
          {people
            .filter((p) => p.approved_at)
            .map((p) => (
              <PersonCard
                key={p.id}
                title={p.name}
                subtitle={p.employee_id}
                initial={p.areas}
                saveLabel={t('access.save')}
                onSave={(areas) => api.setUserAreas(p.id, areas)}
                onSaved={load}
                onError={setError}
              />
            ))}
        </ul>
      </section>
    </div>
  );
}

function PersonCard({
  title,
  subtitle,
  initial,
  saveLabel,
  onSave,
  onSaved,
  onError,
}: {
  title: string;
  subtitle: string;
  initial: readonly string[];
  saveLabel: string;
  onSave: (areas: string[]) => Promise<unknown>;
  onSaved: () => void;
  onError: (message: string) => void;
}) {
  const { t } = useTranslation();
  const [areas, setAreas] = useState<string[]>([...initial]);
  const [busy, setBusy] = useState(false);

  const changed = areas.length !== initial.length || areas.some((a) => !initial.includes(a));

  function toggle(area: string) {
    setAreas((current) =>
      current.includes(area) ? current.filter((a) => a !== area) : [...current, area],
    );
  }

  async function save() {
    setBusy(true);
    try {
      await onSave(areas);
      onSaved();
    } catch (e) {
      onError(e instanceof Error ? e.message : t('access.failed'));
    } finally {
      setBusy(false);
    }
  }

  return (
    <li
      className="arch border px-4 py-3"
      style={{ borderColor: 'var(--line)', background: 'var(--surface)' }}
    >
      <div className="flex items-baseline justify-between gap-2">
        <span className="font-semibold" style={{ color: 'var(--ink)' }}>
          {title}
        </span>
        <span style={{ color: 'var(--ink-muted)', fontSize: 'var(--text-sm)' }}>{subtitle}</span>
      </div>

      <fieldset className="mt-3">
        <legend className="sr-only">{t('access.areasLegend')}</legend>
        <div className="flex flex-wrap gap-2">
          {AREAS.map((area) => {
            const on = areas.includes(area);
            return (
              <button
                key={area}
                type="button"
                onClick={() => toggle(area)}
                aria-pressed={on}
                className="arch border px-3 py-2 font-medium"
                style={{
                  fontSize: 'var(--text-sm)',
                  borderColor: on ? 'var(--accent)' : 'var(--line)',
                  background: on ? 'var(--accent-quiet)' : 'var(--surface)',
                  color: on ? 'var(--ink)' : 'var(--ink-muted)',
                }}
              >
                {t(`access.areas.${area}`)}
              </button>
            );
          })}
        </div>
      </fieldset>

      {/* Said out loud while the boxes are still empty, rather than behind a
          confirmation after the decision is made. */}
      {changed && areas.length === 0 && (
        <p className="mt-2" style={{ color: 'var(--rust)', fontSize: 'var(--text-sm)' }}>
          {t('access.revokeWarning', { name: title })}
        </p>
      )}

      <button
        type="button"
        onClick={() => void save()}
        disabled={busy || !changed}
        className="arch mt-3 w-full py-3 font-semibold disabled:opacity-60"
        style={{ background: 'var(--accent)', color: 'var(--accent-ink)' }}
      >
        {busy ? t('access.saving') : saveLabel}
      </button>
    </li>
  );
}
