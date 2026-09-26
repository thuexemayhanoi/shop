// Node fallback tooling tests for the content factory.
// Run: node --test tests/js/
//
// Covers the publish-bottleneck fallback requirements:
//   - large matrix round-trip (the real ~990 KB ledger, byte-exact)
//   - row count / headers / unrelated rows preserved byte-semantically
//   - exactly selected ids modified; duplicates/missing ids rejected
//   - invalid state transitions rejected
//   - dry-run produces no modifications
//   - publish updates matrix + hubs + sitemap consistently
//   - interrupted/error operations leave no partial publication state
//   - RFC 4180 quoting round-trips and matches Python csv conventions

import { test } from 'node:test';
import assert from 'node:assert';
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';
import { parseLedger, serializeRow, roundTrip, applyUpdates, findRows } from '../../scripts/js/ledger.mjs';
import { factoryProgress, rebuildBatchReport, setRepo } from '../../scripts/js/factory.mjs';

const REPO = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const REAL_MATRIX = fs.readFileSync(path.join(REPO, 'data', 'content-matrix.csv'), 'utf8');
const FACTORY = path.join(REPO, 'scripts', 'js', 'factory.mjs');

// ---------------------------------------------------------------- ledger

test('large matrix round-trip is byte-exact (real 990KB ledger)', () => {
  assert.strictEqual(roundTrip(REAL_MATRIX), REAL_MATRIX);
  const led = parseLedger(REAL_MATRIX);
  assert.strictEqual(led.rows.length, 2008); // 2000 production + 8 SAMPLE
  assert.strictEqual(led.header.length, 23);
  const prod = led.rows.filter((r) => !r.fields[0].startsWith('SAMPLE'));
  assert.strictEqual(prod.length, 2000);
  const ids = led.rows.map((r) => r.fields[0]);
  assert.strictEqual(new Set(ids).size, ids.length, 'ids must be unique');
});

test('applyUpdates: row count, header and unrelated rows unchanged byte-exactly', () => {
  // SAMPLE rows are production-stable, so this test is state-independent
  const header = parseLedger(REAL_MATRIX).header;
  const out = applyUpdates(REAL_MATRIX, new Map([
    ['SAMPLE-KN-01', { notes: 'TEST-SENTINEL' }],
  ]), { expectHeader: header });
  assert.notStrictEqual(out.text, REAL_MATRIX);
  const before = REAL_MATRIX.split('\r\n');
  const after = out.text.split('\r\n');
  assert.strictEqual(after.length, before.length, 'line count unchanged');
  assert.strictEqual(before[0], after[0], 'header unchanged');
  let changed = [];
  for (let i = 1; i < before.length; i++) {
    if (before[i] !== after[i]) changed.push(i);
  }
  assert.strictEqual(changed.length, 1, 'exactly one line changed');
  const row = after[changed[0]].split(',');
  assert.strictEqual(row[0], 'SAMPLE-KN-01');
  assert.strictEqual(row[header.indexOf('notes')], 'TEST-SENTINEL');
});

test('applyUpdates modifies exactly the selected ids (multi-id)', () => {
  const header = parseLedger(REAL_MATRIX).header;
  const out = applyUpdates(REAL_MATRIX, new Map([
    ['SAMPLE-KN-01', { notes: 'SENTINEL-A' }],
    ['SAMPLE-KN-03', { notes: 'SENTINEL-B' }],
    ['SAMPLE-DL-02', { notes: 'SENTINEL-C' }],
  ]), { expectHeader: header });
  const before = REAL_MATRIX.split('\r\n');
  const after = out.text.split('\r\n');
  const changedIds = [];
  for (let i = 1; i < before.length; i++) {
    if (before[i] !== after[i]) changedIds.push(after[i].split(',')[0]);
  }
  assert.deepStrictEqual(changedIds.sort(), ['SAMPLE-DL-02', 'SAMPLE-KN-01', 'SAMPLE-KN-03']);
});

test('applyUpdates rejects missing ids', () => {
  const header = parseLedger(REAL_MATRIX).header;
  assert.throws(
    () => applyUpdates(REAL_MATRIX, new Map([['KN-9999', { status: 'PUBLISHED' }]]), { expectHeader: header }),
    /not found in ledger/);
});

