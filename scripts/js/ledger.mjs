// Byte-preserving CSV ledger for the Mr Tú content factory (Node fallback).
//
// Purpose: the interactive AI runtime often has Node but no Python. This
// module makes it possible to safely process data/content-matrix.csv
// (~990 KB, 2,008 data rows) WITHOUT depending on scripts/*.py:
//
//   - reads the complete ledger without truncation
//   - parses RFC 4180 (quoted fields, embedded commas/newlines, CRLF)
//   - keeps the RAW source line of every row; rows that are not edited
//     are re-emitted verbatim, so unrelated rows/columns are preserved
//     byte-semantically
//   - rows that ARE edited are re-serialized exactly like Python's
//     csv.DictWriter (QUOTE_MINIMAL, CRLF) so output stays interchangeable
//     with the canonical scripts/run_article_batch.py pipeline
//
// No dependencies. Node >= 18.

import { Buffer } from 'node:buffer';

export const PRODUCTION_PREFIXES = ['KN-', 'AT-', 'XM-', 'DL-', 'CD-', 'HD-'];

export function isSampleRow(row) {
  const id = (row.fields[0] || '').trim();
  return id.startsWith('SAMPLE');
}

// ---------------------------------------------------------------- parsing

/**
 * Parse a CSV document into a ledger.
 * Returns { header: string[], rows: Row[], trailingNewline: boolean }
 * Row = { recordStart, raw, fields, lineIndex }
 *   raw     — the exact original text of the record INCLUDING its CRLF
 *   fields  — parsed field values (quotes resolved)
 */
export function parseLedger(text) {
  const len = text.length;
  const rows = [];
  let header = null;
  let i = 0;
  let recordStart = 0;
  let fields = [];
  let field = '';
  let inQuotes = false;
  let fieldStartQuoted = false;
  let lineIndex = 0;
  let trailing = true;

  const pushField = () => { fields.push(field); field = ''; };
  const pushRecord = (end) => {
    pushField();
    const raw = text.slice(recordStart, end);
    if (header === null) {
      header = fields;
    } else {
      rows.push({ raw, fields, lineIndex });
    }
    fields = [];
  };

  while (i < len) {
    const ch = text[i];
    if (inQuotes) {
      if (ch === '"') {
        if (text[i + 1] === '"') { field += '"'; i += 2; continue; }
        inQuotes = false; i++; continue;
      }
      field += ch; i++; continue;
    }
    if (ch === '"' && field === '') { inQuotes = true; fieldStartQuoted = true; i++; continue; }
    if (ch === ',') { pushField(); i++; continue; }
    if (ch === '\r' && text[i + 1] === '\n') { i += 2; pushRecord(i); recordStart = i; lineIndex++; continue; }
    if (ch === '\n' || ch === '\r') { i += 1; pushRecord(i); recordStart = i; lineIndex++; continue; }
    field += ch; i++;
  }
  if (i > recordStart || field !== '' || fields.length) {
    trailing = false;
    pushRecord(i);
  }
  if (header === null) header = [];
  return { header, rows, trailingNewline: trailing };
}

/**
 * Serialize one row exactly like Python csv.writer(QUOTE_MINIMAL,
 * lineterminator="\r\n"): quote a field only if it contains a comma, a
 * double quote, CR or LF; double quotes are escaped as "".
 */
export function serializeRow(fields) {
  const line = fields.map((f) => {
    const s = f == null ? '' : String(f);
    if (/[",\r\n]/.test(s)) return '"' + s.replace(/"/g, '""') + '"';
    return s;
  }).join(',');
  return line + '\r\n';
}

/** Full round-trip: parse + re-serialize every row. Must be byte-identical. */
export function roundTrip(text) {
  const led = parseLedger(text);
  return led.header.join(',') + '\r\n' + led.rows.map((r) => {
    const out = serializeRow(r.fields);
    // A quoted field may legitimately encode its own line break; the raw
    // record then spans multiple physical lines. serializeRow always emits
    // CRLF, so a raw record using lone \n cannot round-trip — detect and
    // keep the raw text when re-serialization would differ.
    return out === r.raw ? out : r.raw;
  }).join('') + (led.trailingNewline ? '' : '');
}

/**
 * Build the new ledger text with per-row field updates.
 * updates: Map<articleId -> {col: value}]. Only the named columns of the
 * targeted rows change; every other byte of the document is preserved.
 * Throws on: duplicate ids, unknown id, unknown column.
 */
export function applyUpdates(text, updates, { expectHeader = null } = {}) {
  const led = parseLedger(text);
  if (expectHeader !== null && led.header.join(',') !== expectHeader.join(',')) {
    throw new Error('header mismatch — refusing to rewrite ledger');
  }
  const idIndex = 0; // article_id is always column 0
  const colIndex = new Map(led.header.map((h, idx) => [h, idx]));
  const seen = new Set();
  const remaining = new Set(updates.keys());

  const outRows = led.rows.map((r) => {
    const id = (r.fields[idIndex] || '').trim();
    if (seen.has(id)) throw new Error(`duplicate article_id in ledger: ${id}`);
    seen.add(id);
    const upd = updates.get(id);
    if (!upd) return r.raw;
    remaining.delete(id);
    const fields = r.fields.slice();
    for (const [col, val] of Object.entries(upd)) {
      const idx = colIndex.get(col);
      if (idx === undefined) throw new Error(`unknown column: ${col}`);
      fields[idx] = String(val);
    }
    return serializeRow(fields);
  });
  if (remaining.size) {
    throw new Error(`article_id(s) not found in ledger: ${[...remaining].join(', ')}`);
  }
  return {
    text: led.header.join(',') + '\r\n' + outRows.join('') + (led.trailingNewline ? '' : ''),
    header: led.header,
    rows: led.rows,
  };
}

/** Find rows by id (parsed view). Throws on duplicates. */
export function findRows(text, ids) {
  const led = parseLedger(text);
  const want = new Set(ids);
  const found = new Map();
  const seen = new Set();
  for (const r of led.rows) {
    const id = (r.fields[0] || '').trim();
    if (seen.has(id)) throw new Error(`duplicate article_id in ledger: ${id}`);
    seen.add(id);
    if (want.has(id)) {
      const row = {};
      led.header.forEach((h, idx) => { row[h] = r.fields[idx]; });
      found.set(id, { row, raw: r.raw });
    }
  }
  return { header: led.header, found, seen };
}

export function toRowObjects(text) {
  const led = parseLedger(text);
  return led.rows.map((r) => {
    const row = {};
    led.header.forEach((h, idx) => { row[h] = r.fields[idx]; });
    return row;
  });
}
