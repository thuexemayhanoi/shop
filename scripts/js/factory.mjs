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
//   --rebuild-child-hubs                 regenerate /cam-nang/chu-de/ topic
//                                        hub pages (+ index, sitemap) from the
//                                        canonical taxonomy (no-op without it)
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

// -------------------------------------------------- child topic hubs
//
// The canonical taxonomy (data/content-taxonomy.json + -map.csv, built by
// scripts/build_taxonomy.py) groups the 2000 production rows into child
// topic clusters under the 6 parent categories. Every child cluster gets
// ONE hub page under cam-nang/chu-de/<child-slug>.html listing only
// PUBLISHED articles, so future factory publications appear in their hub
// automatically. When the taxonomy files are absent (legacy repos, test
// fixtures) ALL child-hub behaviour degrades to a no-op.

const CHILD_HUB_DIR = 'cam-nang/chu-de';

// Canonical chatbot embed snippet: every factory-generated page
// carries exactly one lazy embed of the external assistant.
const CHATBOT_SNIPPET = `<link rel="stylesheet" href="/shop/assets/css/chatbot-embed.css">\n<script src="/shop/assets/js/chatbot-embed.js" defer></script>\n`;

// Compact shared footer for factory-generated pages. Generated from the
// SAME taxonomy source as everything else by scripts/build_footer_snippet.py
// into _snippets/footer-compact.html (underscore dir: never deployed).
// Never hard-code a second taxonomy copy in this file.
const FOOTER_SNIPPET = (() => {
  try {
    return fs.readFileSync(path.join(REPO, '_snippets', 'footer-compact.html'), 'utf8');
  } catch (_) {
    return '';
  }
})();


function loadTaxonomy() {
  let tax = null;
  try {
    tax = JSON.parse(fs.readFileSync(path.join(REPO, 'data', 'content-taxonomy.json'), 'utf8'));
  } catch (_) { tax = null; }
  if (!tax || !Array.isArray(tax.parents)) return null;
  const map = new Map();
  try {
    const text = fs.readFileSync(path.join(REPO, 'data', 'content-taxonomy-map.csv'), 'utf8');
    for (const line of text.split('\n').filter(Boolean).slice(1)) {
      const cols = line.split(',');
      if (cols.length >= 4 && cols[0] && cols[2]) {
        map.set(cols[0].trim(), { parent_id: cols[1].trim(), child_id: cols[2].trim(), child_hub: cols[3].trim() });
      }
    }
  } catch (_) { return null; }
  if (!map.size) return null;
  return { tax, map };
}

function childHubFilePath(childHubUrl, baseurl) {
  const base = (baseurl || '/shop').replace(/\/+$/, '');
  const p = childHubUrl.startsWith(base) ? childHubUrl.slice(base.length) : childHubUrl;
  return p.replace(/^\/+/, '');
}

function childHubPublished(rows, map, childId) {
  const out = [];
  for (const r of rows) {
    if (isSampleRowFields(r)) continue;
    if ((r.status || '').trim() !== 'PUBLISHED') continue;
    const e = map.get((r.article_id || '').trim());
    if (e && e.child_id === childId) out.push(r);
  }
  out.sort((a, b) => (a.article_id || '').localeCompare(b.article_id || ''));
  return out;
}

