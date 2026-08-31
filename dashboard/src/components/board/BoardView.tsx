/**
 * The board surface. Control-room density.
 *
 * Brief from the spec: glanceable in ten seconds from across a room, drillable
 * in three clicks. A plant head opens this between meetings, or it runs
 * permanently on a wall screen in the maintenance office.
 *
 * Reading order is deliberate:
 *   1. Six headline numbers, each with a sparkline, so a figure carries a
 *      direction rather than sitting alone
 *   2. What needs attention — the action queue, because a report you cannot
 *      act on is just a report
 *   3. Why: the Pareto, then the daily trend
 *   4. Where: worst machines, then sections
 *   5. How trustworthy the data is: root-cause quality
 *
 * Every tier above the floor renders this same component. What differs is what
 * the API returns — a corporate role gets aggregates and a redacted feed with
 * nothing to click. That decision lives on the server; this file only lays out
 * what arrived.
 */

import { useCallback, useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';

import { formatDuration, sectionColour, toneForDelta } from '@greenlam/core';

import * as api from '../../lib/api';
import { DowntimeTrendChart } from '../charts/DowntimeTrend';
import { MttrTrend, Sparkline } from '../charts/MttrTrend';
import { ParetoChart } from '../charts/ParetoChart';
import { TopMachines } from '../charts/TopMachines';
import { SEQ_COLOURS, rampColour } from '../charts/primitives';
import { useSectionName } from '../../lib/masterNames';
import { ExceptionCard } from '../ExceptionCard';
import { Aurora, Reveal, SplitHeadline, TiltCard } from './Atmosphere';
import { PlantMap } from './PlantMap';
import { MachinePerformancePanel } from './MachinePerformancePanel';
import { ProductionPanel } from './ProductionPanel';
import { WorkbookDownload } from './WorkbookDownload';
import { TicketSheet } from '../floor/TicketSheet';
import { FocusStrip, type BoardFocus } from './FocusStrip';

const PERIODS = [30, 90, 180] as const;

export function BoardView({ canDrill }: { canDrill: boolean }) {
  const { t } = useTranslation();
  const [days, setDays] = useState<number>(90);
  const [feed, setFeed] = useState<api.ExceptionFeed | null>(null);
  const [stats, setStats] = useState<api.Analytics | null>(null);
  const [summary, setSummary] = useState<api.BoardSummary | null>(null);
  const [quality, setQuality] = useState<api.RootCauseQuality | null>(null);
  const [prod, setProd] = useState<api.ProductionAnalytics | null>(null);
  const [openTicket, setOpenTicket] = useState<string | null>(null);
  // Set by clicking any machine or cause in any chart. One piece of state for
  // every drill target on the board, so the charts never learn about each other.
  const [focus, setFocus] = useState<BoardFocus | null>(null);
  const [failed, setFailed] = useState(false);
  // True until the first load settles. Without it the board renders its
  // empty state — "0 machines", "Open tickets 0", "No closed tickets yet" —
  // which are assertions about data that has not arrived. On a cold free-tier
  // instance that lasts several seconds and reads as "the plant has no data",
  // which is the opposite of true.
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setFailed(false);
    try {
      const [f, a, s, q, p] = await Promise.all([
        api.exceptions(),
        api.analytics(days),
        api.boardSummary(),
        api.rootCauseQuality(days).catch(() => null),
        api.productionAnalytics(days).catch(() => null),
      ]);
      setFeed(f);
      setStats(a);
      setSummary(s);
      setQuality(q);
      setProd(p);
    } catch {
      setFailed(true);
    } finally {
      setLoading(false);
    }
  }, [days]);

  useEffect(() => {
    void load();
  }, [load]);

  const alerting = useMemo(
    () => new Set((feed?.items ?? []).map((i) => i.machine_code)),
    [feed],
  );

  const sectionOrder = useMemo(() => {
    const map = new Map<string, number>();
    summary?.sections.forEach((s) => map.set(s.section_name, s.sort_order));
    return map;
  }, [summary]);

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

  const k = stats?.kpis;
  // MTBF and availability both divide by the same base, so one note covers both.
  const basisNote =
    k?.availability_basis === 'scheduled' ? 'board.scheduledBasis' : 'board.calendarBasis';

  return (
    <div className="board-surface space-y-7 pb-12">
      <Aurora />

      {focus && (
        <FocusStrip
          focus={focus}
          stats={stats}
          prod={prod}
          feed={feed}
          onOpenTicket={(id) => setOpenTicket(id)}
          onDismiss={() => setFocus(null)}
        />
      )}

      {/* Editorial hero. The board is read by someone deciding where to spend
          next month, so it opens with the question rather than a number. */}
      <header className="pt-2 pb-1">
        <h1
          className="font-display font-semibold"
          style={{ fontSize: 'var(--text-2xl)', lineHeight: 1.15, color: 'var(--ink)' }}
        >
          <SplitHeadline text={t('board.heroLead')} />
          <br />
          <span style={{ color: 'var(--accent)' }}>
            <SplitHeadline text={t('board.heroAccent')} delay={0.12} />
          </span>
        </h1>
        <p className="mt-2" style={{ color: 'var(--ink-muted)' }}>
          {loading
            ? t('board.heroLoading', { days })
            : t('board.heroSub', { machines: stats?.machine_count ?? 0, days })}
        </p>
      </header>

      <PeriodPicker days={days} onChange={setDays} />

      {/* ---- ROW 1: headline ---- */}
      <section aria-label={t('board.headline')}>
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-3 xl:grid-cols-6">
          <Tile
            label={t('board.downtime')}
            value={k ? formatDuration(k.downtime_minutes) : '—'}
            delta={k?.downtime_delta ?? null}
            higherIsBetter={false}
            spark={stats?.sparklines.downtime}
            days={days}
            hero
          />
          <Tile
            label={t('board.mttr')}
            value={k?.mttr_minutes != null ? formatDuration(k.mttr_minutes) : '—'}
            delta={k?.mttr_delta ?? null}
            higherIsBetter={false}
            spark={stats?.sparklines.mttr}
            days={days}
          />
          <Tile
            label={t('board.mtta')}
            value={k?.mtta_minutes != null ? formatDuration(k.mtta_minutes) : '—'}
            delta={k?.mtta_delta ?? null}
            higherIsBetter={false}
            spark={stats?.sparklines.mtta}
            days={days}
          />
          <Tile
            label={t('board.openTickets')}
            value={loading ? '—' : String(feed?.open_total ?? 0)}
            sub={
              loading ? '' : t('board.escalatedCount', { count: feed?.escalated_total ?? 0 })
            }
            tone={feed && feed.escalated_total > 0 ? 'bad' : 'neutral'}
          />
          <Tile
            label={t('board.firstTimeFix')}
            value={k?.first_time_fix_percent != null ? `${k.first_time_fix_percent}%` : '—'}
            sub={`${t('board.reopenRate')}: ${k?.reopen_percent != null ? k.reopen_percent : '—'}%`}
            tone={
              k?.first_time_fix_percent == null
                ? 'neutral'
                : k.first_time_fix_percent >= 90
                  ? 'good'
                  : k.first_time_fix_percent >= 80
                    ? 'watch'
                    : 'bad'
            }
          />
          <Tile
            label={t('board.rootCauseQuality')}
            value={k?.root_cause_usable_percent != null ? `${k.root_cause_usable_percent}%` : '—'}
            sub={t('board.usableEntries')}
            tone={
              k?.root_cause_usable_percent == null
                ? 'neutral'
                : k.root_cause_usable_percent >= 70
                  ? 'good'
                  : k.root_cause_usable_percent >= 50
                    ? 'watch'
                    : 'bad'
            }
          />
        </div>

        {/* Cost, once every machine that went down has a rate.
            Until then it says why it is missing and how far off it is. A
            guessed rupee figure gets quoted in a meeting; a blank one gets
            chased — and "9 of 33 priced" gets chased at the right person. */}
        <p className="mt-2" style={{ fontSize: 'var(--text-sm)', color: 'var(--ink-muted)' }}>
          {k?.downtime_cost != null ? (
            <>
              <span className="tabular font-semibold" style={{ color: 'var(--ink)' }}>
                {t('board.costValue', {
                  amount: k.downtime_cost.toLocaleString('en-IN', {
                    maximumFractionDigits: 0,
                  }),
                })}
              </span>{' '}
              {t('board.costBasis', { days })}
            </>
          ) : k && k.cost_total_machines > 0 ? (
            t('board.costPartial', {
              priced: k.cost_priced_machines,
              total: k.cost_total_machines,
            })
          ) : (
            t('board.costPending')
          )}
        </p>
      </section>

      {/* ---- ROW 2: reliability + action queue ---- */}
      <div className="grid gap-6 lg:grid-cols-2">
        <section aria-labelledby="reliability">
          <h2
            id="reliability"
            className="register-rule pb-1 font-semibold"
            style={{ fontSize: 'var(--text-sm)', color: 'var(--ink)' }}
          >
            {t('board.reliability')}
          </h2>
          <dl className="mt-3 grid grid-cols-2 gap-x-6 gap-y-2">
            <Stat
              term={t('board.mtbf')}
              value={k?.mtbf_hours != null ? `${k.mtbf_hours} h` : '—'}
              note={t(basisNote)}
            />
            <Stat
              term={t('board.availability')}
              value={k?.availability_percent != null ? `${k.availability_percent}%` : '—'}
              note={t(basisNote)}
            />
          </dl>
          {k && <Ageing buckets={k.ageing} />}
        </section>

        <section aria-labelledby="needs-attention">
          <h2
            id="needs-attention"
            className="register-rule flex items-baseline justify-between pb-1 font-semibold"
            style={{ fontSize: 'var(--text-sm)', color: 'var(--ink)' }}
          >
            <span>{t('board.needsAttention')}</span>
            <span style={{ color: 'var(--ink-muted)', fontWeight: 400 }}>{feed?.scope_label}</span>
          </h2>

          {feed && feed.items.length === 0 ? (
            <p className="py-6" style={{ color: 'var(--ink-muted)' }}>
              {t('board.nothingFlagged')}
            </p>
          ) : (
            <ul className="mt-2 space-y-2">
              {(feed?.items ?? []).slice(0, 5).map((item, i) => (
                <li key={`${item.machine_code}-${i}`}>
                  <ExceptionCard
                    item={item}
                    compact
                    onOpen={
                      canDrill && item.ticket_id ? () => setOpenTicket(item.ticket_id) : undefined
                    }
                  />
                </li>
              ))}
            </ul>
          )}

          {feed && feed.resolution !== 'operational' && (
            <p className="mt-3" style={{ fontSize: 'var(--text-xs)', color: 'var(--ink-muted)' }}>
              {t('board.summarisedNote')}
            </p>
          )}
        </section>
      </div>

      {/* ---- ROW 3: where, spatially ---- */}
      {stats && (
        <Reveal>
          <PlantMap
            machines={stats.top_machines}
            sections={summary?.sections ?? []}
            alerting={alerting}
            onSelect={(code) => setFocus({ kind: 'machine', code })}
          />
        </Reveal>
      )}

      {/* ---- ROW 4: why ---- */}
      {stats && (
        <ParetoChart
          data={stats.pareto_by_cause}
          onSelect={(slice) => setFocus({ kind: 'cause', label: slice.label })}
        />
      )}
      {stats && <DowntimeTrendChart data={stats.downtime_trend} />}

      {/* ---- ROW 4: where ---- */}
      <div className="grid gap-6 lg:grid-cols-[1.2fr_1fr]">
        {stats && (
          <TopMachines
            data={stats.top_machines}
            sectionOrder={sectionOrder}
            onSelect={(code) => setFocus({ kind: 'machine', code })}
          />
        )}
        <section aria-labelledby="by-section">
          <h2
            id="by-section"
            className="register-rule pb-1 font-semibold"
            style={{ fontSize: 'var(--text-sm)', color: 'var(--ink)' }}
          >
            {t('board.bySection')}
          </h2>
          <SectionBars rows={summary?.sections ?? []} loading={loading} />
        </section>
      </div>

      {/* ---- ROW 5: trend + trust ---- */}
      {stats && <MttrTrend data={stats.monthly} />}

      {/* ---- ROW 6: the other half of the plant ---- */}
      {/* Machine by machine: downtime and scrap side by side, plus the
          impregnation view where RC and VC replace a reject rate. */}
      <MachinePerformancePanel days={days} basis={k?.availability_basis} />

      {prod && <ProductionPanel data={prod} />}
      {quality && <QualityPanel quality={quality} />}

      {/* Last on the page on purpose: it is what somebody reaches for after
          reading the board, not before. */}
      <WorkbookDownload />

      {openTicket && (
        <TicketSheet
          ticketId={openTicket}
          onClose={() => setOpenTicket(null)}
          onChanged={() => void load()}
        />
      )}
    </div>
  );
}

