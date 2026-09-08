/**
 * A minimal .xlsx writer, with no dependency and no network.
 *
 * WHY NOT A LIBRARY
 *
 * The dashboard is served under a CSP with `script-src 'self'` — no CDN can
 * load, so anything used has to be bundled. SheetJS is around 900 KB, and this
 * bundle is also served to the floor, which is cheap Android phones on plant
 * Wi-Fi. Nine hundred kilobytes so a manager can export a table is the wrong
 * trade for everybody who never presses the button.
 *
 * WHY NOT CSV, WHICH IS FREE
 *
 * Two reasons, and neither is cosmetic.
 *
 * Free-text root causes contain commas and newlines. V5 stores them exactly as
 * typed and forbids touching them, so quoting is the only defence and one
 * missed quote silently shifts a row's columns — a corrupted report that still
 * opens, which is the worst kind.
 *
 * And Excel on Windows opens a UTF-8 CSV as mojibake unless it carries a BOM,
 * which is a per-machine gamble. Half this plant's data is Devanagari. An xlsx
 * stores UTF-8 XML natively, so Hindi arrives as Hindi everywhere.
 *
 * HOW IT WORKS
 *
 * An .xlsx is a ZIP of XML parts. ZIP allows entries to be STORED rather than
 * deflated, which removes the only part that would need a compressor — so this
 * is a CRC32, a handful of headers, and the four XML parts Excel requires. The
 * files are bigger than a compressed workbook and nobody will notice: a
 * filtered report is hundreds of rows, not hundreds of thousands.
 *
 * Strings are written inline rather than through a shared-string table. That
 * costs bytes on repeated values and removes an entire class of bug — an index
 * into a table that disagrees with the table.
 */

export type CellValue = string | number | null | undefined;

export interface Sheet {
  /** Tab name. Excel refuses names over 31 chars and the characters below. */
  name: string;
  /** First row is the header. */
  rows: CellValue[][];
}

// ---------------------------------------------------------------------------
// XML
// ---------------------------------------------------------------------------

