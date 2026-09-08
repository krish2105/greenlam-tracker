/**
 * The AC Room: treated paper, assembled against a press load.
 *
 * WHY IT IS NOT THE PRESS FORM
 *
 * Nothing is made here. Treated paper arrives, it is conditioned and issued for
 * a particular load, and what gets recorded is how many sheets went through and
 * how many did not survive. There is no design, no size, no texture to choose —
 * the press form's four dropdowns would all be unanswerable, and a form full of
 * fields an operator must skip teaches them to skip the ones that matter too.
 *
 * The Load No. is the whole point of the entry. It is not required here the way
 * it is at the press — V5 §6.2A says the AC room carries it *where* paper is
 * being assembled for a particular load, which is most of the time but not a
 * rule — so it is asked for first and prominently, and left to the operator.
 *
 * The pack-order photo (V5 §6.2) is taken AFTER the entry is saved, not before.
 * The entry needs an id for the photo to hang off, and asking for a photo
 * first would mean holding the counts in limbo while somebody hunts for the
 * paperwork. "when normally available" is V5's own wording, so it is offered
 * rather than required.
 */

import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';

import * as api from '../../lib/api';
import { PhotoButton } from './PhotoButton';
import { Sheet } from '../Sheet';

export function ACRoomSheet({
  machine,
  onClose,
  onLogged,
  onDrafted,
  draft = null,
}: {
  machine: api.Machine;
  onClose: () => void;
  onLogged: () => void;
  /** Saved half-finished (V5 §6.3). It reaches nothing until Done. */
  onDrafted: () => void;
  /** Resuming an unfinished AC room entry. */
  draft?: api.ProductionDraft | null;
}) {
  const { t } = useTranslation();

  const [shifts, setShifts] = useState<api.Shift[]>([]);
  const [reasons, setReasons] = useState<api.RejectReason[]>([]);
  const [shiftId, setShiftId] = useState<number | null>(draft?.shift_id ?? null);

  const [loadNo, setLoadNo] = useState(draft?.load_no ?? '');
  const [processed, setProcessed] = useState(
    draft ? String(draft.produced_qty || '') : '',
  );
  const [rejected, setRejected] = useState(draft ? String(draft.rejected_qty) : '0');
  const [reasonId, setReasonId] = useState<number | null>(draft?.reject_reason_id ?? null);

  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [savedId, setSavedId] = useState<string | null>(null);

  useEffect(() => {
    void Promise.all([
      api.listShifts().catch(() => []),
      api.listRejectReasons().catch(() => []),
    ]).then(([sh, r]) => {
      setShifts(sh);
      setReasons(r);
      if (sh.length) setShiftId(sh[0]!.id);
    });
  }, []);

  const processedCount = Number(processed) || 0;
  const rejectedCount = Number(rejected) || 0;

  const field = {
    borderColor: 'var(--line-strong)',
    background: 'var(--surface)',
    color: 'var(--ink)',
  } as const;
  const labelStyle = { fontSize: 'var(--text-sm)', color: 'var(--ink)' } as const;

  function fields() {
    return {
      machine_id: machine.id,
      shift_id: shiftId,
      load_no: loadNo.trim() || null,
      // Deliberately absent: the AC room has no size or texture to report.
      produced_qty: processedCount,
      rejected_qty: rejectedCount,
      reject_reason_id: rejectedCount > 0 ? reasonId : null,
    };
  }

  /**
   * Save for later (V5 §6.3).
   *
   * The AC room writes to the same table as the press, so it gets the same
   * half-finished state. Nothing is validated: a sheet count typed before the
   * reject reason is known is exactly what this holds.
   *
   * No pack-order photo step afterwards — a photo hangs off an entry, and a
   * draft is not one yet. It is offered when the entry is finished.
   */
  async function saveDraft() {
    setBusy(true);
    setError('');
    try {
      if (draft) await api.updateDraft(draft.id, fields());
      else await api.logProduction({ ...fields(), draft: true });
      onDrafted();
    } catch (e) {
      setError(e instanceof Error ? e.message : t('production.errors.failed'));
    } finally {
      setBusy(false);
    }
  }

  async function submit() {
    if (!processedCount) return setError(t('production.errors.needQty'));
    if (rejectedCount > processedCount) return setError(t('production.errors.tooManyRejects'));
    if (rejectedCount > 0 && reasonId === null) return setError(t('production.errors.needReason'));

    setBusy(true);
    setError('');
    try {
      let row;
      if (draft) {
        // Values up first, then the Done press validates what is stored.
        await api.updateDraft(draft.id, fields());
        row = await api.submitProduction(draft.id);
      } else {
        row = await api.logProduction(fields());
      }
      // The counts are saved. The pack-order photo is offered next rather than
      // demanded first — the entry needs an id for a photo to hang off, and
      // holding the numbers hostage while somebody finds the paperwork is how
      // a shift's output goes unrecorded.
      setSavedId(row.id);
    } catch {
      setError(t('production.errors.failed'));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Sheet
      title={
        draft ? t('production.resumeTitle') : t('acRoom.title', { machine: machine.code })
      }
      onClose={onClose}
    >
      <div className="space-y-5">
        <div>
          <label htmlFor="ac-load" className="mb-1 block font-medium" style={labelStyle}>
            {t('production.loadNoOptional')}
          </label>
          <input
            id="ac-load"
            value={loadNo}
            onChange={(e) => setLoadNo(e.target.value.toUpperCase())}
            placeholder={t('production.loadNoPlaceholder')}
            autoComplete="off"
            autoCapitalize="characters"
            spellCheck={false}
            aria-describedby="ac-load-hint"
            className="arch w-full border px-3 py-3"
            style={field}
          />
          <p
            id="ac-load-hint"
            className="mt-1"
            style={{ fontSize: 'var(--text-xs)', color: 'var(--ink-muted)' }}
          >
            {t('acRoom.loadHint')}
          </p>
        </div>

        {shifts.length > 0 && (
          <fieldset>
            <legend className="mb-1 font-medium" style={labelStyle}>
              {t('production.shift')}
            </legend>
            <div className="grid grid-cols-3 gap-2">
              {shifts.map((s) => (
                <button
                  key={s.id}
                  type="button"
                  onClick={() => setShiftId(s.id)}
                  aria-pressed={s.id === shiftId}
                  className="arch border px-3 py-2.5 font-medium"
                  style={{
                    fontSize: 'var(--text-sm)',
                    borderColor: s.id === shiftId ? 'var(--accent)' : 'var(--line)',
                    background: s.id === shiftId ? 'var(--accent-quiet)' : 'var(--surface)',
                    color: s.id === shiftId ? 'var(--ink)' : 'var(--ink-muted)',
                  }}
                >
                  {s.name}
                </button>
              ))}
            </div>
          </fieldset>
        )}

        <div className="grid grid-cols-2 gap-3">
          <div>
            <label htmlFor="ac-processed" className="mb-1 block font-medium" style={labelStyle}>
              {t('acRoom.processed')}
            </label>
            <input
              id="ac-processed"
              value={processed}
              onChange={(e) => setProcessed(e.target.value.replace(/\D/g, ''))}
              inputMode="numeric"
              className="tabular arch w-full border px-3 py-3"
              style={field}
            />
          </div>
          <div>
            <label htmlFor="ac-rejected" className="mb-1 block font-medium" style={labelStyle}>
              {t('production.rejected')}
            </label>
            <input
              id="ac-rejected"
              value={rejected}
              onChange={(e) => setRejected(e.target.value.replace(/\D/g, ''))}
              inputMode="numeric"
              className="tabular arch w-full border px-3 py-3"
              style={field}
            />
          </div>
        </div>

        {/* Appears only when there is something to explain. */}
        {rejectedCount > 0 && (
          <fieldset>
            <legend className="mb-1 font-medium" style={labelStyle}>
              {t('production.rejectReason')}
            </legend>
            <div className="flex flex-wrap gap-2">
              {reasons.map((r) => (
                <button
                  key={r.id}
                  type="button"
                  onClick={() => setReasonId(r.id)}
                  aria-pressed={r.id === reasonId}
                  className="arch border px-3 py-2.5 font-medium"
                  style={{
                    fontSize: 'var(--text-sm)',
                    borderColor: r.id === reasonId ? 'var(--accent)' : 'var(--line)',
                    background: r.id === reasonId ? 'var(--accent-quiet)' : 'var(--surface)',
                    color: r.id === reasonId ? 'var(--ink)' : 'var(--ink-muted)',
                  }}
                >
                  {r.name}
                </button>
              ))}
            </div>
          </fieldset>
        )}

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

        {savedId ? (
          <div className="space-y-3">
            <p role="status" style={{ color: 'var(--primary)' }}>
              {t('acRoom.saved')}
            </p>
            <PhotoButton
              label={t('acRoom.packOrderPhoto')}
              onCapture={async (photo) => {
                await api.uploadProductionPhoto(savedId, photo);
              }}
            />
            <button
              type="button"
              onClick={onLogged}
              className="arch w-full py-4 font-semibold"
              style={{ background: 'var(--accent)', color: 'var(--accent-ink)' }}
            >
              {t('acRoom.done')}
            </button>
          </div>
        ) : (
          <>
            <button
              type="button"
              onClick={() => void submit()}
              disabled={busy}
              className="arch w-full py-4 font-semibold disabled:opacity-60"
              style={{ background: 'var(--accent)', color: 'var(--accent-ink)' }}
            >
              {busy ? t('production.submitting') : t('production.submit')}
            </button>

            <button
              type="button"
              onClick={() => void saveDraft()}
              disabled={busy}
              className="arch w-full border py-3 font-medium disabled:opacity-60"
              style={{ borderColor: 'var(--line-strong)', color: 'var(--ink)' }}
            >
              {t('production.saveDraft')}
            </button>
            <p style={{ fontSize: 'var(--text-xs)', color: 'var(--ink-muted)' }}>
              {t('production.draftHint')}
            </p>
          </>
        )}
      </div>
    </Sheet>
  );
}
