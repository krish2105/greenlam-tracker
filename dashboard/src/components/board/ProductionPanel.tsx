/**
 * Production quality on the board.
 *
 * Three things, in the order a plant head would ask them:
 *   1. What are we throwing away, and why — the reject Pareto
 *   2. Where is it concentrated — shift, texture, machine
 *   3. The leading indicator: does quality degrade before a machine fails?
 *
 * That third one is spec §6.1's "one derived metric worth building", and it is
 * given the most prominent treatment on the page because it is the only thing
 * here that predicts rather than reports.
 */

import { useTranslation } from 'react-i18next';

import type { ProductionAnalytics, SegmentRow } from '../../lib/api';
import { useRejectReasonName, useSectionName } from '../../lib/masterNames';
import { OutputTrend } from '../charts/OutputTrend';
import {
  CLAY_COLOURS,
  ChartFrame,
  ChartTooltip,
  EmptyChart,
  fitLabel,
  linePath,
  rampColour,
  useBandHitTest,
  useChartFocus,
  useChartWidth,
} from '../charts/primitives';

export function ProductionPanel({
  data,
  showCorrelation = true,
}: {
  data: ProductionAnalytics;
  /**
   * The downtime-against-scrap finding belongs to the Combined dashboard
   * (V5 §11, view 3). On the HPL Production view it is answering a maintenance
   * question nobody asked, using a machine list the filters may have excluded.
   */
  showCorrelation?: boolean;
}) {
  const { t } = useTranslation();

  return (
    <section aria-labelledby="production" className="space-y-6">
      <h2
        id="production"
        className="register-rule flex items-baseline justify-between pb-1 font-semibold"
        style={{ fontSize: 'var(--text-sm)', color: 'var(--ink)' }}
      >
        <span>{t('production.title')}</span>
        <span className="tabular" style={{ color: 'var(--ink-muted)', fontWeight: 400 }}>
          {t('production.headline', {
            produced: data.total_produced.toLocaleString('en-IN'),
            percent: data.reject_percent,
          })}
        </span>
      </h2>

      {/* The finding that predicts, not reports. */}
      {showCorrelation && data.breakdown_correlation.length > 0 && (
        <div
          className="arch lift border px-4 py-3.5"
          style={{
            borderColor: 'var(--amber)',
            borderLeftWidth: '4px',
            background: 'var(--surface)',
          }}
        >
          <p className="font-semibold" style={{ color: 'var(--ink)' }}>
            {t('production.leadingIndicator')}
          </p>
          <ul className="mt-2 space-y-1.5">
            {data.breakdown_correlation.map((c) => (
              <li key={c.machine_code} className="tabular" style={{ color: 'var(--ink)' }}>
                {t('production.correlationLine', {
                  machine: c.machine_code,
                  near: c.reject_percent_near_breakdown,
                  away: c.reject_percent_otherwise,
                  lift: c.lift_percent,
                  breakdowns: c.breakdowns,
                })}
              </li>
            ))}
          </ul>
          <p className="mt-2" style={{ fontSize: 'var(--text-xs)', color: 'var(--ink-muted)' }}>
            {t('production.correlationCaveat')}
          </p>
        </div>
      )}

      {/* Volume first, then why. V5 §11 leads the production view with output
          — the Pareto explains a number the reader has not been shown yet. */}
      <OutputTrend data={data.daily} />

      <RejectPareto data={data} />

      <div className="grid gap-6 lg:grid-cols-2 xl:grid-cols-4">
        <SegmentTable title={t('production.byShift')} rows={data.by_shift} />
        <SegmentTable title={t('production.byTexture')} rows={data.by_texture} />
        <SegmentTable title={t('production.byMachine')} rows={data.by_machine.slice(0, 5)} />
        {/* §11 asks for rejection rates by machine AND by section. The section
            view is the one that survives a machine being renamed. */}
        <SegmentTable title={t('production.bySection')} rows={data.by_section} localiseSection />
      </div>
    </section>
  );
}

/**
 * Same Pareto discipline as downtime: bars, cumulative line, 80% marked.
 *
 * Painted in the clay ramp rather than a flat `--rust`. Rust is the interface's
 * word for "this is bad" — it is on the alert border six inches above, and on
 * the worst row of every segment table below. Spending it on eight bars that
 * are merely CATEGORIES devalues it everywhere else: if everything is red,
 * nothing is. The ramp says "ranked scrap reason"; rust stays reserved for
 * "look here now".
 */