test('applyUpdates rejects unknown columns and header mismatch', () => {
  const header = parseLedger(REAL_MATRIX).header;
  assert.throws(
    () => applyUpdates(REAL_MATRIX, new Map([['KN-0002', { bogus_column: 'x' }]]), { expectHeader: header }),
    /unknown column/);
  assert.throws(
    () => applyUpdates(REAL_MATRIX, new Map([['KN-0002', { status: 'X' }]]), { expectHeader: ['wrong', 'header'] }),
    /header mismatch/);
});

test('duplicate ids in the ledger are rejected', () => {
  const header = parseLedger(REAL_MATRIX).header;
  const lines = REAL_MATRIX.split('\r\n');
  const dup = [...lines, lines[9]].join('\r\n') + '\r\n';
  assert.throws(
    () => applyUpdates(dup, new Map([['KN-0002', { status: 'PUBLISHED' }]]), { expectHeader: header }),
    /duplicate article_id/);
  assert.throws(() => findRows(dup, ['KN-0002']), /duplicate/);
});

test('RFC 4180 quoting round-trips and matches Python csv conventions', () => {
  // Python csv.writer(QUOTE_MINIMAL, \r\n) expected outputs
  assert.strictEqual(serializeRow(['plain', 'a b']), 'plain,a b\r\n');
  assert.strictEqual(serializeRow(['a,b']), '"a,b"\r\n');
  assert.strictEqual(serializeRow(['he said "hi"']), '"he said ""hi"""\r\n');
  assert.strictEqual(serializeRow(['line\r\nbreak']), '"line\r\nbreak"\r\n');
  // round-trip of a quoted document
  const doc = 'id,txt\r\n"1","comma, inside"\r\n"2","quote ""x"" and\r\nnewline"\r\n';
  assert.strictEqual(roundTrip(doc), doc);
  const led = parseLedger(doc);
  assert.strictEqual(led.rows.length, 2);
  assert.strictEqual(led.rows[1].fields[1], 'quote "x" and\r\nnewline');
});

// --------------------------------------------------------------- sandbox

