// calc.js 공식 산식 검증 — 가짜 원천(tests/make_sample.py, 모든 숫자 임의값)으로 만든 백업 사용
//   node --test tests/*.mjs
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const require = createRequire(import.meta.url);
const ROOT = path.resolve(path.dirname(new URL(import.meta.url).pathname), '..');
const C = require(path.join(ROOT, 'calc.js'));

function buildSample() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'adsample-'));
  const py = process.env.PYTHON || 'python3';
  execFileSync(py, [path.join(ROOT, 'tests/make_sample.py'), dir], { stdio: 'ignore' });
  const code = `import sys, json; sys.path.insert(0, ${JSON.stringify(ROOT)}); import build_data as bd
from pathlib import Path
d = Path(${JSON.stringify(dir)})
p = bd.build([d/'sample_row.pkl', d/'sample_row_1001.pkl'])
open(d/'b.json', 'w', encoding='utf-8').write(bd.to_json(p))`;
  execFileSync(py, ['-c', code], { stdio: 'ignore' });
  return JSON.parse(fs.readFileSync(path.join(dir, 'b.json'), 'utf8'));
}
const P = buildSample();
const R = C.prepare(P.row, C.ROW_METS);
const near = (a, b, eps = 0.051) => assert.ok(Math.abs(a - b) <= eps, `${a} ≉ ${b}`);

test('월 일평균 = 기간 합 ÷ 데이터 일수, CPA = 합 ÷ 합', () => {
  const ts = C.daily(R, { group: 't' });
  const tot = C.addSeries([...ts.values()], C.ROW_METS, R.dates.length);
  const ps = C.periods(R, 'month'), sep = ps.at(-1);
  assert.equal(sep.key, '2026-10'); assert.equal(sep.idx.length, 4); assert.equal(sep.partial, true);
  let cost = 0, join = 0;
  for (let i = 0; i < R.n; i++) if (R.dates[R.f.d[i]].startsWith('2026-10')) { cost += R.f.cost[i]; join += R.f.join[i]; }
  near(C.value(C.METRIC.cost, C.sumIdx(tot, sep.idx, ['cost']), 4, 'avg'), cost / 4, 1e-6);
  near(C.value(C.METRIC.jcpa, C.sumIdx(tot, sep.idx, ['cost', 'join']), 4, 'avg'), cost / join, 1e-6);
  near(C.value(C.METRIC.cost, C.sumIdx(tot, sep.idx, ['cost']), 4, 'sum'), cost, 1e-6);
});

test('진행 중인 월의 전년·전월 비교는 같은 일자까지만', () => {
  const ps = C.periods(R, 'month'), oct = ps.at(-1), sep = ps.at(-2);
  const yoy = C.compareIdx(R, oct, 'month', 'yoy'), pop = C.compareIdx(R, oct, 'month', 'pop');
  assert.equal(yoy.length, 4); assert.equal(R.dates[yoy.at(-1)], '2025-10-04');
  assert.equal(pop.length, 4); assert.equal(R.dates[pop.at(-1)], '2026-09-04');
  assert.equal(C.compareIdx(R, sep, 'month', 'pop').length, 31);
});

test('주차: ISO 월~일, 표시는 목요일 기준 · 전년은 364일 전', () => {
  const ws = C.periods(R, 'week'), last = ws.at(-1);
  assert.equal(last.key, '2026-09-28'); assert.equal(last.label, '26년 10월 1주차'); assert.equal(last.idx.length, 7); assert.equal(last.partial, false);
  assert.deepEqual(C.compareIdx(R, last, 'week', 'yoy').map(i => R.dates[i]).slice(0, 2), ['2025-09-29', '2025-09-30']);
});

// 날짜 구간별 하루 고정값을 넣은 가짜 시리즈 (구매고객 · 첫구매 · UV)
function fixedSeries(spec) {
  const n = R.dates.length, o = { buy: new Float64Array(n), fp: new Float64Array(n), uv: new Float64Array(n) };
  R.dates.forEach((d, i) => { for (const [a, b, buy, fp, uv] of spec) if (d >= a && d <= b) { o.buy[i] = buy; o.fp[i] = fp; o.uv[i] = uv; } });
  return o;
}