function childHubContent(parent, child, articles, site, siblings) {
  const base = (site.baseurl || '/shop').replace(/\/+$/, '');
  const siteBase = site.site_url.replace(/\/+$/, '');
  const rel = childHubFilePath(child.child_hub_url, site.baseurl);
  const canonical = `${siteBase}/${rel}`;
  const title = `${child.child_title} | Cẩm nang ${parent.parent_title} - Mr Tú`;
  const description = `${child.description} Tổng hợp bài viết thuộc chủ đề ${child.child_title.toLowerCase()} trong cẩm nang thuê xe máy Hà Nội của Mr Tú, cập nhật liên tục.`;
  const crumb = `<p class="breadcrumb"><a href="${base}/">Trang chủ</a> › <a href="${base}/${CHILD_HUB_DIR}/">Cẩm nang</a> › <a href="${parent.parent_hub}">${parent.parent_title}</a> › <span>${htmlEscape(child.child_title)}</span></p>`;
  const ld = `{"@context":"https://schema.org","@type":"BreadcrumbList","itemListElement":[{"@type":"ListItem","position":1,"name":"Trang chủ","item":"${siteBase}/"},{"@type":"ListItem","position":2,"name":"Cẩm nang","item":"${siteBase}/${CHILD_HUB_DIR}/"},{"@type":"ListItem","position":3,"name":"${htmlEscape(parent.parent_title)}","item":"${siteBase}/${childHubFilePath(parent.parent_hub, site.baseurl)}"},{"@type":"ListItem","position":4,"name":"${htmlEscape(child.child_title)}","item":"${canonical}"}]}`;
  const list = articles.length
    ? `<ul class="article-list">\n${articles.map((r) => `<li class="article-card"><a href="${base}/${(r.output_path || '').replace(/^\/+/, '')}">${htmlEscape(r.working_title || r.slug)}</a></li>`).join('\n')}\n</ul>`
    : `<p>Chủ đề này nằm trong kế hoạch nội dung của Mr Tú. Các bài viết sẽ xuất hiện tại đây ngay khi được xuất bản.</p>`;
  const sib = siblings.length
    ? `<h2>Các chủ đề khác trong ${parent.parent_title}</h2>\n<ul class="article-list">\n${siblings.map((s) => `<li class="article-card"><a href="${s.child_hub_url}">${htmlEscape(s.child_title)}</a></li>`).join('\n')}\n</ul>\n<p><a href="${parent.parent_hub}">Xem tất cả bài viết ${parent.parent_title}</a></p>`
    : '';
  return `<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>${htmlEscape(title)}</title>
<meta name="description" content="${htmlEscape(description)}">
<meta name="robots" content="index, follow">
<link rel="canonical" href="${canonical}">
<script type="application/ld+json">${ld}</script>
<style>
body{font-family:system-ui,-apple-system,sans-serif;line-height:1.6;margin:0;background:#050505;color:#f5f5f7}
main{max-width:860px;margin:0 auto;padding:24px 16px 48px}
.breadcrumb{font-size:14px;color:#aeaeb2}
.breadcrumb a{color:#409cff;text-decoration:none}
.article-list{list-style:none;padding-left:0}
.article-card{margin:8px 0;padding:12px 14px;background:#1c1c1e;border:1px solid #2c2c2e;border-radius:10px}
.article-card a{color:#f5f5f7;text-decoration:none;font-weight:600}
.article-card a:hover{color:#ff6b00}
h1{font-size:26px}
h2{font-size:20px;margin-top:28px}
</style>
</head>
<body>
<main>
${crumb}
<h1>${htmlEscape(child.child_title)}</h1>
<p>${htmlEscape(child.description)} Đây là trang tổng hợp chủ đề <strong>${htmlEscape(child.child_title.toLowerCase())}</strong> trong mục ${parent.parent_title} của cẩm nang thuê xe máy Hà Nội Mr Tú.</p>
<p>Chủ đề hiện có <strong>${articles.length}</strong> bài viết đã xuất bản.</p>
<h2>Bài viết trong chủ đề</h2>
${list}
${sib}
</main>
${FOOTER_SNIPPET}${CHATBOT_SNIPPET}</body>
</html>
`;
}

