/**
 * Export whatever the board is currently showing (V5 §11.2).
 *
 * "Any filtered report/view can be exported to PDF or Excel on demand." The
 * Share-through-Outlook half of that section needs a Microsoft Graph app
 * registration nobody has issued yet; this is the half that does not.
 *
 * WHY THE FIRST SHEET IS THE FILTERS
 *
 * This file leaves the building. It gets forwarded, printed, and quoted in a
 * meeting three weeks later by somebody who was not in the room when it was
 * made. A workbook of numbers with no statement of what they cover is worse
 * than no workbook: "downtime 4 hours" reads as the plant until you learn it
 * was one press, on the night shift, for a fortnight.
 *
 * So sheet one says the period, the module, every filter that was applied, and
 * when it was generated. It is the only sheet that cannot be omitted.
 *
 * WHY IT IS BUILT IN THE BROWSER
 *
 * CLAUDE.md: Excel generation never runs on Render — 512 MB and 0.1 CPU are
 * for serving the floor, not for building workbooks. The data for this one is
 * already in the page, so the honest place to assemble it is here, where it
 * costs the server nothing and works on a sleeping instance.
 *
 * INDIVIDUAL NAMES ARE NOT IN IT
 *
 * Nothing here is per-person. CLAUDE.md is explicit that individual technician
 * metrics never travel in an emailed workbook, and a "who fixed what" sheet is
 * exactly the thing somebody would add without thinking.
 */

import { buildWorkbook, type CellValue, type Sheet } from '@greenlam/core';

import type * as api from './api';

export interface ExportContext {
  module: 'maintenance' | 'production' | 'combined';
  days: number;
  filters: api.BoardFilters;
  /** Already localised by the caller — this module has no i18n of its own. */
  labels: {
    title: string;
    generatedAt: string;
    period: string;
    module: string;
    moduleName: string;
    filter: string;
    value: string;
    noFilters: string;
    sheets: Record<string, string>;
    columns: Record<string, string>;
  };
  /** Human-readable filter lines, resolved to names by the caller. */
  appliedFilters: { label: string; value: string }[];
}

function summarySheet(ctx: ExportContext): Sheet {
  const l = ctx.labels;
  const rows: CellValue[][] = [
    [l.title],
    [],
    [l.generatedAt, new Date().toLocaleString()],
    [l.period, ctx.days],
    [l.module, l.moduleName],
    [],
    [l.filter, l.value],
  ];
  if (ctx.appliedFilters.length === 0) rows.push([l.noFilters]);
  else for (const f of ctx.appliedFilters) rows.push([f.label, f.value]);
  return { name: l.sheets.summary!, rows };
}

function kpiSheet(stats: api.Analytics, ctx: ExportContext): Sheet {
  const c = ctx.labels.columns;
  const k = stats.kpis;
  return {
    name: ctx.labels.sheets.kpis!,
    rows: [
      [c.measure!, c.value!],
      [c.downtimeMinutes!, k.downtime_minutes],
      [c.breakdowns!, k.breakdown_total],
      [c.mttr!, k.mttr_minutes],
      [c.mtta!, k.mtta_minutes],
      [c.mtbf!, k.mtbf_hours],
      [c.availability!, k.availability_percent],
      [c.firstTimeFix!, k.first_time_fix_percent],
      [c.reopenRate!, k.reopen_percent],
      [c.rootCauseUsable!, k.root_cause_usable_percent],
      [],
      [c.criticality!, c.count!],
      ...['Low', 'Medium', 'High'].map((band): CellValue[] => [
        band,
        k.criticality_mix[band] ?? 0,
      ]),
      [c.criticalityUnmeasured!, k.criticality_unmeasured],
    ],
  };
}

function machineSheet(stats: api.Analytics, ctx: ExportContext): Sheet {
  const c = ctx.labels.columns;
  return {
    name: ctx.labels.sheets.machines!,
    rows: [
      [c.machine!, c.section!, c.downtimeMinutes!, c.breakdowns!, c.mtbf!, c.lastFailure!],
      ...stats.top_machines.map((m): CellValue[] => [
        m.machine_code,
        m.section_name,
        m.minutes,
        m.failures,
        m.mtbf_hours,
        m.last_failure,
      ]),
    ],
  };
}

