/**
 * The xlsx writer produces BYTES, and a wrong byte does not fail loudly — it
 * makes Excel say "we found a problem with some content" and offer to repair,
 * with no hint what. So these read the ZIP structure back rather than trusting
 * that it looks right.
 */

import { describe, expect, it } from 'vitest';

import { buildWorkbook, columnName, crc32, safeSheetName } from './xlsx';

/** Read the stored entries back out of the ZIP, by name. */
function unzip(bytes: Uint8Array): Map<string, string> {
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const out = new Map<string, string>();
  let at = 0;
  while (at + 4 <= bytes.length && view.getUint32(at, true) === 0x04034b50) {
    const nameLen = view.getUint16(at + 26, true);
    const extraLen = view.getUint16(at + 28, true);
    const size = view.getUint32(at + 22, true);
    const storedCrc = view.getUint32(at + 14, true);
    const name = new TextDecoder().decode(bytes.subarray(at + 30, at + 30 + nameLen));
    const start = at + 30 + nameLen + extraLen;
    const body = bytes.subarray(start, start + size);
    // The CRC is the one field nothing else would catch: Excel checks it and
    // refuses the file, but every string comparison in this test would pass.
    expect(crc32(body)).toBe(storedCrc);
    out.set(name, new TextDecoder().decode(body));
    at = start + size;
  }
  return out;
}

describe('column names', () => {
  it('counts past Z the way a spreadsheet does', () => {
    expect(columnName(0)).toBe('A');
    expect(columnName(25)).toBe('Z');
    expect(columnName(26)).toBe('AA');
    expect(columnName(51)).toBe('AZ');
    expect(columnName(52)).toBe('BA');
    expect(columnName(701)).toBe('ZZ');
  });
});

describe('sheet names', () => {
  it('strips what Excel refuses rather than letting it corrupt the file', () => {
    // An invalid tab name makes Excel declare the WHOLE workbook broken, with
    // no hint which sheet — so it is fixed here, not discovered there.
    expect(safeSheetName('Press/Sanding: 2026', 'x')).toBe('Press Sanding  2026');
    expect(safeSheetName('a'.repeat(50), 'x')).toHaveLength(31);
    expect(safeSheetName('   ', 'Sheet1')).toBe('Sheet1');
  });
});

describe('the workbook', () => {
  it('has the four parts Excel requires, plus one per sheet', () => {
    const files = unzip(buildWorkbook([{ name: 'One', rows: [['a']] }]));
    expect([...files.keys()].sort()).toEqual([
      '[Content_Types].xml',
      '_rels/.rels',
      'xl/_rels/workbook.xml.rels',
      'xl/workbook.xml',
      'xl/worksheets/sheet1.xml',
    ]);
  });

  it('names every sheet and points each relationship at its own file', () => {
    const files = unzip(
      buildWorkbook([
        { name: 'Tickets', rows: [] },
        { name: 'Production', rows: [] },
      ]),
    );
    const workbook = files.get('xl/workbook.xml')!;
    expect(workbook).toContain('name="Tickets"');
    expect(workbook).toContain('name="Production"');
    const rels = files.get('xl/_rels/workbook.xml.rels')!;
    expect(rels).toContain('Target="worksheets/sheet1.xml"');
    expect(rels).toContain('Target="worksheets/sheet2.xml"');
    expect(files.has('xl/worksheets/sheet2.xml')).toBe(true);
  });

  it('writes numbers as numbers and text as text', () => {
    // A sheet count arriving as text is a column that will not SUM, which is
    // the first thing anybody does to it.
    const sheet = unzip(buildWorkbook([{ name: 'S', rows: [['Machine', 'Made'], ['Press-1', 250]] }])).get(
      'xl/worksheets/sheet1.xml',
    )!;
    expect(sheet).toContain('<c r="B2"><v>250</v></c>');
    expect(sheet).toContain('<c r="A2" t="inlineStr">');
  });

  it('escapes what would otherwise close a tag', () => {
    const sheet = unzip(
      buildWorkbook([{ name: 'S', rows: [['Bearing <worn> & "loose"']] }]),
    ).get('xl/worksheets/sheet1.xml')!;
    expect(sheet).toContain('Bearing &lt;worn&gt; &amp; &quot;loose&quot;');
  });

  it('keeps Devanagari intact', () => {
    // The reason this is not a CSV. Excel on Windows opens a UTF-8 CSV as
    // mojibake without a BOM; xlsx carries UTF-8 XML natively.
    const sheet = unzip(buildWorkbook([{ name: 'S', rows: [['बेयरिंग घिस गया']] }])).get(
      'xl/worksheets/sheet1.xml',
    )!;
    expect(sheet).toContain('बेयरिंग घिस गया');
  });

  it('drops control characters instead of producing a file Excel repairs', () => {
    // Escapes, not literal bytes: a control character in a test fixture is
    // invisible in every diff and editor, and the next person to touch this
    // line would delete it without knowing.
    const nasty = 'bad\u0000text\u0007here';
    const sheet = unzip(buildWorkbook([{ name: 'S', rows: [[nasty]] }])).get(
      'xl/worksheets/sheet1.xml',
    )!;
    expect(sheet).toContain('badtexthere');
  });

  it('keeps the newline inside a typed root cause', () => {
    // Legal XML, and the operator meant it. Only the illegal ones go.
    const sheet = unzip(buildWorkbook([{ name: 'S', rows: [['line one\nline two']] }])).get(
      'xl/worksheets/sheet1.xml',
    )!;
    expect(sheet).toContain('line one\nline two');
  });

  it('leaves an empty cell out rather than writing an empty string', () => {
    const sheet = unzip(buildWorkbook([{ name: 'S', rows: [['a', null, 'c']] }])).get(
      'xl/worksheets/sheet1.xml',
    )!;
    expect(sheet).toContain('r="A1"');
    expect(sheet).not.toContain('r="B1"');
    expect(sheet).toContain('r="C1"');
  });

  it('is byte-identical when exported twice from the same data', () => {
    // Nothing reads the clock, so "has this changed since last week?" is
    // answerable by comparing two files.
    const rows = [['Machine', 'Made'], ['Press-1', 250]];
    expect(buildWorkbook([{ name: 'S', rows }])).toEqual(buildWorkbook([{ name: 'S', rows }]));
  });

  it('starts with the ZIP magic, so the browser and Excel both recognise it', () => {
    const bytes = buildWorkbook([{ name: 'S', rows: [] }]);
    expect([...bytes.slice(0, 4)]).toEqual([0x50, 0x4b, 0x03, 0x04]);
  });

  it('survives being asked for nothing', () => {
    expect(() => unzip(buildWorkbook([]))).not.toThrow();
  });
});
