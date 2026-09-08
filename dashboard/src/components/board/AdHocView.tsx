/**
 * Chart a spreadsheet somebody brought with them (V5 §11).
 *
 * "Let a dashboard user upload an arbitrary Excel file and get it
 * charted/analyzed on the spot, independent of the main database (useful for
 * one-off comparisons)."
 *
 * THE FILE NEVER LEAVES THE BROWSER
 *
 * It is read, charted and forgotten when the tab closes. Nothing is uploaded,
 * nothing is stored, and the API never sees it. That is the feature, not a
 * shortcut: somebody comparing a vendor quote or last year's register against
 * this plant's numbers should not first have to decide whether that file is
 * allowed to sit on a server. There is nothing to retain and nothing to
 * explain to IT.
 *
 * WHY IT ASKS WHICH COLUMNS RATHER THAN GUESSING
 *
 * An arbitrary file has no schema. The app can tell which columns hold numbers
 * — that is arithmetic — but not which one the reader came to look at. A guess
 * that lands on "Year" instead of "Downtime" produces a confident chart of
 * nothing, and confident is the problem. So the columns are picked, with a
 * sensible pair chosen up front so the first look costs no clicks.
 *
 * DELIBERATELY SEPARATE FROM /import
 *
 * Import rewrites shared history for the whole plant and is guarded by
 * `editMasters`. This changes nothing and is guarded by Dashboard. Putting
 * them on one screen would be one misread button between "look at my file" and
 * "overwrite the plant's".
 */

import { useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';

import {
  groupBy,
  numericColumns,
  readWorkbook,
  WorkbookError,
  type ReadSheet,
} from '../../lib/readWorkbook';
import { SEQ_COLOURS, rampColour } from '../charts/primitives';

export function AdHocView() {
  const { t } = useTranslation();
  const input = useRef<HTMLInputElement>(null);

  const [fileName, setFileName] = useState('');
  const [sheets, setSheets] = useState<ReadSheet[]>([]);
  const [active, setActive] = useState(0);
  const [labelCol, setLabelCol] = useState(0);
  const [valueCol, setValueCol] = useState(1);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const sheet = sheets[active];
  const headers = useMemo(
    () => (sheet?.rows[0] ?? []).map((h, i) => String(h ?? `#${i + 1}`)),
    [sheet],
  );
  const numeric = useMemo(() => (sheet ? numericColumns(sheet.rows) : []), [sheet]);
  const grouped = useMemo(
    () => (sheet ? groupBy(sheet.rows, labelCol, valueCol).slice(0, 20) : []),
    [sheet, labelCol, valueCol],
  );

  /** Pick a first pair worth looking at, so the file charts on arrival. */
  function chooseColumns(s: ReadSheet) {
    const nums = numericColumns(s.rows);
    const value = nums[0] ?? 1;
    // A label column that is not the value column, preferring a text one.
    const width = Math.max(...s.rows.map((r) => r.length), 1);
    let label = 0;
    for (let c = 0; c < width; c += 1) {
      if (c !== value && !nums.includes(c)) {
        label = c;
        break;
      }
    }
    setLabelCol(label);
    setValueCol(value);
  }

  async function take(file: File | undefined) {
    if (!file) return;
    setBusy(true);
    setError('');
    try {
      const read = await readWorkbook(file);
      setSheets(read);
      setActive(0);
      setFileName(file.name);
      chooseColumns(read[0]!);
    } catch (e) {
      setSheets([]);
      setFileName('');
      setError(
        e instanceof WorkbookError
          ? t(`adhoc.errors.${e.message}`, { defaultValue: t('adhoc.errors.failed') })
          : t('adhoc.errors.failed'),
      );
    } finally {
      setBusy(false);
      if (input.current) input.current.value = '';
    }
  }

  const field = {
    fontSize: 'var(--text-sm)',
    borderColor: 'var(--line-strong)',
    background: 'var(--surface)',
    color: 'var(--ink)',
  } as const;

  const max = Math.max(...grouped.map((g) => Math.abs(g.value)), 1);

  return (
    <div className="space-y-6 pt-2 pb-12">
      <header>
        <h1
          className="font-display font-semibold"
          style={{ fontSize: 'var(--text-2xl)', color: 'var(--ink)' }}
        >
          {t('adhoc.title')}
        </h1>
        <p className="mt-1" style={{ color: 'var(--ink-muted)' }}>
          {t('adhoc.blurb')}
        </p>
      </header>

      <div>
        <input
          ref={input}
          type="file"
          accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
          className="sr-only"
          id="adhoc-file"
          onChange={(e) => void take(e.target.files?.[0])}
        />
        <label
          htmlFor="adhoc-file"
          className="arch inline-block cursor-pointer border px-4 py-3 font-medium"
          style={{ borderColor: 'var(--accent)', background: 'var(--accent-quiet)', color: 'var(--ink)' }}
        >
          {busy ? t('adhoc.reading') : fileName ? t('adhoc.chooseAnother') : t('adhoc.choose')}
        </label>
        {fileName && (
          <span className="ml-3" style={{ color: 'var(--ink-muted)', fontSize: 'var(--text-sm)' }}>
            {fileName}
          </span>
        )}
        <p className="mt-2" style={{ fontSize: 'var(--text-xs)', color: 'var(--ink-muted)' }}>
          {t('adhoc.privacy')}
        </p>
      </div>

      {error && (
        <p
          role="alert"
          className="arch px-3 py-2"
          style={{ background: 'var(--rust-tint)', color: 'var(--rust)' }}
        >
          {error}
        </p>
      )}

      {sheet && (
        <>
          {sheets.length > 1 && (
            <div role="radiogroup" aria-label={t('adhoc.sheet')} className="flex flex-wrap gap-2">
              {sheets.map((s, i) => (
                <button
                  key={s.name}
                  type="button"
                  role="radio"
                  aria-checked={i === active}
                  onClick={() => {
                    setActive(i);
                    chooseColumns(s);
                  }}
                  className="arch border px-3 py-1.5 font-medium"
                  style={{
                    fontSize: 'var(--text-sm)',
                    borderColor: i === active ? 'var(--accent)' : 'var(--line)',
                    background: i === active ? 'var(--accent-quiet)' : 'var(--surface)',
                    color: 'var(--ink)',
                  }}
                >
                  {s.name}
                </button>
              ))}
            </div>
          )}

          <div className="flex flex-wrap items-end gap-3">
            <div>
              <label
                htmlFor="adhoc-label"
                className="mb-1 block font-medium"
                style={{ fontSize: 'var(--text-xs)', color: 'var(--ink-muted)' }}
              >
                {t('adhoc.groupBy')}
              </label>
              <select
                id="adhoc-label"
                value={labelCol}
                onChange={(e) => setLabelCol(Number(e.target.value))}
                className="arch border px-2.5 py-2"
                style={field}
              >
                {headers.map((h, i) => (
                  <option key={i} value={i}>
                    {h}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label
                htmlFor="adhoc-value"
                className="mb-1 block font-medium"
                style={{ fontSize: 'var(--text-xs)', color: 'var(--ink-muted)' }}
              >
                {t('adhoc.measure')}
              </label>
              <select
                id="adhoc-value"
                value={valueCol}
                onChange={(e) => setValueCol(Number(e.target.value))}
                className="arch border px-2.5 py-2"
                style={field}
              >
                {headers.map((h, i) => (
                  <option key={i} value={i} disabled={!numeric.includes(i)}>
                    {/* Non-numeric columns stay visible but unpickable: hiding
                        them makes a reader hunt for a column that is right
                        there in their file. */}
                    {h}
                    {numeric.includes(i) ? '' : ` — ${t('adhoc.notNumeric')}`}
                  </option>
                ))}
              </select>
            </div>
          </div>

          {grouped.length === 0 ? (
            <p style={{ color: 'var(--ink-muted)' }}>{t('adhoc.nothingToChart')}</p>
          ) : (
            <section aria-labelledby="adhoc-chart">
              <h2
                id="adhoc-chart"
                className="register-rule pb-1 font-semibold"
                style={{ fontSize: 'var(--text-sm)', color: 'var(--ink)' }}
              >
                {t('adhoc.chartTitle', {
                  measure: headers[valueCol] ?? '',
                  group: headers[labelCol] ?? '',
                })}
              </h2>
              <ul className="mt-3 space-y-2">
                {grouped.map((g, i) => (
                  <li key={g.label}>
                    <div className="flex items-baseline justify-between gap-3">
                      <span style={{ fontSize: 'var(--text-sm)', color: 'var(--ink)' }}>
                        {g.label}
                      </span>
                      <span
                        className="tabular shrink-0"
                        style={{ fontSize: 'var(--text-sm)', color: 'var(--ink-muted)' }}
                      >
                        {g.value.toLocaleString('en-IN')}
                      </span>
                    </div>
                    <div
                      className="mt-1 h-2 w-full overflow-hidden rounded-full"
                      style={{ background: 'var(--viz-track)' }}
                      aria-hidden="true"
                    >
                      <div
                        className="h-full rounded-full"
                        style={{
                          width: `${Math.max(2, (Math.abs(g.value) / max) * 100)}%`,
                          background: rampColour(SEQ_COLOURS, i),
                        }}
                      />
                    </div>
                  </li>
                ))}
              </ul>
              <p className="mt-3" style={{ fontSize: 'var(--text-xs)', color: 'var(--ink-muted)' }}>
                {t('adhoc.rowsRead', { count: Math.max(0, sheet.rows.length - 1) })}
              </p>
            </section>
          )}

          <section aria-labelledby="adhoc-table">
            <h2
              id="adhoc-table"
              className="register-rule pb-1 font-semibold"
              style={{ fontSize: 'var(--text-sm)', color: 'var(--ink)' }}
            >
              {t('adhoc.firstRows')}
            </h2>
            <div className="mt-2 overflow-x-auto">
              <table style={{ fontSize: 'var(--text-sm)', color: 'var(--ink)' }}>
                <thead>
                  <tr>
                    {headers.map((h, i) => (
                      <th
                        key={i}
                        scope="col"
                        className="px-2 py-1 text-left font-semibold whitespace-nowrap"
                        style={{ borderBottom: '1px solid var(--line-strong)' }}
                      >
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {sheet.rows.slice(1, 11).map((row, r) => (
                    <tr key={r}>
                      {headers.map((_, c) => (
                        <td
                          key={c}
                          className="px-2 py-1 whitespace-nowrap"
                          style={{ borderBottom: '1px solid var(--line)' }}
                        >
                          {row[c] ?? ''}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        </>
      )}
    </div>
  );
}
