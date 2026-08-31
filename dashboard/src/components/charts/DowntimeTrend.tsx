/**
 * Daily downtime over the period, stacked by cause.
 *
 * The "are we getting better" chart. Ninety daily points is too many to label,
 * so only month boundaries get a tick — a dense axis on a wall screen is
 * noise, and the shape is what the reader is here for.
 *
 * Categories are limited to the top four plus Other, decided server-side. A
 * stacked area with nine bands cannot be read by anyone, and the Pareto has
 * already established that the tail does not matter.
 *
 * THE HONEST LIMITATION OF A STACKED AREA
 * Only the bottom band and the total outline can actually be judged by eye;
 * the middle bands sit on a moving baseline, so their shape is a lie about
 * their size. That is a property of the chart type, not of this code. Two
 * things make it survivable here: the legend chips MUTE a series, so any band
 * can be dropped to the baseline where it becomes readable, and the tooltip
 * gives the exact split for the day under the cursor. Without those, this
 * chart could only ever answer "is the total going down".
 *
 * COLOUR
 * The categorical five, whose separation is carried by a luminance staircase
 * rather than by hue (see index.css). The old set — primary, info, amber,
 * rust, line-strong — mixed two status colours with two neutrals, so a band
 * meaning "Electrical" was painted in the same rust that means "bad" three
 * inches away on the same screen. Status colour and series colour must not be
 * the same vocabulary.
 */

import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';

import type { DowntimeTrend as TrendData } from '../../lib/api';
import { useCategoryName } from '../../lib/masterNames';
import {
  ChartFrame,
  ChartTooltip,
  EmptyChart,
  LegendChip,
  SERIES_COLOURS,
  areaPath,
  formatHours,
  niceMax,
  useChartFocus,
  useChartWidth,
} from './primitives';