function PeriodPicker({ days, onChange }: { days: number; onChange: (d: number) => void }) {
  const { t } = useTranslation();
  return (
    <div
      role="radiogroup"
      aria-label={t('board.periodLabel', { days })}
      className="inline-flex rounded-full border p-0.5"
      style={{ borderColor: 'var(--line)', background: 'var(--surface-muted)' }}
    >
      {PERIODS.map((p) => {
        const active = p === days;
        return (
          <button
            key={p}
            type="button"
            role="radio"
            aria-checked={active}
            onClick={() => onChange(p)}
            className="rounded-full px-3.5 py-1.5 font-medium"
            style={{
              fontSize: 'var(--text-sm)',
              background: active ? 'var(--surface)' : 'transparent',
              color: active ? 'var(--ink)' : 'var(--ink-muted)',
              boxShadow: active ? 'var(--shadow)' : 'none',
            }}
          >
            {p}d
          </button>
        );
      })}
    </div>
  );
}

type Tone = 'good' | 'watch' | 'bad' | 'neutral';

const TONE_COLOUR: Record<Tone, string> = {
  good: 'var(--primary)',
  watch: 'var(--amber)',
  bad: 'var(--rust)',
  neutral: 'var(--ink)',
};

function Tile({
  label,
  value,
  sub,
  tone = 'neutral',
  delta,
  higherIsBetter,
  spark,
  days,
  hero = false,
}: {
  label: string;
  value: string;
  sub?: string;
  tone?: Tone;
  delta?: number | null;
  higherIsBetter?: boolean;
  spark?: number[];
  days?: number;
  /** The headline number gets the gradient hairline. Only one card should. */
  hero?: boolean;
}) {
  const { t } = useTranslation();
  // Direction-of-good is stated by the caller, never inferred from the sign.
  // A rising MTTR is bad and a rising output is good; guessing gets it wrong
  // half the time, and a board that misleads is worse than no board.
  const deltaTone: Tone =
    delta == null || higherIsBetter === undefined
      ? 'neutral'
      : (toneForDelta(delta, higherIsBetter) as Tone);

  return (
    <TiltCard
      className={`arch lift border px-3 py-3 ${hero ? 'gradient-border' : ''}`}
      style={{ borderColor: 'var(--line)', background: 'var(--surface)' }}
    >
      <p style={{ fontSize: 'var(--text-xs)', color: 'var(--ink-muted)' }}>{label}</p>
      <p
        className="tabular mt-0.5 font-semibold"
        style={{ fontSize: 'var(--text-2xl)', color: TONE_COLOUR[tone], lineHeight: 1.1 }}
      >
        {value}
      </p>

      {delta !== undefined && delta !== null && (
        <p
          className="tabular mt-0.5"
          style={{ fontSize: 'var(--text-xs)', color: TONE_COLOUR[deltaTone] }}
        >
          {delta > 0 ? '▲' : '▼'} {Math.abs(delta)}%{' '}
          <span style={{ color: 'var(--ink-muted)' }}>{t('board.vsPrevious', { days })}</span>
        </p>
      )}
      {delta === null && higherIsBetter !== undefined && (
        <p className="mt-0.5" style={{ fontSize: 'var(--text-xs)', color: 'var(--ink-muted)' }}>
          {t('board.noComparison')}
        </p>
      )}
      {sub && (
        <p className="mt-0.5" style={{ fontSize: 'var(--text-xs)', color: 'var(--ink-muted)' }}>
          {sub}
        </p>
      )}

      {spark && spark.length > 1 && (
        <div className="mt-2">
          <Sparkline values={spark} tone={TONE_COLOUR[deltaTone]} />
        </div>
      )}
    </TiltCard>
  );
}