function childHubIndexContent(tax, rows, site, map) {
  const base = (site.baseurl || '/shop').replace(/\/+$/, '');
  const siteBase = site.site_url.replace(/\/+$/, '');
  const canonical = `${siteBase}/${CHILD_HUB_DIR}/`;
  const sections = [];
  for (const parent of tax.parents || []) {
    const items = (parent.children || []).map((c) => {
      const pub = childHubPublished(rows, map, c.child_id).length;
      return `<li class="article-card"><a href="${c.child_hub_url}">${htmlEscape(c.child_title)}</a> <span>(${c.article_count} bài, ${pub} đã xuất bản)</span></li>`;
    }).join('\n');
    sections.push(`<h2>${parent.parent_title}</h2>\n<ul class="article-list">\n${items}\n</ul>`);
  }
  const ld = `{"@context":"https://schema.org","@type":"BreadcrumbList","itemListElement":[{"@type":"ListItem","position":1,"name":"Trang chủ","item":"${siteBase}/"},{"@type":"ListItem","position":2,"name":"Cẩm nang","item":"${canonical}"}]}`;
  return `<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Tất cả chủ đề cẩm nang thuê xe máy Hà Nội - Mr Tú</title>
<meta name="description" content="Danh mục đầy đủ các chủ đề cẩm nang thuê xe máy Hà Nội của Mr Tú: kinh nghiệm, an toàn, xe máy, du lịch, cung đường và hỏi đáp.">
<meta name="robots" content="index, follow">
<link rel="canonical" href="${canonical}">
<script type="application/ld+json">${ld}</script>
<style>
body{font-family:system-ui,-apple-system,sans-serif;line-height:1.6;margin:0;background:#050505;color:#f5f5f7}
main{max-width:860px;margin:0 auto;padding:24px 16px 48px}
.breadcrumb{font-size:14px;color:#aeaeb2}
.breadcrumb a{color:#409cff;text-decoration:none}
.article-list{list-style:none;padding-left:0}
.article-card{margin:8px 0;padding:12px 14px;background:#1c1c1e;border:1px solid #2c2c2e;border-radius:10px}
.article-card a{color:#f5f5f7;text-decoration:none;font-weight:600}
.article-card a:hover{color:#ff6b00}
.article-card span{color:#aeaeb2;font-size:13px}
h1{font-size:26px}
h2{font-size:20px;margin-top:28px}
</style>
</head>
<body>
<main>
<p class="breadcrumb"><a href="${base}/">Trang chủ</a> › <span>Cẩm nang</span></p>
<h1>Tất cả chủ đề cẩm nang</h1>
<p>Toàn bộ chủ đề cẩm nang thuê xe máy Hà Nội của Mr Tú, xếp theo từng mục lớn. Mỗi chủ đề tổng hợp các bài viết đã xuất bản trong chuyên mục đó.</p>
${sections.join('\n')}
</main>
${FOOTER_SNIPPET}${CHATBOT_SNIPPET}</body>
</html>
`;
}

export function buildChildHubWrites(rows, taxonomy, site) {
  if (!taxonomy) return [];
  const writes = [];
  for (const parent of taxonomy.tax.parents || []) {
    for (const child of parent.children || []) {
      const arts = childHubPublished(rows, taxonomy.map, child.child_id);
      const siblings = (parent.children || []).filter((s) => s.child_id !== child.child_id);
      writes.push({
        path: path.join(REPO, childHubFilePath(child.child_hub_url, site.baseurl)),
        content: childHubContent(parent, child, arts, site, siblings),
      });
    }
  }
  writes.push({
    path: path.join(REPO, CHILD_HUB_DIR, 'index.html'),
    content: childHubIndexContent(taxonomy.tax, rows, site, taxonomy.map),
  });
  // only files whose planned content actually differs from disk
  return writes.filter((w) => {
    try { return fs.readFileSync(w.path, 'utf8') !== w.content; } catch (_) { return true; }
  });
}

function childHubSitemapUrls(taxonomy, site) {
  if (!taxonomy) return [];
  const siteBase = site.site_url.replace(/\/+$/, '');
  const urls = [];
  for (const parent of taxonomy.tax.parents || []) {
    for (const child of parent.children || []) {
      urls.push(`${siteBase}/${childHubFilePath(child.child_hub_url, site.baseurl)}`);
    }
  }
  urls.push(`${siteBase}/${CHILD_HUB_DIR}/`);
  return urls;
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
  // child topic hub URLs are structural pages: preserved like legacy
  // commercial URLs even when the taxonomy files are temporarily absent
  const legacy = existing.filter((u) => !u.startsWith(factoryPrefix)
    || u.startsWith(factoryPrefix + 'chu-de'));
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
  for (const u of childHubSitemapUrls(loadTaxonomy(), site)) {
    if (!wanted.includes(u)) wanted.push(u);
  }
  const content = buildUrlset(wanted, date);
  const cur = fs.existsSync(sitemapPath) ? fs.readFileSync(sitemapPath, 'utf8') : '';
  if (content === cur) return null;
  return { path: sitemapPath, content, urls: wanted };
}

// ------------------------------------------------------ reports / progress

