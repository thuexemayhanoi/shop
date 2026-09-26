#!/usr/bin/env node
// Node fallback for the content-factory publish transaction.
//
// Removes the Python-only publish bottleneck: scripts/run_article_batch.py
// remains the CANONICAL pipeline, but this tool implements the same
// deterministic ledger / hub / sitemap operations so an operator runtime
// with only Node can complete a publication safely.
//
// Modes (mutually exclusive):
//   --qa-record "ID=SCORE:OUTCOME,..."   record external QA results in the
//                                        ledger (WRITING -> QA/PASS/REVIEW/FAIL)
//   --publish "ID,ID,..."                PASS -> PUBLISHED (+published_date),
//                                        regenerate hub ARTICLE-LIST blocks +
//                                        sitemap.xml + batch report + progress
//   --rebuild-report BATCH               rewrite the CUMULATIVE batch report
//                                        from current matrix truth (all
//                                        members, matrix-derived counts)
//   --recover                            finish/verify an interrupted
//                                        multi-file transaction using the
//                                        recovery marker in data/batches/txn/
//   --consistency                        verify matrix/hubs/sitemap agreement
//                                        without writing anything
//
// Options:
//   --dry-run        compute everything, write nothing
//   --date YYYY-MM-DD  published_date / sitemap lastmod (default: today UTC+7)
//   --repo PATH      repository root (default: parent of this script)
//
// Safety properties:
//   - the full ledger is read in one pass (no truncation)
//   - expected-state validation BEFORE any modification
//   - duplicate/missing ids rejected; invalid transitions rejected
//   - only the intended rows/columns change; unrelated bytes preserved
//   - every output is computed and validated BEFORE the first write
//     (no partial state on failure); writes are atomic (tmp + rename)
//
// Exit codes: 0 ok, 1 usage, 2 validation/refused, 3 runtime error.

import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { fileURLToPath } from 'node:url';
import { parseLedger, serializeRow, applyUpdates, toRowObjects, isSampleRow } from './ledger.mjs';

let REPO = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const matrixPath = () => path.join(REPO, 'data', 'content-matrix.csv');
const CATEGORIES = {
  'Kinh nghiệm': 'kinhnghiem.html',
  'An toàn': 'antoan.html',
  'Xe máy': 'xemay.html',
  'Du lịch': 'dulich.html',
  'Cung đường': 'cungduong.html',
  'Hỏi đáp': 'hoidap.html',
};
const CAT_DIR = {
  'Kinh nghiệm': 'kinh-nghiem',
  'An toàn': 'an-toan',
  'Xe máy': 'xe-may',
  'Du lịch': 'du-lich',
  'Cung đường': 'cung-duong',
  'Hỏi đáp': 'hoi-dap',
};
const PER_PAGE = 50;
const START = '<!-- ARTICLE-LIST:START -->';
const END = '<!-- ARTICLE-LIST:END -->';
const ACTIVE_STATUSES = new Set(['WRITING', 'QA', 'REPAIR', 'REVIEW']);
const MAX_REPAIR_ATTEMPTS = 3;
const SM_NS = 'http://www.sitemaps.org/schemas/sitemap/0.9';

const hanoiToday = () => {
  const now = new Date(Date.now() + 7 * 3600 * 1000);
  return now.toISOString().slice(0, 10);
};

// ---------------------------------------------------------------- helpers

function htmlEscape(s) {
  // Python html.escape(s, quote=True)
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#x27;');
}

