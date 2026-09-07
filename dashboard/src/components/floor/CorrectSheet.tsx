/**
 * Fix a mistake on a ticket that has already closed (V5 §7).
 *
 * WHY THIS IS A SEPARATE SHEET FROM REOPEN
 *
 * They are one keystroke apart in the interface and worlds apart in meaning.
 * Reopen says the machine is still broken and sends the ticket back into the
 * live Pending count. Correct says a word was wrong and changes nothing else.
 * A person reaching for the wrong one puts a working press back on the
 * breakdown board, so they get different words, different colours and
 * different screens — never the same button with a mode.
 *
 * WHAT IT DOES NOT OFFER
 *
 * Timestamps. They are correctable through the API and deliberately not here:
 * moving a recorded time re-measures the repair and re-bands its criticality,
 * which is a thing to do deliberately from a desk after looking at the event
 * log, not from a phone on a noisy floor. Machine, status and stage are not
 * correctable anywhere — a ticket raised against the wrong machine is a new
 * ticket, not an edit.
 */

import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';

import * as api from '../../lib/api';
import { Sheet } from '../Sheet';

/**
 * The fields a person on the floor can sensibly re-read and fix.
 *
 * The locale key is derived from the API field name rather than written out,
 * so a field here and the same field in the correction history below cannot
 * end up labelled two different ways.
 */
const FIELDS = [
  { key: 'description', rows: 3 },
  { key: 'immediate_correction', rows: 2 },
  { key: 'why_1', rows: 2 },
  { key: 'why_2', rows: 2 },
  { key: 'why_3', rows: 2 },
  { key: 'preventive_action', rows: 2 },
] as const;

export function CorrectSheet({
  ticket,
  onClose,
  onCorrected,
}: {
  ticket: api.Ticket;
  onClose: () => void;
  onCorrected: () => void;
}) {
  const { t } = useTranslation();

  const initial = Object.fromEntries(
    FIELDS.map((f) => [f.key, (ticket[f.key as keyof api.Ticket] as string | null) ?? '']),
  ) as Record<string, string>;

  const [values, setValues] = useState<Record<string, string>>(initial);
  const [reason, setReason] = useState('');
  const [history, setHistory] = useState<api.CorrectionEntry[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    void api
      .ticketCorrections(ticket.id)
      .then(setHistory)
      .catch(() => setHistory([]));
  }, [ticket.id]);

  // Only what actually moved is sent. A field re-saved with the value it
  // already had is not a correction, and sending it would put a row in the
  // audit log saying nothing happened.
  const changes = Object.fromEntries(
    Object.entries(values).filter(([k, v]) => v !== initial[k]),
  );
  const nothingChanged = Object.keys(changes).length === 0;

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
      // Empty means cleared, which is a real correction — a why that was
      // filled in by mistake should be able to go back to blank.
      const payload = Object.fromEntries(
        Object.entries(changes).map(([k, v]) => [k, v.trim() || null]),
      );
      await api.correctTicket(ticket.id, payload, reason.trim() || undefined);
      onCorrected();
    } catch (e) {
      setError(e instanceof Error ? e.message : t('correct.failed'));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Sheet title={t('correct.title', { ticket: ticket.ticket_no ?? '' })} onClose={onClose}>
      <div className="space-y-5">
        <p style={{ color: 'var(--ink-muted)', fontSize: 'var(--text-sm)' }}>
          {t('correct.blurb')}
        </p>

        {FIELDS.map((f) => (
          <div key={f.key}>
            <label htmlFor={`c-${f.key}`} className="mb-1 block font-medium" style={labelStyle}>
              {t(`correct.fields.${f.key}`)}
            </label>
            <textarea
              id={`c-${f.key}`}
              rows={f.rows}
              value={values[f.key] ?? ''}
              onChange={(e) => setValues((v) => ({ ...v, [f.key]: e.target.value }))}
              className="arch w-full border px-3 py-3"
              style={{
                ...field,
                // The fields being changed are marked as you type, so it is
                // obvious at a glance what this correction will touch.
                borderColor:
                  values[f.key] !== initial[f.key] ? 'var(--accent)' : 'var(--line-strong)',
              }}
            />
          </div>
        ))}

        <div>
          <label htmlFor="c-reason" className="mb-1 block font-medium" style={labelStyle}>
            {t('correct.reason')}
          </label>
          <input
            id="c-reason"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder={t('correct.reasonPlaceholder')}
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
          disabled={busy || nothingChanged}
          className="arch w-full py-4 font-semibold disabled:opacity-60"
          style={{ background: 'var(--accent)', color: 'var(--accent-ink)' }}
        >
          {busy ? t('correct.saving') : t('correct.save')}
        </button>

        {/* What has already been changed. Shown here rather than on a separate
            screen because the question "has somebody already fixed this?" only
            ever comes up at the moment you are about to fix it yourself. */}
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
                  {h.reason && (
                    <span
                      className="mt-1 block"
                      style={{ color: 'var(--ink-muted)', fontSize: 'var(--text-xs)' }}
                    >
                      {h.reason}
                    </span>
                  )}
                </li>
              ))}
            </ul>
          </section>
        )}
      </div>
    </Sheet>
  );
}
