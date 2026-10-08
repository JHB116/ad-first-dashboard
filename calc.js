/* 광고 신규 실적 대시보드 — 공식 산식 (화면과 테스트가 함께 쓴다)
 * 브라우저: window.AdCalc / Node: require('./calc.js')
 * 원칙: 합계형 지표는 기간 합 ÷ 데이터 일수, 비율·CPA 는 합계 ÷ 합계 (일평균의 평균 X)
 */
(function (root) {
  'use strict';

  const TYPES = ['브랜드검색광고', '사이트검색광고', '쇼핑검색광고', 'DA', 'DA(페이먼츠)', '메시지', 'PA'];
  const TOTAL = '합계';
  const ROW_METS = ['cost', 'uv', 'join', 'fp', 'fpr', 'fpn', 'nb', 'nrev', 'buy', 'rev', 'wb'];

  // 화면 지표 — kind: money(원) · count(명) · cpa(원/명) · ratio(0~1)
  const METRICS = [
    { k: 'cost', n: '광고비', kind: 'money', base: ['cost'], f: s => s.cost },
    { k: 'join', n: '가입', kind: 'count', base: ['join'], f: s => s.join },
    { k: 'jcpa', n: '가입CPA', kind: 'cpa', base: ['cost', 'join'], f: s => div(s.cost, s.join), lowerBetter: true },
    { k: 'fp', n: '첫구매', kind: 'count', base: ['fp'], f: s => s.fp },
    { k: 'fcpa', n: '첫구매CPA', kind: 'cpa', base: ['cost', 'fp'], f: s => div(s.cost, s.fp), lowerBetter: true },
    { k: 'fpr', n: '첫구매거래액', kind: 'money', base: ['fpr'], f: s => s.fpr },
    { k: 'nb', n: '신규구매자', kind: 'count', base: ['nb'], f: s => s.nb },
    { k: 'nrev', n: '신규거래액', kind: 'money', base: ['nrev'], f: s => s.nrev },
  ];
  // 드릴다운 표에만 쓰는 보조 지표
  const EXTRA = [
    { k: 'fpj', n: '첫구매/가입', kind: 'ratio', base: ['fp', 'join'], f: s => div(s.fp, s.join) },
    { k: 'fpn', n: '첫구매(순결제)', kind: 'count', base: ['fpn'], f: s => s.fpn },
    { k: 'uv', n: 'UV', kind: 'count', base: ['uv'], f: s => s.uv },
    { k: 'buy', n: '구매고객', kind: 'count', base: ['buy'], f: s => s.buy },
    { k: 'fps', n: '첫구매 비중', kind: 'ratio', base: ['fp', 'buy'], f: s => div(s.fp, s.buy) },   // 첫구매 ÷ 구매고객(총결제)
    { k: 'fpu', n: '첫구매 전환율', kind: 'ratio', base: ['fp', 'uv'], f: s => div(s.fp, s.uv) },    // 첫구매 ÷ UV
  ];
  const METRIC = Object.fromEntries([...METRICS, ...EXTRA].map(m => [m.k, m]));

  function div(a, b) { return b ? a / b : null; }
  function pct(a, b) { return (a == null || b == null || !b || !isFinite(a) || !isFinite(b)) ? null : (a / b - 1) * 100; }

  // ── 날짜 ───────────────────────────────────────────────────────────
  const DAY = 864e5;
  function dnum(iso) { return Math.round(Date.UTC(+iso.slice(0, 4), +iso.slice(5, 7) - 1, +iso.slice(8, 10)) / DAY); }
  function iso(n) { return new Date(n * DAY).toISOString().slice(0, 10); }
  function dow(n) { return (new Date(n * DAY).getUTCDay()); } // 0=일
  function monthDays(y, m) { return new Date(Date.UTC(y, m, 0)).getUTCDate(); } // m 1~12
  const WD = ['일', '월', '화', '수', '목', '금', '토'];

  // 공휴일(요일 보정에서 주말과 같이 취급) — 필요하면 추가
  const HOLIDAYS = {
    '2024-01-01': '신정', '2024-02-09': '설날', '2024-02-10': '설날', '2024-02-11': '설날', '2024-02-12': '대체공휴일',
    '2024-03-01': '삼일절', '2024-04-10': '총선', '2024-05-05': '어린이날', '2024-05-06': '대체공휴일', '2024-05-15': '부처님오신날',
    '2024-06-06': '현충일', '2024-08-15': '광복절', '2024-09-16': '추석', '2024-09-17': '추석', '2024-09-18': '추석',
    '2024-10-01': '국군의날', '2024-10-03': '개천절', '2024-10-09': '한글날', '2024-12-25': '성탄절',
    '2025-01-01': '신정', '2025-01-27': '임시공휴일', '2025-01-28': '설날', '2025-01-29': '설날', '2025-01-30': '설날',
    '2025-03-01': '삼일절', '2025-03-03': '대체공휴일', '2025-05-05': '어린이날·부처님오신날', '2025-05-06': '대체공휴일',
    '2025-06-03': '대선', '2025-06-06': '현충일', '2025-08-15': '광복절', '2025-10-03': '개천절', '2025-10-05': '추석',
    '2025-10-06': '추석', '2025-10-07': '추석', '2025-10-08': '대체공휴일', '2025-10-09': '한글날', '2025-12-25': '성탄절',
    '2026-01-01': '신정', '2026-02-16': '설날', '2026-02-17': '설날', '2026-02-18': '설날', '2026-03-01': '삼일절',
    '2026-03-02': '대체공휴일', '2026-05-05': '어린이날', '2026-05-24': '부처님오신날', '2026-05-25': '대체공휴일',
    '2026-06-03': '지방선거', '2026-06-06': '현충일', '2026-08-15': '광복절', '2026-08-17': '대체공휴일',
    '2026-09-24': '추석', '2026-09-25': '추석', '2026-09-26': '추석', '2026-10-03': '개천절', '2026-10-05': '대체공휴일',
    '2026-10-09': '한글날', '2026-12-25': '성탄절',
  };
  function isOff(n) { const w = dow(n); return w === 0 || w === 6 || !!HOLIDAYS[iso(n)]; }

  // 차트 주석 — 배경 이벤트
  const EVENTS = [
    { date: '2026-07-01', label: '20% 앱전용 쿠폰' },
    { date: '2026-08-01', label: '웰컴백 쿠폰 앱전용' },
  ];

  // ── 데이터셋 ───────────────────────────────────────────────────────
  // 백업의 row / af 섹션 → 타입 배열로 (dims: 값 목록, f: 인덱스·지표 배열)
  function prepare(sec, mets) {
    if (!sec) return null;
    const n = sec.n != null ? sec.n : sec.f.d.length;
    const ds = {
      dates: sec.dates, dn: Int32Array.from(sec.dates.map(dnum)), n,
      dims: sec.dims, dimKeys: Object.keys(sec.dims), mets: mets.filter(m => sec.f[m]),
      f: {}, byNum: new Map(),
    };
    ds.dates.forEach((d, i) => ds.byNum.set(ds.dn[i], i));
    ds.f.d = Int32Array.from(sec.f.d);
    for (const k of ds.dimKeys) ds.f[k] = Int32Array.from(sec.f[k]);
    for (const m of ds.mets) ds.f[m] = Float64Array.from(sec.f[m]);
    // 지표별 '데이터 없음' 날짜 (그 날짜 원천에 컬럼이 없었음) — 합계가 0 이 아니라 NaN 이 된다
    ds.na = {};
    for (const [m, list] of Object.entries(sec.na || {})) {
      const a = new Uint8Array(ds.dates.length);
      for (const d of list) { const i = ds.byNum.get(dnum(d)); if (i != null) a[i] = 1; }
      ds.na[m] = a;
    }
    return ds;
  }

  // 조건(dim → Set 값)에 맞는 행만 · 그룹 키 함수로 일자별 합계
  // 반환: Map(groupKey → {met: Float64Array(날짜수)})
  function daily(ds, { where = null, group = null, mets = ds.mets } = {}) {
    const nd = ds.dates.length, out = new Map();
    const conds = where ? Object.entries(where).filter(([, v]) => v).map(([k, v]) => [ds.f[k], maskOf(ds.dims[k], v)]) : [];
    const gk = group ? (typeof group === 'function' ? group : (i => ds.f[group][i])) : (() => '_');
    const F = mets.map(m => ds.f[m]);
    for (let i = 0; i < ds.n; i++) {
      let ok = true;
      for (const [col, mask] of conds) if (!mask[col[i]]) { ok = false; break; }
      if (!ok) continue;
      const key = gk(i);
      if (key == null) continue;
      let o = out.get(key);
      if (!o) { o = {}; for (const m of mets) o[m] = new Float64Array(nd); withNa(o, ds.na); out.set(key, o); }
      const d = ds.f.d[i];
      for (let j = 0; j < mets.length; j++) o[mets[j]][d] += F[j][i];
    }
    return out;
  }
  function maskOf(vals, sel) {
    const s = sel instanceof Set ? sel : new Set(sel);
    return Uint8Array.from(vals.map(v => s.has(v) ? 1 : 0));
  }
  function withNa(o, na) { Object.defineProperty(o, '_na', { value: na || {}, enumerable: false }); return o; }
  function addSeries(list, mets, nd) {
    const o = {}; for (const m of mets) { o[m] = new Float64Array(nd); for (const s of list) if (s) { const a = s[m]; for (let i = 0; i < nd; i++) o[m][i] += a[i]; } }
    const src = list.find(s => s && s._na);
    return withNa(o, src ? src._na : {});
  }
  // 날짜 집합 중 하루라도 '데이터 없음'이면 그 지표의 기간 값은 없음
  function naIn(na, m, idx) { const a = na && na[m]; if (!a) return false; for (const i of idx) if (a[i]) return true; return false; }

  // ── 기간 ───────────────────────────────────────────────────────────
  // ISO 주(월~일), 표시 월·주차는 그 주 목요일 기준
  function weekInfo(n) {
    const mon = n - ((dow(n) + 6) % 7), thu = mon + 3, t = iso(thu);
    const y = +t.slice(0, 4), m = +t.slice(5, 7), dd = +t.slice(8, 10);
    return { mon, key: iso(mon), y, m, w: Math.ceil(dd / 7) };
  }
  // 데이터 날짜(인덱스)들을 월/주/일 기간으로 묶는다
  function periods(ds, grain, valid = null) {
    const map = new Map(), list = [];
    for (let i = 0; i < ds.dates.length; i++) {
      if (valid && !valid[i]) continue;
      const n = ds.dn[i], d = ds.dates[i];
      let key, label, short, y, m, start, end;
      if (grain === 'month') {
        y = +d.slice(0, 4); m = +d.slice(5, 7); key = d.slice(0, 7);
        label = `${String(y).slice(2)}.${String(m).padStart(2, '0')}`; short = label;
        start = dnum(`${key}-01`); end = start + monthDays(y, m) - 1;
      } else if (grain === 'week') {
        const w = weekInfo(n); y = w.y; m = w.m; key = w.key;
        label = `${String(y).slice(2)}년 ${m}월 ${w.w}주차`; short = `${m}/${w.w}주`;
        start = w.mon; end = w.mon + 6;
      } else {
        y = +d.slice(0, 4); m = +d.slice(5, 7); key = d;
        label = `${d.slice(2).replace(/-/g, '.')}(${WD[dow(n)]})`; short = `${m}/${+d.slice(8, 10)}`;
        start = end = n;
      }
      let p = map.get(key);
      if (!p) { p = { key, label, short, y, m, start, end, idx: [] }; map.set(key, p); list.push(p); }
      p.idx.push(i);
    }
    list.sort((a, b) => a.start - b.start);
    for (const p of list) {
      p.calDays = p.end - p.start + 1;
      p.lastN = ds.dn[p.idx[p.idx.length - 1]];
      p.partial = p.lastN < p.end;    // 진행 중(부분) 기간
    }
    return list;
  }
  // 비교 기간의 데이터 날짜 인덱스
  //  - 일·주: 전년 = 364일 전 같은 요일, 전기 = 1일/7일 전
  //  - 월: 전년 = 전년 같은 월, 전기 = 전월. 진행 중인 월이면 같은 일자(1일~N일)까지만
  function compareIdx(ds, p, grain, cmp, valid = null) {
    const out = [];
    const take = n => { const i = ds.byNum.get(n); if (i != null && (!valid || valid[i])) out.push(i); };
    if (grain === 'month') {
      let y = p.y, m = p.m;
      if (cmp === 'yoy') y -= 1; else { m -= 1; if (!m) { m = 12; y -= 1; } }
      const md = monthDays(y, m), lim = p.partial ? Math.min(md, p.lastN - p.start + 1) : md;
      const s = dnum(`${y}-${String(m).padStart(2, '0')}-01`);
      for (let k = 0; k < lim; k++) take(s + k);
    } else {
      const shift = cmp === 'yoy' ? 364 : (grain === 'week' ? 7 : 1);
      for (const i of p.idx) take(ds.dn[i] - shift);
    }
    return out;
  }
  // 날짜 범위(포함) → 데이터 날짜 인덱스
  function rangeIdx(ds, from, to, valid = null) {
    const a = typeof from === 'string' ? dnum(from) : from, b = typeof to === 'string' ? dnum(to) : to, out = [];
    for (let i = 0; i < ds.dates.length; i++) if (ds.dn[i] >= a && ds.dn[i] <= b && (!valid || valid[i])) out.push(i);
    return out;
  }

  // ── 합계 · 지표 ────────────────────────────────────────────────────
  function sumIdx(series, idx, mets) {
    const s = {}, na = series._na;
    for (const m of mets) {
      if (naIn(na, m, idx)) { s[m] = NaN; continue; }
      let v = 0; const a = series[m]; for (const i of idx) v += a[i]; s[m] = v;
    }
    return s;
  }
  // 합계형은 mode==='avg' 이면 ÷일수, CPA·비율은 합계÷합계
  function value(metric, sums, days, mode) {
    if (!days) return null;
    const v = metric.f(sums);
    if (v == null || Number.isNaN(v)) return null;
    if ((metric.kind === 'money' || metric.kind === 'count') && mode === 'avg') return v / days;
    return v;
  }
  function seriesValues(metric, series, plist, mode) {
    return plist.map(p => value(metric, sumIdx(series, p.idx, metric.base || ROW_METS), p.idx.length, mode));
  }

  // ── 드릴다운 트리 ───────────────────────────────────────────────────
  // 날짜 집합 여러 개(sets[0]=현재, [1]=비교 …)에 대해 dims 순서대로 단계별 합계
  // 노드 키 = 값 인덱스를 '|' 로 이은 접두사. 노드.s[k] = k번째 집합의 합계
  function tree(ds, { where = null, dims, sets, mets = ds.mets, rowFilter = null }) {
    const nd = ds.dates.length, K = sets.length;
    const slots = sets.map(set => { const a = new Uint8Array(nd); for (const i of set) a[i] = 1; return a; });
    const conds = where ? Object.entries(where).filter(([, v]) => v).map(([k, v]) => [ds.f[k], maskOf(ds.dims[k], v)]) : [];
    const cols = dims.map(k => ds.f[k]), F = mets.map(m => ds.f[m]);
    const nodes = new Map(), total = sets.map(() => zero(mets));
    const hit = new Int8Array(K);
    for (let i = 0; i < ds.n; i++) {
      const d = ds.f.d[i];
      let any = false;
      for (let k = 0; k < K; k++) { hit[k] = slots[k][d]; if (hit[k]) any = true; }
      if (!any) continue;
      let ok = true;
      for (const [col, mask] of conds) if (!mask[col[i]]) { ok = false; break; }
      if (!ok || (rowFilter && !rowFilter(i))) continue;
      let key = '';
      for (let L = 0; L < cols.length; L++) {
        key = L ? key + '|' + cols[L][i] : String(cols[L][i]);
        let node = nodes.get(key);
        if (!node) { node = { key, level: L, dim: dims[L], v: ds.dims[dims[L]][cols[L][i]], s: sets.map(() => zero(mets)) }; nodes.set(key, node); }
        for (let k = 0; k < K; k++) if (hit[k]) { const tgt = node.s[k]; for (let j = 0; j < mets.length; j++) tgt[mets[j]] += F[j][i]; }
      }
      for (let k = 0; k < K; k++) if (hit[k]) for (let j = 0; j < mets.length; j++) total[k][mets[j]] += F[j][i];
    }
    // '데이터 없음' 날짜가 낀 집합의 지표는 NaN
    sets.forEach((set, k) => {
      for (const m of mets) if (naIn(ds.na, m, set)) { total[k][m] = NaN; for (const n of nodes.values()) n.s[k][m] = NaN; }
    });
    return { nodes, total, days: sets.map(s => s.length) };
  }
  function zero(mets) { const o = {}; for (const m of mets) o[m] = 0; return o; }
  function children(t, parentKey, level) {
    const out = [];
    for (const n of t.nodes.values()) {
      if (n.level !== level) continue;
      if (level > 0 && n.key.slice(0, n.key.lastIndexOf('|')) !== parentKey) continue;
      out.push(n);
    }
    return out;
  }
  // 노드 키 → 행 필터 (그 노드의 추이 그리기용)
  function keyWhere(ds, dims, key) {
    const parts = key.split('|').map(Number), w = {};
    parts.forEach((ix, L) => { w[dims[L]] = new Set([ds.dims[dims[L]][ix]]); });
    return w;
  }

  // ── 베이스라인 · 계절 기대치 · 요일 보정 ─────────────────────────────
  // series: {buy, fp, uv, ...} 일자 배열. base/recent: 날짜 인덱스 배열. ref*: 비교 연도 같은 구간
  function avgOf(series, idx, mets) { const s = sumIdx(series, idx, mets), n = idx.length; const o = { days: n }; for (const m of mets) o[m] = n ? s[m] / n : null; return o; }
  function weekdaySplit(ds, idx) {
    const off = [], on = [];
    for (const i of idx) (isOff(ds.dn[i]) ? off : on).push(i);
    return { on, off };
  }
  // 베이스라인을 비교구간의 평일/주말·휴일 구성으로 다시 가중
  function weekdayAdjusted(ds, series, baseIdx, recentIdx, mets) {
    const b = weekdaySplit(ds, baseIdx), r = weekdaySplit(ds, recentIdx);
    const aOn = avgOf(series, b.on, mets), aOff = avgOf(series, b.off, mets), n = recentIdx.length, o = { on: r.on.length, off: r.off.length };
    for (const m of mets) {
      if (!n || aOn[m] == null || aOff[m] == null) { o[m] = null; continue; }
      o[m] = (aOn[m] * r.on.length + aOff[m] * r.off.length) / n;
    }
    return o;
  }
  function baseline(ds, series, { base, recent, refBase, refRecent }) {
    const mets = ['buy', 'fp', 'uv'];
    const B = avgOf(series, base, mets), R = avgOf(series, recent, mets);
    const RB = avgOf(series, refBase, mets), RR = avgOf(series, refRecent, mets);
    const W = weekdayAdjusted(ds, series, base, recent, mets);
    const RW = weekdayAdjusted(ds, series, refBase, refRecent, mets);
    const out = { base: B, recent: R, refBase: RB, refRecent: RR, adj: W, refAdj: RW, rows: {} };
    // buy 구매고객 · fp 첫구매 · share 첫구매 비중(fp/buy) · uv · cr 첫구매 전환율(fp/uv)
    for (const k of ['buy', 'fp', 'share', 'uv', 'cr']) {
      const get = o => k === 'share' ? div(o.fp, o.buy) : k === 'cr' ? div(o.fp, o.uv) : o[k];
      const b = get(B), r = get(R), rb = get(RB), rr = get(RR), w = get(W), rw = get(RW);
      const season = (rb && rr != null) ? rr / rb : null;            // 비교 연도 같은 구간 증감 배수
      const exp = (b != null && season != null) ? b * season : null;  // 단순 기대치
      const seasonAdj = (rw && rr != null) ? rr / rw : null;           // 비교 연도도 요일 보정
      const expAdj = (w != null && seasonAdj != null) ? w * seasonAdj : null;
      out.rows[k] = { base: b, recent: r, chg: pct(r, b), refBase: rb, refRecent: rr, season: season == null ? null : (season - 1) * 100,
        exp, vsExp: pct(r, exp), adjBase: w, expAdj, vsExpAdj: pct(r, expAdj) };
    }
    return out;
  }
  // 날짜를 다른 연도의 같은 월·일로 (2/29 → 2/28)
  function sameDateIn(isoDate, year) {
    let md = isoDate.slice(5);
    if (md === '02-29' && monthDays(year, 2) < 29) md = '02-28';
    return `${year}-${md}`;
  }

  // ── 구성 효과 분해 (shift-share) ───────────────────────────────────
  // items: [{name, b:{buy,fp}, r:{buy,fp}}] (일평균). 비중 R = Σ w_i r_i
  //  구성효과 = Σ (w1-w0) r0 · 내부효과 = Σ w1 (r1-r0)
  function mixDecompose(items) {
    const O0 = items.reduce((a, x) => a + x.b.buy, 0), O1 = items.reduce((a, x) => a + x.r.buy, 0);
    const F0 = items.reduce((a, x) => a + x.b.fp, 0), F1 = items.reduce((a, x) => a + x.r.fp, 0);
    let mix = 0, within = 0;
    const rows = items.map(x => {
      const w0 = O0 ? x.b.buy / O0 : 0, w1 = O1 ? x.r.buy / O1 : 0;
      const r0 = x.b.buy ? x.b.fp / x.b.buy : 0, r1 = x.r.buy ? x.r.fp / x.r.buy : r0;
      const m = (w1 - w0) * r0, wi = w1 * (r1 - r0);
      mix += m; within += wi;
      return { ...x, w0, w1, r0: x.b.buy ? r0 : null, r1: x.r.buy ? x.r.fp / x.r.buy : null, mix: m, within: wi, dfp: x.r.fp - x.b.fp };
    });
    const R0 = div(F0, O0), R1 = div(F1, O1);
    return { rows, R0, R1, mix, within, F0, F1, O0, O1 };
  }

  // ── 백업 합치기 ────────────────────────────────────────────────────
  // 브라우저에 저장된 백업(base)에 새로 만든 백업(add)을 합친다. add 에 있는 날짜는 add 값으로 교체, 나머지는 base 유지
  function mergeBackup(base, add) {
    if (!base || !base.row) return add;
    if (!add || !add.row) return base;
    const B = base.row, A = add.row, addDates = new Set(A.dates);
    const dimKeys = [...new Set([...Object.keys(B.dims), ...Object.keys(A.dims)])];
    const metKeys = [...new Set([...Object.keys(B.f), ...Object.keys(A.f)])].filter(k => k !== 'd' && !dimKeys.includes(k));
    const keepB = B.dates.map(d => !addDates.has(d));
    const dates = [...B.dates.filter((d, i) => keepB[i]), ...A.dates].sort();
    const dIx = new Map(dates.map((d, i) => [d, i]));
    // 차원 값 사전 합치기 (광고유형은 고정 순서)
    const dims = {}, remap = { B: {}, A: {} };
    for (const k of dimKeys) {
      const bv = B.dims[k] || ['-'], av = A.dims[k] || ['-'];
      let vals = [...new Set([...bv, ...av])];
      if (k === 't') vals = TYPES.filter(t => vals.includes(t)).concat(vals.filter(t => !TYPES.includes(t)));
      const ix = new Map(vals.map((v, i) => [v, i]));
      dims[k] = vals; remap.B[k] = bv.map(v => ix.get(v)); remap.A[k] = av.map(v => ix.get(v));
    }
    const f = { d: [] };
    for (const k of [...dimKeys, ...metKeys]) f[k] = [];
    const push = (S, side, keep) => {
      const n = S.f.d.length;
      for (let i = 0; i < n; i++) {
        const di = S.f.d[i];
        if (keep && !keep[di]) continue;
        f.d.push(dIx.get(S.dates[di]));
        for (const k of dimKeys) f[k].push(S.f[k] ? remap[side][k][S.f[k][i]] : remap[side][k][0]);
        for (const m of metKeys) f[m].push(S.f[m] ? S.f[m][i] : 0);
      }
    };
    push(B, 'B', keepB);
    push(A, 'A', null);
    // '데이터 없음' 날짜: base 의 남은 날짜 + add 날짜 (한쪽에 지표 컬럼이 아예 없으면 그쪽 날짜 전부)
    const na = {};
    for (const m of metKeys) {
      const set = new Set();
      if (B.f[m]) (B.na && B.na[m] || []).forEach(d => { if (!addDates.has(d)) set.add(d); });
      else B.dates.forEach((d, i) => { if (keepB[i]) set.add(d); });
      if (A.f[m]) (A.na && A.na[m] || []).forEach(d => set.add(d));
      else A.dates.forEach(d => set.add(d));
      if (set.size) na[m] = [...set].sort();
    }
    const sb = (base.source || {}).row || {}, sa = (add.source || {}).row || {};
    const ub = sb.unclassified || {}, ua = sa.unclassified || {};
    const files = [...(sb.files || []), ...(sa.files || [])];
    const row = {
      files, file: files.slice(-3).join(', '), rows: f.d.length, from: dates[0], to: dates[dates.length - 1], days: dates.length,
      unclassified: { rows: (ub.rows || 0) + (ua.rows || 0), cost: (ub.cost || 0) + (ua.cost || 0), join: (ub.join || 0) + (ua.join || 0),
        adtypes: [...new Set([...(ub.adtypes || []), ...(ua.adtypes || [])])] },
      na: Object.fromEntries(Object.entries(na).map(([m, v]) => [m, { from: v[0], to: v[v.length - 1], days: v.length }])),
    };
    const replaced = B.dates.filter(d => addDates.has(d)).length;
    return {
      format: add.format, version: add.version, created: add.created, lastDate: dates[dates.length - 1],
      source: { ...(base.source || {}), row }, row: { dates, dims, f, n: f.d.length, na },
      merged: { added: A.dates.length - replaced, replaced, kept: dates.length - A.dates.length },
    };
  }

  // ── 표기 ───────────────────────────────────────────────────────────
  // 광고비·거래액: 백만원 소수 1자리(10만원 이하면 만원) · CPA: 만원 · 비율: %
  function fmtNum(v, dp = 1) {
    if (v == null || !isFinite(v)) return '–';
    if (Math.abs(v) < 0.5 * Math.pow(10, -dp)) v = 0;   // -0.0 방지
    return v.toLocaleString('ko-KR', { minimumFractionDigits: dp, maximumFractionDigits: dp });
  }
  function fmt(kind, v, opt = {}) {
    if (v == null || !isFinite(v)) return '–';
    if (kind === 'money') {
      if (Math.abs(v) < 1e5 && v !== 0 && !opt.fixed) return fmtNum(v / 1e4, 1) + '만';
      return fmtNum(v / 1e6, 1);
    }
    if (kind === 'cpa') return fmtNum(v / 1e4, 1);
    if (kind === 'ratio') return fmtNum(v * 100, opt.dp != null ? opt.dp : 1) + '%';
    if (kind === 'count') return fmtNum(v, opt.dp != null ? opt.dp : (Math.abs(v) >= 1000 ? 0 : 1));
    return fmtNum(v, 1);
  }
  // 차트 축 값 (단위 환산만)
  function scaled(kind, v) {
    if (v == null) return null;
    if (kind === 'money') return v / 1e6;
    if (kind === 'cpa') return v / 1e4;
    if (kind === 'ratio') return v * 100;
    return v;
  }
  function unit(kind, mode) {
    if (kind === 'money') return mode === 'avg' ? '백만원/일' : '백만원';
    if (kind === 'cpa') return '만원';
    if (kind === 'ratio') return '%';
    return mode === 'avg' ? '명/일' : '명';
  }

  const api = {
    TYPES, TOTAL, ROW_METS, METRICS, EXTRA, METRIC, HOLIDAYS, EVENTS, WD,
    div, pct, dnum, iso, dow, isOff, monthDays, weekInfo,
    prepare, daily, addSeries, naIn, periods, compareIdx, rangeIdx, sumIdx, value, seriesValues,
    tree, children, keyWhere, avgOf, weekdaySplit, weekdayAdjusted, baseline, sameDateIn, mixDecompose,
    fmt, fmtNum, scaled, unit, mergeBackup,
  };
  root.AdCalc = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : globalThis);