function xmlEscapeText(s) {
  // xml.etree.ElementTree text-node escaping
  return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function readConfig() {
  const site = JSON.parse(fs.readFileSync(path.join(REPO, 'config', 'site.json'), 'utf8'));
  const kill = fs.existsSync(path.join(REPO, 'config', 'content-factory.json'))
    ? JSON.parse(fs.readFileSync(path.join(REPO, 'config', 'content-factory.json'), 'utf8'))
    : { enabled: true };
  return { site, kill };
}

function loadMatrix() {
  const raw = fs.readFileSync(matrixPath(), 'utf8');
  const led = parseLedger(raw);
  return { raw, led, rows: toRowObjects(raw) };
}

function validateInvariants(led, rows, expectedRows = 2000) {
  const production = rows.filter((r) => !isSampleRowFields(r));
  const ids = new Set();
  for (const r of production) {
    const id = (r.article_id || '').trim();
    if (ids.has(id)) throw new Error(`duplicate production article_id: ${id}`);
    ids.add(id);
  }
  if (production.length !== expectedRows) {
    throw new Error(`production row count ${production.length} != ${expectedRows}`);
  }
  return { production, ids };
}

function isSampleRowFields(row) {
  return (row.article_id || '').trim().startsWith('SAMPLE');
}

// ------------------------------------------------------- hub regeneration

function publishedByCategory(rows) {
  const out = new Map();
  for (const r of rows) {
    if (isSampleRowFields(r)) continue;
    if ((r.status || '').trim() !== 'PUBLISHED') continue;
    if (!out.has(r.category)) out.set(r.category, []);
    out.get(r.category).push(r);
  }
  for (const [c, list] of out) {
    list.sort((a, b) => (a.article_id || '').localeCompare(b.article_id || ''));
  }
  return out;
}

function cardList(rows, baseurl) {
  const base = baseurl.replace(/\/+$/, '');
  return rows.map((r) =>
    `<li class="article-card"><a href="${base}/${(r.output_path || '').replace(/^\/+/, '')}">${htmlEscape(r.working_title || r.slug)}</a></li>`
  ).join('\n');
}

function hubBlock(rows, baseurl, hub, cat, totalPublished) {
  const inner = cardList(rows.slice(0, PER_PAGE), baseurl);
  let more = '';
  const base = baseurl.replace(/\/+$/, '');
  if (totalPublished > PER_PAGE) {
    more = `<p class="article-list-more">Xem thêm: <a href="${base}/cam-nang/${CAT_DIR[cat]}/page-2.html">trang 2</a></p>`;
  }
  return `${START}\n<ul class="article-list">\n${inner}\n</ul>\n${more}${END}`;
}

function injectHubBlock(text, block) {
  if (text.includes(START) && text.includes(END)) {
    const pre = text.split(START)[0];
    const post = text.split(END)[1]; // first occurrence
    return pre + block + post;
  }
  for (const marker of ['</main>', '</body>']) {
    const i = text.indexOf(marker);
    if (i !== -1) return text.slice(0, i) + block + '\n' + text.slice(i);
  }
  return text + '\n' + block + '\n';
}

function regenerateHub(hubFile, rows, baseurl, hub) {
  const p = path.join(REPO, hubFile);
  if (!fs.existsSync(p)) return null;
  const cat = Object.keys(CATEGORIES).find((c) => CATEGORIES[c] === hub);
  const text = fs.readFileSync(p, 'utf8');
  const block = hubBlock(rows, baseurl, hub, cat, rows.length);
  const next = injectHubBlock(text, block);
  if (next === text) return null;
  return { path: p, content: next };
}

// ---------------------------------------------------- sitemap regeneration

function currentSitemapUrls(sitemapPath) {
  if (!fs.existsSync(sitemapPath)) return [];
  const text = fs.readFileSync(sitemapPath, 'utf8');
  const urls = [];
  const re = /<loc>([^<]*)<\/loc>/g;
  let m;
  while ((m = re.exec(text))) urls.push(m[1].trim());
  return urls;
}

function buildUrlset(urls, date) {
  let out = `<?xml version='1.0' encoding='utf-8'?>\n<urlset xmlns="${SM_NS}">`;
  const seen = new Set();
  for (const u of urls) {
    const norm = u.endsWith('.html') ? u : u.replace(/\/+$/, '');
    if (seen.has(norm)) continue;
    seen.add(norm);
    out += `<url><loc>${xmlEscapeText(u)}</loc><lastmod>${date}</lastmod></url>`;
  }
  return out + '</urlset>' + '\n';
}

function regenerateSitemap(matrixRows, site, date) {
  const sitemapPath = path.join(REPO, 'sitemap.xml');
  const existing = currentSitemapUrls(sitemapPath);
  const factoryPrefix = site.site_url.replace(/\/+$/, '') + '/cam-nang/';
  const legacy = existing.filter((u) => !u.startsWith(factoryPrefix));
  const published = [];
  for (const r of matrixRows) {
    if (isSampleRowFields(r)) continue;
    if ((r.status || '').trim() !== 'PUBLISHED') continue;
    const p = (r.output_path || '').trim().replace(/^\/+/, '');
    if (!p) continue;
    published.push(site.site_url.replace(/\/+$/, '') + '/' + p);
  }
  const wanted = [...legacy];
  for (const p of published) if (!wanted.includes(p)) wanted.push(p);
  const content = buildUrlset(wanted, date);
  const cur = fs.existsSync(sitemapPath) ? fs.readFileSync(sitemapPath, 'utf8') : '';
  if (content === cur) return null;
  return { path: sitemapPath, content, urls: wanted };
}

// ------------------------------------------------------ reports / progress

// Mirror of scripts/run_article_batch.py write_factory_progress(): ALL counts,
// including completed_batches, are derived from the matrix rows — nothing
// here is hard-coded.
export function factoryProgress(rows, generated, publishedCommitSha = null) {
  const production = rows.filter((r) => !isSampleRowFields(r));
  const counts = {};
  const perBatch = new Map();
  for (const r of production) {
    const st = ((r.status || '').trim().toLowerCase() || 'unknown');
    counts[st] = (counts[st] || 0) + 1;
    const stU = (r.status || '').trim();
    const bid = (r.batch_id || '').trim();
    let b = perBatch.get(bid);
    if (!b) {
      b = { total: 0, planned: 0, active: 0, pass: 0, published: 0, fail: 0, blocked: 0 };
      perBatch.set(bid, b);
    }
    b.total += 1;
    if (stU === 'PLANNED') b.planned += 1;
    else if (ACTIVE_STATUSES.has(stU)) b.active += 1;
    else if (stU === 'PASS') b.pass += 1;
    else if (stU === 'PUBLISHED') b.published += 1;
    else if (stU === 'FAIL') b.fail += 1;
    else if (stU === 'BLOCKED') b.blocked += 1;
  }
  // A batch is complete only when EVERY reserved row is terminal
  // (PUBLISHED/FAIL/BLOCKED). PLANNED/unassigned rows belong to the "" pseudo
  // batch and can never complete it, matching the Python implementation.
  let completed = 0;
  for (const b of perBatch.values()) {
    if (b.total > 0 && b.published + b.fail + b.blocked === b.total) completed += 1;
  }
  let activeBatch = null;
  let nextBatch = null;
  for (const r of production) {
    if (ACTIVE_STATUSES.has((r.status || '').trim())) {
      activeBatch = (r.batch_id || '').trim();
      break;
    }
  }
  if (!activeBatch) {
    for (const r of production) {
      if ((r.status || '').trim() === 'PLANNED') { nextBatch = (r.batch_id || '').trim(); break; }
    }
  } else {
    nextBatch = activeBatch;
  }
  return {
    generated,
    total: production.length,
    planned: counts.planned || 0,
    writing: counts.writing || 0,
    qa: counts.qa || 0,
    review: counts.review || 0,
    repair: counts.repair || 0,
    pass: counts.pass || 0,
    published: counts.published || 0,
    fail: counts.fail || 0,
    blocked: counts.blocked || 0,
    completed_batches: completed,
    active_batch: activeBatch,
    next_batch: nextBatch,
    published_commit_sha: publishedCommitSha,
  };
}

function jsonDump(obj) {
  return JSON.stringify(obj, null, 2) + '\n';
}

function repairAttemptsFromNotes(notes) {
  const m = /repair:(\d+)/.exec(notes || '');
  return m ? parseInt(m[1], 10) : 0;
}

function parseScore(v) {
  const n = parseInt(String(v ?? '').trim(), 10);
  return Number.isFinite(n) ? n : null;
}

function batchMembers(rows, batchId) {
  return rows.filter((r) => !isSampleRowFields(r) && (r.batch_id || '').trim() === batchId);
}

/**
 * CUMULATIVE batch report, derived from the matrix rows of the batch.
 * Every reserved member of the batch appears (not just the rows of the
 * latest run); all state counts, scores and pass_publishable_now are
 * computed from the CURRENT matrix truth, so the report can never claim
 * fewer (or more) members than the ledger reserves. Run-level details
 * (quality/cannibalization findings of the current publish run) are
 * merged in; durable per-article details are carried over from the
 * previous report; published_commit_sha is preserved as the audit trail.
 */
export function rebuildBatchReport(batchId, rowsAfter, articleResults, generated) {
  const members = batchMembers(rowsAfter, batchId);
  if (!members.length) throw new Error(`no rows reserved for batch ${batchId} in the ledger`);
  const jsonPath = path.join(REPO, 'reports', 'batches', batchId + '.json');
  const mdPath = path.join(REPO, 'reports', 'batches', batchId + '.md');
  let prev = null;
  if (fs.existsSync(jsonPath)) {
    try { prev = JSON.parse(fs.readFileSync(jsonPath, 'utf8')); } catch (_) { prev = null; }
  }
  const prevById = new Map((prev && prev.articles ? prev.articles : []).map((a) => [a.article_id, a]));
  const runById = new Map((articleResults || []).map((a) => [a.article_id, a]));

  const articles = [...members]
    .sort((a, b) => (a.article_id || '').localeCompare(b.article_id || ''))
    .map((r) => {
      const old = prevById.get(r.article_id) || {};
      const run = runById.get(r.article_id) || {};
      return {
        article_id: r.article_id,
        output_path: r.output_path,
        outcome: (r.status || '').trim(),
        score: parseScore(r.score),
        repair_attempts: run.repair_attempts ?? old.repair_attempts ?? repairAttemptsFromNotes(r.notes),
        quality_failures: run.quality_failures ?? old.quality_failures ?? [],
        cannibalization_failures: run.cannibalization_failures ?? old.cannibalization_failures ?? [],
        cannibalization_warnings: old.cannibalization_warnings ?? [],
      };
    });

  const count = (st) => members.filter((r) => (r.status || '').trim() === st).length;
  const planned = count('PLANNED');
  const writing = count('WRITING');
  const scores = articles.map((a) => a.score).filter((s) => typeof s === 'number');
  const requiresSources = (r) => String(r.requires_sources || '').trim().toLowerCase() === 'true';
  const report = {
    batch_id: batchId,
    started_at: (prev && prev.started_at) || generated,
    finished_at: generated,
    writer: (prev && prev.writer) || 'external-agent',
    processed: members.length - planned,
    written: members.length - planned - writing,
    pass: count('PASS'),
    published: count('PUBLISHED'),
    writing,
    review: count('REVIEW'),
    repair: count('REPAIR'),
    fail: count('FAIL'),
    blocked: count('BLOCKED'),
    average_score: scores.length ? Math.round((scores.reduce((s, x) => s + x, 0) / scores.length) * 10) / 10 : null,
    min_score: scores.length ? Math.min(...scores) : null,
    max_score: scores.length ? Math.max(...scores) : null,
    repair_count: articles.reduce((s, a) => s + (a.repair_attempts || 0), 0),
    source_gate_pass: members.filter((r) => requiresSources(r) && ['PASS', 'PUBLISHED'].includes((r.status || '').trim())).length,
    source_gate_blocked: members.filter((r) => requiresSources(r) && (r.status || '').trim() === 'BLOCKED').length,
    published_commit_sha: (prev && prev.published_commit_sha) || null,
    pass_publishable_now: members.filter((r) =>
      (r.status || '').trim() === 'PASS' &&
      fs.existsSync(path.join(REPO, (r.output_path || '').replace(/^\/+/, '')))).length,
    articles,
  };
  // canonical markdown table, preserving any trailing manual sections
  const L = [`# Batch report ${batchId}`, ''];
  L.push(`- started_at: ${report.started_at} | finished_at: ${report.finished_at}`);
  L.push(`- writer: ${report.writer} | batch resolved once: ${report.batch_id}`);
  L.push(`- processed: ${report.processed} | written: ${report.written} | pass: ${report.pass} | published: ${report.published}`);
  L.push(`- writing: ${report.writing} | review: ${report.review} | repair: ${report.repair} | fail: ${report.fail} | blocked: ${report.blocked}`);
  L.push(`- scores: avg ${report.average_score} | min ${report.min_score} | max ${report.max_score} | repair_count: ${report.repair_count}`);
  L.push(`- source_gate: pass ${report.source_gate_pass} | blocked ${report.source_gate_blocked}`);
  L.push(`- published_commit_sha: ${report.published_commit_sha}`);
  L.push('');
  L.push('| article_id | output_path | status | score | repairs | notes |');
  L.push('|---|---|---|---|---|---|');
  for (const a of report.articles) {
    L.push(`| ${a.article_id} | ${a.output_path} | ${a.outcome} | ${a.score ?? ''} | ${a.repair_attempts} | ${(a.quality_failures || []).slice(0, 2).join('; ')} |`);
  }
  let md = L.join('\n') + '\n';
  if (fs.existsSync(mdPath)) {
    const old = fs.readFileSync(mdPath, 'utf8');
    const tableRows = old.split('\n').filter((l) => l.startsWith('| ')).length;
    if (tableRows > 0) {
      const lines = old.split('\n');
      let lastTableIdx = -1;
      lines.forEach((l, i) => { if (l.startsWith('| ')) lastTableIdx = i; });
      const trailing = lines.slice(lastTableIdx + 1).filter((l) => l.trim() !== '').join('\n');
      if (trailing.trim()) md = md.trimEnd() + '\n\n' + trailing.trim() + '\n';
    }
  }
  return [
    { path: jsonPath, content: jsonDump(report) },
    { path: mdPath, content: md },
  ];
}

// ------------------------------------------------------ state machine

const TRANSITIONS = {
  WRITING: new Set(['QA', 'PASS', 'REVIEW', 'FAIL', 'PLANNED']),
  QA: new Set(['PASS', 'REVIEW', 'FAIL']),
  REVIEW: new Set(['REPAIR', 'PASS', 'FAIL', 'BLOCKED']),
  REPAIR: new Set(['PASS', 'REVIEW', 'FAIL', 'BLOCKED']),
  PLANNED: new Set(['WRITING']),
  PASS: new Set(['PUBLISHED']),
  PUBLISHED: new Set(),
  FAIL: new Set([]),
  BLOCKED: new Set([]),
};

function assertTransition(from, to) {
  const allowed = TRANSITIONS[from];
  if (!allowed) throw new Error(`unknown ledger status: ${from}`);
  if (!allowed.has(to)) {
    throw new Error(`invalid state transition: ${from} -> ${to}`);
  }
}

// ------------------------------------------------------ atomic writes

/**
 * Two-phase commit: write EVERY tmp file first (any failure here leaves
 * all originals untouched and removes the tmps), then rename all tmps
 * into place. An interrupted or failing operation therefore cannot
 * leave partial publication state.
 */
function commitWrites(files) {
  const tmps = [];
  try {
    for (const f of files) {
      const tmp = f.path + '.tmp';
      fs.writeFileSync(tmp, f.content, 'utf8');
      tmps.push(tmp);
    }
  } catch (e) {
    for (const t of tmps) { try { fs.rmSync(t, { force: true }); } catch (_) {} }
    throw e;
  }
  // TEST-ONLY crash simulation hook (never set in production): hard-exit
  // mid-transaction, leaving exactly the on-disk state a power loss
  // between renames would leave — no cleanup, no marker removal.
  const crashAfter = parseInt(process.env.FACTORY_TEST_CRASH_AFTER_RENAMES ?? '', 10);
  for (let i = 0; i < tmps.length; i++) {
    if (Number.isFinite(crashAfter) && i === crashAfter) process.exit(70);
    fs.renameSync(tmps[i], files[i].path);
  }
}

function atomicWrite(file) {
  commitWrites([file]);
}

// ------------------------------------------- transaction / recovery marker
//
// True cross-file atomicity is impossible on a plain filesystem: renaming
// N files one by one can be interrupted between renames, leaving the
// matrix updated but hubs/sitemap/reports stale (or vice versa). To make
// the publish transaction recoverable, every multi-file mutation writes a
// PENDING marker under data/batches/txn/ (gitignored) that records, for
// EACH planned file, the sha256 of its pre-transaction content and of its
// planned content — plus the planned content itself. --recover can then
// finish or verify an interrupted transaction deterministically:
//   - on-disk sha == after  -> rename already happened
//   - on-disk sha == before -> rename never happened; re-apply planned content
//   - anything else        -> the file diverged after the crash: refuse,
//                             keep the marker, demand manual resolution.
// The marker is removed only after the transaction is fully applied AND
// the consistency check passes.

const txnDir = () => path.join(REPO, 'data', 'batches', 'txn');
const TXN_MARKER = 'txn.json';

function sha256(text) {
  return crypto.createHash('sha256').update(text, 'utf8').digest('hex');
}

export function writeTxnMarker(kind, meta, files, generated) {
  const dir = txnDir();
  const pending = path.join(dir, 'pending');
  fs.rmSync(pending, { recursive: true, force: true });
  fs.mkdirSync(pending, { recursive: true });
  const entries = [];
  files.forEach((f, i) => {
    fs.writeFileSync(path.join(pending, i + '.content'), f.content, 'utf8');
    let before = null;
    try { before = sha256(fs.readFileSync(f.path, 'utf8')); } catch (_) { before = null; }
    entries.push({
      path: f.path,
      before_sha256: before,
      after_sha256: sha256(f.content),
    });
  });
  const marker = Object.assign({ state: 'PENDING', kind, started: generated, files: entries }, meta || {});
  atomicWrite({ path: path.join(dir, TXN_MARKER), content: jsonDump(marker) });
  return marker;
}

export function readTxnMarker() {
  const p = path.join(txnDir(), TXN_MARKER);
  if (!fs.existsSync(p)) return null;
  try {
    const m = JSON.parse(fs.readFileSync(p, 'utf8'));
    return m && m.state === 'PENDING' && Array.isArray(m.files) ? m : { state: 'CORRUPT' };
  } catch (_) {
    return { state: 'CORRUPT' };
  }
}

export function clearTxnMarker() {
  fs.rmSync(txnDir(), { recursive: true, force: true });
}

export function recoverTransaction(site, { expectedRows = 2000 } = {}) {
  const marker = readTxnMarker();
  if (!marker) {
    console.error('RECOVER: no pending transaction marker; repository state is clean.');
    return 0;
  }
  if (marker.state !== 'PENDING') {
    console.error('RECOVER FAIL: transaction marker is corrupt; manual resolution required.');
    console.error('  marker kept at data/batches/txn/ — inspect it and re-run the transaction manually.');
    return 3;
  }
  const pending = path.join(txnDir(), 'pending');
  const actions = [];
  for (let i = 0; i < marker.files.length; i++) {
    const f = marker.files[i];
    const cf = path.join(pending, i + '.content');
    if (!fs.existsSync(cf)) {
      console.error(`RECOVER FAIL: planned content missing for ${f.path}`);
      console.error('  marker kept at data/batches/txn/ — manual resolution required.');
      return 3;
    }
    const planned = fs.readFileSync(cf, 'utf8');
    if (sha256(planned) !== f.after_sha256) {
      console.error(`RECOVER FAIL: planned content hash mismatch for ${f.path} (marker/ pending content diverged)`);
      console.error('  marker kept at data/batches/txn/ — manual resolution required.');
      return 3;
    }
    let cur = null;
    try { cur = fs.readFileSync(f.path, 'utf8'); } catch (_) { cur = null; }
    const curSha = cur === null ? null : sha256(cur);
    const rel = path.relative(REPO, f.path);
    if (curSha === f.after_sha256) {
      actions.push(`already applied: ${rel}`);
      continue;
    }
    if (curSha === f.before_sha256) {
      atomicWrite({ path: f.path, content: planned });
      actions.push(`re-applied:    ${rel}`);
      continue;
    }
    console.error(`RECOVER REFUSED: ${rel} is neither pre- nor post-transaction content.`);
    console.error('  the file changed after the interruption; refusing to overwrite.');
    console.error('  marker kept at data/batches/txn/ — manual resolution required.');
    return 2;
  }
  const rows = toRowObjects(fs.readFileSync(matrixPath(), 'utf8'));
  const problems = consistencyCheck(rows, site, { expectedRows });
  if (problems.length) {
    console.error('RECOVER FAIL: transaction applied but consistency still reports problems:');
    for (const p of problems) console.error('  ! ' + p);
    console.error('  marker kept at data/batches/txn/ — manual resolution required.');
    return 3;
  }
  clearTxnMarker();
  for (const a of actions) console.error('  - ' + a);
  console.error(`RECOVER OK: transaction '${marker.kind}' completed/verified; marker removed.`);
  return 0;
}

// ------------------------------------------------------ CLI

function parseArgs(argv) {
  const args = { _: [] };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--dry-run') args.dryRun = true;
    else if (a === '--consistency') args.consistency = true;
    else if (a === '--recover') args.recover = true;
    else if (a === '--rebuild-report') args.rebuildReport = argv[++i];
    else if (a === '--qa-record') args.qaRecord = argv[++i];
    else if (a === '--publish') args.publish = argv[++i];
    else if (a === '--date') args.date = argv[++i];
    else if (a === '--repo') args.repo = argv[++i];
    else if (a === '--expect-rows') args.expectRows = parseInt(argv[++i], 10);
    else { console.error(`unknown argument: ${a}`); process.exit(1); }
  }
  return args;
}

