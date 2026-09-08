/**
 * The floor surface. Answer-first.
 *
 * The person holding this phone is standing next to a machine that has
 * stopped. They do not want a list; they want to know whether anything is
 * waiting on them and then to log the thing in front of them in under thirty
 * seconds. So the order is:
 *
 *   1. What needs you  — nothing else competes for the top of the screen
 *   2. Raise           — one large target, always reachable by thumb
 *   3. Everything else — the shift's open work, below the fold
 *
 * The previous version put a 33-row machine list here, which is the same
 * information arranged so that none of it is an answer.
 */

import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';

import { can, formatDuration } from '@greenlam/core';

import * as api from '../../lib/api';
import { NotificationCard } from '../NotificationCard';
import { ExceptionCard } from '../ExceptionCard';
import { PerformancePanel } from '../PerformancePanel';
import { LogProductionSheet } from './LogProductionSheet';
import { LogRollSheet } from './LogRollSheet';
import { RaiseSheet } from './RaiseSheet';
import { ScanSheet } from './ScanSheet';
import { TicketSheet } from './TicketSheet';

interface FloorViewProps {
  user: api.ApiUser;
  canRaise: boolean;
  canSeeTeam: boolean;
}

export function FloorView({ user, canRaise, canSeeTeam }: FloorViewProps) {
  const { t } = useTranslation();
  const [feed, setFeed] = useState<api.ExceptionFeed | null>(null);
  const [tickets, setTickets] = useState<api.Ticket[]>([]);
  const [handover, setHandover] = useState<api.Handover | null>(null);
  const [openTicket, setOpenTicket] = useState<string | null>(null);
  const [raising, setRaising] = useState(false);
  const [logging, setLogging] = useState(false);
  const [loggingRoll, setLoggingRoll] = useState(false);
  const [rollVerdict, setRollVerdict] = useState<api.ImpregnationRoll | null>(null);
  const [scanning, setScanning] = useState(false);
  const [scanned, setScanned] = useState<api.ScanResolution | null>(null);
  const [failed, setFailed] = useState(false);
  // "Nothing needs you right now" is a claim, not a placeholder. Rendering it
  // before the open tickets have arrived tells a technician the floor is clear
  // when it may not be — the one sentence on this screen that must never be
  // wrong.
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setFailed(false);
    try {
      const [f, ts, h] = await Promise.all([
        api.exceptions(),
        api.listTickets('open'),
        api.handover().catch(() => null),
      ]);
      setFeed(f);
      setTickets(ts);
      setHandover(h);
    } catch {
      setFailed(true);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  if (failed) {
    return (
      <div role="alert" className="py-8">
        <p style={{ color: 'var(--ink)' }}>{t('masters.loadFailed')}</p>
        <button
          type="button"
          onClick={() => void load()}
          className="arch mt-3 border px-4 py-2.5"
          style={{ borderColor: 'var(--line-strong)', color: 'var(--ink)' }}
        >
          {t('masters.retry')}
        </button>
      </div>
    );
  }

  const needsYou = feed?.items ?? [];

  return (
    <div className="pb-28">
      <Greeting name={user.name} count={needsYou.length} loading={loading} />

      {needsYou.length > 0 && (
        <section aria-labelledby="needs-you" className="mt-4">
          <h2 id="needs-you" className="sr-only">
            {t('floor.needsYou', { count: needsYou.length })}
          </h2>
          <ul className="space-y-2">
            {needsYou.map((item, i) => (
              <li key={`${item.machine_code}-${i}`}>
                <ExceptionCard
                  item={item}
                  onOpen={item.ticket_id ? () => setOpenTicket(item.ticket_id) : undefined}
                />
              </li>
            ))}
          </ul>
        </section>
      )}

      {handover && <HandoverStrip handover={handover} />}

      <section aria-labelledby="open-work" className="mt-6">
        <h2
          id="open-work"
          className="register-rule pb-1 font-semibold"
          style={{ fontSize: 'var(--text-sm)', color: 'var(--ink)' }}
        >
          {t('floor.openWork')}{' '}
          <span style={{ color: 'var(--ink-muted)', fontWeight: 400 }}>
            · {loading ? '—' : tickets.length}
          </span>
        </h2>

        {loading ? (
          <p className="py-6" style={{ color: 'var(--ink-muted)' }}>
            {t('masters.loading')}
          </p>
        ) : tickets.length === 0 ? (
          // An empty screen is an invitation, not a dead end. But it has to be
          // true first — "no open tickets" before the list has loaded is the
          // same lie as the greeting above.
          <p className="py-6" style={{ color: 'var(--ink-muted)' }}>
            {t('floor.allClear')}
          </p>
        ) : (
          <ul className="mt-2 space-y-2">
            {tickets.map((ticket) => (
              <li key={ticket.id}>
                <TicketRow ticket={ticket} onOpen={() => setOpenTicket(ticket.id)} />
              </li>
            ))}
          </ul>
        )}
      </section>

      {/* Below the work, above nothing. Somebody opens this screen to deal
          with a breakdown; turning on alerts is what they do once, on the day
          they are set up, and then never again. */}
      <NotificationCard />

      <PerformancePanel canSeeTeam={canSeeTeam} />

      {canRaise && (
        // Fixed to the thumb zone, above the safe-area inset. This is the one
        // control that has to be reachable without looking.
        <div
          className="fixed inset-x-0 bottom-0 z-30 border-t px-4 pt-3"
          style={{
            background: 'var(--surface)',
            borderColor: 'var(--line)',
            paddingBottom: 'max(0.75rem, env(safe-area-inset-bottom))',
          }}
        >
          <div className="mb-2 flex gap-2">
            <button
              type="button"
              onClick={() => setScanning(true)}
              className="arch flex flex-1 items-center justify-center gap-2 border py-3 font-medium"
              style={{ borderColor: 'var(--accent)', color: 'var(--ink)' }}
            >
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                <path d="M3 8V5a2 2 0 0 1 2-2h3M16 3h3a2 2 0 0 1 2 2v3M21 16v3a2 2 0 0 1-2 2h-3M8 21H5a2 2 0 0 1-2-2v-3M7 12h10" />
              </svg>
              {t('scan.button')}
            </button>
            <button
              type="button"
              onClick={() => setLogging(true)}
              className="arch flex-1 border py-3 font-medium"
              style={{ borderColor: 'var(--line-strong)', color: 'var(--ink)' }}
            >
              {t('production.logTitle')}
            </button>
          </div>
          {/* Impregnation sits beside production rather than inside it. A roll
              is not a sheet, and one combined form would show a press operator
              eight paper fields he can never fill. */}
          <button
            type="button"
            onClick={() => setLoggingRoll(true)}
            className="arch w-full border py-3 font-medium"
            style={{ borderColor: 'var(--line-strong)', color: 'var(--ink)' }}
          >
            {t('roll.button')}
          </button>
          <button
            type="button"
            onClick={() => setRaising(true)}
            className="arch flex w-full items-center justify-center gap-2 py-4 font-semibold"
            style={{ background: 'var(--accent)', color: 'var(--accent-ink)' }}
          >
            <svg
              width="20"
              height="20"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2.25"
              strokeLinecap="round"
              aria-hidden="true"
            >
              <path d="M12 5v14M5 12h14" />
            </svg>
            {t('floor.raise')}
          </button>
        </div>
      )}

      {scanning && (
        <ScanSheet
          onClose={() => setScanning(false)}
          onResolved={(result) => {
            // Straight from label to a prefilled ticket. That path is the whole
            // point: point, tap, type, submit.
            setScanning(false);
            setScanned(result);
            setRaising(true);
          }}
        />
      )}

      {raising && (
        <RaiseSheet
          prefill={scanned}
          onClose={() => {
            setRaising(false);
            setScanned(null);
          }}
          onRaised={(ticket) => {
            setRaising(false);
            if (scanned) {
              // Non-blocking: adoption telemetry must never delay a ticket.
              void api.recordScanOutcome(scanned.machine_id, 'ticket').catch(() => {});
              setScanned(null);
            }
            void load();
            setOpenTicket(ticket.id);
          }}
        />
      )}

      {loggingRoll && (
        <LogRollSheet
          onClose={() => setLoggingRoll(false)}
          onLogged={(roll) => {
            setLoggingRoll(false);
            // Out-of-spec rolls stay on screen a moment longer, because the
            // whole point is that the operator SEES the verdict rather than
            // the sheet closing on a silent flag.
            if (!roll.out_of_spec) void load();
            else {
              setRollVerdict(roll);
              void load();
            }
          }}
        />
      )}

      {rollVerdict && (
        <div
          role="alert"
          className="arch lift fixed inset-x-3 bottom-3 z-40 border px-4 py-3"
          style={{
            borderColor: 'var(--rust)',
            borderLeftWidth: '4px',
            background: 'var(--surface-raised)',
          }}
        >
          <p className="font-semibold" style={{ color: 'var(--rust)' }}>
            {t('roll.outOfSpec')} — {rollVerdict.roll_no}
          </p>
          {rollVerdict.spec_note && (
            <p className="mt-0.5" style={{ fontSize: 'var(--text-sm)', color: 'var(--ink)' }}>
              {rollVerdict.spec_note}
            </p>
          )}
          <button
            type="button"
            onClick={() => setRollVerdict(null)}
            className="arch mt-2 border px-3 py-1.5"
            style={{
              fontSize: 'var(--text-sm)',
              borderColor: 'var(--line-strong)',
              color: 'var(--ink)',
            }}
          >
            {t('common.close')}
          </button>
        </div>
      )}

      {logging && (
        <LogProductionSheet
          onClose={() => setLogging(false)}
          onLogged={() => {
            setLogging(false);
            void load();
          }}
        />
      )}

      {openTicket && (
        <TicketSheet
          ticketId={openTicket}
          onClose={() => setOpenTicket(null)}
          onChanged={() => void load()}
          canReassign={can(user.areas, 'reassignTicket')}
          canWork={can(user.areas, 'workTicket')}
        />
      )}
    </div>
  );
}

function Greeting({
  name,
  count,
  loading,
}: {
  name: string;
  count: number;
  loading: boolean;
}) {
  const { t } = useTranslation();
  const firstName = name.split(' ')[0] ?? name;
  return (
    <div className="pt-1">
      <p style={{ color: 'var(--ink-muted)', fontSize: 'var(--text-sm)' }}>
        {t('floor.greeting', { name: firstName })}
      </p>
      <p
        className="font-semibold"
        style={{ fontSize: 'var(--text-xl)', color: 'var(--ink)' }}
      >
        {loading
          ? t('floor.checking')
          : count === 0
            ? t('floor.nothingNeedsYou')
            : t('floor.needsYou', { count })}
      </p>
    </div>
  );
}

function HandoverStrip({ handover }: { handover: api.Handover }) {
  const { t } = useTranslation();
  return (
    <section
      aria-label={t('handover.title')}
      className="arch lift mt-5 border px-3 py-2.5"
      style={{ borderColor: 'var(--line)', background: 'var(--surface-muted)' }}
    >
      <p
        className="font-semibold"
        style={{ fontSize: 'var(--text-xs)', color: 'var(--ink-muted)' }}
      >
        {t('handover.title')}
      </p>
      {/* V5 §5.6's four counters. "Down" counted everything not fully closed
          before, which said a press was stopped when it had been running since
          Correction Complete and only the write-up was outstanding. Those are
          two different problems for two different people, so they are now two
          numbers. */}
      <p className="tabular mt-1" style={{ color: 'var(--ink)' }}>
        {t('handover.summary', {
          raised: handover.raised_in_shift,
          closed: handover.closed_in_shift,
          down: handover.machines_down,
        })}
      </p>
      {handover.rca_pending > 0 && (
        <p className="mt-1" style={{ fontSize: 'var(--text-sm)', color: 'var(--amber)' }}>
          {t('handover.rcaPending', { count: handover.rca_pending })}
        </p>
      )}
    </section>
  );
}

const PRIORITY_TONE: Record<string, string> = {
  Critical: 'var(--rust)',
  High: 'var(--amber)',
  Medium: 'var(--ink-muted)',
  Low: 'var(--ink-muted)',
};

function TicketRow({ ticket, onOpen }: { ticket: api.Ticket; onOpen: () => void }) {
  const { t } = useTranslation();
  const escalated = ticket.escalation.level !== 'none';
  const waiting = (Date.now() - Date.parse(ticket.raised_at)) / 60000;

  return (
    <button
      type="button"
      onClick={onOpen}
      className="arch lift w-full border px-3 py-3 text-left"
      style={{
        borderColor: escalated ? 'var(--rust)' : 'var(--line)',
        background: 'var(--surface)',
      }}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            {escalated && (
              <span
                className="pulse relative inline-block h-2 w-2 shrink-0 rounded-full"
                style={{ background: 'var(--rust)', color: 'var(--rust)' }}
                aria-hidden="true"
              />
            )}
            <span className="font-semibold" style={{ color: 'var(--ink)' }}>
              {ticket.machine_code}
            </span>
            <span
              className="font-medium"
              style={{
                fontSize: 'var(--text-xs)',
                color: PRIORITY_TONE[ticket.priority],
              }}
            >
              {ticket.priority}
            </span>
          </div>
          <p
            className="mt-0.5 truncate"
            style={{ fontSize: 'var(--text-sm)', color: 'var(--ink-muted)' }}
          >
            {ticket.description}
          </p>
        </div>
        <div className="shrink-0 text-right">
          <p className="tabular" style={{ fontSize: 'var(--text-sm)', color: 'var(--ink)' }}>
            {formatDuration(waiting)}
          </p>
          <p style={{ fontSize: 'var(--text-xs)', color: 'var(--ink-muted)' }}>
            {t(`stage.${ticket.stage}`)}
          </p>
        </div>
      </div>
    </button>
  );
}
