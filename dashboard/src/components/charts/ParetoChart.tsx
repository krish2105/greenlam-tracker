/**
 * Downtime Pareto by cause.
 *
 * Bars descending, cumulative percentage on a secondary axis, and the 80%
 * crossing marked. Addendum §3.3 calls this the chart that changes behaviour:
 * three or four causes usually account for most of the downtime, and where the
 * line crosses 80% is where the reader stops and next month's maintenance
 * agenda begins.
 *
 * The 80% rule is drawn, not left to be inferred — a reference line and a
 * label. A cumulative curve nobody knows how to read is decoration.
 *
 * COLOUR
 * Bars inside the 80% take the sequential ramp, so the ranking is legible
 * before a single label is read; the tail is muted. The cumulative line is
 * ink, not lime. It is an annotation ON the bars — the moment it out-shouts
 * them, the chart is about the curve instead of about the causes, which is
 * backwards. (The previous version drew it in brand lime at 2.5px, which is
 * exactly the "childish" note: a highlighter across a ledger.)
 */

import { useTranslation } from 'react-i18next';

import type { ParetoSlice } from '../../lib/api';
import { useCategoryName } from '../../lib/masterNames';
import {
  ChartFrame,
  ChartTooltip,
  EmptyChart,
  fitLabel,
  formatHours,
  linePath,
  rampColour,
  SEQ_COLOURS,
  useBandHitTest,
  useChartFocus,
  useChartWidth,
} from './primitives';

