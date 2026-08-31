/**
 * Uploading the plant's Excel register.
 *
 * THE SCREEN IS A CONFIRMATION, NOT A FORM
 *
 * Picking a file does not import it. It runs a dry run and shows the reader
 * exactly what would happen — how many breakdowns would be created, how many
 * already exist, and every row that could not be read, by its Excel row number.
 * Only then is there something to press.
 *
 * That extra step is the whole feature. The file is a hand-maintained register
 * with years of plant history in it, and the failure this guards against is not
 * a crash — it is four thousand plausible-looking tickets that are silently one
 * column out. A confirm dialog would not catch that. A list of the twelve rows
 * that are wrong does.
 *
 * WHAT THE ERROR LIST IS FOR
 *
 * Not to block the import. A register with 12 bad rows out of 4,000 should
 * still go in; the 12 are reported so somebody can fix the spreadsheet, which
 * is where they came from and where they will come from again next month.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';

import * as api from '../../lib/api';

type Phase = 'idle' | 'previewing' | 'ready' | 'committing' | 'done';

export function ImportView() {
  const { t, i18n } = useTranslation();
  const [phase, setPhase] = useState<Phase>('idle');
  const [file, setFile] = useState<File | null>(null);
  const [plan, setPlan] = useState<api.ImportPlan | null>(null);
  const [result, setResult] = useState<api.ImportPlan | null>(null);
  const [history, setHistory] = useState<api.ImportRun[]>([]);
  const [freshness, setFreshness] = useState<api.ImportFreshness | null>(null);
  const [error, setError] = useState('');
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const refresh = useCallback(() => {
    void api.importHistory().then(setHistory).catch(() => setHistory([]));
    void api.importFreshness().then(setFreshness).catch(() => setFreshness(null));
  }, []);

  useEffect(refresh, [refresh]);

  async function choose(picked: File | null) {
    if (!picked) return;
    setFile(picked);
    setPlan(null);
    setResult(null);
    setError('');
    setPhase('previewing');
    try {
      setPlan(await api.previewImport(picked));
      setPhase('ready');
    } catch (e) {
      setError(e instanceof api.ApiError ? e.message : t('imports.failed'));
      setPhase('idle');
    } finally {
      refresh();
    }
  }

  async function apply() {
    if (!file) return;
    setPhase('committing');
    setError('');
    try {
      setResult(await api.commitImport(file));
      setPhase('done');
    } catch (e) {
      setError(e instanceof api.ApiError ? e.message : t('imports.failed'));
      setPhase('ready');
    } finally {
      refresh();
    }
  }

  function reset() {
    setFile(null);
    setPlan(null);
    setResult(null);
    setError('');
    setPhase('idle');
    if (inputRef.current) inputRef.current.value = '';
  }

  const busy = phase === 'previewing' || phase === 'committing';
  const formatWhen = (iso: string) =>
    new Date(iso).toLocaleString(i18n.language, {
      dateStyle: 'medium',
      timeStyle: 'short',
    });

  return (
    <div className="space-y-6 pb-12">
      <header>
        <h1 className="font-semibold" style={{ fontSize: 'var(--text-xl)', color: 'var(--ink)' }}>
          {t('imports.title')}
        </h1>
        <p className="mt-1" style={{ color: 'var(--ink-muted)' }}>
          {t('imports.subtitle')}
        </p>
        {/* Said plainly, because the belief that the register must be uploaded
            twice — once for the app, once for the dashboard — is the most
            common misunderstanding about this system. It never was true: both
            surfaces read one database. That is a communication failure, so it
            is fixed here in words rather than with machinery. */}
        <p
          className="arch mt-3 border px-3 py-2"
          style={{
            fontSize: 'var(--text-sm)',
            borderColor: 'var(--line)',
            borderLeftWidth: '4px',
            borderLeftColor: 'var(--viz-1)',
            background: 'var(--surface)',
            color: 'var(--ink)',
          }}
        >
          {t('imports.oneUpload')}
        </p>
      </header>

      {/* Freshness. The "refreshed daily" half of the requirement — nothing
          here can make somebody export their spreadsheet, but the dashboard
          can at least be honest about how old its register is. A board reading
          a chart deserves to know whether it is today's plant or last week's. */}
      {freshness && (
        <p
          className="arch border px-3 py-2"
          style={{
            fontSize: 'var(--text-sm)',
            borderColor: freshness.stale ? 'var(--amber)' : 'var(--line)',
            borderLeftWidth: '4px',
            background: freshness.stale ? 'var(--amber-tint)' : 'var(--surface)',
            color: freshness.stale ? 'var(--amber)' : 'var(--ink-muted)',
          }}
        >
          {freshness.never
            ? t('imports.neverImported')
            : freshness.stale
              ? t('imports.stale', { hours: Math.round(freshness.hours_ago ?? 0) })
              : t('imports.fresh', {
                  when: formatWhen(freshness.last_import_at!),
                  rows: freshness.rows ?? 0,
                })}
        </p>
      )}

      {/* Drop zone. A real <input type="file"> underneath, wrapped in a label,
          so it stays keyboard-reachable and announces itself — a div with a
          drop handler is invisible to anyone not using a mouse. */}
      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          void choose(e.dataTransfer.files[0] ?? null);
        }}
        className="arch border-2 border-dashed px-4 py-8 text-center"
        style={{
          borderColor: dragging ? 'var(--accent)' : 'var(--line-strong)',
          background: dragging ? 'var(--accent-quiet)' : 'var(--surface)',
        }}
      >
        <label className="block cursor-pointer">
          <input
            ref={inputRef}
            type="file"
            accept=".xlsx,.xlsm"
            className="sr-only"
            disabled={busy}
            onChange={(e) => void choose(e.target.files?.[0] ?? null)}
          />
          <span
            className="arch inline-block px-4 py-3 font-semibold"
            style={{ background: 'var(--accent)', color: 'var(--accent-ink)' }}
          >
            {busy ? t('imports.reading') : t('imports.choose')}
          </span>
          <span className="mt-3 block" style={{ color: 'var(--ink-muted)' }}>
            {t('imports.dropHint')}
          </span>
        </label>
        {file && (
          <p className="mt-3" style={{ fontSize: 'var(--text-sm)', color: 'var(--ink)' }}>
            {file.name} · {Math.max(1, Math.round(file.size / 1024))} KB
          </p>
        )}
      </div>

      {error && (
        <p
          role="alert"
          className="arch px-3 py-2"
          style={{ background: 'var(--rust-tint)', color: 'var(--rust)' }}
        >
          {error}
        </p>
      )}

      {plan && phase !== 'done' && <PlanReport plan={plan} />}
      {result && phase === 'done' && <PlanReport plan={result} committed />}

      {phase === 'ready' && plan && (
        <div className="flex flex-wrap gap-3">
          <button
            type="button"
            onClick={() => void apply()}
            disabled={!plan.can_commit}
            className="arch px-5 py-3 font-semibold disabled:opacity-50"
            style={{ background: 'var(--accent)', color: 'var(--accent-ink)' }}
          >
            {t('imports.apply', { count: plan.creates + plan.updates })}
          </button>
          <button
            type="button"
            onClick={reset}
            className="arch border px-5 py-3"
            style={{ borderColor: 'var(--line-strong)', color: 'var(--ink)' }}
          >
            {t('common.close')}
          </button>
        </div>
      )}

      {phase === 'committing' && (
        <p aria-live="polite" style={{ color: 'var(--ink-muted)' }}>
          {t('imports.applying')}
        </p>
      )}

      {phase === 'done' && (
        <button
          type="button"
          onClick={reset}
          className="arch border px-5 py-3"
          style={{ borderColor: 'var(--line-strong)', color: 'var(--ink)' }}
        >
          {t('imports.another')}
        </button>
      )}

      {history.length > 0 && (
        <section aria-labelledby="import-history">
          <h2
            id="import-history"
            className="register-rule pb-1 font-semibold"
            style={{ fontSize: 'var(--text-sm)', color: 'var(--ink)' }}
          >
            {t('imports.history')}
          </h2>
          <ul className="mt-2 space-y-1.5">
            {history.map((run) => (
              <li
                key={run.id}
                className="arch flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1 border px-3 py-2"
                style={{
                  borderColor: 'var(--line)',
                  background: 'var(--surface)',
                  // A dry run is not a failure and must not look like one; it
                  // is simply a lighter thing than a commit.
                  opacity: run.status === 'preview' ? 0.72 : 1,
                }}
              >
                <span className="min-w-0">
                  <span className="block truncate" style={{ color: 'var(--ink)' }}>
                    {run.filename}
                  </span>
                  <span style={{ fontSize: 'var(--text-xs)', color: 'var(--ink-muted)' }}>
                    {t(`imports.status.${run.status}`, { defaultValue: run.status })} ·{' '}
                    {run.uploaded_by} · {formatWhen(run.created_at)}
                  </span>
                </span>
                <span
                  className="tabular shrink-0"
                  style={{ fontSize: 'var(--text-sm)', color: 'var(--ink-muted)' }}
                >
                  {t('imports.counts', {
                    created: run.created_count,
                    updated: run.updated_count,
                    errors: run.error_count,
                  })}
                </span>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}

/** What would happen, or what did. Same component — the numbers mean the same
 *  thing either way, and a separate "success" screen would only invite the two
 *  to drift apart. */
function PlanReport({ plan, committed = false }: { plan: api.ImportPlan; committed?: boolean }) {
  const { t } = useTranslation();

  if (plan.missing_columns.length > 0) {
    return (
      <div
        role="alert"
        className="arch border px-4 py-3"
        style={{
          borderColor: 'var(--rust)',
          borderLeftWidth: '4px',
          background: 'var(--surface)',
        }}
      >
        <p className="font-semibold" style={{ color: 'var(--ink)' }}>
          {t('imports.wrongShape')}
        </p>
        <p className="mt-1" style={{ fontSize: 'var(--text-sm)', color: 'var(--ink-muted)' }}>
          {t('imports.missingColumns', { columns: plan.missing_columns.join(', ') })}
        </p>
      </div>
    );
  }

  const stats: { label: string; value: number; tone?: string }[] = [
    { label: committed ? t('imports.created') : t('imports.willCreate'), value: plan.creates },
    { label: committed ? t('imports.updated') : t('imports.willUpdate'), value: plan.updates },
    { label: t('imports.skipped'), value: plan.skips },
    { label: t('imports.problems'), value: plan.issues_total, tone: 'var(--clay-2)' },
  ];

  return (
    <section className="space-y-4">
      <p
        className="font-semibold"
        style={{ color: 'var(--ink)', fontSize: 'var(--text-base)' }}
      >
        {committed
          ? t('imports.doneHeadline', { rows: plan.creates + plan.updates })
          : t('imports.previewHeadline', { rows: plan.rows_read, sheet: plan.sheet_name })}
      </p>

      <dl className="flex flex-wrap gap-x-8 gap-y-3">
        {stats.map((s) => (
          <div key={s.label}>
            <dt style={{ fontSize: 'var(--text-xs)', color: 'var(--ink-muted)' }}>{s.label}</dt>
            <dd
              className="tabular font-semibold"
              style={{
                fontSize: 'var(--text-xl)',
                color: s.value > 0 && s.tone ? s.tone : 'var(--ink)',
              }}
            >
              {s.value.toLocaleString('en-IN')}
            </dd>
          </div>
        ))}
      </dl>

      {plan.unknown_machines.length > 0 && (
        <div
          className="arch border px-3 py-2"
          style={{
            borderColor: 'var(--amber)',
            borderLeftWidth: '4px',
            background: 'var(--surface)',
          }}
        >
          <p style={{ fontSize: 'var(--text-sm)', color: 'var(--ink)' }}>
            {t('imports.unknownMachines', {
              codes: plan.unknown_machines.slice(0, 8).join(', '),
            })}
          </p>
        </div>
      )}

      {plan.issues.length > 0 && (
        <details>
          <summary
            className="cursor-pointer font-medium"
            style={{ fontSize: 'var(--text-sm)', color: 'var(--ink)' }}
          >
            {t('imports.showProblems', {
              shown: plan.issues.length,
              total: plan.issues_total,
            })}
          </summary>
          {/* A table, because this is tabular — and it scrolls inside its own
              box so the page never scrolls sideways on a phone. */}
          <div className="mt-2 overflow-x-auto">
            <table className="w-full" style={{ fontSize: 'var(--text-sm)' }}>
              <thead>
                <tr style={{ color: 'var(--ink-muted)' }}>
                  <th scope="col" className="py-1 pr-3 text-left">
                    {t('imports.row')}
                  </th>
                  <th scope="col" className="py-1 pr-3 text-left">
                    {t('imports.column')}
                  </th>
                  <th scope="col" className="py-1 text-left">
                    {t('imports.problem')}
                  </th>
                </tr>
              </thead>
              <tbody>
                {plan.issues.map((issue, i) => (
                  <tr key={i} style={{ borderTop: '1px solid var(--line)' }}>
                    <td className="tabular py-1.5 pr-3" style={{ color: 'var(--ink)' }}>
                      {issue.row}
                    </td>
                    <td className="py-1.5 pr-3" style={{ color: 'var(--ink-muted)' }}>
                      {issue.column || '—'}
                    </td>
                    <td
                      className="py-1.5"
                      style={{
                        color:
                          issue.severity === 'error' ? 'var(--clay-2)' : 'var(--ink-muted)',
                      }}
                    >
                      {issue.message}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      )}

      {!committed && plan.sample.length > 0 && (
        <details>
          <summary
            className="cursor-pointer font-medium"
            style={{ fontSize: 'var(--text-sm)', color: 'var(--ink)' }}
          >
            {t('imports.showRows', { shown: plan.sample.length, total: plan.sample_total })}
          </summary>
          <div className="mt-2 overflow-x-auto">
            <table className="w-full" style={{ fontSize: 'var(--text-sm)' }}>
              <thead>
                <tr style={{ color: 'var(--ink-muted)' }}>
                  <th scope="col" className="py-1 pr-3 text-left">
                    {t('imports.row')}
                  </th>
                  <th scope="col" className="py-1 pr-3 text-left">
                    {t('chart.machine')}
                  </th>
                  <th scope="col" className="py-1 pr-3 text-left">
                    {t('chart.date')}
                  </th>
                  <th scope="col" className="py-1 pr-3 text-right">
                    {t('chart.downtime')}
                  </th>
                  <th scope="col" className="py-1 text-left">
                    {t('imports.action')}
                  </th>
                </tr>
              </thead>
              <tbody>
                {plan.sample.map((row) => (
                  <tr key={row.row} style={{ borderTop: '1px solid var(--line)' }}>
                    <td className="tabular py-1.5 pr-3" style={{ color: 'var(--ink-muted)' }}>
                      {row.row}
                    </td>
                    <td className="py-1.5 pr-3" style={{ color: 'var(--ink)' }}>
                      {row.machine_code}
                    </td>
                    <td className="tabular py-1.5 pr-3" style={{ color: 'var(--ink-muted)' }}>
                      {row.date}
                    </td>
                    <td
                      className="tabular py-1.5 pr-3 text-right"
                      style={{ color: 'var(--ink-muted)' }}
                    >
                      {row.minutes} min
                    </td>
                    <td className="py-1.5" style={{ color: 'var(--ink-muted)' }}>
                      {t(`imports.action_${row.action}`)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      )}
    </section>
  );
}
