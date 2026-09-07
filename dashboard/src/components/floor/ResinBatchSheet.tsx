/**
 * A batch out of a resin kettle.
 *
 * Short on purpose. The kettle operator has a clipboard and a batch number;
 * everything else can be filled in when the inspection result is known, so
 * only the number is required.
 *
 * The batch number is the one field that carries weight beyond this form: an
 * impregnated roll references it, and a blister found at the press is traced
 * backwards through it. The server refuses a duplicate rather than merging
 * two batches under one number, and this form says so plainly when it does.
 */

import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';

import * as api from '../../lib/api';
import { Sheet } from '../Sheet';

export function ResinBatchSheet({
  machine,
  onClose,
  onSaved,
}: {
  machine: api.Machine;
  onClose: () => void;
  onSaved: () => void;
}) {
  const { t } = useTranslation();

  const [shifts, setShifts] = useState<api.Shift[]>([]);
  const [reasons, setReasons] = useState<api.RejectReason[]>([]);
  const [shiftId, setShiftId] = useState<number | null>(null);

  const [batchNo, setBatchNo] = useState('');
  const [quantity, setQuantity] = useState('');
  const [rejected, setRejected] = useState('');
  const [reasonId, setReasonId] = useState<number | null>(null);
  const [notes, setNotes] = useState('');

  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void api.listShifts().then(setShifts).catch(() => setShifts([]));
    void api.listRejectReasons().then(setReasons).catch(() => setReasons([]));
  }, []);

  const rejectedNum = Number(rejected || 0);
  const quantityNum = Number(quantity || 0);
  const needsReason = rejectedNum > 0 && reasonId === null;
  const rejectsTooMany = quantity !== '' && rejectedNum > quantityNum;

  const canSave =
    batchNo.trim().length > 0 && !needsReason && !rejectsTooMany && !saving;

  const labelStyle = { color: 'var(--ink)', fontSize: 'var(--text-sm)' } as const;
  const fieldStyle = {
    borderColor: 'var(--line-strong)',
    background: 'var(--surface)',
    color: 'var(--ink)',
  } as const;

  async function save() {
    setSaving(true);
    setError(null);
    try {
      await api.logResinBatch({
        machine_id: machine.id,
        shift_id: shiftId,
        batch_no: batchNo.trim(),
        quantity: quantity === '' ? null : quantity,
        rejected_qty: rejected === '' ? null : rejected,
        reject_reason_id: reasonId,
        notes: notes.trim() || null,
      });
      onSaved();
    } catch (e) {
      setError(e instanceof Error ? e.message : t('masters.loadFailed'));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Sheet title={t('resin.title', { machine: machine.code })} onClose={onClose}>
      <div className="space-y-5">
        <div>
          <label htmlFor="resin-batch-no" className="mb-1 block font-medium" style={labelStyle}>
            {t('resin.batchNo')}
          </label>
          <input
            id="resin-batch-no"
            value={batchNo}
            onChange={(e) => setBatchNo(e.target.value)}
            autoComplete="off"
            className="arch w-full border px-3 py-3"
            style={fieldStyle}
          />
          <p className="mt-1" style={{ color: 'var(--ink-muted)', fontSize: 'var(--text-xs)' }}>
            {t('resin.batchNoHint')}
          </p>
        </div>

        <div className="grid gap-3 sm:grid-cols-2">
          <div>
            <label htmlFor="resin-qty" className="mb-1 block font-medium" style={labelStyle}>
              {t('resin.quantity')}
            </label>
            <input
              id="resin-qty"
              type="number"
              inputMode="decimal"
              min="0"
              value={quantity}
              onChange={(e) => setQuantity(e.target.value)}
              className="arch w-full border px-3 py-3"
              style={fieldStyle}
            />
          </div>
          <div>
            <label htmlFor="resin-shift" className="mb-1 block font-medium" style={labelStyle}>
              {t('production.shift')}
            </label>
            <select
              id="resin-shift"
              value={shiftId ?? ''}
              onChange={(e) => setShiftId(e.target.value ? Number(e.target.value) : null)}
              className="arch w-full border px-3 py-3"
              style={fieldStyle}
            >
              <option value="">—</option>
              {shifts.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </select>
          </div>
        </div>

        {/* "for resin as well" — a batch is inspected like a batch of sheets. */}
        <div className="grid gap-3 sm:grid-cols-2">
          <div>
            <label htmlFor="resin-rejected" className="mb-1 block font-medium" style={labelStyle}>
              {t('resin.rejected')}
            </label>
            <input
              id="resin-rejected"
              type="number"
              inputMode="decimal"
              min="0"
              value={rejected}
              onChange={(e) => setRejected(e.target.value)}
              className="arch w-full border px-3 py-3"
              style={fieldStyle}
            />
            {rejectsTooMany && (
              <p className="mt-1" style={{ color: 'var(--danger)', fontSize: 'var(--text-xs)' }}>
                {t('resin.rejectedTooMany')}
              </p>
            )}
          </div>
          {rejectedNum > 0 && (
            <div>
              <label htmlFor="resin-reason" className="mb-1 block font-medium" style={labelStyle}>
                {t('production.rejectReason')}
              </label>
              <select
                id="resin-reason"
                value={reasonId ?? ''}
                onChange={(e) => setReasonId(e.target.value ? Number(e.target.value) : null)}
                className="arch w-full border px-3 py-3"
                style={fieldStyle}
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
        </div>

        <div>
          <label htmlFor="resin-notes" className="mb-1 block font-medium" style={labelStyle}>
            {t('resin.notes')}
          </label>
          <textarea
            id="resin-notes"
            rows={2}
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            className="arch w-full border px-3 py-3"
            style={fieldStyle}
          />
        </div>

        {error && (
          <p role="alert" style={{ color: 'var(--danger)', fontSize: 'var(--text-sm)' }}>
            {error}
          </p>
        )}

        <button
          type="button"
          disabled={!canSave}
          onClick={() => void save()}
          className="arch w-full py-4 font-semibold"
          style={{
            background: canSave ? 'var(--accent)' : 'var(--surface-muted)',
            color: canSave ? 'var(--accent-ink)' : 'var(--ink-muted)',
          }}
        >
          {saving ? t('masters.loading') : t('resin.save')}
        </button>
      </div>
    </Sheet>
  );
}