function makeSandbox() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'factory-test-'));
  const header = parseLedger(REAL_MATRIX).header;
  const mk = (p) => { fs.mkdirSync(path.dirname(path.join(dir, p)), { recursive: true }); return path.join(dir, p); };
  fs.mkdirSync(path.join(dir, 'config'), { recursive: true });
  fs.copyFileSync(path.join(REPO, 'config', 'site.json'), path.join(dir, 'config', 'site.json'));
  fs.copyFileSync(path.join(REPO, 'config', 'content-factory.json'), path.join(dir, 'config', 'content-factory.json'));

  const row = (id, status, cat, hub, extra = {}) => [
    id, status, cat, 'kw' + id, 'kw' + id, 'informational', 'Title ' + id,
    id.toLowerCase(), `cam-nang/x/${id.toLowerCase()}.html`, hub, 'no', 'false',
    'note', hub, '', 'Mr Tú', '2027-01-01', '95', 'PASS', '2026-09-25', '', '', 'BATCH-001',
  ];
  const rows = [
    row('SAMPLE-A', 'SAMPLE', 'Kinh nghiệm', 'kinhnghiem.html'),
    ['KN-0100', 'PLANNED', 'Kinh nghiệm'].concat(Array(header.length - 3).fill('')).slice(0, header.length),
    ['KN-0101', 'WRITING', 'Kinh nghiệm'].concat(Array(header.length - 3).fill('')).slice(0, header.length),
    row('KN-0102', 'PASS', 'Kinh nghiệm', 'kinhnghiem.html'),
    row('XM-0100', 'PUBLISHED', 'Xe máy', 'xemay.html', {}),
    row('XM-0101', 'PASS', 'Xe máy', 'xemay.html'),
    ['DL-0100', 'PLANNED', 'Du lịch'].concat(Array(header.length - 3).fill('')).slice(0, header.length),
  ];
  // fix column count / required fields for synthetic rows
  const fixed = rows.map((r) => {
    const f = r.slice();
    while (f.length < header.length) f.push('');
    return f;
  });
  // give simple rows proper minimal shape
  for (const f of fixed) {
    if (['KN-0100', 'KN-0101', 'DL-0100'].includes(f[0])) {
      f[2] = f[0].startsWith('DL') ? 'Du lịch' : 'Kinh nghiệm';
      f[3] = 'kw ' + f[0]; f[6] = 'Title ' + f[0]; f[7] = f[0].toLowerCase();
      f[8] = `cam-nang/x/${f[0].toLowerCase()}.html`;
      f[9] = f[0].startsWith('DL') ? 'dulich.html' : 'kinhnghiem.html';
      f[10] = 'no'; f[11] = 'false'; f[14] = f[9]; f[16] = 'Mr Tú'; f[22] = 'BATCH-001';
    }
  }
  fs.writeFileSync(path.join(dir, 'data', 'content-matrix.csv') && mk('data/content-matrix.csv'),
    header.join(',') + '\r\n' + fixed.map((f) => serializeRow(f)).join(''), 'utf8');

  // article files for PASS/PUBLISHED rows
  for (const f of fixed) {
    if (['PASS', 'PUBLISHED'].includes(f[1])) {
      fs.writeFileSync(mk(f[8]), '<!DOCTYPE html><html lang="vi"><body><main><h1>' + f[0] + '</h1></main></body></html>\n', 'utf8');
    }
  }
  // hubs
  const START = '<!-- ARTICLE-LIST:START -->';
  const END = '<!-- ARTICLE-LIST:END -->';
  fs.writeFileSync(mk('kinhnghiem.html'),
    '<html><body><main><h1>KN</h1>\n' + START + '\n<ul class="article-list">\n<li class="article-card"><a href="/shop/cam-nang/x/kn-0102.html">Title KN-0102</a></li>\n</ul>\n' + END + '\n</main></body></html>\n', 'utf8');
  fs.writeFileSync(mk('xemay.html'),
    '<html><body><main><h1>XM</h1>\n' + START + '\n<ul class="article-list">\n<li class="article-card"><a href="/shop/cam-nang/x/xm-0100.html">Title XM-0100</a></li>\n</ul>\n' + END + '\n</main></body></html>\n', 'utf8');
  fs.writeFileSync(mk('dulich.html'), '<html><body><main><h1>DL</h1>\n</main></body></html>\n', 'utf8');
  // sitemap with one legacy + one factory URL
  fs.writeFileSync(mk('sitemap.xml'),
    `<?xml version='1.0' encoding='utf-8'?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>https://thuexemayhanoi.github.io/shop/</loc><lastmod>2026-09-25</lastmod></url><url><loc>https://thuexemayhanoi.github.io/shop/cam-nang/x/xm-0100.html</loc><lastmod>2026-09-25</lastmod></url></urlset>\n`, 'utf8');
  // batch report
  fs.writeFileSync(mk('reports/batches/BATCH-001.json'), JSON.stringify({
    batch_id: 'BATCH-001', started_at: '2026-09-25T20:00:00', finished_at: '2026-09-25T20:00:01',
    writer: 'external-agent', processed: 2, written: 2, pass: 2, published: 0, review: 0,
    repair: 0, fail: 0, blocked: 0, average_score: 98, min_score: 96, max_score: 100,
    repair_count: 0, source_gate_pass: 0, source_gate_blocked: 0, published_commit_sha: null,
    articles: [
      { article_id: 'KN-0102', output_path: 'cam-nang/x/kn-0102.html', outcome: 'PASS', score: 100, repair_attempts: 0, quality_failures: [] },
      { article_id: 'XM-0101', output_path: 'cam-nang/x/xm-0101.html', outcome: 'PASS', score: 96, repair_attempts: 0, quality_failures: [] },
    ],
  }, null, 2) + '\n', 'utf8');
  fs.writeFileSync(mk('reports/batches/BATCH-001.md'),
    '# Batch report BATCH-001\n\n| article_id | output_path | status | score | repairs | notes |\n|---|---|---|---|---|---|\n| KN-0102 | cam-nang/x/kn-0102.html | PASS | 100 | 0 |  |\n\n## Operator notes\n\nPreserve me.\n', 'utf8');
  return dir;
}

