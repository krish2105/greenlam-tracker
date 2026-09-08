/**
 * Output per day, with the reject rate riding on top (V5 §11 — "output
 * volumes").
 *
 * WHY BOTH ON ONE CHART
 *
 * Sheets made and sheets scrapped are the same question asked twice, and read
 * apart they mislead in opposite directions. A day that produced 4,000 sheets
 * looks like a good day until you see it rejected nine percent of them; a day
 * that rejected two percent looks clean until you see it barely ran. Put them
 * on one frame and the bad days announce themselves: a tall bar with a spike
 * over it is the shift worth asking about.
 *
 * Two axes, which is normally a warning sign — they invite a reader to compare
 * two lines that share no units. It is defensible here because the bars and
 * the line are deliberately drawn as different objects rather than two lines
 * of the same weight: nobody reads a bar and a line as the same series.
 */

import { useMemo } from 'react';
import { useTranslation } from 'react-i18next';

import {
  ChartFrame,
  ChartTooltip,
  EmptyChart,
  linePath,
  niceMax,
  tickIndices,
  useBandHitTest,
  useChartFocus,
  useChartWidth,
} from './primitives';

export interface OutputDay {
  date: string;
  produced: number;
  rejected: number;
  reject_percent: number;
}

export function OutputTrend({ data }: { data: OutputDay[] }) {
  const { t } = useTranslation();
  const [ref, { width, compact, ready }] = useChartWidth();

  const H = compact ? 180 : 210;
  const PAD = { top: 14, right: compact ? 34 : 42, bottom: 26, left: compact ? 40 : 48 };
  const plotW = Math.max(1, width - PAD.left - PAD.right);
  const plotH = H - PAD.top - PAD.bottom;
  const band = plotW / Math.max(1, data.length);

  const hit = useBandHitTest(PAD.left, band, data.length);
  const focus = useChartFocus(data.length, hit);

  const maxProduced = useMemo(
    () => niceMax(Math.max(1, ...data.map((d) => d.produced + d.rejected))),
    [data],
  );
  const maxReject = useMemo(
    () => niceMax(Math.max(1, ...data.map((d) => d.reject_percent))),
    [data],
  );

  if (data.length === 0) {
    return (
      <ChartFrame title={t('production.outputTrend')} ariaLabel={t('production.outputTrendEmpty')}>
        <EmptyChart message={t('chart.noData')} />
      </ChartFrame>
    );
  }

  const totalMade = data.reduce((sum, d) => sum + d.produced, 0);
  const worst = data.reduce((a, b) => (b.reject_percent > a.reject_percent ? b : a));

  const x = (i: number) => PAD.left + band * (i + 0.5);
  const yQty = (v: number) => PAD.top + plotH * (1 - v / maxProduced);
  const yPct = (v: number) => PAD.top + plotH * (1 - v / maxReject);

  const rejectLine = linePath(data.map((d, i) => [x(i), yPct(d.reject_percent)]));
  const ticks = tickIndices(data.length, compact ? 3 : 6);
  const formatDay = (iso: string) =>
    new Date(iso).toLocaleDateString(undefined, { month: 'short', day: 'numeric' });

  const active = focus.index !== null ? data[focus.index] : null;

  return (
    <ChartFrame
      title={t('production.outputTrend')}
      ariaLabel={t('production.outputTrendSummary', {
        total: totalMade.toLocaleString('en-IN'),
        days: data.length,
        worst: formatDay(worst.date),
        percent: worst.reject_percent,
      })}
      liveMessage={
        active
          ? t('production.outputTrendPoint', {
              date: formatDay(active.date),
              produced: active.produced.toLocaleString('en-IN'),
              percent: active.reject_percent,
            })
          : undefined
      }
      note={t('production.outputTrendNote')}
      table={{
        headers: [
          t('chart.date'),
          t('production.produced'),
          t('production.rejected'),
          t('production.rejectPercent'),
        ],
        rows: data.map((d) => [d.date, d.produced, d.rejected, `${d.reject_percent}%`]),
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
            {[0, 0.5, 1].map((f) => (
              <line
                key={f}
                x1={PAD.left}
                x2={width - PAD.right}
                y1={PAD.top + plotH * f}
                y2={PAD.top + plotH * f}
                stroke="var(--viz-grid)"
                strokeWidth={1}
              />
            ))}

            {data.map((d, i) => {
              const good = yQty(d.produced);
              const top = yQty(d.produced + d.rejected);
              // Capped, because a single logged day would otherwise draw one
              // bar the full width of the card — which reads as "this is what
              // the plant makes" rather than "one day, so far".
              const w = Math.max(1, Math.min(band * 0.62, 44));
              const bx = x(i) - w / 2;
              const on = focus.index === i;
              return (
                <g key={d.date} opacity={focus.index === null || on ? 1 : 0.45}>
                  {/* Scrap stacked on top of good output, so the bar's full
                      height is everything the machine actually ran. */}
                  <rect
                    x={bx}
                    y={top}
                    width={w}
                    height={Math.max(0, good - top)}
                    fill="var(--rust)"
                  />
                  <rect
                    x={bx}
                    y={good}
                    width={w}
                    height={Math.max(0, PAD.top + plotH - good)}
                    fill="var(--primary)"
                  />
                </g>
              );
            })}

            <path d={rejectLine} fill="none" stroke="var(--amber)" strokeWidth={2} />
            {active && focus.index !== null && (
              <circle
                cx={x(focus.index)}
                cy={yPct(active.reject_percent)}
                r={4}
                fill="var(--amber)"
                stroke="var(--surface)"
                strokeWidth={2}
              />
            )}

            {ticks.map((i) => (
              <text
                key={i}
                x={x(i)}
                y={H - 8}
                textAnchor="middle"
                fill="var(--ink-muted)"
                style={{ fontSize: 10 }}
              >
                {formatDay(data[i]!.date)}
              </text>
            ))}

            <text x={4} y={PAD.top + 4} fill="var(--ink-muted)" style={{ fontSize: 10 }}>
              {maxProduced.toLocaleString('en-IN')}
            </text>
            <text
              x={width - 4}
              y={PAD.top + 4}
              textAnchor="end"
              fill="var(--amber)"
              style={{ fontSize: 10 }}
            >
              {maxReject}%
            </text>
          </svg>
        )}

        {active && focus.index !== null && (
          <ChartTooltip
            x={x(focus.index)}
            y={PAD.top}
            width={width}
            title={formatDay(active.date)}
            rows={[
              {
                label: t('production.produced'),
                value: active.produced.toLocaleString('en-IN'),
                colour: 'var(--primary)',
              },
              {
                label: t('production.rejected'),
                value: active.rejected.toLocaleString('en-IN'),
                colour: 'var(--rust)',
              },
              {
                label: t('production.rejectPercent'),
                value: `${active.reject_percent}%`,
                colour: 'var(--amber)',
              },
            ]}
          />
        )}
      </div>
    </ChartFrame>
  );
}
