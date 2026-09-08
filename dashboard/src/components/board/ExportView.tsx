/**
 * Take this view away with you (V5 §11.2).
 *
 * Two buttons, because they answer two different questions.
 *
 * EXCEL is for the person who wants to do arithmetic on it — pivot it, chart
 * it their own way, paste a column into a deck. It carries the numbers behind
 * every panel on screen, not a picture of them.
 *
 * PRINT is for the person who wants the page as it looks, on paper or as a
 * PDF. It is `window.print()` rather than a bundled PDF library: the browser's
 * own dialog already offers Save as PDF on every platform this runs on, it
 * renders the real charts rather than a redrawn approximation, and it costs
 * nothing to load for the hundreds of people who never press it.
 *
 * WHAT V5 ASKS FOR THAT IS NOT HERE
 *
 * The "Share" action that mails the export through Outlook. It calls the same
 * Microsoft Graph app registration as the §8 Excel sync, and Greenlam IT has
 * not issued one — there is nothing to authenticate against and nothing to
 * test. Writing it blind would produce code that has never once run.
 */

import { useState } from 'react';
import { useTranslation } from 'react-i18next';

import type * as api from '../../lib/api';
import { downloadView, type ExportContext } from '../../lib/exportView';
import type { BoardModule } from './FilterBar';

export function ExportView({
  module,
  days,
  filters,
  stats,
  prod,
  machines,
  sections,
  shifts,
}: {
  module: BoardModule;
  days: number;
  filters: api.BoardFilters;
  stats: api.Analytics | null;
  prod: api.ProductionAnalytics | null;
  /** Passed in so the export can name what the filters selected, not number it. */
  machines: api.Machine[];
  sections: api.Section[];
  shifts: api.Shift[];
}) {
  const { t } = useTranslation();
  const [busy, setBusy] = useState(false);

  function applied(): { label: string; value: string }[] {
    const out: { label: string; value: string }[] = [];
    // Resolved to names. "section_id 3" in a workbook somebody opens next month
    // is not a filter, it is a puzzle.
    if (filters.section_id != null) {
      const s = sections.find((x) => x.id === filters.section_id);
      out.push({ label: t('filters.machineType'), value: s?.name ?? String(filters.section_id) });
    }
    if (filters.machine_id != null) {
      const m = machines.find((x) => x.id === filters.machine_id);
      out.push({ label: t('filters.machine'), value: m?.code ?? String(filters.machine_id) });
    }
    if (filters.shift_id != null) {
      const s = shifts.find((x) => x.id === filters.shift_id);
      out.push({ label: t('filters.shift'), value: s?.name ?? String(filters.shift_id) });
    }
    if (filters.hour_from != null && filters.hour_to != null) {
      const hh = (h: number) => `${String(h).padStart(2, '0')}:00`;
      out.push({
        label: t('filters.timeOfDay'),
        value: `${hh(filters.hour_from)} – ${hh(filters.hour_to)}`,
      });
    }
    if (filters.load_no) out.push({ label: t('filters.loadNo'), value: filters.load_no });
    return out;
  }

  function context(): ExportContext {
    return {
      module,
      days,
      filters,
      appliedFilters: applied(),
      labels: {
        title: t('exportView.title'),
        generatedAt: t('exportView.generatedAt'),
        period: t('exportView.periodDays'),
        module: t('board.viewLabel'),
        moduleName: t(
          module === 'combined'
            ? 'board.viewCombined'
            : module === 'maintenance'
              ? 'board.viewMaintenance'
              : 'board.viewProduction',
        ),
        filter: t('exportView.filter'),
        value: t('exportView.value'),
        noFilters: t('exportView.noFilters'),
        sheets: {
          summary: t('exportView.sheetSummary'),
          kpis: t('exportView.sheetKpis'),
          machines: t('exportView.sheetMachines'),
          causes: t('exportView.sheetCauses'),
          downtimeDaily: t('exportView.sheetDowntimeDaily'),
          outputDaily: t('exportView.sheetOutputDaily'),
          rejectReasons: t('exportView.sheetRejectReasons'),
          byMachine: t('exportView.sheetByMachine'),
          byShift: t('exportView.sheetByShift'),
          bySection: t('exportView.sheetBySection'),
          byTexture: t('exportView.sheetByTexture'),
        },
        columns: {
          measure: t('exportView.colMeasure'),
          value: t('exportView.value'),
          count: t('exportView.colCount'),
          date: t('chart.date'),
          total: t('chart.total'),
          machine: t('filters.machine'),
          section: t('filters.machineType'),
          cause: t('exportView.colCause'),
          reason: t('exportView.colReason'),
          segment: t('exportView.colSegment'),
          share: t('exportView.colShare'),
          cumulative: t('chart.cumulative'),
          sheets: t('production.sheets'),
          produced: t('production.produced'),
          rejected: t('production.rejected'),
          rejectPercent: t('production.rejectPercent'),
          downtimeMinutes: t('exportView.colDowntimeMinutes'),
          breakdowns: t('exportView.colBreakdowns'),
          mttr: t('board.mttr'),
          mtta: t('board.mtta'),
          mtbf: t('board.mtbf'),
          availability: t('board.availability'),
          firstTimeFix: t('board.firstTimeFix'),
          reopenRate: t('board.reopenRate'),
          rootCauseUsable: t('board.rootCauseQuality'),
          criticality: t('board.criticalityTitle'),
          criticalityUnmeasured: t('exportView.colCriticalityUnmeasured'),
          lastFailure: t('exportView.colLastFailure'),
        },
      },
    };
  }

  function toExcel() {
    setBusy(true);
    try {
      downloadView(context(), stats, prod);
    } finally {
      setBusy(false);
    }
  }

  const button = {
    fontSize: 'var(--text-sm)',
    borderColor: 'var(--line-strong)',
    color: 'var(--ink)',
  } as const;

  return (
    // Hidden on paper: a print of the page should not show the buttons that
    // made the print.
    <div className="no-print flex gap-2">
      <button
        type="button"
        onClick={toExcel}
        disabled={busy || (!stats && !prod)}
        className="arch border px-3 py-1.5 font-medium disabled:opacity-50"
        style={button}
      >
        {t('exportView.excel')}
      </button>
      <button
        type="button"
        onClick={() => window.print()}
        className="arch border px-3 py-1.5 font-medium"
        style={button}
      >
        {t('exportView.print')}
      </button>
    </div>
  );
}
