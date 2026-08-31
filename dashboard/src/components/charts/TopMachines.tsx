/**
 * Worst machines by downtime, as horizontal bars.
 *
 * Directly answers "which machine cost us the most last month", which the spec
 * sets as the thirty-second test for the whole dashboard. Horizontal because
 * machine codes are text and vertical bars would force rotated labels, which
 * nobody reads on a wall screen.
 *
 * MTBF and ticket count sit alongside on purpose: a machine with 89 hours over
 * 46 tickets is a different problem from 89 hours over 3, and the bar alone
 * cannot tell them apart.
 *
 * WHY THE BARS ARE NO LONGER PEACOCK
 * They used to be filled with the section's brand feather — magenta for Press,
 * olive for Sanding — defended in a comment that said the feather "labels, it
 * does not measure". The comment was right about the intent and wrong about
 * the result. A 300px saturated magenta bar is the largest, loudest object on
 * the card; whatever it was meant to encode, what it actually does is dominate.
 * That single decision is most of why the board read as childish.
 *
 * Section identity now sits where it was designed to sit: a 4px feather rule
 * down the left edge of the row, beside the section's name in words. The bar
 * itself takes the sequential ramp, so its colour carries the ranking that the
 * bar length and the rank marker already state — three cues, one message.
 */

import { useState } from 'react';
import { useTranslation } from 'react-i18next';

import { sectionColour } from '@greenlam/core';

import type { MachineLoad } from '../../lib/api';
import { useSectionName } from '../../lib/masterNames';
import { ChartFrame, EmptyChart, SEQ_COLOURS, formatHours, rampColour } from './primitives';

export function TopMachines({
  data,
  sectionOrder,
  onSelect,
}: {
  data: MachineLoad[];
  sectionOrder: Map<string, number>;
  onSelect?: (machineCode: string) => void;
}) {
  const { t } = useTranslation();
  const sectionName = useSectionName();
  const [active, setActive] = useState<string | null>(null);

  if (data.length === 0) {
    return (
      <ChartFrame title={t('chart.topMachines')} ariaLabel={t('chart.topMachinesEmpty')}>
        <EmptyChart message={t('chart.noData')} />
      </ChartFrame>
    );
  }

  const max = Math.max(...data.map((d) => d.minutes), 1);
  const worst = data[0]!;
  const focused = data.find((d) => d.machine_code === active) ?? null;

  return (
    <ChartFrame
      title={t('chart.topMachines')}
      ariaLabel={t('chart.topMachinesSummary', {
        machine: worst.machine_code,
        hours: formatHours(worst.minutes),
        count: worst.count,
      })}
      liveMessage={
        focused
          ? t('chart.machinePoint', {
              machine: focused.machine_code,
              hours: formatHours(focused.minutes),
              count: focused.count,
            })
          : undefined
      }
      table={{
        headers: [
          t('chart.machine'),
          t('masters.sections'),
          t('chart.downtime'),
          t('chart.issues'),
          'MTBF',
        ],
        rows: data.map((d) => [
          d.machine_code,
          sectionName(d.section_name),
          formatHours(d.minutes),
          d.count,
          d.mtbf_hours ? `${d.mtbf_hours}h` : '—',
        ]),
      }}
    >
      <ul className="space-y-1">
        {data.map((row, index) => {
          const width = Math.max(2, (row.minutes / max) * 100);
          const isActive = active === row.machine_code;
          const feather = sectionColour(sectionOrder.get(row.section_name), row.section_name);

          const body = (
            <>
              <div className="flex items-baseline justify-between gap-3">
                <span className="min-w-0 truncate font-medium" style={{ color: 'var(--ink)' }}>
                  <span className="rank-marker mr-2" aria-hidden="true">
                    {String(index + 1).padStart(2, '0')}
                  </span>
                  {row.machine_code}
                </span>
                <span
                  className="tabular shrink-0"
                  style={{ fontSize: 'var(--text-sm)', color: 'var(--ink-muted)' }}
                >
                  {formatHours(row.minutes)} · {t('board.issues', { count: row.count })}
                </span>
              </div>
              <div
                className="mt-1.5 h-2 w-full overflow-hidden rounded-full"
                style={{ background: 'var(--viz-track)' }}
              >
                <div
                  className="h-full rounded-full"
                  style={{
                    width: `${width}%`,
                    background: rampColour(SEQ_COLOURS, index),
                    // Cheap on a mid-range Android: transform/opacity only.
                    transition: 'opacity 150ms ease-out',
                    opacity: active === null || isActive ? 1 : 0.55,
                  }}
                />
              </div>
              <p
                className="mt-1 flex flex-wrap gap-x-2"
                style={{ fontSize: 'var(--text-xs)', color: 'var(--ink-muted)' }}
              >
                <span>{sectionName(row.section_name)}</span>
                {row.mtbf_hours ? <span className="tabular">MTBF {row.mtbf_hours}h</span> : null}
              </p>
            </>
          );

          const shell = 'feather arch block w-full px-2.5 py-2 text-left';
          const shellStyle = {
            // Identity lives here now — a rule, not a fill.
            '--feather': feather,
            background: isActive ? 'var(--surface-muted)' : 'transparent',
            transition: 'background 150ms ease-out',
          } as React.CSSProperties;

          return (
            <li key={row.machine_code}>
              {onSelect ? (
                <button
                  type="button"
                  onClick={() => onSelect(row.machine_code)}
                  onPointerEnter={() => setActive(row.machine_code)}
                  onPointerLeave={() => setActive(null)}
                  onFocus={() => setActive(row.machine_code)}
                  onBlur={() => setActive(null)}
                  className={shell}
                  style={shellStyle}
                >
                  {body}
                </button>
              ) : (
                <div className={shell} style={shellStyle}>
                  {body}
                </div>
              )}
            </li>
          );
        })}
      </ul>
    </ChartFrame>
  );
}
