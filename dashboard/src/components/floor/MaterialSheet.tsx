/**
 * Does this repair need a part, and is it here yet? (V5 §5.2)
 *
 * WHY THIS SCREEN DECIDES WHETHER THE NUMBERS MEAN ANYTHING
 *
 * Criticality is banded on Solve Time, and Solve Time is
 *
 *     (correction complete − correction started) − time spent waiting
 *
 * The subtraction only happens if somebody records the waiting. Until this
 * screen existed there was no way to, so every wait counted as repair work: a
 * twenty-minute fix that sat three hours for a bearing was banded as a
 * three-hour repair, and on a press that is the difference between Low and
 * High. Silently, on every ticket, for as long as nobody noticed.
 *
 * So the two buttons here are not paperwork. They are what makes the plant's
 * repair times true.
 *
 * WHAT IT DELIBERATELY DOES NOT ASK
 *
 * Cost, vendor, PO number. The API accepts all three and a technician standing
 * at a stores counter with a stopped press behind them does not have any of
 * them. They belong on a desk, later, through the Correct path — not between a
 * broken machine and the person fixing it.
 */

import { useState } from 'react';
import { useTranslation } from 'react-i18next';

import * as api from '../../lib/api';
import { PhotoButton } from './PhotoButton';
import { Sheet } from '../Sheet';

type Step = 'ask' | 'details';

export function MaterialSheet({
  ticket,
  onClose,
  onDone,
}: {
  ticket: api.Ticket;
  onClose: () => void;
  onDone: () => void;
}) {
  const { t } = useTranslation();

  const [step, setStep] = useState<Step>('ask');
  const [source, setSource] = useState<'store' | 'purchase'>('store');
  const [name, setName] = useState('');
  const [bin, setBin] = useState('');
  const [busy, setBusy] = useState(false);
  const [photoTaken, setPhotoTaken] = useState(false);
  const [error, setError] = useState('');

  const field = {
    borderColor: 'var(--line-strong)',
    background: 'var(--surface)',
    color: 'var(--ink)',
  } as const;
  const labelStyle = { fontSize: 'var(--text-sm)', color: 'var(--ink)' } as const;

  async function record(needed: boolean) {
    setBusy(true);
    setError('');
    try {
      await api.advanceTicket(ticket.id, {
        type: 'MATERIAL_RECORDED',
        material_source: needed ? source : 'none',
        material_name: needed ? name.trim() || undefined : undefined,
        material_bin: needed && bin.trim() ? bin.trim() : undefined,
      });
      // Recording the need and starting the wait are two acts, and the second
      // is optional: a part that is on the shelf never stops the clock. So the
      // hold is offered from the ticket, not forced here.
      onDone();
    } catch (e) {
      setError(e instanceof Error ? e.message : t('material.failed'));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Sheet title={t('material.title', { machine: ticket.machine_code })} onClose={onClose}>
      <div className="space-y-5">
        {step === 'ask' ? (
          <>
            <p style={{ color: 'var(--ink-muted)', fontSize: 'var(--text-sm)' }}>
              {t('material.askBody')}
            </p>

            <button
              type="button"
              onClick={() => setStep('details')}
              disabled={busy}
              className="arch w-full border py-4 font-semibold disabled:opacity-60"
              style={{
                borderColor: 'var(--accent)',
                background: 'var(--accent-quiet)',
                color: 'var(--ink)',
              }}
            >
              {t('material.yes')}
            </button>

            <button
              type="button"
              onClick={() => void record(false)}
              disabled={busy}
              className="arch w-full border py-4 font-medium disabled:opacity-60"
              style={{ borderColor: 'var(--line-strong)', color: 'var(--ink)' }}
            >
              {busy ? t('material.saving') : t('material.no')}
            </button>
          </>
        ) : (
          <>
            <fieldset>
              <legend className="mb-1 font-medium" style={labelStyle}>
                {t('material.source')}
              </legend>
              <div className="grid grid-cols-2 gap-2">
                {(['store', 'purchase'] as const).map((s) => (
                  <button
                    key={s}
                    type="button"
                    onClick={() => setSource(s)}
                    aria-pressed={source === s}
                    className="arch border px-3 py-3 font-medium"
                    style={{
                      fontSize: 'var(--text-sm)',
                      borderColor: source === s ? 'var(--accent)' : 'var(--line)',
                      background: source === s ? 'var(--accent-quiet)' : 'var(--surface)',
                      color: source === s ? 'var(--ink)' : 'var(--ink-muted)',
                    }}
                  >
                    {t(`material.${s}`)}
                  </button>
                ))}
              </div>
            </fieldset>

            <div>
              <label htmlFor="mat-name" className="mb-1 block font-medium" style={labelStyle}>
                {t('material.what')}
              </label>
              <input
                id="mat-name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder={t('material.whatPlaceholder')}
                autoComplete="off"
                className="arch w-full border px-3 py-3"
                style={field}
              />
            </div>

            {source === 'store' && (
              <div>
                <label htmlFor="mat-bin" className="mb-1 block font-medium" style={labelStyle}>
                  {t('material.bin')}
                </label>
                <input
                  id="mat-bin"
                  value={bin}
                  onChange={(e) => setBin(e.target.value)}
                  autoComplete="off"
                  className="arch w-full border px-3 py-3"
                  style={field}
                />
              </div>
            )}

            {/* V5 §5.4 asks for a photo of the receipt and the material. Not
                blocking here: a technician at a stores counter with a stopped
                press behind them may not have the receipt in hand yet, and a
                gate at this point would be answered by photographing anything.
                The gate that matters is on Resume — the claim with a number
                attached. */}
            <PhotoButton
              label={t('photo.takeReceiptPhoto')}
              done={photoTaken}
              onCapture={async (photo) => {
                await api.uploadTicketPhoto(ticket.id, 'material', photo);
                setPhotoTaken(true);
              }}
            />

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
              onClick={() => void record(true)}
              disabled={busy || !name.trim()}
              className="arch w-full py-4 font-semibold disabled:opacity-60"
              style={{ background: 'var(--accent)', color: 'var(--accent-ink)' }}
            >
              {busy ? t('material.saving') : t('material.save')}
            </button>

            <p style={{ color: 'var(--ink-muted)', fontSize: 'var(--text-xs)' }}>
              {t('material.thenHold')}
            </p>
          </>
        )}
      </div>
    </Sheet>
  );
}