function RejectPareto({ data }: { data: ProductionAnalytics }) {
  const { t } = useTranslation();
  const reasonName = useRejectReasonName();
  const [ref, { width, compact, ready }] = useChartWidth();
  const slices = data.reject_pareto;

  const shown = compact ? slices.slice(0, 5) : slices;
  const H = compact ? 206 : 230;
  const PAD = {
    top: 16,
    right: compact ? 32 : 46,
    bottom: compact ? 38 : 46,
    left: compact ? 32 : 46,
  };
  const plotW = Math.max(1, width - PAD.left - PAD.right);
  const plotH = H - PAD.top - PAD.bottom;
  const band = shown.length > 0 ? plotW / shown.length : plotW;

  const focus = useChartFocus(shown.length, useBandHitTest(PAD.left, band, shown.length));

  if (slices.length === 0) {
    return (
      <ChartFrame title={t('production.pareto')} ariaLabel={t('production.paretoEmpty')}>
        <EmptyChart message={t('chart.noData')} />
      </ChartFrame>
    );
  }

  const max = Math.max(...shown.map((s) => s.quantity), 1);
  const barW = Math.min(band * 0.6, 70);

  const cx = (i: number) => PAD.left + band * i + band / 2;
  const barTop = (q: number) => PAD.top + plotH * (1 - q / max);
  const cumY = (p: number) => PAD.top + plotH * (1 - p / 100);

  const cutoffIndex = slices.findIndex((s) => s.cumulative_percent >= 80);
  const cutoff = cutoffIndex >= 0 ? cutoffIndex : null;
  const top = slices.slice(0, cutoff !== null ? cutoff + 1 : slices.length);
  const active = focus.index !== null ? shown[focus.index] : null;

  return (
    <ChartFrame
      title={t('production.pareto')}
      ariaLabel={t('production.paretoSummary', {
        count: top.length,
        reasons: top.map((s) => reasonName(s.label)).join(', '),
        percent: Math.round(top[top.length - 1]?.cumulative_percent ?? 0),
      })}
      liveMessage={
        active
          ? t('production.paretoPoint', {
              reason: reasonName(active.label),
              sheets: active.quantity.toLocaleString('en-IN'),
              percent: active.cumulative_percent,
            })
          : undefined
      }
      note={t('production.paretoNote', {
        count: top.length,
        percent: Math.round(top[top.length - 1]?.cumulative_percent ?? 0),
      })}
      table={{
        headers: [t('production.reason'), t('production.sheets'), '%', t('chart.cumulative')],
        rows: slices.map((s) => [
          reasonName(s.label),
          s.quantity,
          `${s.percent}%`,
          `${s.cumulative_percent}%`,
        ]),
      }}
    >
      <div ref={ref} className="relative w-full">
        {ready && (
          <svg
            width={width}
            height={H}
            viewBox={`0 0 ${width} ${H}`}
            className="block touch-pan-y select-none"
            role="presentation"
            style={{ outline: 'none' }}
            {...focus.handlers}
          >
            {[0, 50, 100].map((p) => (
              <line
                key={p}
                x1={PAD.left}
                x2={width - PAD.right}
                y1={cumY(p)}
                y2={cumY(p)}
                stroke="var(--line)"
              />
            ))}
            <line
              x1={PAD.left}
              x2={width - PAD.right}
              y1={cumY(80)}
              y2={cumY(80)}
              stroke="var(--viz-ref)"
              strokeWidth="1"
              strokeDasharray="4 4"
              opacity="0.55"
            />
            <text
              x={width - PAD.right + 3}
              y={cumY(80) + 3.5}
              fontSize="10"
              fontFamily="var(--font-mono)"
              fill="var(--ink-muted)"
            >
              80%
            </text>

            {shown.map((s, i) => (
              <rect
                key={`hit-${s.label}`}
                x={PAD.left + band * i}
                y={PAD.top}
                width={band}
                height={plotH}
                fill={focus.index === i ? 'var(--viz-track)' : 'transparent'}
              />
            ))}

            {shown.map((s, i) => {
              const on = focus.index === i;
              return (
                <g key={s.label} pointerEvents="none">
                  <rect
                    x={cx(i) - barW / 2}
                    y={barTop(s.quantity)}
                    width={barW}
                    height={PAD.top + plotH - barTop(s.quantity)}
                    rx="2"
                    fill={
                      cutoff === null || i <= cutoff
                        ? rampColour(CLAY_COLOURS, i)
                        : 'var(--viz-muted)'
                    }
                    opacity={focus.index === null || on ? 1 : 0.55}
                  />
                  {on && (
                    <rect
                      x={cx(i) - barW / 2 - 1.5}
                      y={barTop(s.quantity) - 1.5}
                      width={barW + 3}
                      height={PAD.top + plotH - barTop(s.quantity) + 1.5}
                      rx="3"
                      fill="none"
                      stroke="var(--ink)"
                      strokeWidth="1.5"
                    />
                  )}
                  {!compact && (
                    <text
                      x={cx(i)}
                      y={barTop(s.quantity) - 5}
                      textAnchor="middle"
                      fontSize="11"
                      fontFamily="var(--font-mono)"
                      fill="var(--ink-muted)"
                    >
                      {s.quantity.toLocaleString('en-IN')}
                    </text>
                  )}
                  {/* Reason names are long; two lines beats rotated text, and
                      on a phone one ellipsised line beats both. */}
                  {compact ? (
                    <text
                      x={cx(i)}
                      y={H - PAD.bottom + 15}
                      textAnchor="middle"
                      fontSize="10"
                      fill={on ? 'var(--ink)' : 'var(--ink-muted)'}
                      fontWeight={on ? 600 : 400}
                    >
                      {fitLabel(reasonName(s.label), band - 4)}
                    </text>
                  ) : (
                    reasonName(s.label)
                      .split(' ')
                      .slice(0, 2)
                      .map((word, j) => (
                        <text
                          key={j}
                          x={cx(i)}
                          y={H - PAD.bottom + 16 + j * 12}
                          textAnchor="middle"
                          fontSize="10.5"
                          fill={on ? 'var(--ink)' : 'var(--ink-muted)'}
                          fontWeight={on ? 600 : 400}
                        >
                          {word}
                        </text>
                      ))
                  )}
                </g>
              );
            })}

            <path
              d={linePath(shown.map((s, i) => [cx(i), cumY(s.cumulative_percent)]))}
              fill="none"
              stroke="var(--viz-ref)"
              strokeWidth="1.75"
              strokeLinejoin="round"
              pointerEvents="none"
            />
            {shown.map((s, i) => (
              <circle
                key={s.label}
                cx={cx(i)}
                cy={cumY(s.cumulative_percent)}
                r={focus.index === i ? 4 : 2.75}
                fill="var(--surface)"
                stroke="var(--viz-ref)"
                strokeWidth="1.75"
                pointerEvents="none"
              />
            ))}
          </svg>
        )}

        {active && focus.index !== null && (
          <ChartTooltip
            x={cx(focus.index)}
            y={Math.max(4, barTop(active.quantity) - 88)}
            width={width}
            title={reasonName(active.label)}
            rows={[
              { label: t('production.sheets'), value: active.quantity.toLocaleString('en-IN') },
              { label: t('production.share'), value: `${active.percent}%` },
              { label: t('chart.cumulative'), value: `${active.cumulative_percent}%` },
            ]}
          />
        )}
      </div>
    </ChartFrame>
  );
}