test('베이스라인 · 계절 기대치 · 비중 · 전환율', () => {
  const s = fixedSeries([
    ['2025-07-01', '2025-09-30', 1000, 125, 50000], ['2025-10-01', '2025-10-31', 1100, 150, 50000],
    ['2026-07-01', '2026-09-30', 1200, 100, 40000], ['2026-10-01', '2026-10-31', 1500, 114, 38000],
  ]);
  const r = C.baseline(R, s, {
    base: C.rangeIdx(R, '2026-07-01', '2026-09-30'), recent: C.rangeIdx(R, '2026-10-01', '2026-10-04'),
    refBase: C.rangeIdx(R, '2025-07-01', '2025-09-30'), refRecent: C.rangeIdx(R, '2025-10-01', '2025-10-04'),
  }).rows;
  near(r.buy.base, 1200); near(r.fp.base, 100); near(r.buy.recent, 1500); near(r.fp.recent, 114);
  near(r.buy.chg, 25); near(r.fp.chg, 14); near(r.buy.season, 10); near(r.fp.season, 20);
  near(r.buy.exp, 1320); near(r.fp.exp, 120); near(r.fp.vsExp, -5);
  near(r.share.base, 100 / 1200, 1e-9); near(r.share.recent, 114 / 1500, 1e-9);
  near(r.cr.base, 100 / 40000, 1e-12); near(r.cr.recent, 114 / 38000, 1e-12); near(r.uv.chg, -5);
  near(r.fp.expAdj, 120);   // 하루 고정값이면 요일 보정 기대치 = 단순 기대치
});

test('요일 보정: 평일·주말 평균을 비교구간 요일 구성으로 가중', () => {
  const n = R.dates.length, s = { buy: new Float64Array(n), fp: new Float64Array(n), uv: new Float64Array(n) };
  R.dates.forEach((d, i) => { s.buy[i] = C.isOff(R.dn[i]) ? 20 : 10; s.fp[i] = 1; });
  const base = C.rangeIdx(R, '2026-07-01', '2026-09-30'), recent = C.rangeIdx(R, '2026-10-01', '2026-10-04');
  const w = C.weekdayAdjusted(R, s, base, recent, ['buy']);
  // 10/1(목) 10/2(금) 평일, 10/3(토·개천절) 10/4(일) → (10*2 + 20*2)/4
  assert.equal(w.on, 2); assert.equal(w.off, 2); near(w.buy, 15, 1e-9);
});

test('구성 효과 분해: 구성 + 내부 = 비중 변화 (브랜드/기획전 기준)', () => {
  const base = C.rangeIdx(R, '2026-07-01', '2026-09-28'), recent = C.rangeIdx(R, '2026-09-29', '2026-10-04');
  const t = C.tree(R, { where: { t: new Set(['브랜드검색광고']) }, dims: ['bp'], sets: [base, recent], mets: ['buy', 'fp'] });
  const d = t.days;
  const items = [...t.nodes.values()].map(n => ({ name: n.v, b: { buy: n.s[0].buy / d[0], fp: n.s[0].fp / d[0] }, r: { buy: n.s[1].buy / d[1], fp: n.s[1].fp / d[1] } }));
  assert.deepEqual(items.map(x => x.name).sort(), ['브랜드A', '우포스', '킨']);
  const dec = C.mixDecompose(items);
  near(dec.mix + dec.within, dec.R1 - dec.R0, 1e-9);
  near(dec.F0, items.reduce((a, x) => a + x.b.fp, 0), 1e-9);
});

test('드릴다운 트리: 하위 합 = 상위 (브랜드/기획전 · 디바이스 포함)', () => {
  const ps = C.periods(R, 'month'), at = ps.at(-1);
  const t = C.tree(R, { dims: ['t', 'bp', 'dev'], sets: [at.idx, C.compareIdx(R, at, 'month', 'yoy')] });
  for (const top of C.children(t, '', 0)) {
    const kids = C.children(t, top.key, 1);
    near(kids.reduce((a, k) => a + k.s[0].cost, 0), top.s[0].cost, 1e-6);
    for (const k of kids) near(C.children(t, k.key, 2).reduce((a, x) => a + x.s[0].join, 0), k.s[0].join, 1e-6);
  }
  near(C.children(t, '', 0).reduce((a, k) => a + k.s[1].join, 0), t.total[1].join, 1e-6);
});

test('데이터 없음: 2024년 원천에 없는 지표는 0 이 아니라 값 없음', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'adsample24-'));
  const py = process.env.PYTHON || 'python3';
  execFileSync(py, [path.join(ROOT, 'tests/make_sample.py'), dir], { stdio: 'ignore' });
  const code = `import sys, json; sys.path.insert(0, ${JSON.stringify(ROOT)}); import build_data as bd
from pathlib import Path
d = Path(${JSON.stringify(dir)})
p = bd.build([d/'sample_row_2024.pkl', d/'sample_row.pkl'])
open(d/'b.json', 'w', encoding='utf-8').write(bd.to_json(p))`;
  execFileSync(py, ['-c', code], { stdio: 'ignore' });
  const R2 = C.prepare(JSON.parse(fs.readFileSync(path.join(dir, 'b.json'), 'utf8')).row, C.ROW_METS);
  const tot = C.daily(R2).get('_');
  const ps = C.periods(R2, 'month');
  const m24 = ps.find(p => p.key === '2024-09'), m25 = ps.find(p => p.key === '2025-09');
  // 2024: 신규구매자 없음, 첫구매 · 구매고객은 있음
  assert.equal(C.value(C.METRIC.nb, C.sumIdx(tot, m24.idx, ['nb']), m24.idx.length, 'avg'), null);
  assert.ok(C.value(C.METRIC.fp, C.sumIdx(tot, m24.idx, ['fp']), m24.idx.length, 'avg') > 0);
  assert.ok(C.value(C.METRIC.fps, C.sumIdx(tot, m24.idx, ['fp', 'buy']), m24.idx.length, 'avg') > 0);
  // 2025 신규구매자의 전년비는 계산하지 않는다 (-100% 가 아니라 –)
  const v25 = C.value(C.METRIC.nb, C.sumIdx(tot, m25.idx, ['nb']), m25.idx.length, 'avg');
  const yoy = C.compareIdx(R2, m25, 'month', 'yoy');
  assert.ok(v25 > 0);
  assert.equal(C.pct(v25, C.value(C.METRIC.nb, C.sumIdx(tot, yoy, ['nb']), yoy.length, 'avg')), null);
  // 트리도 같은 규칙
  const t = C.tree(R2, { dims: ['t'], sets: [m25.idx, yoy], mets: ['nb', 'fp'] });
  assert.ok(Number.isNaN(t.total[1].nb)); assert.ok(t.total[1].fp > 0); assert.ok(t.total[0].nb > 0);
});