function causeSheet(stats: api.Analytics, ctx: ExportContext): Sheet {
  const c = ctx.labels.columns;
  return {
    name: ctx.labels.sheets.causes!,
    rows: [
      [c.cause!, c.downtimeMinutes!, c.breakdowns!, c.cumulative!],
      ...stats.pareto_by_cause.map((p): CellValue[] => [
        p.label,
        p.minutes,
        p.count,
        p.cumulative_percent,
      ]),
    ],
  };
}

function downtimeTrendSheet(stats: api.Analytics, ctx: ExportContext): Sheet {
  const c = ctx.labels.columns;
  return {
    name: ctx.labels.sheets.downtimeDaily!,
    rows: [
      [c.date!, ...stats.downtime_trend.series, c.total!],
      ...stats.downtime_trend.points.map((p): CellValue[] => [
        p.date,
        ...p.values,
        p.values.reduce((a, b) => a + b, 0),
      ]),
    ],
  };
}

function productionSheets(prod: api.ProductionAnalytics, ctx: ExportContext): Sheet[] {
  const c = ctx.labels.columns;
  const s = ctx.labels.sheets;

  const segment = (name: string, rows: api.SegmentRow[]): Sheet => ({
    name,
    rows: [
      [c.segment!, c.produced!, c.rejected!, c.rejectPercent!],
      ...rows.map((r): CellValue[] => [r.label, r.produced, r.rejected, r.reject_percent]),
    ],
  });

  return [
    {
      name: s.outputDaily!,
      rows: [
        [c.date!, c.produced!, c.rejected!, c.rejectPercent!],
        ...prod.daily.map((d): CellValue[] => [
          d.date,
          d.produced,
          d.rejected,
          d.reject_percent,
        ]),
      ],
    },
    {
      name: s.rejectReasons!,
      rows: [
        [c.reason!, c.sheets!, c.share!, c.cumulative!],
        ...prod.reject_pareto.map((r): CellValue[] => [
          r.label,
          r.quantity,
          r.percent,
          r.cumulative_percent,
        ]),
      ],
    },
    segment(s.byMachine!, prod.by_machine),
    segment(s.byShift!, prod.by_shift),
    segment(s.bySection!, prod.by_section),
    segment(s.byTexture!, prod.by_texture),
  ];
}

/** The sheets this view is worth, in reading order. */
export function sheetsFor(
  ctx: ExportContext,
  stats: api.Analytics | null,
  prod: api.ProductionAnalytics | null,
): Sheet[] {
  const sheets: Sheet[] = [summarySheet(ctx)];
  // Each half is included only when it is on screen. Exporting the maintenance
  // numbers from the production view would hand somebody a sheet they never
  // saw and cannot account for.
  if (ctx.module !== 'production' && stats) {
    sheets.push(
      kpiSheet(stats, ctx),
      machineSheet(stats, ctx),
      causeSheet(stats, ctx),
      downtimeTrendSheet(stats, ctx),
    );
  }
  if (ctx.module !== 'maintenance' && prod) {
    sheets.push(...productionSheets(prod, ctx));
  }
  return sheets;
}

/**
 * A filename somebody can find again in a Downloads folder six weeks later.
 *
 * Module and date, not "export (3).xlsx".
 */
export function exportFilename(ctx: ExportContext): string {
  const day = new Date().toISOString().slice(0, 10);
  return `greenlam-${ctx.module}-${ctx.days}d-${day}.xlsx`;
}

/** Build the workbook and hand it to the browser. */
export function downloadView(
  ctx: ExportContext,
  stats: api.Analytics | null,
  prod: api.ProductionAnalytics | null,
): void {
  const bytes = buildWorkbook(sheetsFor(ctx, stats, prod));
  const blob = new Blob([bytes as unknown as BlobPart], {
    type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = exportFilename(ctx);
  document.body.appendChild(a);
  a.click();
  a.remove();
  // Revoked on the next tick rather than immediately: Safari has been known to
  // cancel the download if the URL dies in the same frame as the click.
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