export function ParetoChart({
  data,
  onSelect,
}: {
  data: ParetoSlice[];
  /** Drill into a cause. Wired by the board to filter the ticket list. */
  onSelect?: (cause: ParetoSlice) => void;
}) {
  const { t } = useTranslation();
  // Cause labels ARE issue categories — admin-editable master data that the
  // analytics query denormalises into a bare string.
  const causeName = useCategoryName();
  const [ref, { width, compact, ready }] = useChartWidth();

  // On a phone the tail is unreadable anyway; showing six 9px-wide bars is
  // worse than showing five that can be labelled. The full set stays in the
  // screen-reader table, so nothing is actually lost.
  const shown = compact ? data.slice(0, 5) : data;

  const H = compact ? 208 : 260;
  const PAD = {
    top: 18,
    right: compact ? 34 : 46,
    bottom: compact ? 34 : 42,
    left: compact ? 32 : 46,
  };
  const plotW = Math.max(1, width - PAD.left - PAD.right);
  const plotH = H - PAD.top - PAD.bottom;
  const bandWidth = shown.length > 0 ? plotW / shown.length : plotW;

  const hitTest = useBandHitTest(PAD.left, bandWidth, shown.length);
  const focus = useChartFocus(
    shown.length,
    hitTest,
    onSelect ? (i) => shown[i] && onSelect(shown[i]!) : undefined,
  );

  if (data.length === 0) {
    return (
      <ChartFrame title={t('chart.pareto')} ariaLabel={t('chart.paretoEmpty')}>
        <EmptyChart message={t('chart.noData')} />
      </ChartFrame>
    );
  }

  const max = Math.max(...shown.map((d) => d.minutes), 1);
  const barWidth = Math.min(bandWidth * 0.6, 72);
  const centreX = (i: number) => PAD.left + bandWidth * i + bandWidth / 2;
  const barTop = (minutes: number) => PAD.top + plotH * (1 - minutes / max);
  const cumulativeY = (percent: number) => PAD.top + plotH * (1 - percent / 100);

  const cumulativePoints: [number, number][] = shown.map((d, i) => [
    centreX(i),
    cumulativeY(d.cumulative_percent),
  ]);

  // Where the cumulative line first reaches 80% — the whole point of the chart.
  const cutoffIndex = data.findIndex((d) => d.cumulative_percent >= 80);
  const cutoff = cutoffIndex >= 0 ? cutoffIndex : null;

  const topCauses = data.slice(0, cutoff !== null ? cutoff + 1 : data.length);
  const ariaLabel = t('chart.paretoSummary', {
    count: topCauses.length,
    causes: topCauses.map((d) => causeName(d.label)).join(', '),
    percent: topCauses[topCauses.length - 1]?.cumulative_percent ?? 100,
  });

  const active = focus.index !== null ? shown[focus.index] : null;

  return (
    <ChartFrame
      title={t('chart.pareto')}
      ariaLabel={ariaLabel}
      liveMessage={
        active
          ? t('chart.paretoPoint', {
              cause: causeName(active.label),
              hours: formatHours(active.minutes),
              count: active.count,
              percent: active.cumulative_percent,
            })
          : undefined
      }
      note={
        cutoff !== null
          ? t('chart.paretoNote', {
              count: cutoff + 1,
              // The real cumulative, not the literal 80. Three causes reached
              // 79.5% in the pilot data, so quoting "80%" would print a number
              // that appears nowhere on the chart.
              percent: Math.round(topCauses[topCauses.length - 1]?.cumulative_percent ?? 0),
              causes: topCauses.map((d) => causeName(d.label)).join(', '),
            })
          : undefined
      }
      table={{
        headers: [t('chart.cause'), t('chart.downtime'), t('chart.issues'), t('chart.cumulative')],
        rows: data.map((d) => [
          causeName(d.label),
          formatHours(d.minutes),
          d.count,
          `${d.cumulative_percent}%`,
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
            aria-describedby={undefined}
            style={{ outline: 'none' }}
            {...focus.handlers}
          >
            {/* Gridlines, low contrast so they never compete with the data. */}
            {[0, 25, 50, 75, 100].map((pct) => (
              <line
                key={pct}
                x1={PAD.left}
                x2={width - PAD.right}
                y1={cumulativeY(pct)}
                y2={cumulativeY(pct)}
                stroke="var(--line)"
                strokeWidth="1"
              />
            ))}

            {/* The 80% reference. Restrained — it marks a threshold, it is not
                a series, so it gets a hairline and a small label rather than a
                saturated dashed rule competing with the bars. */}
            <line
              x1={PAD.left}
              x2={width - PAD.right}
              y1={cumulativeY(80)}
              y2={cumulativeY(80)}
              stroke="var(--viz-ref)"
              strokeWidth="1"
              strokeDasharray="4 4"
              opacity="0.55"
            />
            <text
              x={width - PAD.right + 3}
              y={cumulativeY(80) + 3.5}
              fontSize="10"
              fill="var(--ink-muted)"
              fontFamily="var(--font-mono)"
            >
              80%
            </text>

            {/* Hit bands. Full height, so pointing anywhere in the column
                works — chasing a 12px bar with a fingertip does not. */}
            {shown.map((d, i) => (
              <rect
                key={`hit-${d.label}`}
                x={PAD.left + bandWidth * i}
                y={PAD.top}
                width={bandWidth}
                height={plotH}
                fill={focus.index === i ? 'var(--viz-track)' : 'transparent'}
                style={{ cursor: onSelect ? 'pointer' : 'default' }}
                onClick={onSelect ? () => onSelect(d) : undefined}
              />
            ))}

            {shown.map((d, i) => {
              const withinCutoff = cutoff === null || i <= cutoff;
              const focused = focus.index === i;
              return (
                <g key={d.label} pointerEvents="none">
                  <rect
                    x={centreX(i) - barWidth / 2}
                    y={barTop(d.minutes)}
                    width={barWidth}
                    height={PAD.top + plotH - barTop(d.minutes)}
                    rx="2"
                    // Inside the 80%, rank is the message, so the sequential
                    // ramp carries it. The tail is muted — present, readable,
                    // and visibly not the recommendation.
                    fill={withinCutoff ? rampColour(SEQ_COLOURS, i) : 'var(--viz-muted)'}
                    opacity={focus.index === null || focused ? 1 : 0.55}
                  />
                  {focused && (
                    <rect
                      x={centreX(i) - barWidth / 2 - 1.5}
                      y={barTop(d.minutes) - 1.5}
                      width={barWidth + 3}
                      height={PAD.top + plotH - barTop(d.minutes) + 1.5}
                      rx="3"
                      fill="none"
                      stroke="var(--ink)"
                      strokeWidth="1.5"
                    />
                  )}
                  {/* Value labels are the first thing to go when space is
                      tight — the tooltip carries them, and a smudged number
                      is worse than no number. */}
                  {!compact && (
                    <text
                      x={centreX(i)}
                      y={barTop(d.minutes) - 5}
                      textAnchor="middle"
                      fontSize="11"
                      fontFamily="var(--font-mono)"
                      fill="var(--ink-muted)"
                    >
                      {formatHours(d.minutes)}
                    </text>
                  )}
                  <text
                    x={centreX(i)}
                    y={H - PAD.bottom + 15}
                    textAnchor="middle"
                    fontSize={compact ? 10 : 11}
                    fill={focused ? 'var(--ink)' : 'var(--ink-muted)'}
                    fontWeight={focused ? 600 : 400}
                  >
                    {fitLabel(causeName(d.label), bandWidth - 4)}
                  </text>
                  {!compact && (
                    <text
                      x={centreX(i)}
                      y={H - PAD.bottom + 29}
                      textAnchor="middle"
                      fontSize="10"
                      fontFamily="var(--font-mono)"
                      fill="var(--ink-muted)"
                    >
                      {d.count}
                    </text>
                  )}
                </g>
              );
            })}

            <path
              d={linePath(cumulativePoints)}
              fill="none"
              stroke="var(--viz-ref)"
              strokeWidth="1.75"
              strokeLinejoin="round"
              strokeLinecap="round"
              pointerEvents="none"
            />
            {cumulativePoints.map(([x, y], i) => (
              <circle
                key={i}
                cx={x}
                cy={y}
                r={focus.index === i ? 4 : 2.75}
                fill="var(--surface)"
                stroke="var(--viz-ref)"
                strokeWidth="1.75"
                pointerEvents="none"
              />
            ))}

            {(compact ? [0, 100] : [0, 50, 100]).map((pct) => (
              <text
                key={pct}
                x={PAD.left - 6}
                y={cumulativeY(pct) + 3.5}
                textAnchor="end"
                fontSize="10"
                fontFamily="var(--font-mono)"
                fill="var(--ink-muted)"
              >
                {pct}
              </text>
            ))}
          </svg>
        )}

        {active && focus.index !== null && (
          <ChartTooltip
            x={centreX(focus.index)}
            y={Math.max(4, barTop(active.minutes) - 96)}
            width={width}
            title={causeName(active.label)}
            rows={[
              { label: t('chart.downtime'), value: formatHours(active.minutes) },
              { label: t('chart.issues'), value: String(active.count) },
              { label: t('chart.cumulative'), value: `${active.cumulative_percent}%` },
            ]}
            hint={onSelect ? t('chart.drillHint') : undefined}
          />
        )}
      </div>
    </ChartFrame>
  );
}
