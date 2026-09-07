/**
 * One ticket, and whatever it needs next.
 *
 * The stage decides what is on screen. A technician who opens a ticket at
 * "repair" sees one field and one button, not a seven-stage form with six
 * sections greyed out.
 *
 * The diagnosis step is the important one. Three prompted why-levels replace
 * the single free-text box, and the quality score is shown to the person
 * typing, live, before they submit. That is deliberate: addendum §4.2 says
 * root-cause data decays into "belt issue" within a fortnight, and the cheapest
 * intervention is letting someone see their entry is thin while they can still
 * do something about it. The score is never shown to anyone above their
 * supervisor.
 */

import { useEffect, useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';

import { formatDuration, scoreRootCause } from '@greenlam/core';

import * as api from '../../lib/api';
import { CorrectSheet } from './CorrectSheet';
import { Sheet } from '../Sheet';

interface TicketSheetProps {
  ticketId: string;
  onClose: () => void;
  onChanged: () => void;
}

export function TicketSheet({ ticketId, onClose, onChanged }: TicketSheetProps) {
  const { t } = useTranslation();
  const [ticket, setTicket] = useState<api.Ticket | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const [correction, setCorrection] = useState('');
  const [why1, setWhy1] = useState('');
  const [why2, setWhy2] = useState('');
  const [why3, setWhy3] = useState('');
  const [prevention, setPrevention] = useState('');
  const [rating, setRating] = useState(0);
  const [correcting, setCorrecting] = useState(false);

  useEffect(() => {
    void api.getTicket(ticketId).then(setTicket).catch(() => setError(t('ticket.loadFailed')));
  }, [ticketId, t]);

  async function advance(event: api.TicketEventInput) {
    setBusy(true);
    setError('');
    try {
      setTicket(await api.advanceTicket(ticketId, event));
      onChanged();
    } catch (err) {
      setError(err instanceof api.ApiError ? err.message : t('ticket.actionFailed'));
    } finally {
      setBusy(false);
    }
  }

  if (!ticket) {
    return (
      <Sheet title={t('ticket.title')} onClose={onClose}>
        <p style={{ color: 'var(--ink-muted)' }}>{error || t('masters.loading')}</p>
      </Sheet>
    );
  }

  const waiting = (Date.now() - Date.parse(ticket.raised_at)) / 60000;

  return (
    <Sheet title={ticket.ticket_no ?? t('ticket.title')} onClose={onClose}>
      <div className="space-y-4 pb-4">
        <header>
          <div className="flex items-baseline gap-2">
            <h3
              className="font-semibold"
              style={{ fontSize: 'var(--text-xl)', color: 'var(--ink)' }}
            >
              {ticket.machine_code}
            </h3>
            {/* Two different facts, and they are never shown as one badge.
                The plate is how much this machine matters, which is known
                before anything breaks and is what ranks the queue. The second
                appears only once the repair is over and says how long the work
                actually took. A ticket mid-repair shows one; a resolved one
                shows both, and they routinely disagree — a quick fix on a
                critical press is exactly that. */}
            <span className="plate">{ticket.priority}</span>
            {ticket.criticality_calculated && (
              <span
                className="plate"
                title={t('ticket.solveTime', { minutes: ticket.solve_minutes ?? 0 })}
              >
                {t(`ticket.criticality.${ticket.criticality_calculated}`)}
              </span>
            )}
            {/* V5 §7: an amended record is marked wherever it is shown, so a
                number nobody expected to change is never read as the one that
                was logged at the time. */}
            {ticket.last_edited_at && (
              <span
                className="plate"
                title={t('ticket.editedBy', { name: ticket.last_edited_by_name ?? '—' })}
                style={{ borderColor: 'var(--rust)', color: 'var(--rust)' }}
              >
                {t('ticket.edited')}
              </span>
            )}
          </div>
          <p className="mt-1" style={{ color: 'var(--ink)' }}>
            {ticket.description}
          </p>
          <p
            className="tabular mt-1"
            style={{ fontSize: 'var(--text-sm)', color: 'var(--ink-muted)' }}
          >
            {t('ticket.raisedBy', {
              name: ticket.raised_by_name,
              ago: formatDuration(waiting),
            })}
          </p>
        </header>

        {ticket.escalation.level !== 'none' && (
          <p
            role="status"
            className="arch px-3 py-2 font-medium"
            style={{ background: 'var(--rust-tint)', color: 'var(--rust)' }}
          >
            {t('ticket.escalatedTo', {
              level: t(`escalation.${ticket.escalation.level}`),
              overdue: formatDuration(ticket.escalation.overdue_minutes),
            })}
          </p>
        )}

        {ticket.repeat_count > 1 && (
          <p
            className="arch px-3 py-2"
            style={{ background: 'var(--amber-tint)', color: 'var(--amber)' }}
          >
            {t('ticket.repeat', { count: ticket.repeat_count })}
          </p>
        )}

        <StageTrail stage={ticket.current_stage} />

        {ticket.immediate_correction && (
          <Detail label={t('ticket.correction')} value={ticket.immediate_correction} />
        )}
        {ticket.root_cause && (
          <Detail label={t('ticket.rootCause')} value={ticket.root_cause} />
        )}
        {ticket.preventive_action && (
          <Detail label={t('ticket.prevention')} value={ticket.preventive_action} />
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

        {/* One stage, one action. */}
        <div className="border-t pt-4" style={{ borderColor: 'var(--line)' }}>
          {ticket.current_stage === 0 && (
            <Action
              busy={busy}
              label={t('ticket.acknowledge')}
              onClick={() => void advance({ type: 'ACKNOWLEDGED' })}
            />
          )}

          {ticket.current_stage === 1 && (
            <div className="space-y-2">
              <Action
                busy={busy}
                label={t('ticket.noMaterial')}
                onClick={() =>
                  void advance({ type: 'MATERIAL_RECORDED', material_source: 'none' })
                }
              />
              <p style={{ fontSize: 'var(--text-xs)', color: 'var(--ink-muted)' }}>
                {t('ticket.materialLater')}
              </p>
            </div>
          )}

          {ticket.current_stage === 2 && (
            <Action
              busy={busy}
              label={t('ticket.startRepair')}
              onClick={() => void advance({ type: 'REPAIR_STARTED' })}
            />
          )}

          {ticket.current_stage === 3 && (
            <Field
              id="correction"
              label={t('ticket.correctionPrompt')}
              value={correction}
              onChange={setCorrection}
              placeholder={t('ticket.correctionPlaceholder')}
              action={
                <Action
                  busy={busy}
                  label={t('ticket.markResolved')}
                  onClick={() =>
                    void advance({
                      type: 'RESOLVED',
                      immediate_correction: correction,
                    })
                  }
                />
              }
            />
          )}

          {ticket.current_stage === 4 && (
            <WhyWhy
              why1={why1}
              why2={why2}
              why3={why3}
              prevention={prevention}
              setWhy1={setWhy1}
              setWhy2={setWhy2}
              setWhy3={setWhy3}
              setPrevention={setPrevention}
              busy={busy}
              onSubmit={() =>
                void advance({
                  type: 'DIAGNOSED',
                  why_1: why1,
                  why_2: why2,
                  why_3: why3,
                  preventive_action: prevention,
                })
              }
            />
          )}

          {ticket.current_stage === 5 && (
            <div className="space-y-3">
              <p className="font-medium" style={{ color: 'var(--ink)' }}>
                {t('ticket.ratePrompt')}
              </p>
              <div className="flex gap-1" role="radiogroup" aria-label={t('ticket.ratePrompt')}>
                {[1, 2, 3, 4, 5].map((n) => (
                  <button
                    key={n}
                    type="button"
                    role="radio"
                    aria-checked={n === rating}
                    aria-label={t('ticket.stars', { count: n })}
                    onClick={() => setRating(n)}
                    className="flex h-12 w-12 items-center justify-center"
                    style={{ color: n <= rating ? 'var(--amber)' : 'var(--line-strong)' }}
                  >
                    <svg width="26" height="26" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
                      <path d="m12 2 3 6.5 7 .9-5 4.9 1.2 7L12 18l-6.2 3.3L7 14.3l-5-4.9 7-.9z" />
                    </svg>
                  </button>
                ))}
              </div>
              <Action
                busy={busy || rating === 0}
                label={t('ticket.verifyClose')}
                onClick={() => void advance({ type: 'CLOSED', rating })}
              />
            </div>
          )}

          {ticket.current_stage === 6 && (
            <div className="space-y-3">
              <p style={{ color: 'var(--primary)' }}>
                {t('ticket.closed', {
                  duration: formatDuration(ticket.downtime_minutes ?? 0),
                })}
              </p>
              {/* Two different actions, two different sentences.
                  Reopen says the machine is still broken and puts this back on
                  the breakdown board. Correct says a word was wrong. They sit
                  together because that is where somebody looks for either, and
                  they are never one button with a mode. */}
              <button
                type="button"
                onClick={() => void advance({ type: 'REOPENED' })}
                disabled={busy}
                className="arch w-full border py-3 font-medium disabled:opacity-60"
                style={{ borderColor: 'var(--line-strong)', color: 'var(--ink)' }}
              >
                {t('ticket.reopen')}
              </button>
              <button
                type="button"
                onClick={() => setCorrecting(true)}
                disabled={busy}
                className="arch w-full border py-3 font-medium disabled:opacity-60"
                style={{ borderColor: 'var(--line)', color: 'var(--ink-muted)' }}
              >
                {t('ticket.correct')}
              </button>
              <p style={{ color: 'var(--ink-muted)', fontSize: 'var(--text-xs)' }}>
                {t('ticket.correctHint')}
              </p>
            </div>
          )}
        </div>
      </div>

      {correcting && (
        <CorrectSheet
          ticket={ticket}
          onClose={() => setCorrecting(false)}
          onCorrected={() => {
            setCorrecting(false);
            // Reload the ticket, not just the list behind it. A correction
            // that left the sheet showing the value it just replaced is the
            // one moment somebody would reasonably conclude it had not saved.
            void api.getTicket(ticketId).then(setTicket).catch(() => undefined);
            onChanged();
          }}
        />
      )}
    </Sheet>
  );
}

/**
 * The guided why-why, with live quality feedback.
 *
 * The score is computed by the same `packages/core` function the server uses,
 * so what the technician sees while typing is exactly what gets stored.
 */
function WhyWhy({
  why1,
  why2,
  why3,
  prevention,
  setWhy1,
  setWhy2,
  setWhy3,
  setPrevention,
  busy,
  onSubmit,
}: {
  why1: string;
  why2: string;
  why3: string;
  prevention: string;
  setWhy1: (v: string) => void;
  setWhy2: (v: string) => void;
  setWhy3: (v: string) => void;
  setPrevention: (v: string) => void;
  busy: boolean;
  onSubmit: () => void;
}) {
  const { t } = useTranslation();
  const quality = scoreRootCause({
    why1,
    why2,
    why3,
    preventiveAction: prevention,
  });
  const touched = Boolean(why1.trim());

  return (
    <div className="space-y-3">
      <p className="font-medium" style={{ color: 'var(--ink)' }}>
        {t('ticket.whyTitle')}
      </p>

      <WhyField id="why1" n={1} value={why1} onChange={setWhy1} />
      <WhyField id="why2" n={2} value={why2} onChange={setWhy2} />
      <WhyField id="why3" n={3} value={why3} onChange={setWhy3} />

      <div>
        <label
          htmlFor="prevention"
          className="mb-1 block font-medium"
          style={{ fontSize: 'var(--text-sm)', color: 'var(--ink)' }}
        >
          {t('ticket.preventionPrompt')}
        </label>
        <textarea
          id="prevention"
          value={prevention}
          onChange={(e) => setPrevention(e.target.value)}
          rows={2}
          placeholder={t('ticket.preventionPlaceholder')}
          className="arch w-full border px-3 py-2.5"
          style={{
            borderColor: 'var(--line-strong)',
            background: 'var(--surface)',
            color: 'var(--ink)',
          }}
        />
      </div>

      {touched && (
        // Shown to the person typing, never sent upward with their name.
        <div
          className="arch px-3 py-2.5"
          aria-live="polite"
          style={{
            background: quality.usable ? 'var(--primary-tint)' : 'var(--amber-tint)',
            color: quality.usable ? 'var(--primary)' : 'var(--amber)',
          }}
        >
          <p className="font-medium" style={{ fontSize: 'var(--text-sm)' }}>
            {quality.usable ? t('ticket.qualityGood') : t('ticket.qualityThin')}
          </p>
          {!quality.usable && quality.reasons.length > 0 && (
            <ul className="mt-1 list-disc pl-4" style={{ fontSize: 'var(--text-xs)' }}>
              {quality.reasons.slice(0, 2).map((reason) => (
                <li key={reason}>{reason}</li>
              ))}
            </ul>
          )}
        </div>
      )}

      <Action busy={busy} label={t('ticket.saveRootCause')} onClick={onSubmit} />
    </div>
  );
}

function WhyField({
  id,
  n,
  value,
  onChange,
}: {
  id: string;
  n: number;
  value: string;
  onChange: (v: string) => void;
}) {
  const { t } = useTranslation();
  return (
    <div>
      <label
        htmlFor={id}
        className="mb-1 block"
        style={{ fontSize: 'var(--text-sm)', color: 'var(--ink-muted)' }}
      >
        <span className="font-semibold" style={{ color: 'var(--ink)' }}>
          {t('ticket.whyN', { n })}
        </span>{' '}
        {t(`ticket.whyHint${n}`)}
      </label>
      <textarea
        id={id}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        rows={2}
        className="arch w-full border px-3 py-2.5"
        style={{
          borderColor: 'var(--line-strong)',
          background: 'var(--surface)',
          color: 'var(--ink)',
        }}
      />
    </div>
  );
}

function Field({
  id,
  label,
  value,
  onChange,
  placeholder,
  action,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder: string;
  action: ReactNode;
}) {
  return (
    <div className="space-y-3">
      <div>
        <label
          htmlFor={id}
          className="mb-1 block font-medium"
          style={{ fontSize: 'var(--text-sm)', color: 'var(--ink)' }}
        >
          {label}
        </label>
        <textarea
          id={id}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          rows={2}
          placeholder={placeholder}
          className="arch w-full border px-3 py-2.5"
          style={{
            borderColor: 'var(--line-strong)',
            background: 'var(--surface)',
            color: 'var(--ink)',
          }}
        />
      </div>
      {action}
    </div>
  );
}

function Action({
  label,
  onClick,
  busy,
}: {
  label: string;
  onClick: () => void;
  busy: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={busy}
      className="arch w-full py-4 font-semibold disabled:opacity-60"
      style={{ background: 'var(--accent)', color: 'var(--accent-ink)' }}
    >
      {label}
    </button>
  );
}

function Detail({ label, value }: { label: string; value: string }) {
  return (
    <div className="arch px-3 py-2.5" style={{ background: 'var(--surface-muted)' }}>
      <p style={{ fontSize: 'var(--text-xs)', color: 'var(--ink-muted)' }}>{label}</p>
      <p className="mt-0.5" style={{ color: 'var(--ink)' }}>
        {value}
      </p>
    </div>
  );
}

const TRAIL = ['raised', 'ack', 'material', 'repair', 'resolved', 'diagnosis', 'closed'];

function StageTrail({ stage }: { stage: number }) {
  const { t } = useTranslation();
  return (
    <ol className="flex items-center gap-1" aria-label={t('ticket.progress')}>
      {TRAIL.map((name, i) => {
        const done = i < stage;
        const current = i === stage;
        return (
          <li key={name} className="flex-1">
            <span className="sr-only">
              {t(`stage.${name}`)}
              {current ? ` — ${t('ticket.current')}` : ''}
            </span>
            <span
              aria-hidden="true"
              className="block h-1.5 rounded-full"
              style={{
                background: done
                  ? 'var(--primary)'
                  : current
                    ? 'var(--accent)'
                    : 'var(--line)',
              }}
            />
          </li>
        );
      })}
    </ol>
  );
}
