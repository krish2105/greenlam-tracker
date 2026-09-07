/**
 * Fix a mistake on a production entry (V5 §7).
 *
 * The correction that actually happens on a factory floor is a missing zero:
 * 480 typed where 4800 was meant, spotted when somebody queries the shift
 * total. So the counts come first and the rest follows.
 *
 * The server refuses the same things it refused when the entry was saved —
 * more rejects than produced, a rejection with no reason — because a
 * correction path that skipped them would be a way to walk every one of those
 * rules past the door one entry at a time.
 */

import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';

import * as api from '../../lib/api';
import { Sheet } from '../Sheet';

export function CorrectProductionSheet({
  row,
  onClose,
  onCorrected,
}: {
  row: api.ProductionRow;
  onClose: () => void;
  onCorrected: () => void;
}) {
  const { t } = useTranslation();

  const [produced, setProduced] = useState(String(row.produced_qty));
  const [rejected, setRejected] = useState(String(row.rejected_qty));
  const [loadNo, setLoadNo] = useState(row.load_no ?? '');
  const [reasonId, setReasonId] = useState<number | null>(null);
  const [reasons, setReasons] = useState<api.RejectReason[]>([]);
  const [why, setWhy] = useState('');
  const [history, setHistory] = useState<api.CorrectionEntry[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    void api.listRejectReasons().then(setReasons).catch(() => setReasons([]));
    void api.productionCorrections(row.id).then(setHistory).catch(() => setHistory([]));
  }, [row.id]);

  const producedNum = Number(produced) || 0;
  const rejectedNum = Number(rejected) || 0;

  const changes: Record<string, unknown> = {};
  if (producedNum !== row.produced_qty) changes.produced_qty = producedNum;
  if (rejectedNum !== row.rejected_qty) changes.rejected_qty = rejectedNum;
  if ((loadNo.trim() || null) !== row.load_no) changes.load_no = loadNo.trim() || null;
  // Only sent when the rejects moved above zero — the entry may already carry
  // a reason, and re-sending the one that is there is not a correction.
  if (reasonId !== null && rejectedNum > 0) changes.reject_reason_id = reasonId;

  const nothingChanged = Object.keys(changes).length === 0;
  // The server checks this too. Saying so here saves a round trip and,
  // more usefully, says it while the cursor is still in the field.
  const tooManyRejects = rejectedNum > producedNum;
  const needsReason = rejectedNum > 0 && row.reject_reason === null && reasonId === null;

  const field = {
    borderColor: 'var(--line-strong)',
    background: 'var(--surface)',
    color: 'var(--ink)',
  } as const;
  const labelStyle = { fontSize: 'var(--text-sm)', color: 'var(--ink)' } as const;

  async function save() {
    setBusy(true);
    setError('');
    try {
      await api.correctProduction(row.id, changes, why.trim() || undefined);
      onCorrected();
    } catch (e) {
      setError(e instanceof Error ? e.message : t('correct.failed'));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Sheet title={t('correct.productionTitle', { machine: row.machine_code })} onClose={onClose}>
      <div className="space-y-5">
        <p style={{ color: 'var(--ink-muted)', fontSize: 'var(--text-sm)' }}>
          {t('correct.productionBlurb')}
        </p>

        <div className="grid grid-cols-2 gap-3">
          <div>
            <label htmlFor="cp-produced" className="mb-1 block font-medium" style={labelStyle}>
              {t('production.produced')}
            </label>
            <input
              id="cp-produced"
              value={produced}
              onChange={(e) => setProduced(e.target.value.replace(/\D/g, ''))}
              inputMode="numeric"
              className="tabular arch w-full border px-3 py-3"
              style={field}
            />
          </div>
          <div>
            <label htmlFor="cp-rejected" className="mb-1 block font-medium" style={labelStyle}>
              {t('production.rejected')}
            </label>
            <input
              id="cp-rejected"
              value={rejected}
              onChange={(e) => setRejected(e.target.value.replace(/\D/g, ''))}
              inputMode="numeric"
              className="tabular arch w-full border px-3 py-3"
              style={field}
            />
            {tooManyRejects && (
              <p className="mt-1" style={{ color: 'var(--rust)', fontSize: 'var(--text-xs)' }}>
                {t('production.errors.tooManyRejects')}
              </p>
            )}
          </div>
        </div>

        {needsReason && (
          <div>
            <label htmlFor="cp-reason" className="mb-1 block font-medium" style={labelStyle}>
              {t('production.rejectReason')}
            </label>
            <select
              id="cp-reason"
              value={reasonId ?? ''}
              onChange={(e) => setReasonId(e.target.value ? Number(e.target.value) : null)}
              className="arch w-full border px-3 py-3"
              style={field}
            >
              <option value="">—</option>
              {reasons.map((r) => (
                <option key={r.id} value={r.id}>
                  {r.name}
                </option>
              ))}
            </select>
          </div>
        )}

        <div>
          <label htmlFor="cp-load" className="mb-1 block font-medium" style={labelStyle}>
            {t('production.loadNoOptional')}
          </label>
          <input
            id="cp-load"
            value={loadNo}
            onChange={(e) => setLoadNo(e.target.value.toUpperCase())}
            autoCapitalize="characters"
            spellCheck={false}
            className="arch w-full border px-3 py-3"
            style={field}
          />
        </div>

        <div>
          <label htmlFor="cp-why" className="mb-1 block font-medium" style={labelStyle}>
            {t('correct.reason')}
          </label>
          <input
            id="cp-why"
            value={why}
            onChange={(e) => setWhy(e.target.value)}
            placeholder={t('correct.productionReasonPlaceholder')}
            className="arch w-full border px-3 py-3"
            style={field}
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
          onClick={() => void save()}
          disabled={busy || nothingChanged || tooManyRejects || needsReason}
          className="arch w-full py-4 font-semibold disabled:opacity-60"
          style={{ background: 'var(--accent)', color: 'var(--accent-ink)' }}
        >
          {busy ? t('correct.saving') : t('correct.save')}
        </button>

        {history.length > 0 && (
          <section>
            <h3 className="register-rule pb-1 font-semibold" style={labelStyle}>
              {t('correct.historyTitle')}
            </h3>
            <ul className="mt-2 space-y-2">
              {history.map((h, i) => (
                <li
                  key={i}
                  className="arch border px-3 py-2"
                  style={{ borderColor: 'var(--line)', fontSize: 'var(--text-sm)' }}
                >
                  <span style={{ color: 'var(--ink-muted)' }}>
                    {t('correct.historyLine', {
                      name: h.corrected_by_name,
                      field: t(`correct.fields.${h.field}`, { defaultValue: h.field }),
                    })}
                  </span>
                  <span className="mt-1 block" style={{ color: 'var(--ink)' }}>
                    {h.old_value ?? '—'} → {h.new_value ?? '—'}
                  </span>
                </li>
              ))}
            </ul>
          </section>
        )}
      </div>
    </Sheet>
  );
}
