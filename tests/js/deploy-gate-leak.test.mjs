// DEPLOY GATE regression (BATCH-017 chunk 24 incident, 2026-10-04): a
// WRITING row whose draft was written straight to the PUBLIC output_path
// must fail `factory.mjs --consistency`, so an external writer can never
// expose an unpublished draft at its live URL. Only the publisher may
// promote _drafts/<output_path> -> <output_path> after QA PASS.
// Self-contained sandbox: 6 production rows + 1 SAMPLE row, mirroring
// factory.test.mjs's makeSandbox contract (--expect-rows 6).
import { test } from 'node:test';
import assert from 'node:assert';
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';
import { parseLedger, serializeRow } from '../../scripts/js/ledger.mjs';

const REPO = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const REAL_MATRIX = fs.readFileSync(path.join(REPO, 'data', 'content-matrix.csv'), 'utf8');
const FACTORY = path.join(REPO, 'scripts', 'js', 'factory.mjs');

function makeSandbox() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'deploy-gate-test-'));
  const header = parseLedger(REAL_MATRIX).header;
  const mk = (p) => { fs.mkdirSync(path.dirname(path.join(dir, p)), { recursive: true }); return path.join(dir, p); };
  fs.mkdirSync(path.join(dir, 'config'), { recursive: true });
  fs.copyFileSync(path.join(REPO, 'config', 'site.json'), path.join(dir, 'config', 'site.json'));
  fs.copyFileSync(path.join(REPO, 'config', 'content-factory.json'), path.join(dir, 'config', 'content-factory.json'));
  fs.copyFileSync(path.join(REPO, 'config', 'article-rubric.json'), path.join(dir, 'config', 'article-rubric.json'));

  const row = (id, status, cat, hub) => [
    id, status, cat, 'kw' + id, 'kw' + id, 'informational', 'Title ' + id,
    id.toLowerCase(), `cam-nang/x/${id.toLowerCase()}.html`, hub, 'no', 'false',
    'note', hub, '', 'Mr Tú', '2027-01-01', '95', 'PASS', '2026-09-25', '', '', 'BATCH-001',
  ];
  const minimal = (id, cat, hub, status = 'PLANNED') => {
    const f = [id, status].concat(Array(header.length - 2).fill(''));
    f[2] = cat; f[3] = 'kw ' + id; f[6] = 'Title ' + id; f[7] = id.toLowerCase();
    f[8] = `cam-nang/x/${id.toLowerCase()}.html`; f[9] = hub; f[10] = 'no';
    f[11] = 'false'; f[14] = hub; f[16] = 'Mr Tú'; f[22] = 'BATCH-001';
    return f;
  };
  const rows = [
    ['SAMPLE-A', 'SAMPLE', 'Kinh nghiệm', 'kwSAMPLE-A', 'kwSAMPLE-A', 'informational',
      'Title SAMPLE-A', 'sample-a', 'tests/fixtures/sample-a.html', 'kinhnghiem.html', 'no', 'false',
      'note', 'kinhnghiem.html', '', 'Mr Tú', '2027-01-01', '95', 'PASS', '2026-09-25', '', '', 'BATCH-001'],
    minimal('KN-0100', 'Kinh nghiệm', 'kinhnghiem.html'),
    minimal('KN-0101', 'Kinh nghiệm', 'kinhnghiem.html', 'WRITING'),
    row('KN-0102', 'PASS', 'Kinh nghiệm', 'kinhnghiem.html'),
    row('XM-0100', 'PUBLISHED', 'Xe máy', 'xemay.html'),
    row('XM-0101', 'PASS', 'Xe máy', 'xemay.html'),
    minimal('DL-0100', 'Du lịch', 'dulich.html'),
  ].map((r) => { const f = r.slice(); while (f.length < header.length) f.push(''); return f; });

  fs.writeFileSync(mk('data/content-matrix.csv'),
    header.join(',') + '\r\n' + rows.map((f) => serializeRow(f)).join(''), 'utf8');

  // DEPLOY GATE files: PUBLISHED at the public path, PASS under _drafts/
  for (const f of rows) {
    const doc = '<!DOCTYPE html><html lang="vi"><body><main><h1>' + f[0] + '</h1></main></body></html>\n';
    if (f[1] === 'PUBLISHED') fs.writeFileSync(mk(f[8]), doc, 'utf8');
    else if (f[1] === 'PASS') fs.writeFileSync(mk('_drafts/' + f[8]), doc, 'utf8');
  }

  const START = '<!-- ARTICLE-LIST:START -->';
  const END = '<!-- ARTICLE-LIST:END -->';
  fs.writeFileSync(mk('kinhnghiem.html'),
    '<html><body><main><h1>KN</h1>\n' + START + '\n<ul class="article-list">\n<li class="article-card"><a href="/shop/cam-nang/x/kn-0102.html">Title KN-0102</a></li>\n</ul>\n' + END + '\n</main></body></html>\n', 'utf8');
  fs.writeFileSync(mk('xemay.html'),
    '<html><body><main><h1>XM</h1>\n' + START + '\n<ul class="article-list">\n<li class="article-card"><a href="/shop/cam-nang/x/xm-0100.html">Title XM-0100</a></li>\n</ul>\n' + END + '\n</main></body></html>\n', 'utf8');
  fs.writeFileSync(mk('dulich.html'), '<html><body><main><h1>DL</h1>\n</main></body></html>\n', 'utf8');
  fs.writeFileSync(mk('sitemap.xml'),
    `<?xml version='1.0' encoding='utf-8'?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>https://thuexemayhanoi.github.io/shop/</loc><lastmod>2026-09-25</lastmod></url><url><loc>https://thuexemayhanoi.github.io/shop/cam-nang/x/xm-0100.html</loc><lastmod>2026-09-25</lastmod></url></urlset>\n`, 'utf8');
  return dir;
}

function runFactoryRaw(dir, args) {
  return spawnSync('node', [FACTORY, ...args, '--repo', dir, '--expect-rows', '6'], {
    encoding: 'utf8',
  });
}

test('deploy gate: a WRITING row written to its public path fails consistency; _drafts/ is green', () => {
  const dir = makeSandbox();
  // green baseline
  let r = runFactoryRaw(dir, ['--consistency']);
  assert.strictEqual(r.status, 0, 'baseline consistency must pass\n' + r.stdout + r.stderr);

  // simulate the wrong-path writer bug (BATCH-017 chunk 24): the WRITING
  // row KN-0101 gets a file at its PUBLIC output_path instead of _drafts/
  const leaked = path.join(dir, 'cam-nang', 'x', 'kn-0101.html');
  fs.mkdirSync(path.dirname(leaked), { recursive: true });
  fs.writeFileSync(leaked,
    '<!DOCTYPE html><html lang="vi"><body><main><h1>KN-0101</h1></main></body></html>\n', 'utf8');
  r = runFactoryRaw(dir, ['--consistency']);
  assert.notStrictEqual(r.status, 0, 'consistency must FAIL while an unpublished draft sits at its public path');
  assert.match(r.stdout + r.stderr,
    /unpublished row leaked to public path: KN-0101 \(WRITING\)/);

  // moving the draft back under _drafts/ restores consistency
  const draftsPath = path.join(dir, '_drafts', 'cam-nang', 'x', 'kn-0101.html');
  fs.mkdirSync(path.dirname(draftsPath), { recursive: true });
  fs.renameSync(leaked, draftsPath);
  r = runFactoryRaw(dir, ['--consistency']);
  assert.strictEqual(r.status, 0, 'consistency must pass again once the draft lives under _drafts/\n' + r.stdout + r.stderr);
});