// Mirror of scripts/run_article_batch.py write_factory_progress(): ALL counts,
// including completed_batches, are derived from the matrix rows — nothing
// here is hard-coded.
export function factoryProgress(rows, generated, publishedCommitSha = null, matrixCommitSha = null) {
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
    matrix_commit_sha: matrixCommitSha || null,
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
 * Resolve the durable published_commit_sha for a batch report, in order:
 *   1. the previous batch report's recorded value (audit trail wins once set)
 *   2. the publish checkpoint recorded in factory-progress.json
 *   3. null
 * Mirrors run_article_batch.py _resolve_published_sha().
 */
export function resolvePublishedSha(prevReport) {
  const prevSha = (prevReport && prevReport.published_commit_sha) || null;
  if (prevSha) return prevSha;
  const p = path.join(REPO, 'reports', 'batches', 'factory-progress.json');
  try {
    return (JSON.parse(fs.readFileSync(p, 'utf8')) || {}).published_commit_sha || null;
  } catch (_) {
    return null;
  }
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
    published_commit_sha: resolvePublishedSha(prev),
    pass_publishable_now: members.filter((r) => {
      if ((r.status || '').trim() !== 'PASS') return false;
      const rel = (r.output_path || '').replace(/^\/+/, '');
      // DEPLOY GATE: QA-passed drafts legitimately live under _drafts/ until publish.
      return fs.existsSync(path.join(REPO, rel)) || fs.existsSync(path.join(REPO, '_drafts', rel));
    }).length,
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
 * Cumulative throughput counters (reports/batches/factory-throughput.json).
 * Mirrors scripts/run_article_batch.py update_throughput(): every counter is
 * incremented only by deterministic tooling with the exact number of rows
 * it verified — no estimated numbers are ever written.
 */
function updateThroughput(batchId, deltas) {
  const p = path.join(REPO, 'reports', 'batches', 'factory-throughput.json');
  let data = null;
  if (fs.existsSync(p)) {
    try { data = JSON.parse(fs.readFileSync(p, 'utf8')) || null; } catch (_) { data = null; }
  }
  if (!data || data.schema_version !== 1 || typeof data.batches !== 'object') {
    data = { schema_version: 1, batches: {} };
  }
  const b = data.batches[batchId] || {
    articles_written: 0, articles_qa_checked: 0, articles_published: 0,
    chunks_completed: 0, publish_operations: 0, repair_count: 0,
    qa_score_sum: 0, qa_score_count: 0, average_qa_score: null,
  };
  for (const k of ['articles_written', 'articles_qa_checked', 'articles_published',
                   'chunks_completed', 'publish_operations', 'repair_count',
                   'qa_score_sum', 'qa_score_count']) {
    if (deltas[k]) b[k] = (b[k] || 0) + deltas[k];
  }
  b.average_qa_score = b.qa_score_count ? Math.round((b.qa_score_sum / b.qa_score_count) * 10) / 10 : null;
  data.batches[batchId] = b;
  data.updated_at = new Date().toISOString().slice(0, 19);
  fs.mkdirSync(path.dirname(p), { recursive: true });
  fs.writeFileSync(p, jsonDump(data) + '\n', 'utf8');
}

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
  // DEPLOY GATE cleanup: a publish transaction that was interrupted after
  // committing the final files but before deleting the promoted drafts is
  // finished here (draft content is already safely at the public path).
  if (Array.isArray(marker.draft_paths)) {
    for (const d of marker.draft_paths) {
      try { fs.rmSync(d, { force: true }); } catch (_) {}
    }
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
    else if (a === '--rebuild-child-hubs') args.rebuildChildHubs = true;
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
    } else if (fs.existsSync(path.join(REPO, r.output_path))) {
      // DEPLOY GATE: only PUBLISHED articles may occupy a public URL path.
      problems.push(`unpublished row leaked to public path: ${r.article_id} (${r.status})`);
    }
  }
  // sitemap agreement
  const sitemapPath = path.join(REPO, 'sitemap.xml');
  const existing = currentSitemapUrls(sitemapPath);
  const factoryPrefix = site.site_url.replace(/\/+$/, '') + '/cam-nang/';
  // child topic hub URLs are structural pages: preserved like legacy
  // commercial URLs even when the taxonomy files are temporarily absent
  const legacy = existing.filter((u) => !u.startsWith(factoryPrefix)
    || u.startsWith(factoryPrefix + 'chu-de'));
  const published = [];
  for (const r of production) {
    if ((r.status || '').trim() === 'PUBLISHED') {
      published.push(site.site_url.replace(/\/+$/, '') + '/' + (r.output_path || '').replace(/^\/+/, ''));
    }
  }
  const wanted = [...legacy];
  for (const p of published) if (!wanted.includes(p)) wanted.push(p);
  const taxonomy = loadTaxonomy();
  if (taxonomy) {
    for (const u of childHubSitemapUrls(taxonomy, site)) {
      if (!wanted.includes(u)) wanted.push(u);
    }
    if (taxonomy.map.size !== production.length) {
      problems.push(`taxonomy map rows ${taxonomy.map.size} != production rows ${production.length}`);
    }
  }
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
  if (taxonomy) {
    for (const parent of taxonomy.tax.parents || []) {
      for (const child of parent.children || []) {
        const arts = childHubPublished(rows, taxonomy.map, child.child_id);
        const siblings = (parent.children || []).filter((s) => s.child_id !== child.child_id);
        const expected = childHubContent(parent, child, arts, site, siblings);
        const p = path.join(REPO, childHubFilePath(child.child_hub_url, site.baseurl));
        let cur = null;
        try { cur = fs.readFileSync(p, 'utf8'); } catch (_) { cur = null; }
        if (cur === null) problems.push(`child-hub missing: ${child.child_id}`);
        else if (cur !== expected) problems.push(`child-hub stale: ${child.child_id}`);
      }
    }
    const idxExpected = childHubIndexContent(taxonomy.tax, rows, site, taxonomy.map);
    let idxCur = null;
    try { idxCur = fs.readFileSync(path.join(REPO, CHILD_HUB_DIR, 'index.html'), 'utf8'); } catch (_) { idxCur = null; }
    if (idxCur === null) problems.push('child-hub missing: chu-de index');
    else if (idxCur !== idxExpected) problems.push('child-hub stale: chu-de index');
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
    || (args.rebuildReport !== undefined && !args.dryRun)
    || (args.rebuildChildHubs && !args.dryRun);
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

  if (args.rebuildChildHubs) {
    const taxonomy = loadTaxonomy();
    if (!taxonomy) {
      console.error('refused: data/content-taxonomy.json not found (run scripts/build_taxonomy.py first)');
      return 2;
    }
    const writes = buildChildHubWrites(rows, taxonomy, site);
    const sitemapOut = regenerateSitemap(rows, site, date);
    if (sitemapOut) writes.push(sitemapOut);
    if (args.dryRun || !writes.length) {
      console.error(args.dryRun
        ? `DRY RUN rebuild-child-hubs: would write ${writes.length} file(s)`
        : `CHILD-HUBS: ${writes.length} write(s) needed; files already current otherwise.`);
      for (const w of writes) console.error(`  ${path.relative(REPO, w.path)} (${w.content.length} bytes)`);
      return 0;
    }
    for (const w of writes) fs.mkdirSync(path.dirname(w.path), { recursive: true });
    writeTxnMarker('rebuild-child-hubs', {}, writes, generated);
    commitWrites(writes);
    const postRows = toRowObjects(fs.readFileSync(matrixPath(), 'utf8'));
    const postProblems = consistencyCheck(postRows, site, { expectedRows: args.expectRows || 2000 });
    if (postProblems.length) {
      console.error('REBUILD-CHILD-HUBS INCONSISTENT after commit; transaction marker KEPT:');
      for (const p of postProblems) console.error('  ! ' + p);
      return 3;
    }
    clearTxnMarker();
    console.error(`REBUILD-CHILD-HUBS OK: ${writes.length} file(s) written; child hubs + sitemap consistent.`);
    return 0;
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
    const promotions = [];
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
      // DEPLOY GATE: the QA-passed file may be a draft under _drafts/.
      // Publishing promotes it to the REAL output_path inside this same
      // transaction, so an unreviewed article can never sit on a public
      // URL (Jekyll never copies _drafts/ into the deployed site).
      const finalPath = path.join(REPO, row.output_path || '');
      const draftPath = path.join(REPO, '_drafts', (row.output_path || '').replace(/^[\/]+/, ''));
      let promote = null;
      if (!fs.existsSync(finalPath)) {
        if (!fs.existsSync(draftPath)) {
          console.error(`refused: ${id} PASS row without article file (draft or final): ${row.output_path}`);
          return 2;
        }
        promote = { id: id, draft: draftPath, final: finalPath };
      }
      batchIds.add((row.batch_id || '').trim());
      updates.set(id, { status: 'PUBLISHED', published_date: date });
      if (promote) promotions.push(promote);
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
    const childWrites = buildChildHubWrites(rowsAfter, loadTaxonomy(), site);
    if (childWrites.length) writes.push(...childWrites);
    // carry the recorded published_commit_sha forward: it is the durable
    // audit trail of the last pushed publish transaction and must not be
    // silently reset to null by a later publish run
    const progressPath = path.join(REPO, 'reports', 'batches', 'factory-progress.json');
    let prevSha = null;
    if (fs.existsSync(progressPath)) {
      try { prevSha = (JSON.parse(fs.readFileSync(progressPath, 'utf8')) || {}).published_commit_sha || null; } catch (_) { prevSha = null; }
    }
    const progress = factoryProgress(rowsAfter, generated, prevSha, process.env.GITHUB_SHA || null);
    writes.push({ path: progressPath, content: jsonDump(progress) });
    const reportFiles = rebuildBatchReport(batchId, rowsAfter, results, generated);
    if (reportFiles) writes.push(...reportFiles);

    // pre-write consistency on the computed state
    const simProblems = consistencyCheck(rowsAfter, site, { quiet: true, expectedRows: args.expectRows || 2000 });
    // hubs/sitemap files on disk are still old — verify the planned writes fix them
    const problems = [];
    const plannedContent = new Map(writes.map((w) => [w.path, w.content]));
    // a draft promotion plans exactly the missing public file of its row
    const promotionFixes = new Set(promotions.map((pr) => `PUBLISHED row without file: ${pr.id}`));
    for (const p of simProblems) {
      if (p.startsWith('hub ') || p.startsWith('sitemap') || p.startsWith('child-hub')) {
        // resolved by a planned write? re-check below after writes
        continue;
      }
      if (promotionFixes.has(p)) {
        continue;
      }
      problems.push(p);
    }
    if (problems.length) {
      console.error('REFUSED: consistency problems that publish cannot fix:');
      for (const p of problems) console.error('  ! ' + p);
      return 2;
    }

    // DEPLOY GATE promotion: each QA-passed draft moves from _drafts/ to
    // its REAL output_path as part of this same transaction.
    for (const pr of promotions) {
      const content = fs.readFileSync(pr.draft, 'utf8');
      writes.push({ path: pr.final, content });
    }

    if (args.dryRun) {
      console.error(`DRY RUN publish ${batchId}: ${updates.size} row(s) -> PUBLISHED (${[...updates.keys()].join(', ')}), published_date=${date}`);
      for (const w of writes) console.error(`  would write: ${path.relative(REPO, w.path)} (${w.content.length} bytes)`);
      for (const pr of promotions) console.error(`  promote draft: ${path.relative(REPO, pr.draft)} -> ${path.relative(REPO, pr.final)}`);
      return 0;
    }

    // multi-file transaction: write the recovery marker FIRST so an
    // interruption between renames is always recoverable via --recover
    const allWrites = [{ path: matrixPath(), content: matrixOut.text }, ...writes];
    for (const w of allWrites) fs.mkdirSync(path.dirname(w.path), { recursive: true });
    writeTxnMarker('publish', { batch: batchId, ids: [...updates.keys()], published_date: date, draft_paths: promotions.map((pr) => pr.draft) }, allWrites, generated);
    commitWrites(allWrites);
    // remove promoted draft files AFTER their content is safely committed
    // at the final path (recoverTransaction re-applies allWrites if the
    // process died in between, so the draft is never the only copy)
    for (const pr of promotions) {
      try { fs.rmSync(pr.draft, { force: true }); } catch (_) {}
    }
    for (const r of results) console.error(`PUBLISHED ${r.article_id} -> ${r.output_path} (published_date=${date})`);
    if (promotions.length) console.error(`DEPLOY GATE: ${promotions.length} draft file(s) promoted from _drafts/ to their public URL path.`);
    // The marker is removed ONLY AFTER the full transaction is verified
    // consistent. On failure the marker and planned recovery data stay
    // intact so --recover / manual investigation can finish the job.
    const postRows = toRowObjects(fs.readFileSync(matrixPath(), 'utf8'));
    let postProblems = consistencyCheck(postRows, site, { expectedRows: args.expectRows || 2000 });
    // TEST-ONLY hook (never set in production): simulate a post-write
    // consistency failure to prove the marker survives it.
    if (process.env.FACTORY_TEST_FAIL_POST_CONSISTENCY === '1') {
      postProblems = [...postProblems, 'test-injected post-write inconsistency'];
    }
    if (postProblems.length) {
      console.error('PUBLISH INCONSISTENT after commit; transaction marker KEPT:');
      for (const p of postProblems) console.error('  ! ' + p);
      console.error('  marker + planned recovery data kept at data/batches/txn/ — run --recover (or investigate manually).');
      return 3;
    }
    clearTxnMarker();
    // grouped publish succeeded: record the honest throughput counters
    updateThroughput(batchId, { articles_published: updates.size, publish_operations: 1 });
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