/**
 * A dimension, worst first.
 *
 * Segments are where root causes hide (spec §6.1). The spread between best and
 * worst is the finding, so the bar is drawn relative to the worst row rather
 * than to zero — otherwise a 3.0% and a 4.0% look identical.
 */
function SegmentTable({
  title,
  rows,
  localiseSection = false,
}: {
  title: string;
  rows: SegmentRow[];
  /** Section labels arrive as English strings and need the master lookup. */
  localiseSection?: boolean;
}) {
  const { t } = useTranslation();
  const sectionName = useSectionName();
  if (rows.length === 0) return null;
  const max = Math.max(...rows.map((r) => r.reject_percent), 0.1);

  return (
    <div>
      <h3
        className="font-medium"
        style={{ fontSize: 'var(--text-xs)', color: 'var(--ink-muted)' }}
      >
        {title}
      </h3>
      <ul className="mt-2 space-y-2">
        {rows.map((row, i) => (
          <li key={row.label}>
            <div className="flex items-baseline justify-between gap-2">
              <span style={{ fontSize: 'var(--text-sm)', color: 'var(--ink)' }}>
                {localiseSection ? sectionName(row.label) : row.label}
              </span>
              <span
                className="tabular"
                style={{
                  fontSize: 'var(--text-sm)',
                  // Only the worst row is called out. Colouring every row makes
                  // a 0.1% spread look like a crisis.
                  color: i === 0 && rows.length > 1 ? 'var(--clay-2)' : 'var(--ink-muted)',
                }}
              >
                {row.reject_percent}%
              </span>
            </div>
            <div
              className="mt-1 h-1.5 w-full overflow-hidden rounded-full"
              style={{ background: 'var(--viz-track)' }}
              aria-hidden="true"
            >
              <div
                className="h-full rounded-full"
                style={{
                  width: `${(row.reject_percent / max) * 100}%`,
                  background: i === 0 && rows.length > 1 ? 'var(--clay-3)' : 'var(--viz-muted)',
                }}
              />
            </div>
          </li>
        ))}
      </ul>
      <p className="mt-1.5" style={{ fontSize: 'var(--text-xs)', color: 'var(--ink-muted)' }}>
        {t('production.relativeNote')}
      </p>
    </div>
  );
}