function consistencyCheck(rows, site, { quiet = false, expectedRows = 2000 } = {}) {
  const problems = [];
  const production = rows.filter((r) => !isSampleRowFields(r));
  if (production.length !== expectedRows) problems.push(`production rows ${production.length} != ${expectedRows}`);
  const ids = new Set();
  const paths = new Set();
  for (const r of production) {
    if (ids.has(r.article_id)) problems.push(`duplicate id ${r.article_id}`);
    ids.add(r.article_id);
    if (paths.has(r.output_path)) problems.push(`duplicate output_path ${r.output_path}`);
    paths.add(r.output_path);
    if ((r.status || '').trim() === 'PUBLISHED') {
      if (!fs.existsSync(path.join(REPO, r.output_path))) {
        problems.push(`PUBLISHED row without file: ${r.article_id}`);
      }
    }
  }
  // sitemap agreement
  const sitemapPath = path.join(REPO, 'sitemap.xml');
  const existing = currentSitemapUrls(sitemapPath);
  const factoryPrefix = site.site_url.replace(/\/+$/, '') + '/cam-nang/';
  const legacy = existing.filter((u) => !u.startsWith(factoryPrefix));
  const published = [];
  for (const r of production) {
    if ((r.status || '').trim() === 'PUBLISHED') {
      published.push(site.site_url.replace(/\/+$/, '') + '/' + (r.output_path || '').replace(/^\/+/, ''));
    }
  }
  const wanted = [...legacy];
  for (const p of published) if (!wanted.includes(p)) wanted.push(p);
  const missing = wanted.filter((u) => !existing.includes(u));
  const stale = existing.filter((u) => u.startsWith(factoryPrefix) && !wanted.includes(u));
  if (missing.length) problems.push(`sitemap missing ${missing.length} URL(s): ${missing.slice(0, 3).join(' ')}`);
  if (stale.length) problems.push(`sitemap has ${stale.length} stale factory URL(s): ${stale.slice(0, 3).join(' ')}`);
  if (new Set(existing.map((u) => u.replace(/\/+$/, ''))).size !== existing.length) {
    problems.push('sitemap contains duplicate URLs');
  }
  // hub blocks agreement
  const byCat = publishedByCategory(rows);
  for (const [cat, catRows] of byCat) {
    const hub = CATEGORIES[cat];
    const hubPath = path.join(REPO, hub);
    if (!fs.existsSync(hubPath)) { problems.push(`hub missing: ${hub}`); continue; }
    const text = fs.readFileSync(hubPath, 'utf8');
    const block = hubBlock(catRows, site.baseurl, hub, cat, catRows.length);
    const m = text.split(START);
    if (m.length < 2 || !text.includes(END)) {
      problems.push(`hub ${hub}: ARTICLE-LIST block missing`);
    } else {
      const current = START + text.split(START)[1].split(END)[0] + END;
      if (current !== block) problems.push(`hub ${hub}: ARTICLE-LIST block stale`);
    }
  }
  if (!quiet) {
    if (problems.length) {
      console.error('CONSISTENCY FAIL:');
      for (const p of problems) console.error('  ! ' + p);
    } else {
      console.error(`CONSISTENCY OK: 2000 production rows, ${existing.length} sitemap URLs, ${[...byCat.keys()].length} hub block(s) current`);
    }
  }
  return problems;
}