function esc(text: string): string {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

/**
 * Excel refuses a file containing control characters, and rejects the whole
 * workbook rather than the offending cell. Operator free text comes from phone
 * keyboards and pasted SAP output, so it does contain them. Tab, newline and
 * carriage return are legal XML and kept.
 */
function clean(text: string): string {
  return text.replace(/[\u0000-\u0008\u000B\u000C\u000E-\u001F]/g, '');
}

/** 0 -> A, 25 -> Z, 26 -> AA. */
export function columnName(index: number): string {
  let n = index + 1;
  let out = '';
  while (n > 0) {
    const rem = (n - 1) % 26;
    out = String.fromCharCode(65 + rem) + out;
    n = Math.floor((n - rem) / 26);
  }
  return out;
}

/**
 * Excel's own rules, applied here rather than left to Excel — an invalid tab
 * name makes it declare the whole workbook corrupt, with no hint which sheet.
 */
export function safeSheetName(name: string, fallback: string): string {
  const cleaned = name
    .replace(/[\\/?*[\]:]/g, ' ')
    .trim()
    .slice(0, 31);
  return cleaned || fallback;
}

function cellXml(value: CellValue, ref: string): string {
  if (value === null || value === undefined || value === '') return '';
  if (typeof value === 'number' && Number.isFinite(value)) {
    return `<c r="${ref}"><v>${value}</v></c>`;
  }
  return `<c r="${ref}" t="inlineStr"><is><t xml:space="preserve">${esc(
    clean(String(value)),
  )}</t></is></c>`;
}

function sheetXml(sheet: Sheet): string {
  const rows = sheet.rows
    .map((row, r) => {
      const cells = row.map((value, c) => cellXml(value, `${columnName(c)}${r + 1}`)).join('');
      return `<row r="${r + 1}">${cells}</row>`;
    })
    .join('');
  return (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
    '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">' +
    // A frozen header row. The first thing anybody does with a few hundred
    // rows is scroll, and then not know which column they are looking at.
    '<sheetViews><sheetView workbookViewId="0">' +
    '<pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/>' +
    '</sheetView></sheetViews>' +
    `<sheetData>${rows}</sheetData></worksheet>`
  );
}

// ---------------------------------------------------------------------------
// ZIP
// ---------------------------------------------------------------------------

const CRC_TABLE = (() => {
  const table = new Uint32Array(256);
  for (let i = 0; i < 256; i += 1) {
    let c = i;
    for (let k = 0; k < 8; k += 1) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    table[i] = c >>> 0;
  }
  return table;
})();

export function crc32(bytes: Uint8Array): number {
  let c = 0xffffffff;
  for (let i = 0; i < bytes.length; i += 1) {
    c = CRC_TABLE[(c ^ bytes[i]!) & 0xff]! ^ (c >>> 8);
  }
  return (c ^ 0xffffffff) >>> 0;
}

interface Entry {
  name: string;
  bytes: Uint8Array;
}

/**
 * A ZIP with every entry STORED.
 *
 * The DOS timestamp is fixed rather than read from the clock, so a workbook
 * exported twice from the same data is byte-identical. That makes "has this
 * changed since last week?" answerable by comparing two files.
 */
function zip(entries: Entry[]): Uint8Array {
  const parts: Uint8Array[] = [];
  const central: Uint8Array[] = [];
  let offset = 0;

  const DOS_TIME = 0; // 00:00:00
  const DOS_DATE = 0x2821; // 2000-01-01

  for (const entry of entries) {
    const nameBytes = new TextEncoder().encode(entry.name);
    const crc = crc32(entry.bytes);
    const size = entry.bytes.length;

    const local = new DataView(new ArrayBuffer(30));
    local.setUint32(0, 0x04034b50, true);
    local.setUint16(4, 20, true); // version needed
    local.setUint16(6, 0x0800, true); // names are UTF-8
    local.setUint16(8, 0, true); // stored, not deflated
    local.setUint16(10, DOS_TIME, true);
    local.setUint16(12, DOS_DATE, true);
    local.setUint32(14, crc, true);
    local.setUint32(18, size, true);
    local.setUint32(22, size, true);
    local.setUint16(26, nameBytes.length, true);
    local.setUint16(28, 0, true);

    parts.push(new Uint8Array(local.buffer), nameBytes, entry.bytes);

    const dir = new DataView(new ArrayBuffer(46));
    dir.setUint32(0, 0x02014b50, true);
    dir.setUint16(4, 20, true); // version made by
    dir.setUint16(6, 20, true); // version needed
    dir.setUint16(8, 0x0800, true);
    dir.setUint16(10, 0, true);
    dir.setUint16(12, DOS_TIME, true);
    dir.setUint16(14, DOS_DATE, true);
    dir.setUint32(16, crc, true);
    dir.setUint32(20, size, true);
    dir.setUint32(24, size, true);
    dir.setUint16(28, nameBytes.length, true);
    dir.setUint32(42, offset, true);

    central.push(new Uint8Array(dir.buffer), nameBytes);
    offset += 30 + nameBytes.length + size;
  }

  const centralSize = central.reduce((sum, p) => sum + p.length, 0);
  const end = new DataView(new ArrayBuffer(22));
  end.setUint32(0, 0x06054b50, true);
  end.setUint16(8, entries.length, true);
  end.setUint16(10, entries.length, true);
  end.setUint32(12, centralSize, true);
  end.setUint32(16, offset, true);

  const all = [...parts, ...central, new Uint8Array(end.buffer)];
  const total = all.reduce((sum, p) => sum + p.length, 0);
  const out = new Uint8Array(total);
  let at = 0;
  for (const part of all) {
    out.set(part, at);
    at += part.length;
  }
  return out;
}

// ---------------------------------------------------------------------------
// Workbook
// ---------------------------------------------------------------------------

const utf8 = (text: string) => new TextEncoder().encode(text);

/** The bytes of a .xlsx holding these sheets, in order. */
export function buildWorkbook(sheets: Sheet[]): Uint8Array {
  const used = sheets.length ? sheets : [{ name: 'Sheet1', rows: [] }];
  const names = used.map((s, i) => safeSheetName(s.name, `Sheet${i + 1}`));

  const contentTypes =
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">' +
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>' +
    '<Default Extension="xml" ContentType="application/xml"/>' +
    '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>' +
    used
      .map(
        (_, i) =>
          `<Override PartName="/xl/worksheets/sheet${i + 1}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>`,
      )
      .join('') +
    '</Types>';

  const rootRels =
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' +
    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>' +
    '</Relationships>';

  const workbook =
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
    '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" ' +
    'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>' +
    names
      .map((name, i) => `<sheet name="${esc(name)}" sheetId="${i + 1}" r:id="rId${i + 1}"/>`)
      .join('') +
    '</sheets></workbook>';

  const workbookRels =
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' +
    used
      .map(
        (_, i) =>
          `<Relationship Id="rId${i + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet${i + 1}.xml"/>`,
      )
      .join('') +
    '</Relationships>';

  return zip([
    { name: '[Content_Types].xml', bytes: utf8(contentTypes) },
    { name: '_rels/.rels', bytes: utf8(rootRels) },
    { name: 'xl/workbook.xml', bytes: utf8(workbook) },
    { name: 'xl/_rels/workbook.xml.rels', bytes: utf8(workbookRels) },
    ...used.map((sheet, i) => ({
      name: `xl/worksheets/sheet${i + 1}.xml`,
      bytes: utf8(sheetXml(sheet)),
    })),
  ]);
}
