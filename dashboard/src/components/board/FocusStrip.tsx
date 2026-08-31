/**
 * What a click on a chart is actually for.
 *
 * Making the charts clickable is easy; deciding where a click GOES is the real
 * design question, and "open the ticket list filtered by this machine" is the
 * wrong answer for this audience. A shareholder and a board member both see
 * `ticket_id: null` by design (§4.1 redaction), so a drill-through that lands
 * on a ticket is a dead end for exactly the people who spend the most time on
 * this screen.
 *
 * So a click assembles instead of navigating. Every dataset on the board is
 * already loaded and every one of them is keyed by machine or by cause; they
 * are simply never joined, so the reader does the join by scrolling between
 * four charts and holding numbers in their head. This strip does that join:
 * pick Press-4 anywhere and see its downtime, its failure count, its MTBF, its
 * reject rate and whether it is alerting right now — in one line, sourced from
 * data already in memory, with no extra request and nothing that can 403.
 *
 * The open-ticket button appears only when the reader's tier actually has a
 * ticket id. Absent capability renders nothing rather than a disabled control,
 * because a greyed-out button invites a support call about permissions.
 */

import { useTranslation } from 'react-i18next';

import type {
  Analytics,
  ExceptionFeed,
  ParetoSlice,
  ProductionAnalytics,
} from '../../lib/api';
import { useSectionName } from '../../lib/masterNames';
import { formatHours } from '../charts/primitives';

export type BoardFocus =
  | { kind: 'machine'; code: string }
  | { kind: 'cause'; label: string };

export function FocusStrip({
  focus,
  stats,
  prod,
  feed,
  onOpenTicket,
  onDismiss,
}: {
  focus: BoardFocus;
  stats: Analytics | null;
  prod: ProductionAnalytics | null;
  feed: ExceptionFeed | null;
  onOpenTicket?: (ticketId: string) => void;
  onDismiss: () => void;
}) {
  const { t } = useTranslation();
  const sectionName = useSectionName();

  const facts: { label: string; value: string }[] = [];
  let title = '';
  let subtitle: string | null = null;
  let liveTicket: string | null = null;

  if (focus.kind === 'machine') {
    const machine = stats?.top_machines.find((m) => m.machine_code === focus.code);
    const reject = prod?.by_machine.find((r) => r.label === focus.code);
    const exception = feed?.items.find((i) => i.machine_code === focus.code);
    const correlation = prod?.breakdown_correlation.find(
      (c) => c.machine_code === focus.code,
    );

    title = focus.code;
    subtitle = machine ? sectionName(machine.section_name) : null;
    liveTicket = exception?.ticket_id ?? null;

    if (machine) {
      facts.push({ label: t('chart.downtime'), value: formatHours(machine.minutes) });
      facts.push({ label: t('chart.issues'), value: String(machine.count) });
      if (machine.mtbf_hours) {
        facts.push({ label: 'MTBF', value: `${machine.mtbf_hours}h` });
      }
    }
    if (reject) {
      facts.push({ label: t('production.rejectRate'), value: `${reject.reject_percent}%` });
      facts.push({
        label: t('production.sheets'),
        value: reject.produced.toLocaleString('en-IN'),
      });
    }
    // The one fact on this strip that is predictive rather than historical.
    if (correlation) {
      facts.push({
        label: t('focus.qualityLift'),
        value: `+${correlation.lift_percent}%`,
      });
    }
  } else {
    const slice: ParetoSlice | undefined = stats?.pareto_by_cause.find(
      (p) => p.label === focus.label,
    );
    title = focus.label;
    subtitle = t('focus.causeSubtitle');
    if (slice) {
      facts.push({ label: t('chart.downtime'), value: formatHours(slice.minutes) });
      facts.push({ label: t('chart.issues'), value: String(slice.count) });
      facts.push({
        label: t('chart.cumulative'),
        value: `${slice.cumulative_percent}%`,
      });
      if (slice.count > 0) {
        facts.push({
          label: t('focus.averagePerEvent'),
          value: formatHours(slice.minutes / slice.count),
        });
      }
    }
  }

  const alerting =
    focus.kind === 'machine' &&
    (feed?.items.some((i) => i.machine_code === focus.code) ?? false);

  return (
    <div
      className="arch lift sticky z-30 border px-4 py-3"
      role="status"
      style={{
        // Clears AppHeader, which is `sticky top-0 z-20`. Without the offset
        // the strip slides underneath the header and the reader loses the very
        // thing they just clicked on.
        top: 'calc(var(--header-h, 4.5rem) + 0.5rem)',
        borderColor: 'var(--line-strong)',
        borderLeft: `4px solid ${alerting ? 'var(--rust)' : 'var(--viz-1)'}`,
        background: 'var(--surface-raised)',
      }}
    >
      <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
        <div className="min-w-0">
          <p className="font-semibold" style={{ color: 'var(--ink)' }}>
            {title}
            {alerting && (
              <span
                className="arch ml-2 px-1.5 py-0.5 align-middle"
                style={{
                  fontSize: 'var(--text-xs)',
                  background: 'var(--rust-tint)',
                  color: 'var(--rust)',
                }}
              >
                {t('focus.alerting')}
              </span>
            )}
          </p>
          {subtitle && (
            <p style={{ fontSize: 'var(--text-xs)', color: 'var(--ink-muted)' }}>{subtitle}</p>
          )}
        </div>

        <div className="flex shrink-0 items-center gap-2">
          {liveTicket && onOpenTicket && (
            <button
              type="button"
              onClick={() => onOpenTicket(liveTicket)}
              className="arch min-h-[36px] px-3 font-medium"
              style={{
                fontSize: 'var(--text-sm)',
                background: 'var(--accent)',
                color: 'var(--accent-ink)',
              }}
            >
              {t('focus.openTicket')}
            </button>
          )}
          <button
            type="button"
            onClick={onDismiss}
            className="arch min-h-[36px] border px-3"
            style={{
              fontSize: 'var(--text-sm)',
              borderColor: 'var(--line-strong)',
              color: 'var(--ink-muted)',
            }}
          >
            {t('common.close')}
          </button>
        </div>
      </div>

      {facts.length > 0 ? (
        <dl className="mt-3 flex flex-wrap gap-x-6 gap-y-2">
          {facts.map((f) => (
            <div key={f.label}>
              <dt style={{ fontSize: 'var(--text-xs)', color: 'var(--ink-muted)' }}>
                {f.label}
              </dt>
              <dd
                className="tabular font-semibold"
                style={{ fontSize: 'var(--text-lg)', color: 'var(--ink)' }}
              >
                {f.value}
              </dd>
            </div>
          ))}
        </dl>
      ) : (
        // Not the same sentence as "there is no data" — this reader may simply
        // not be scoped to it, and conflating the two is the CEO-sees-zero bug.
        <p className="mt-2" style={{ fontSize: 'var(--text-sm)', color: 'var(--ink-muted)' }}>
          {t('focus.noDetail')}
        </p>
      )}
    </div>
  );
}