function runFactory(dir, args, env = {}) {
  const r = spawnSync('node', [FACTORY, ...args, '--repo', dir, '--expect-rows', '6'], {
    encoding: 'utf8',
    env: Object.assign({}, process.env, env),
  });
  if (r.status !== 0) {
    throw new Error(`factory exited ${r.status}\n${r.stdout}\n${r.stderr}`);
  }
  return r.stdout + r.stderr;
}

function snapshot(dir) {
  const files = [
    'data/content-matrix.csv', 'sitemap.xml', 'kinhnghiem.html', 'xemay.html', 'dulich.html',
    'reports/batches/BATCH-001.json', 'reports/batches/BATCH-001.md',
  ];
  const snap = {};
  for (const f of files) {
    const p = path.join(dir, f);
    snap[f] = fs.existsSync(p) ? fs.readFileSync(p, 'utf8') : null;
  }
  return snap;
}

// ------------------------------------------------------------ CLI tests

test('invalid state transitions are rejected (PLANNED->PUBLISHED, WRITING->PUBLISHED)', () => {
  const dir = makeSandbox();
  assert.throws(() => runFactory(dir, ['--publish', 'KN-0100']), /publish requires PASS/);
  assert.throws(() => runFactory(dir, ['--publish', 'KN-0101']), /publish requires PASS/);
  assert.throws(() => runFactory(dir, ['--publish', 'KN-9999']), /not in ledger/);
  assert.throws(() => runFactory(dir, ['--publish', 'KN-0102,KN-0102']), /duplicate article ids/);
});

test('qa-record enforces the state machine and score threshold', () => {
  const dir = makeSandbox();
  // PLANNED -> PASS is invalid
  assert.throws(() => runFactory(dir, ['--qa-record', 'KN-0100=95:PASS']), /invalid state transition/);
  // WRITING -> PASS with score < 90 refused
  assert.throws(() => runFactory(dir, ['--qa-record', 'KN-0101=85:PASS']), /score >= 90/);
  // WRITING -> PASS valid
  const out = runFactory(dir, ['--qa-record', 'KN-0101=95:PASS']);
  const led = parseLedger(fs.readFileSync(path.join(dir, 'data', 'content-matrix.csv'), 'utf8'));
  const row = led.rows.find((r) => r.fields[0] === 'KN-0101');
  assert.strictEqual(row.fields[1], 'PASS');
  assert.strictEqual(row.fields[17], '95');
  // PUBLISHED rows can never transition
  assert.throws(() => runFactory(dir, ['--qa-record', 'XM-0100=95:PASS']), /invalid state transition/);
});

test('dry-run produces no modifications at all', () => {
  const dir = makeSandbox();
  const before = snapshot(dir);
  runFactory(dir, ['--publish', 'KN-0102,XM-0101', '--dry-run', '--date', '2026-09-26']);
  assert.deepStrictEqual(snapshot(dir), before);
  runFactory(dir, ['--qa-record', 'KN-0101=95:PASS', '--dry-run']);
  assert.deepStrictEqual(snapshot(dir), before);
});

