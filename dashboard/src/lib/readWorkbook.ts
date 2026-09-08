/**
 * Read an .xlsx somebody dropped on the page (V5 §11).
 *
 * "Let a dashboard user upload an arbitrary Excel file and get it
 * charted/analyzed on the spot, independent of the main database."
 *
 * INDEPENDENT MEANS INDEPENDENT
 *
 * The file is never uploaded. It is read in the browser, charted in the
 * browser, and forgotten when the tab closes. That is not a shortcut — it is
 * the feature: somebody comparing a vendor quote or last year's register
 * against this plant's numbers should not have to decide whether that file is
 * allowed to land on a server first. Nothing to store, nothing to retain,
 * nothing to explain to IT.
 *
 * WHY THIS IS NOT IN packages/core
 *
 * The writer next door is pure TypeScript and lives there. This one needs
 * `DecompressionStream` and `DOMParser` — real files from Excel are DEFLATE
 * compressed, unlike the ones we write — and CLAUDE.md's rule for that package
 * is no DOM and no browser API. So the reader lives here, where those exist.
 *
 * The dashboard is desktop-only by V5 §11, which is what makes
 * `DecompressionStream` a safe dependency: it has been in every desktop
 * browser since 2023.
 */

export interface ReadSheet {
  name: string;
  rows: (string | number | null)[][];
}

// A spreadsheet somebody drags in is theirs, not ours, and could be anything.
// Refusing early beats freezing a tab on a 200 MB file.
const MAX_BYTES = 25 * 1024 * 1024;
const MAX_ROWS = 5000;

export class WorkbookError extends Error {}

// ---------------------------------------------------------------------------
// ZIP
// ---------------------------------------------------------------------------

async function inflateRaw(bytes: Uint8Array): Promise<Uint8Array> {
  const stream = new Blob([bytes as unknown as BlobPart])
    .stream()
    .pipeThrough(new DecompressionStream('deflate-raw'));
  return new Uint8Array(await new Response(stream).arrayBuffer());
}

/**
 * Every entry in the ZIP, by name.
 *
 * Walked from the END, through the central directory, rather than by scanning
 * local headers forward. A local header may declare its sizes as zero and put
 * them in a trailing descriptor — legal, and what several writers do — so
 * walking forward loses its place on exactly the files Excel itself produces.
 */
async function readZip(bytes: Uint8Array): Promise<Map<string, Uint8Array>> {
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);

  // The end-of-central-directory record is last, but a ZIP may carry a comment
  // after it, so it is searched for backwards.
  let eocd = -1;
  for (let i = bytes.length - 22; i >= 0 && i > bytes.length - 22 - 65536; i -= 1) {
    if (view.getUint32(i, true) === 0x06054b50) {
      eocd = i;
      break;
    }
  }
  if (eocd < 0) throw new WorkbookError('not-a-zip');

  const count = view.getUint16(eocd + 10, true);
  let at = view.getUint32(eocd + 16, true);

  const out = new Map<string, Uint8Array>();
  for (let i = 0; i < count; i += 1) {
    if (view.getUint32(at, true) !== 0x02014b50) break;
    const method = view.getUint16(at + 10, true);
    const compressedSize = view.getUint32(at + 20, true);
    const nameLen = view.getUint16(at + 28, true);
    const extraLen = view.getUint16(at + 30, true);
    const commentLen = view.getUint16(at + 32, true);
    const localAt = view.getUint32(at + 42, true);
    const name = new TextDecoder().decode(bytes.subarray(at + 46, at + 46 + nameLen));

    // The local header's own name and extra lengths, which may differ from the
    // central directory's. Using the central ones here is a classic off-by-a-
    // few-bytes that yields plausible garbage.
    const localNameLen = view.getUint16(localAt + 26, true);
    const localExtraLen = view.getUint16(localAt + 28, true);
    const start = localAt + 30 + localNameLen + localExtraLen;
    const body = bytes.subarray(start, start + compressedSize);

    if (method === 0) out.set(name, body);
    else if (method === 8) out.set(name, await inflateRaw(body));
    // Anything else (bzip2, LZMA) is legal ZIP and not something Excel writes.

    at += 46 + nameLen + extraLen + commentLen;
  }
  return out;
}

// ---------------------------------------------------------------------------
// Sheet XML
// ---------------------------------------------------------------------------

const decode = (bytes: Uint8Array | undefined) =>
  bytes ? new TextDecoder().decode(bytes) : '';

function parse(xml: string): Document {
  const doc = new DOMParser().parseFromString(xml, 'application/xml');
  if (doc.querySelector('parsererror')) throw new WorkbookError('bad-xml');
  return doc;
}

/** Column letters back to a zero-based index: A1 -> 0, AA7 -> 26. */
function columnIndex(ref: string): number {
  let n = 0;
  for (const ch of ref) {
    const code = ch.charCodeAt(0);
    if (code < 65 || code > 90) break;
    n = n * 26 + (code - 64);
  }
  return n - 1;
}