function Stat({ term, value, note }: { term: string; value: string; note?: string }) {
  return (
    <div>
      <dt style={{ fontSize: 'var(--text-xs)', color: 'var(--ink-muted)' }}>{term}</dt>
      <dd
        className="tabular font-semibold"
        style={{ fontSize: 'var(--text-lg)', color: 'var(--ink)', margin: 0 }}
      >
        {value}
      </dd>
      {note && <p style={{ fontSize: 'var(--text-xs)', color: 'var(--ink-muted)' }}>{note}</p>}
    </div>
  );
}

/**
 * Open tickets by how long they have waited.
 *
 * Buckets rather than an average, because an average hides the one ticket that
 * has been open eleven days — and that ticket is the entire point of the view.
 */
function Ageing({ buckets }: { buckets: Record<string, number> }) {
  const { t } = useTranslation();
  const rows = [
    { key: 'under_24h', label: t('board.ageingUnder24h'), tone: 'var(--primary)' },
    { key: 'd1_3', label: t('board.ageingD1_3'), tone: 'var(--info)' },
    { key: 'd3_7', label: t('board.ageingD3_7'), tone: 'var(--amber)' },
    { key: 'over_7d', label: t('board.ageingOver7d'), tone: 'var(--rust)' },
  ];
  const total = rows.reduce((sum, r) => sum + (buckets[r.key] ?? 0), 0);

  return (
    <div className="mt-5">
      <p className="font-medium" style={{ fontSize: 'var(--text-xs)', color: 'var(--ink-muted)' }}>
        {t('board.ageingTitle')}
      </p>
      <ul className="mt-2 space-y-1.5">
        {rows.map((row) => {
          const count = buckets[row.key] ?? 0;
          return (
            <li key={row.key} className="flex items-center gap-2">
              <span
                aria-hidden="true"
                className="inline-block h-2 w-2 shrink-0 rounded-full"
                style={{ background: row.tone }}
              />
              <span className="flex-1" style={{ fontSize: 'var(--text-sm)', color: 'var(--ink)' }}>
                {row.label}
              </span>
              <span
                className="tabular font-medium"
                style={{
                  fontSize: 'var(--text-sm)',
                  color: count > 0 ? row.tone : 'var(--ink-muted)',
                }}
              >
                {count}
              </span>
              <div
                className="h-1.5 w-20 overflow-hidden rounded-full"
                style={{ background: 'var(--surface-muted)' }}
                aria-hidden="true"
              >
                <div
                  className="h-full rounded-full"
                  style={{
                    width: total ? `${(count / total) * 100}%` : '0%',
                    background: row.tone,
                  }}
                />
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function SectionBars({ rows, loading }: { rows: api.SectionSummary[]; loading: boolean }) {
  const { t } = useTranslation();
  const sectionName = useSectionName();

  if (loading) {
    return (
      <p className="py-6" style={{ color: 'var(--ink-muted)' }}>
        {t('masters.loading')}
      </p>
    );
  }

  if (rows.length === 0) {
    return (
      <p className="py-6" style={{ color: 'var(--ink-muted)' }}>
        {t('board.noSectionData')}
      </p>
    );
  }

  const max = Math.max(...rows.map((r) => r.downtime_minutes), 1);

  return (
    <ul className="mt-3 space-y-2.5">
      {rows.map((row, index) => {
        const issues = row.open_count + row.closed_count;
        return (
          <li
            key={row.section_id}
            className="feather pl-2.5"
            style={{ '--feather': sectionColour(row.sort_order, row.section_name) } as React.CSSProperties}
          >
            <div className="flex items-baseline justify-between gap-3">
              <span style={{ fontSize: 'var(--text-sm)', color: 'var(--ink)' }}>
                {sectionName(row.section_name)}
              </span>
              <span
                className="tabular shrink-0"
                style={{ fontSize: 'var(--text-sm)', color: 'var(--ink-muted)' }}
              >
                {row.downtime_minutes > 0 ? formatDuration(row.downtime_minutes) : '—'} ·{' '}
                {t('board.issues', { count: issues })}
              </span>
            </div>
            <div
              className="mt-1 h-2 w-full overflow-hidden rounded-full"
              style={{ background: 'var(--viz-track)' }}
              role="img"
              aria-label={t('board.sectionBar', {
                section: sectionName(row.section_name),
                duration: formatDuration(row.downtime_minutes),
              })}
            >
              <div
                className="h-full rounded-full"
                style={{
                  width: `${Math.max(3, (row.downtime_minutes / max) * 100)}%`,
                  // Rows arrive sorted worst-first, so the ramp and the order
                  // agree. This bar used to be the section's brand feather —
                  // seven fully saturated hues stacked down one card, which is
                  // the single loudest thing the board ever rendered and read
                  // like a child's paint set. Identity moved to the rule on the
                  // left, which is what a feather was designed to be.
                  background: rampColour(SEQ_COLOURS, index),
                }}
              />
            </div>
          </li>
        );
      })}
    </ul>
  );
}

function QualityPanel({ quality }: { quality: api.RootCauseQuality }) {
  const { t } = useTranslation();
  return (
    <section aria-labelledby="rc-quality">
      <h2
        id="rc-quality"
        className="register-rule pb-1 font-semibold"
        style={{ fontSize: 'var(--text-sm)', color: 'var(--ink)' }}
      >
        {t('board.rootCauseQuality')}
      </h2>
      <div
        className="arch lift mt-2 border px-4 py-3"
        style={{ borderColor: 'var(--line)', background: 'var(--surface)' }}
      >
        <p className="tabular" style={{ color: 'var(--ink)' }}>
          {t('board.qualitySummary', {
            usable: quality.usable_tickets,
            scored: quality.scored_tickets,
            percent: quality.usable_percent,
          })}
        </p>
        {quality.top_reasons.length > 0 && (
          <>
            <p className="mt-2" style={{ fontSize: 'var(--text-xs)', color: 'var(--ink-muted)' }}>
              {t('board.qualityWhyFail')}
            </p>
            <ul
              className="mt-1 list-disc pl-5"
              style={{ fontSize: 'var(--text-sm)', color: 'var(--ink-muted)' }}
            >
              {quality.top_reasons.map((reason) => (
                <li key={reason}>{reason}</li>
              ))}
            </ul>
          </>
        )}
        <p className="mt-2" style={{ fontSize: 'var(--text-xs)', color: 'var(--ink-muted)' }}>
          {t('board.qualityTeamOnly')}
        </p>
      </div>
    </section>
  );
}