test('publish transaction updates matrix + hubs + sitemap consistently', () => {
  const dir = makeSandbox();
  const run = runFactory(dir, ['--publish', 'KN-0102,XM-0101', '--date', '2026-09-26']);
  const matrix = fs.readFileSync(path.join(dir, 'data', 'content-matrix.csv'), 'utf8');
  const led = parseLedger(matrix);
  const kn = led.rows.find((r) => r.fields[0] === 'KN-0102');
  const xm = led.rows.find((r) => r.fields[0] === 'XM-0101');
  assert.strictEqual(kn.fields[1], 'PUBLISHED');
  assert.strictEqual(xm.fields[1], 'PUBLISHED');
  assert.strictEqual(kn.fields[20], '2026-09-26'); // published_date
  assert.strictEqual(xm.fields[20], '2026-09-26');
  // unrelated rows untouched
  const kn101 = led.rows.find((r) => r.fields[0] === 'KN-0101');
  assert.strictEqual(kn101.fields[1], 'WRITING');
  const kn100 = led.rows.find((r) => r.fields[0] === 'KN-0100');
  assert.strictEqual(kn100.fields[1], 'PLANNED');
  // hubs: kinhnghiem got the KN-0102 card, xemay got XM-0101 appended (sorted by id)
  const knHub = fs.readFileSync(path.join(dir, 'kinhnghiem.html'), 'utf8');
  assert.ok(knHub.includes('kn-0102.html'));
  const xmHub = fs.readFileSync(path.join(dir, 'xemay.html'), 'utf8');
  assert.ok(xmHub.includes('xm-0100.html') && xmHub.includes('xm-0101.html'));
  // sitemap: both new URLs present, legacy preserved, no duplicates
  const sm = fs.readFileSync(path.join(dir, 'sitemap.xml'), 'utf8');
  const locs = [...sm.matchAll(/<loc>([^<]*)<\/loc>/g)].map((m) => m[1]);
  assert.ok(locs.includes('https://thuexemayhanoi.github.io/shop/cam-nang/x/kn-0102.html'));
  assert.ok(locs.includes('https://thuexemayhanoi.github.io/shop/cam-nang/x/xm-0101.html'));
  assert.ok(locs.includes('https://thuexemayhanoi.github.io/shop/'));
  assert.strictEqual(new Set(locs).size, locs.length, 'no duplicate URLs');
  // reports updated — CUMULATIVE batch report derived from matrix truth:
  // all 6 BATCH-001 members present, counts from the ledger
  const rep = JSON.parse(fs.readFileSync(path.join(dir, 'reports/batches/BATCH-001.json'), 'utf8'));
  assert.strictEqual(rep.articles.length, 6, 'every batch member appears');
  assert.strictEqual(rep.published, 3); // XM-0100 (earlier) + KN-0102 + XM-0101
  assert.strictEqual(rep.writing, 1);   // KN-0101
  assert.strictEqual(rep.pass, 0);
  assert.strictEqual(rep.processed, 6 - 2); // minus 2 PLANNED (KN-0100, DL-0100)
  const byId = Object.fromEntries(rep.articles.map((a) => [a.article_id, a]));
  assert.strictEqual(byId['KN-0102'].outcome, 'PUBLISHED');
  assert.strictEqual(byId['XM-0101'].outcome, 'PUBLISHED');
  assert.strictEqual(byId['XM-0100'].outcome, 'PUBLISHED');
  assert.strictEqual(byId['KN-0101'].outcome, 'WRITING');
  assert.strictEqual(byId['KN-0100'].outcome, 'PLANNED');
  assert.ok(rep.articles.every((a) => ['PLANNED', 'WRITING', 'PUBLISHED'].includes(a.outcome)));
  // cumulative progress: completed_batches derived, not hard-coded
  const prog = JSON.parse(fs.readFileSync(path.join(dir, 'reports/batches/factory-progress.json'), 'utf8'));
  assert.strictEqual(prog.published, 3);
  assert.strictEqual(prog.completed_batches, 0); // batch has non-terminal rows
  // batch md canonical table preserved trailing operator section
  const md = fs.readFileSync(path.join(dir, 'reports/batches/BATCH-001.md'), 'utf8');
  assert.ok(md.includes('## Operator notes') && md.includes('Preserve me.'));
  assert.ok(md.includes('| KN-0102 | cam-nang/x/kn-0102.html | PUBLISHED | 95 |'));
  // no pending transaction marker is left behind
  assert.ok(!fs.existsSync(path.join(dir, 'data', 'batches', 'txn')), 'txn marker removed after successful commit');
  // final consistency check passes
  runFactory(dir, ['--consistency']);
});

test('interrupted/error publish leaves no partial publication state', () => {
  const dir = makeSandbox();
  const before = snapshot(dir);
  // sabotage: a directory named exactly like the first tmp file makes the
  // phase-1 tmp write fail AFTER earlier tmps were already written
  fs.mkdirSync(path.join(dir, 'data', 'content-matrix.csv.tmp'));
  assert.throws(() => runFactory(dir, ['--publish', 'KN-0102', '--date', '2026-09-26']));
  // NOTHING changed: matrix, sitemap, hubs, reports all byte-identical
  assert.deepStrictEqual(snapshot(dir), before);
  // and phase-1 cleaned up its own tmp files
  const rootTmp = fs.readdirSync(dir).filter((f) => f.endsWith('.tmp'));
  assert.strictEqual(rootTmp.length, 0, 'phase-1 must clean its tmp files');
  fs.rmSync(path.join(dir, 'data', 'content-matrix.csv.tmp'), { recursive: true, force: true });
});