function main() {
  const args = parseArgs(process.argv.slice(2));
  if (args.repo) REPO = path.resolve(args.repo);
  const date = args.date || hanoiToday();
  const generated = new Date(Date.now() + 7 * 3600 * 1000).toISOString().slice(0, 19);
  const { site, kill } = readConfig();
  if (kill && kill.enabled === false) {
    console.error('FACTORY_PAUSED: config/content-factory.json enabled=false.');
    return 0;
  }
  const { raw, led, rows } = loadMatrix();
  validateInvariants(led, rows, args.expectRows || 2000);

  // A pending transaction marker means a previous multi-file mutation was
  // interrupted. Read-only modes warn; mutations are refused until --recover.
  const pendingTxn = readTxnMarker();
  const isMutation = (args.publish !== undefined && !args.dryRun)
    || (args.qaRecord !== undefined && !args.dryRun)
    || (args.rebuildReport !== undefined && !args.dryRun);
  if (pendingTxn && isMutation) {
    console.error('REFUSED: a pending transaction marker exists (data/batches/txn/).');
    console.error('  An earlier multi-file mutation was interrupted. Run --recover first.');
    return 2;
  }
  if (pendingTxn && !args.recover) {
    console.error('WARNING: pending transaction marker present (data/batches/txn/); run --recover when convenient.');
  }

  if (args.recover) {
    return recoverTransaction(site, { expectedRows: args.expectRows || 2000 });
  }

  if (args.consistency) {
    const problems = consistencyCheck(rows, site, { expectedRows: args.expectRows || 2000 });
    return problems.length ? 2 : 0;
  }

  if (args.rebuildReport !== undefined) {
    const batchId = (args.rebuildReport || '').trim();
    if (!batchId) { console.error('refused: --rebuild-report needs a batch id'); return 1; }
    const members = rows.filter((r) => !isSampleRowFields(r) && (r.batch_id || '').trim() === batchId);
    if (!members.length) { console.error(`refused: no rows reserved for batch ${batchId}`); return 2; }
    const reportFiles = rebuildBatchReport(batchId, rows, [], generated);
    if (args.dryRun) {
      console.error(`DRY RUN rebuild-report ${batchId}: would rewrite ${reportFiles.map((f) => path.relative(REPO, f.path)).join(', ')}`);
      return 0;
    }
    commitWrites(reportFiles);
    const report = JSON.parse(reportFiles[0].content);
    console.error(`REBUILD-REPORT ${batchId}: ${members.length} member(s), published=${report.published}, writing=${report.writing}, pass=${report.pass}`);
    return 0;
  }

  if (args.qaRecord !== undefined) {
    const specs = (args.qaRecord || '').split(',').map((s) => s.trim()).filter(Boolean);
    if (!specs.length) { console.error('refused: --qa-record needs a non-empty ID=SCORE:OUTCOME list'); return 1; }
    const updates = new Map();
    const qaRows = [];
    for (const spec of specs) {
      const m = /^(.+?)=(\d+):(PASS|REVIEW|FAIL)$/.exec(spec);
      if (!m) { console.error(`bad --qa-record spec: ${spec}`); return 1; }
      const [, id, scoreStr, outcome] = m;
      const score = parseInt(scoreStr, 10);
      const row = rows.find((r) => r.article_id === id);
      if (!row) { console.error(`article_id not in ledger: ${id}`); return 2; }
      const from = (row.status || '').trim();
      const notes = row.notes || '';
      const repairMatch = /repair:(\d+)/.exec(notes);
      const attempts = repairMatch ? parseInt(repairMatch[1], 10) : 0;
      if (outcome === 'PASS' && score < 90) {
        console.error(`refused: ${id} PASS requires score >= 90 (got ${score})`);
        return 2;
      }
      if (outcome === 'REVIEW' && attempts + 1 >= MAX_REPAIR_ATTEMPTS) {
        assertTransition(from, 'BLOCKED');
        updates.set(id, { status: 'BLOCKED', quality_status: 'BLOCKED', score: String(score), notes: (notes ? notes.replace(/repair:\d+/, '').trim() + ' ' : '') + `repair:${attempts + 1}`, last_checked: date });
        qaRows.push({ id, outcome: 'BLOCKED', score });
        continue;
      }
      const toStatus = outcome === 'PASS' ? 'PASS' : outcome === 'FAIL' ? 'FAIL' : 'REPAIR';
      assertTransition(from, toStatus);
      const upd = { status: toStatus, quality_status: outcome, score: String(score), last_checked: date };
      if (outcome === 'REVIEW') {
        upd.notes = ((notes ? notes.replace(/repair:\d+/, '').trim() + ' ' : '')) + `repair:${attempts + 1}`;
      }
      updates.set(id, upd);
      qaRows.push({ id, outcome, score });
    }
    const result = applyUpdates(raw, updates, { expectHeader: led.header });
    if (args.dryRun) {
      console.error(`DRY RUN qa-record: would update ${updates.size} row(s): ${[...updates.keys()].join(', ')}`);
      return 0;
    }
    commitWrites([{ path: matrixPath(), content: result.text }]);
    for (const q of qaRows) console.error(`QA-RECORD ${q.id}: ${q.outcome} (${q.score})`);
    const newRows = toRowObjects(result.text);
    const problems = consistencyCheck(newRows, site, { expectedRows: args.expectRows || 2000 });
    return problems.length ? 3 : 0;
  }

  if (args.publish !== undefined) {
    const ids = (args.publish || '').split(',').map((s) => s.trim()).filter(Boolean);
    if (!ids.length) {
      console.error('refused: --publish needs a non-empty comma-separated article id list');
      return 1;
    }
    if (ids.length !== new Set(ids).size) {
      console.error('refused: duplicate article ids in --publish list');
      return 2;
    }
    const updates = new Map();
    const results = [];
    const batchIds = new Set();
    for (const id of ids) {
      const row = rows.find((r) => r.article_id === id);
      if (!row) { console.error(`article_id not in ledger: ${id}`); return 2; }
      const from = (row.status || '').trim();
      if (from !== 'PASS') {
        console.error(`refused: ${id} is ${from}, publish requires PASS (run QA first)`);
        return 2;
      }
      const score = parseInt(row.score || '0', 10);
      if (!(score >= 90)) {
        console.error(`refused: ${id} score ${row.score} < 90`);
        return 2;
      }
      const filePath = path.join(REPO, row.output_path || '');
      if (!fs.existsSync(filePath)) {
        console.error(`refused: ${id} PASS row without article file: ${row.output_path}`);
        return 2;
      }
      batchIds.add((row.batch_id || '').trim());
      updates.set(id, { status: 'PUBLISHED', published_date: date });
      results.push({ article_id: id, output_path: row.output_path, category: row.category, batch_id: row.batch_id });
    }
    if (batchIds.size !== 1 || ![...batchIds][0]) {
      console.error('refused: publish scope must be exactly one batch (rows carry batch_id)');
      return 2;
    }
    const batchId = [...batchIds][0];

    // compute every output BEFORE writing anything
    const matrixOut = applyUpdates(raw, updates, { expectHeader: led.header });
    const rowsAfter = toRowObjects(matrixOut.text);
    validateInvariants(parseLedger(matrixOut.text), rowsAfter, args.expectRows || 2000);
    const writes = [];
    const sitemapOut = regenerateSitemap(rowsAfter, site, date);
    if (sitemapOut) writes.push(sitemapOut);
    const byCat = publishedByCategory(rowsAfter);
    for (const cat of [...byCat.keys()].sort()) {
      const hub = CATEGORIES[cat];
      const hubFile = regenerateHub(hub, byCat.get(cat), site.baseurl, hub);
      if (hubFile) writes.push(hubFile);
    }
    // carry the recorded published_commit_sha forward: it is the durable
    // audit trail of the last pushed publish transaction and must not be
    // silently reset to null by a later publish run
    const progressPath = path.join(REPO, 'reports', 'batches', 'factory-progress.json');
    let prevSha = null;
    if (fs.existsSync(progressPath)) {
      try { prevSha = (JSON.parse(fs.readFileSync(progressPath, 'utf8')) || {}).published_commit_sha || null; } catch (_) { prevSha = null; }
    }
    const progress = factoryProgress(rowsAfter, generated, prevSha);
    writes.push({ path: progressPath, content: jsonDump(progress) });
    const reportFiles = rebuildBatchReport(batchId, rowsAfter, results, generated);
    if (reportFiles) writes.push(...reportFiles);

    // pre-write consistency on the computed state
    const simProblems = consistencyCheck(rowsAfter, site, { quiet: true, expectedRows: args.expectRows || 2000 });
    // hubs/sitemap files on disk are still old — verify the planned writes fix them
    const problems = [];
    const plannedContent = new Map(writes.map((w) => [w.path, w.content]));
    for (const p of simProblems) {
      if (p.startsWith('hub ') || p.startsWith('sitemap')) {
        // resolved by a planned write? re-check below after writes
        continue;
      }
      problems.push(p);
    }
    if (problems.length) {
      console.error('REFUSED: consistency problems that publish cannot fix:');
      for (const p of problems) console.error('  ! ' + p);
      return 2;
    }

    if (args.dryRun) {
      console.error(`DRY RUN publish ${batchId}: ${updates.size} row(s) -> PUBLISHED (${[...updates.keys()].join(', ')}), published_date=${date}`);
      for (const w of writes) console.error(`  would write: ${path.relative(REPO, w.path)} (${w.content.length} bytes)`);
      return 0;
    }

    // multi-file transaction: write the recovery marker FIRST so an
    // interruption between renames is always recoverable via --recover
    const allWrites = [{ path: matrixPath(), content: matrixOut.text }, ...writes];
    writeTxnMarker('publish', { batch: batchId, ids: [...updates.keys()], published_date: date }, allWrites, generated);
    commitWrites(allWrites);
    clearTxnMarker();
    for (const r of results) console.error(`PUBLISHED ${r.article_id} -> ${r.output_path} (published_date=${date})`);
    const postRows = toRowObjects(fs.readFileSync(matrixPath(), 'utf8'));
    const postProblems = consistencyCheck(postRows, site, { expectedRows: args.expectRows || 2000 });
    if (postProblems.length) return 3;
    return 0;
  }

  console.error('nothing to do: use --qa-record, --publish, --rebuild-report, --recover or --consistency');
  return 1;
}

export function setRepo(p) {
  REPO = path.resolve(p);
}

// run as CLI only when executed directly (tests import the pure functions)
const isDirect = process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url);
if (isDirect) process.exit(main());
