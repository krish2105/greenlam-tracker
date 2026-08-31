/**
 * MTTR and MTTA by month, plus the Sparkline used inside the headline tiles.
 *
 * Both lines on one chart because they answer different halves of the same
 * question and the gap between them is the finding: if MTTA is large relative
 * to MTTR, the problem is nobody responding, not slow repairs — and response
 * delay is usually the cheaper thing to fix.
 *
 * That sentence was in this file before and the chart did not draw it. Two
 * lines with a gap between them require the reader to do the subtraction by
 * eye, every time, for every month. The gap is now SHADED, so the finding is
 * the visible object rather than a fact you could derive if you thought to.
 *
 * Direction-of-good is inverted here. A rising MTTR is bad, so the colour
 * logic lives with the caller (`toneForDelta`) rather than being inferred from
 * the sign of the slope.
 */

import { useMemo } from 'react';
import { useTranslation } from 'react-i18next';

import type { MonthPoint } from '../../lib/api';
import {
  ChartFrame,
  ChartTooltip,
  EmptyChart,
  LegendChip,
  linePath,
  niceMax,
  tickIndices,
  useChartFocus,
  useChartWidth,
} from './primitives';

export function MttrTrend({ data }: { data: MonthPoint[] }) {
  const { t } = useTranslation();
  const [ref, { width, compact, ready }] = useChartWidth();

  const points = useMemo(() => data.filter((d) => d.mttr_minutes !== null), [data]);

  const H = compact ? 186 : 210;
  const PAD = { top: 16, right: 14, bottom: 34, left: compact ? 38 : 48 };
  const plotW = Math.max(1, width - PAD.left - PAD.right);
  const plotH = H - PAD.top - PAD.bottom;

  const focus = useChartFocus(
    points.length,
    useMemo(
      () => (px: number) => {
        if (points.length === 0) return null;
        const ratio = (px - PAD.left) / plotW;
        if (ratio < -0.05 || ratio > 1.05) return null;
        return Math.min(points.length - 1, Math.max(0, Math.round(ratio * (points.length - 1))));
      },
      [points.length, PAD.left, plotW],
    ),
  );

  if (points.length < 2) {
    return (
      <ChartFrame title={t('chart.mttr')} ariaLabel={t('chart.mttrEmpty')}>
        <EmptyChart message={t('chart.needMoreMonths')} />
      </ChartFrame>
    );
  }

  const max = niceMax(
    Math.max(...points.map((d) => Math.max(d.mttr_minutes ?? 0, d.mtta_minutes ?? 0))),
  );

  const x = (i: number) => PAD.left + (plotW * i) / Math.max(1, points.length - 1);
  const y = (v: number) => PAD.top + plotH * (1 - v / max);

  const mttr: [number, number][] = points.map((d, i) => [x(i), y(d.mttr_minutes ?? 0)]);
  const mtta: [number, number][] = points.map((d, i) => [x(i), y(d.mtta_minutes ?? 0)]);

  // The band between the two lines: time a machine sat broken with nobody on it.
  const gapPath = `${linePath(mttr)} ${mtta
    .slice()
    .reverse()
    .map(([px, py]) => `L${px.toFixed(2)},${py.toFixed(2)}`)
    .join(' ')} Z`;

  const first = points[0]!;
  const last = points[points.length - 1]!;
  const change =
    first.mttr_minutes && last.mttr_minutes
      ? Math.round(100 * ((last.mttr_minutes - first.mttr_minutes) / first.mttr_minutes))
      : 0;

  const label = (month: string) =>
    new Date(`${month}-01T00:00:00Z`).toLocaleDateString(undefined, {
      month: 'short',
      year: '2-digit',
    });

  // Only as many month labels as will physically fit without colliding.
  const visibleTicks = tickIndices(points.length, Math.max(2, Math.floor(plotW / (compact ? 52 : 74))));
  const active = focus.index !== null ? points[focus.index] : null;

  return (
    <ChartFrame
      title={t('chart.mttr')}
      ariaLabel={t('chart.mttrSummary', {
        from: Math.round(first.mttr_minutes ?? 0),
        to: Math.round(last.mttr_minutes ?? 0),
        change: Math.abs(change),
        direction: change >= 0 ? t('chart.up') : t('chart.down'),
      })}
      liveMessage={
        active
          ? t('chart.mttrPoint', {
              month: label(active.month),
              mttr: Math.round(active.mttr_minutes ?? 0),
              mtta: Math.round(active.mtta_minutes ?? 0),
            })
          : undefined
      }
      legend={
        <span className="flex flex-wrap gap-x-3">
          <LegendChip label={t('chart.mttrLegend')} colour="var(--viz-1)" active />
          <LegendChip label={t('chart.mttaLegend')} colour="var(--viz-5)" active />
        </span>
      }
      table={{
        headers: [t('chart.month'), 'MTTR', 'MTTA', t('chart.issues')],
        rows: points.map((d) => [
          d.month,
          `${Math.round(d.mttr_minutes ?? 0)} min`,
          `${Math.round(d.mtta_minutes ?? 0)} min`,
          d.count,
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

            {/* The response gap, drawn rather than implied. */}
            <path d={gapPath} fill="var(--viz-5)" opacity="0.14" pointerEvents="none" />

            {/* MTTA underneath: the wait before anyone starts. Dashed, so the
                two series stay apart for a reader who cannot separate the
                hues — the same colour-is-not-the-only-channel rule as the
                stacked area's luminance staircase. */}
            <path
              d={linePath(mtta)}
              fill="none"
              stroke="var(--viz-5)"
              strokeWidth="1.75"
              strokeDasharray="5 4"
              pointerEvents="none"
            />
            <path
              d={linePath(mttr)}
              fill="none"
              stroke="var(--viz-1)"
              strokeWidth="2.25"
              strokeLinejoin="round"
              strokeLinecap="round"
              pointerEvents="none"
            />

            {focus.index !== null && (
              <line
                x1={x(focus.index)}
                x2={x(focus.index)}
                y1={PAD.top}
                y2={PAD.top + plotH}
                stroke="var(--ink)"
                strokeWidth="1"
                opacity="0.45"
                pointerEvents="none"
              />
            )}

            {mttr.map(([px, py], i) => {
              const on = focus.index === i;
              return (
                <g key={i} pointerEvents="none">
                  <circle
                    cx={px}
                    cy={py}
                    r={on ? 5 : 3.5}
                    fill="var(--surface)"
                    stroke="var(--viz-1)"
                    strokeWidth="2"
                  />
                  {/* Every point labelled is clutter once there are more than
                      a handful; the tooltip and the axis carry it instead. */}
                  {(on || (!compact && points.length <= 6)) && (
                    <text
                      x={px}
                      y={py - 11}
                      textAnchor="middle"
                      fontSize="11"
                      fontFamily="var(--font-mono)"
                      fill={on ? 'var(--ink)' : 'var(--ink-muted)'}
                      fontWeight={on ? 600 : 400}
                    >
                      {Math.round(points[i]!.mttr_minutes ?? 0)}
                    </text>
                  )}
                </g>
              );
            })}

            {focus.index !== null && (
              <circle
                cx={x(focus.index)}
                cy={y(points[focus.index]!.mtta_minutes ?? 0)}
                r="4"
                fill="var(--surface)"
                stroke="var(--viz-5)"
                strokeWidth="2"
                pointerEvents="none"
              />
            )}

            {visibleTicks.map((i) => (
              <text
                key={points[i]!.month}
                x={x(i)}
                y={H - 10}
                textAnchor="middle"
                fontSize={compact ? 10 : 11}
                fill={focus.index === i ? 'var(--ink)' : 'var(--ink-muted)'}
                fontWeight={focus.index === i ? 600 : 400}
              >
                {label(points[i]!.month)}
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
                {Math.round(max * f)}
              </text>
            ))}
          </svg>
        )}

        {active && focus.index !== null && (
          <ChartTooltip
            x={x(focus.index)}
            y={8}
            width={width}
            title={label(active.month)}
            rows={[
              {
                label: t('chart.mttrLegend'),
                value: `${Math.round(active.mttr_minutes ?? 0)} min`,
                colour: 'var(--viz-1)',
              },
              {
                label: t('chart.mttaLegend'),
                value: `${Math.round(active.mtta_minutes ?? 0)} min`,
                colour: 'var(--viz-5)',
              },
              { label: t('chart.issues'), value: String(active.count) },
            ]}
          />
        )}
      </div>
    </ChartFrame>
  );
}

/**
 * The tiny series inside a headline tile.
 *
 * No axes, no labels, no interaction — its only job is to answer "which way is
 * this going", which a bare number cannot. Decorative in isolation, which is
 * why it is always paired with the number it describes and hidden from screen
 * readers; the tile's own text carries the meaning.
 */
export function Sparkline({
  values,
  tone = 'var(--ink-muted)',
  width = 96,
  height = 24,
}: {
  values: number[];
  tone?: string;
  width?: number;
  height?: number;
}) {
  if (values.length < 2) return null;

  const max = Math.max(...values, 1);
  const step = width / (values.length - 1);
  const points: [number, number][] = values.map((v, i) => [
    i * step,
    height - (v / max) * (height - 2) - 1,
  ]);

  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      aria-hidden="true"
      focusable="false"
      className="overflow-visible"
    >
      <path
        d={linePath(points)}
        fill="none"
        stroke={tone}
        strokeWidth="1.5"
        strokeLinejoin="round"
      />
      <circle
        cx={points[points.length - 1]![0]}
        cy={points[points.length - 1]![1]}
        r="2"
        fill={tone}
      />
    </svg>
  );
}