test('consistency check detects drift', () => {
  const dir = makeSandbox();
  runFactory(dir, ['--consistency']); // green first
  // inject drift: publish without regenerating the hub (simulate manual edit)
  const matrixPath = path.join(dir, 'data', 'content-matrix.csv');
  const txt = fs.readFileSync(matrixPath, 'utf8');
  const led = parseLedger(txt);
  const rows = led.rows.map((r) => r.fields[0] === 'KN-0102'
    ? serializeRow(r.fields.map((f, i) => (i === 1 ? 'PUBLISHED' : i === 20 ? '2026-09-26' : f)))
    : r.raw);
  fs.writeFileSync(matrixPath, led.header.join(',') + '\r\n' + rows.join(''), 'utf8');
  assert.throws(() => runFactory(dir, ['--consistency']), /CONSISTENCY FAIL/);
});

// ----------------------------------------- cumulative batch reporting

test('factoryProgress derives completed_batches from matrix state (not hard-coded)', () => {
  const row = (id, status, batch) => ({ article_id: id, status, batch_id: batch });
  // BATCH-A fully terminal (2 PUBLISHED + 1 FAIL); BATCH-B has active rows;
  // unassigned PLANNED rows form the "" pseudo-batch (never complete)
  const rows = [
    row('AA-0001', 'PUBLISHED', 'BATCH-A'),
    row('AA-0002', 'PUBLISHED', 'BATCH-A'),
    row('AA-0003', 'FAIL', 'BATCH-A'),
    row('BB-0001', 'PUBLISHED', 'BATCH-B'),
    row('BB-0002', 'WRITING', 'BATCH-B'),
    row('CC-0001', 'PLANNED', ''),
    row('CC-0002', 'PLANNED', ''),
  ];
  const p = factoryProgress(rows, '2026-09-26T00:00:00');
  assert.strictEqual(p.completed_batches, 1); // BATCH-A only
  assert.strictEqual(p.published, 3);
  assert.strictEqual(p.writing, 1);
  assert.strictEqual(p.planned, 2);
  assert.strictEqual(p.active_batch, 'BATCH-B');
  // all-terminal universe: every batch complete
  const done = [
    row('AA-0001', 'PUBLISHED', 'BATCH-A'),
    row('BB-0001', 'BLOCKED', 'BATCH-B'),
  ];
  assert.strictEqual(factoryProgress(done, 't').completed_batches, 2);
});

test('empty --publish list is refused', () => {
  const dir = makeSandbox();
  assert.throws(() => runFactory(dir, ['--publish', '']), /non-empty comma-separated/);
  assert.throws(() => runFactory(dir, ['--publish', ',,']), /non-empty comma-separated/);
});

test('--rebuild-report regenerates the cumulative batch report from matrix truth', () => {
  const dir = makeSandbox();
  const matrixBefore = fs.readFileSync(path.join(dir, 'data/content-matrix.csv'), 'utf8');
  runFactory(dir, ['--rebuild-report', 'BATCH-001']);
  // ledger untouched
  assert.strictEqual(fs.readFileSync(path.join(dir, 'data/content-matrix.csv'), 'utf8'), matrixBefore);
  const rep = JSON.parse(fs.readFileSync(path.join(dir, 'reports/batches/BATCH-001.json'), 'utf8'));
  assert.strictEqual(rep.articles.length, 6, 'all batch members');
  assert.strictEqual(rep.published, 1); // XM-0100
  assert.strictEqual(rep.pass, 2);      // KN-0102 + XM-0101 (files present)
  assert.strictEqual(rep.pass_publishable_now, 2);
  assert.strictEqual(rep.writing, 1);   // KN-0101
  assert.strictEqual(rep.processed, 4);
  assert.strictEqual(rep.written, 3);
  // md keeps operator notes and gains the full member table
  const md = fs.readFileSync(path.join(dir, 'reports/batches/BATCH-001.md'), 'utf8');
  assert.ok(md.includes('## Operator notes') && md.includes('Preserve me.'));
  assert.ok(md.includes('| DL-0100 | cam-nang/x/dl-0100.html | PLANNED |'));
  assert.ok(md.includes('| XM-0100 | cam-nang/x/xm-0100.html | PUBLISHED |'));
});