export function DowntimeTrendChart({ data }: { data: TrendData }) {
  const { t } = useTranslation();
  const bandName = useCategoryName();
  const [ref, { width, compact, ready }] = useChartWidth();
  const [hidden, setHidden] = useState<Set<string>>(() => new Set());

  const points = data.points;
  const H = compact ? 190 : 220;
  const PAD = { top: 14, right: 12, bottom: 28, left: compact ? 40 : 46 };
  const plotW = Math.max(1, width - PAD.left - PAD.right);
  const plotH = H - PAD.top - PAD.bottom;

  const visibleIndices = useMemo(
    () => data.series.map((_, i) => i).filter((i) => !hidden.has(data.series[i]!)),
    [data.series, hidden],
  );

  const dailyTotals = useMemo(
    () =>
      points.map((p) =>
        visibleIndices.reduce((sum, si) => sum + (p.values[si] ?? 0), 0),
      ),
    [points, visibleIndices],
  );

  const focus = useChartFocus(
    points.length,
    useMemo(
      () => (px: number) => {
        if (points.length === 0) return null;
        const ratio = (px - PAD.left) / plotW;
        if (ratio < -0.02 || ratio > 1.02) return null;
        return Math.min(points.length - 1, Math.max(0, Math.round(ratio * (points.length - 1))));
      },
      [points.length, PAD.left, plotW],
    ),
  );

  if (points.length === 0 || data.series.length === 0) {
    return (
      <ChartFrame title={t('chart.trend')} ariaLabel={t('chart.trendEmpty')}>
        <EmptyChart message={t('chart.noData')} />
      </ChartFrame>
    );
  }

  const max = niceMax(Math.max(...dailyTotals, 1));
  const x = (i: number) => PAD.left + (plotW * i) / Math.max(1, points.length - 1);
  const y = (value: number) => PAD.top + plotH * (1 - value / max);

  // Cumulative stacking: each band sits on the sum of the bands below it.
  // Hidden series are skipped entirely rather than drawn transparent, so the
  // remaining bands drop to a real baseline instead of floating on a ghost.
  const running = new Array(points.length).fill(0);
  const bands = visibleIndices.map((seriesIndex) => {
    const upper: [number, number][] = [];
    const lower: [number, number][] = [];
    points.forEach((point, i) => {
      lower.push([x(i), y(running[i])]);
      running[i] += point.values[seriesIndex] ?? 0;
      upper.push([x(i), y(running[i])]);
    });
    const path = `${upper
      .map(([px, py], i) => `${i === 0 ? 'M' : 'L'}${px.toFixed(2)},${py.toFixed(2)}`)
      .join(' ')} ${lower
      .slice()
      .reverse()
      .map(([px, py]) => `L${px.toFixed(2)},${py.toFixed(2)}`)
      .join(' ')} Z`;
    return {
      name: data.series[seriesIndex]!,
      path,
      colour: SERIES_COLOURS[seriesIndex % SERIES_COLOURS.length]!,
    };
  });

  const total = dailyTotals.reduce((a, b) => a + b, 0);
  const peakIndex = dailyTotals.indexOf(Math.max(...dailyTotals));

  // A tick only where the month changes — and on a phone, only every other one.
  const allMonthTicks = points
    .map((p, i) => ({ i, date: new Date(p.date) }))
    .filter(({ i, date }) => i === 0 || date.getUTCDate() === 1);
  const monthTicks = compact ? allMonthTicks.filter((_, n) => n % 2 === 0) : allMonthTicks;

  const activeIndex = focus.index;
  const activePoint = activeIndex !== null ? points[activeIndex] : null;

  const toggle = (name: string) =>
    setHidden((prev) => {
      const next = new Set(prev);
      // Never let the reader mute the last visible band — an empty plot is a
      // bug report waiting to happen, not a view.
      if (next.has(name)) next.delete(name);
      else if (visibleIndices.length > 1) next.add(name);
      return next;
    });

  const formatDay = (iso: string) =>
    new Date(iso).toLocaleDateString(undefined, { month: 'short', day: 'numeric' });

  return (
    <ChartFrame
      title={t('chart.trend')}
      ariaLabel={t('chart.trendSummary', {
        total: formatHours(total),
        days: points.length,
        peak: formatDay(points[peakIndex]!.date),
        peakValue: formatHours(dailyTotals[peakIndex]!),
      })}
      liveMessage={
        activePoint
          ? t('chart.trendPoint', {
              date: formatDay(activePoint.date),
              total: formatHours(dailyTotals[activeIndex!]!),
            })
          : undefined
      }
      table={{
        headers: [t('chart.date'), ...data.series.map(bandName), t('chart.total')],
        rows: points.map((p, i) => [
          p.date,
          ...p.values.map((v) => formatHours(v)),
          formatHours(dailyTotals[i]!),
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
            {[0, 0.5, 1].map((f) => (
              <line
                key={f}
                x1={PAD.left}
                x2={width - PAD.right}
                y1={y(max * f)}
                y2={y(max * f)}
                stroke="var(--line)"
                strokeWidth="1"
              />
            ))}

            {bands.map((band) => (
              <path key={band.name} d={band.path} fill={band.colour} opacity="0.92" />
            ))}

            {/* Crosshair. A vertical rule reads the day precisely; on 90 daily
                points a dot alone is ambiguous by several days. */}
            {activeIndex !== null && (
              <>
                <line
                  x1={x(activeIndex)}
                  x2={x(activeIndex)}
                  y1={PAD.top}
                  y2={PAD.top + plotH}
                  stroke="var(--ink)"
                  strokeWidth="1"
                  opacity="0.5"
                />
                <circle
                  cx={x(activeIndex)}
                  cy={y(dailyTotals[activeIndex]!)}
                  r="3.5"
                  fill="var(--surface)"
                  stroke="var(--ink)"
                  strokeWidth="1.75"
                />
              </>
            )}

            {monthTicks.map(({ i, date }) => (
              <text
                key={i}
                x={x(i)}
                y={H - 8}
                fontSize={compact ? 10 : 11}
                fill="var(--ink-muted)"
                textAnchor={i === 0 ? 'start' : 'middle'}
              >
                {date.toLocaleDateString(undefined, { month: 'short' })}
              </text>
            ))}

            {(compact ? [0, 1] : [0, 0.5, 1]).map((f) => (
              <text
                key={f}
                x={PAD.left - 6}
                y={y(max * f) + 3.5}
                textAnchor="end"
                fontSize="10"
                fontFamily="var(--font-mono)"
                fill="var(--ink-muted)"
              >
                {formatHours(max * f)}
              </text>
            ))}
          </svg>
        )}

        {activePoint && activeIndex !== null && (
          <ChartTooltip
            x={x(activeIndex)}
            y={8}
            width={width}
            title={formatDay(activePoint.date)}
            rows={[
              ...visibleIndices
                .map((si) => ({
                  label: bandName(data.series[si]!),
                  value: formatHours(activePoint.values[si] ?? 0),
                  colour: SERIES_COLOURS[si % SERIES_COLOURS.length]!,
                  raw: activePoint.values[si] ?? 0,
                }))
                // Zero rows on a five-band tooltip are pure noise on a day when
                // only one cause fired.
                .filter((r) => r.raw > 0),
              { label: t('chart.total'), value: formatHours(dailyTotals[activeIndex]!) },
            ]}
          />
        )}
      </div>

      {/* Legend beside the chart, not below a scroll fold. Each entry is a
          switch — muting a band is the only way to read the ones above it. */}
      <ul className="mt-2 flex flex-wrap gap-x-3 gap-y-1">
        {data.series.map((name, i) => (
          <li key={name}>
            <LegendChip
              label={bandName(name)}
              colour={SERIES_COLOURS[i % SERIES_COLOURS.length]!}
              active={!hidden.has(name)}
              onToggle={() => toggle(name)}
            />
          </li>
        ))}
      </ul>
    </ChartFrame>
  );
}

export { areaPath };