// 샘플 원천 파일 조합으로 백업 payload 만들기
const SAMPLE_DIR = (() => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'adsampleM-'));
  execFileSync(process.env.PYTHON || 'python3', [path.join(ROOT, 'tests/make_sample.py'), dir], { stdio: 'ignore' });
  return dir;
})();
function buildFiles(files) {
  const out = path.join(SAMPLE_DIR, `p${Math.random().toString(36).slice(2)}.json`);
  const code = `import sys, json; sys.path.insert(0, ${JSON.stringify(ROOT)}); import build_data as bd
from pathlib import Path
d = Path(${JSON.stringify(SAMPLE_DIR)})
p = bd.build([d/f for f in ${JSON.stringify(files)}])
open(${JSON.stringify(out)}, 'w', encoding='utf-8').write(bd.to_json(p))`;
  execFileSync(process.env.PYTHON || 'python3', ['-c', code], { stdio: 'ignore' });
  return JSON.parse(fs.readFileSync(out, 'utf8'));
}
function sumBy(P, keyFn) {
  const r = P.row, m = new Map();
  for (let i = 0; i < r.f.d.length; i++) { const k = keyFn(r, i); m.set(k, (m.get(k) || 0) + r.f.cost[i] + r.f.fp[i] * 1e3 + r.f.buy[i]); }
  return m;
}

test('브라우저 합치기 = 한 번에 빌드한 결과 (새 파일 날짜는 교체)', () => {
  const base = buildFiles(['sample_row_2024.pkl', 'sample_row.pkl']);
  const add = buildFiles(['sample_row_1001.pkl']);
  const full = buildFiles(['sample_row_2024.pkl', 'sample_row.pkl', 'sample_row_1001.pkl']);
  const mg = C.mergeBackup(base, add);
  assert.deepEqual(mg.row.dates, full.row.dates);
  assert.deepEqual(mg.row.na, full.row.na);
  assert.deepEqual(mg.merged, { added: 5, replaced: 1, kept: base.row.dates.length - 1 });
  assert.equal(mg.source.row.to, '2026-10-04'); assert.equal(mg.source.row.from, '2024-01-01');
  for (const key of [(r, i) => r.dates[r.f.d[i]] + '|' + r.dims.t[r.f.t[i]], (r, i) => r.dims.bp[r.f.bp[i]] + '|' + r.dims.dev[r.f.dev[i]] + '|' + r.dims.camp[r.f.camp[i]]]) {
    const a = sumBy(mg, key), b = sumBy(full, key);
    assert.equal(a.size, b.size);
    for (const [k, v] of b) near(a.get(k), v, 1e-6);
  }
  // 합친 결과도 화면 산식에 그대로 들어간다
  const R3 = C.prepare(mg.row, C.ROW_METS);
  assert.equal(R3.dates.length, full.row.dates.length);
  // 같은 파일을 두 번 합쳐도 결과가 같다 (날짜 교체라 중복 집계 없음)
  const mg2 = C.mergeBackup(mg, add);
  assert.equal(mg2.row.n, mg.row.n);
  assert.deepEqual(mg2.merged, { added: 0, replaced: 6, kept: mg.row.dates.length - 6 });
});

test('합치기: 저장된 데이터가 없으면 새 백업 그대로', () => {
  const add = buildFiles(['sample_row_1001.pkl']);
  assert.equal(C.mergeBackup(null, add), add);
});

test('표기 규칙', () => {
  assert.equal(C.fmt('money', 12_300_000), '12.3');
  assert.equal(C.fmt('money', 50_000), '5.0만');
  assert.equal(C.fmt('cpa', 76_000), '7.6');
  assert.equal(C.fmt('ratio', 0.0904), '9.0%');
  assert.equal(C.fmt('count', 1234.12), '1,234');
  assert.equal(C.fmt('count', 98.44), '98.4');
});