test('rebuildBatchReport (unit) preserves run details and audit SHA', () => {
  const dir = makeSandbox();
  setRepo(dir);
  const rows = [
    { article_id: 'ZZ-0001', output_path: 'cam-nang/x/zz-0001.html', status: 'PUBLISHED', score: '96', batch_id: 'BATCH-Z', notes: '', requires_sources: 'no' },
    { article_id: 'ZZ-0002', output_path: 'cam-nang/x/zz-0002.html', status: 'WRITING', score: '', batch_id: 'BATCH-Z', notes: 'repair:2', requires_sources: 'no' },
  ];
  const out = rebuildBatchReport('BATCH-Z', rows, [
    { article_id: 'ZZ-0001', repair_attempts: 1, quality_failures: ['x'] },
  ], '2026-09-26T00:00:00');
  const rep = JSON.parse(out[0].content);
  assert.strictEqual(rep.published, 1);
  assert.strictEqual(rep.writing, 1);
  const byId = Object.fromEntries(rep.articles.map((a) => [a.article_id, a]));
  assert.deepStrictEqual(byId['ZZ-0001'].quality_failures, ['x']);
  assert.strictEqual(byId['ZZ-0002'].repair_attempts, 2); // from notes repair:2
  assert.strictEqual(rep.min_score, 96);
  assert.strictEqual(rep.average_score, 96);
});

// ------------------------------------- transaction recovery (--recover)

test('interrupted publish is recoverable via --recover (transaction marker)', () => {
  const dir = makeSandbox();
  // simulate a power loss mid-transaction: crash after the FIRST rename
  // (matrix applied, sitemap/hubs/reports still pre-transaction)
  assert.throws(
    () => runFactory(dir, ['--publish', 'KN-0102', '--date', '2026-09-26'],
      { FACTORY_TEST_CRASH_AFTER_RENAMES: '1' }),
    /factory exited 70/);
  // partial state: matrix says PUBLISHED but sitemap/hubs/reports are stale
  const led = parseLedger(fs.readFileSync(path.join(dir, 'data/content-matrix.csv'), 'utf8'));
  assert.strictEqual(led.rows.find((r) => r.fields[0] === 'KN-0102').fields[1], 'PUBLISHED');
  assert.throws(() => runFactory(dir, ['--consistency']), /CONSISTENCY FAIL/);
  // pending transaction marker present
  assert.ok(fs.existsSync(path.join(dir, 'data', 'batches', 'txn', 'txn.json')));
  // further mutations are refused while the marker is pending
  assert.throws(() => runFactory(dir, ['--publish', 'XM-0101']), /pending transaction marker/);
  // recover the interrupted transaction
  const out = runFactory(dir, ['--recover']);
  assert.match(out, /RECOVER OK/);
  // transaction fully applied and consistent; marker removed
  runFactory(dir, ['--consistency']);
  assert.ok(!fs.existsSync(path.join(dir, 'data', 'batches', 'txn')));
  const sm = fs.readFileSync(path.join(dir, 'sitemap.xml'), 'utf8');
  assert.ok(sm.includes('kn-0102.html'));
  const rep = JSON.parse(fs.readFileSync(path.join(dir, 'reports/batches/BATCH-001.json'), 'utf8'));
  assert.strictEqual(rep.published, 2); // XM-0100 + recovered KN-0102
  // normal operation resumes afterwards
  runFactory(dir, ['--publish', 'XM-0101', '--date', '2026-09-26']);
  runFactory(dir, ['--consistency']);
});

test('--recover with no pending transaction is a clean no-op', () => {
  const dir = makeSandbox();
  const out = runFactory(dir, ['--recover']);
  assert.match(out, /no pending transaction/);
});