function sharedStrings(files: Map<string, Uint8Array>): string[] {
  const xml = decode(files.get('xl/sharedStrings.xml'));
  if (!xml) return [];
  // Each <si> may be one <t> or several inside <r> runs (mixed formatting in
  // one cell). Joining every <t> under the <si> is what Excel displays.
  return [...parse(xml).getElementsByTagName('si')].map((si) =>
    [...si.getElementsByTagName('t')].map((t) => t.textContent ?? '').join(''),
  );
}

function sheetRows(xml: string, strings: string[]): (string | number | null)[][] {
  const doc = parse(xml);
  const rows: (string | number | null)[][] = [];

  for (const row of [...doc.getElementsByTagName('row')].slice(0, MAX_ROWS)) {
    const cells: (string | number | null)[] = [];
    for (const c of [...row.getElementsByTagName('c')]) {
      const ref = c.getAttribute('r') ?? '';
      const type = c.getAttribute('t');
      const index = ref ? columnIndex(ref) : cells.length;

      let value: string | number | null = null;
      if (type === 's') {
        // An index into the shared string table.
        const i = Number(c.getElementsByTagName('v')[0]?.textContent ?? '');
        value = strings[i] ?? null;
      } else if (type === 'inlineStr') {
        value = [...c.getElementsByTagName('t')].map((t) => t.textContent ?? '').join('');
      } else {
        const raw = c.getElementsByTagName('v')[0]?.textContent;
        if (raw != null && raw !== '') {
          const n = Number(raw);
          value = Number.isFinite(n) ? n : raw;
        }
      }

      // Gaps are real. A blank cell is written as nothing at all, so the
      // reference is the only thing that keeps a column under its header.
      while (cells.length < index) cells.push(null);
      cells[index] = value;
    }
    rows.push(cells);
  }
  return rows;
}

// ---------------------------------------------------------------------------
// Workbook
// ---------------------------------------------------------------------------

export async function readWorkbook(file: File): Promise<ReadSheet[]> {
  if (file.size > MAX_BYTES) throw new WorkbookError('too-large');

  const bytes = new Uint8Array(await file.arrayBuffer());
  const files = await readZip(bytes);
  if (!files.has('xl/workbook.xml')) throw new WorkbookError('not-a-workbook');

  const strings = sharedStrings(files);

  // Sheet NAMES live in workbook.xml and sheet CONTENT in a separate part; the
  // relationship file is what ties them together. Assuming sheet1.xml is the
  // first tab is right most of the time and silently wrong for a workbook
  // whose sheets have been reordered or deleted.
  const rels = decode(files.get('xl/_rels/workbook.xml.rels'));
  const target = new Map<string, string>();
  if (rels) {
    for (const r of [...parse(rels).getElementsByTagName('Relationship')]) {
      const id = r.getAttribute('Id');
      const path = r.getAttribute('Target');
      if (id && path) target.set(id, path.replace(/^\/?(xl\/)?/, ''));
    }
  }

  const out: ReadSheet[] = [];
  for (const sheet of [...parse(decode(files.get('xl/workbook.xml'))).getElementsByTagName(
    'sheet',
  )]) {
    const name = sheet.getAttribute('name') ?? `Sheet${out.length + 1}`;
    const rid =
      sheet.getAttribute('r:id') ?? sheet.getAttributeNS(
        'http://schemas.openxmlformats.org/officeDocument/2006/relationships',
        'id',
      );
    const path = (rid && target.get(rid)) || `worksheets/sheet${out.length + 1}.xml`;
    const xml = decode(files.get(`xl/${path}`));
    if (!xml) continue;
    out.push({ name, rows: sheetRows(xml, strings) });
  }

  if (out.length === 0) throw new WorkbookError('no-sheets');
  return out;
}

/**
 * Which columns hold numbers, judged on the data rather than on the header.
 *
 * A column is numeric if most of its non-empty values are. "Most" rather than
 * "all" because a real register has a "n/a" in it somewhere, and refusing to
 * chart the column over one typed word is not helpful.
 */
export function numericColumns(rows: (string | number | null)[][]): number[] {
  if (rows.length < 2) return [];
  const width = Math.max(...rows.map((r) => r.length));
  const out: number[] = [];
  for (let c = 0; c < width; c += 1) {
    let numbers = 0;
    let filled = 0;
    for (const row of rows.slice(1)) {
      const v = row[c];
      if (v === null || v === undefined || v === '') continue;
      filled += 1;
      if (typeof v === 'number') numbers += 1;
    }
    if (filled > 0 && numbers / filled > 0.6) out.push(c);
  }
  return out;
}

/** Sum one numeric column, grouped by the text in another. Worst first. */
export function groupBy(
  rows: (string | number | null)[][],
  labelColumn: number,
  valueColumn: number,
): { label: string; value: number }[] {
  const totals = new Map<string, number>();
  for (const row of rows.slice(1)) {
    const label = String(row[labelColumn] ?? '—').trim() || '—';
    const value = row[valueColumn];
    if (typeof value !== 'number') continue;
    totals.set(label, (totals.get(label) ?? 0) + value);
  }
  return [...totals.entries()]
    .map(([label, value]) => ({ label, value }))
    .sort((a, b) => b.value - a.value);
}
