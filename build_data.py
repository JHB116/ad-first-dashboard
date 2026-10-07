# -*- coding: utf-8 -*-
"""광고 신규 실적 대시보드 — 원천(로우 시트 xlsb · AF 결제 csv) → 백업 파일(.json.gz)

사용법
    python build_data.py                                  # data/raw/ 의 *.xlsb · Sheet_1*.csv 전부로 새로 빌드
    python build_data.py --row a.xlsb b.xlsb --af x.csv   # 파일 직접 지정 (여러 개 가능)
    python build_data.py --base 기존백업.json.gz --row 1001.xlsb   # 기존 백업에 새 날짜 추가 · 같은 날짜 교체
    python build_data.py --lite                           # 하위캠페인 · 브랜드/기획전 · 디바이스 차원 빼고 가볍게

결과: backup/광고신규대시보드_백업_YYYYMMDD.json.gz  → 대시보드 화면에 끌어다 놓아 연다.
Streamlit 화면의 '원천 파일로 백업 만들기'도 같은 함수(build)를 쓴다.

- 로우 원천: 시트 '로우'(첫 행 헤더). 일일보고서 xlsb 전체든, 로우 시트만 뽑은 xlsb 든 같다.
- 같은 날짜가 여러 파일에 있으면 뒤(수정시각이 늦은) 파일 값을 쓴다. 기존 백업보다 새 파일이 우선.
- 큰 xlsb 는 처음 1회만 읽고 data/cache/ 에 pickle 로 저장한다(원본 수정시각이 같으면 캐시 사용).
- 집계 규칙은 docs/METRICS.md 와 같다. 바꾸면 문서와 tests/ 도 함께 고친다.
"""
from __future__ import annotations

import argparse
import datetime as dt
import gzip
import io
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
RAW_DIR = ROOT / 'data' / 'raw'
CACHE_DIR = ROOT / 'data' / 'cache'
OUT_DIR = ROOT / 'backup'

FORMAT = 'ad-new-dashboard-backup'
VERSION = 1

# ── 1-A. 로우 시트 ─────────────────────────────────────────────────────
ROW_SHEET = '로우'
# 원천 컬럼 → 백업 키
ROW_DIMS = {
    '구분_광고유형': 'adtype',
    '구분_채널': 'ch',
    '구분_매체명': 'md',
    '구분_비용출처': 'src',
    '구분_캠페인': 'camp',
    '구분_하위캠페인': 'sub',
    '구분_브랜드/기획전': 'bp',
    '구분_디바이스': 'dev',
}
LITE_DROP = ['sub', 'bp', 'dev']   # --lite 에서 빼는 차원
ROW_METRICS = {
    '지표_광고비': 'cost',
    '지표_UV(전체)': 'uv',
    '지표_가입회원': 'join',
    '지표_총결제고객수(첫구매)': 'fp',      # 첫구매 (최종 정의: 총결제)
    '지표_총결제거래액(첫구매)': 'fpr',     # 첫구매거래액
    '지표_순결제고객수(첫구매)': 'fpn',     # 일보고서 시트 '첫구매수' (참고)
    '지표_당년신규순결제고객수': 'nb',      # 신규구매자
    '지표_당년신규순결제거래액': 'nrev',    # 신규거래액
}
ROW_DATE = '기간_일자'
TYPES = ['브랜드검색광고', '사이트검색광고', '쇼핑검색광고', 'DA', 'DA(페이먼츠)', '메시지', 'PA']
PAY_MEDIA = ['PAYCO', '토스']

# ── 1-B. AF 결제 데이터 ────────────────────────────────────────────────
AF_COLS = {
    '결제_일자': 'date',
    'AF중분류명': 'mid',
    'AF소분류명': 'sub',
    'AF브랜드': 'brand',
    'AF캠페인상세': 'camp',
    '주문고객수': 'ord',
    '거래액': 'rev',
    '신규고객수': 'new',
    '신규거래액': 'nrev',
    '첫구매고객수': 'fp',
    '첫구매거래액': 'fpr',
}
AF_DIMS = ['mid', 'sub', 'brand', 'camp']
AF_METRICS = ['ord', 'rev', 'new', 'nrev', 'fp', 'fpr']
MONEY = {'cost', 'fpr', 'nrev', 'rev'}


def log(*a):
    print(*a, flush=True)


# ── 공통 ───────────────────────────────────────────────────────────────
def to_num(s: pd.Series) -> pd.Series:
    """' - ' · '########' 같은 문자열 · 천단위 콤마가 섞인 숫자 컬럼 정제"""
    if s.dtype.kind in 'if':
        return s.fillna(0).astype(float)
    s = s.astype(str).str.replace(',', '', regex=False).str.strip()
    return pd.to_numeric(s, errors='coerce').fillna(0).astype(float)


def clean_dim(s: pd.Series) -> pd.Series:
    s = s.astype(object).where(s.notna(), '-')
    s = s.map(lambda v: (str(int(v)) if isinstance(v, float) and v.is_integer() else str(v)).strip())
    return s.replace({'': '-', 'nan': '-', 'None': '-'})


def excel_serial_to_date(s: pd.Series) -> pd.Series:
    num = pd.to_numeric(s, errors='coerce')
    if num.notna().mean() > 0.9:
        return pd.to_datetime(num, unit='D', origin='1899-12-30').dt.normalize()
    return pd.to_datetime(s.astype(str).str.strip(), errors='coerce').dt.normalize()


def name_of(src) -> str:
    return getattr(src, 'name', None) or str(src)


# ── 로우 읽기 ──────────────────────────────────────────────────────────
def read_xlsb_sheet(src, sheet: str, want: list[str]) -> pd.DataFrame:
    """pyxlsb 로 시트를 직접 순회 — 필요한 컬럼만 담는다 (read_excel 보다 훨씬 빠르다)"""
    from pyxlsb import open_workbook

    rows, idx, header = [], None, None
    with open_workbook(str(src)) as wb:
        if sheet not in wb.sheets:
            raise ValueError(f'[로우] {name_of(src)} 에 "{sheet}" 시트가 없습니다. 시트: {wb.sheets}')
        with wb.get_sheet(sheet) as sh:
            for n, r in enumerate(sh.rows()):
                vals = [c.v for c in r]
                if header is None:
                    header = [str(v).strip() if v is not None else '' for v in vals]
                    idx = [header.index(c) if c in header else None for c in want]
                    missing = [c for c, i in zip(want, idx) if i is None]
                    if ROW_DATE in missing:
                        raise ValueError(f'[로우] {name_of(src)}: 첫 행에 "{ROW_DATE}" 컬럼이 없습니다 (로우 시트 형식인지 확인)')
                    if missing:
                        log(f'  ! {name_of(src)}: 없는 컬럼(0/빈값으로 채움) {missing}')
                    continue
                rows.append(tuple(vals[i] if i is not None and i < len(vals) else None for i in idx))
                if n % 200000 == 0:
                    log(f'  … {n:,}행')
    return pd.DataFrame(rows, columns=want)


def load_row_raw(path: Path, use_cache: bool = True) -> pd.DataFrame:
    want = [ROW_DATE, *ROW_DIMS, *ROW_METRICS]
    path = Path(path)
    ext = path.suffix.lower()
    if ext == '.xlsb':
        cache = CACHE_DIR / f'{path.stem}.pkl'
        if use_cache and cache.exists() and cache.stat().st_mtime >= path.stat().st_mtime:
            df = pd.read_pickle(cache)
            if list(df.columns) == want:
                log(f'[로우] 캐시 사용: {cache.name}')
                return df
        log(f'[로우] {path.name} 읽는 중 (큰 파일은 2~3분)…')
        df = read_xlsb_sheet(path, ROW_SHEET, want)
        if use_cache:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            df.to_pickle(cache)
        return df
    # 테스트 · 대체 입력: csv / xlsx / pkl
    if ext == '.pkl':
        df = pd.read_pickle(path)
    elif ext in ('.xlsx', '.xlsm'):
        df = pd.read_excel(path, sheet_name=ROW_SHEET)
    else:
        df = pd.read_csv(path, encoding='utf-8-sig')
    for c in want:
        if c not in df.columns:
            df[c] = None
    return df[want]


def classify(df: pd.DataFrame) -> pd.Series:
    """광고유형 분류 — 일보고서 시트와 일치 확인된 규칙 (docs/METRICS.md)"""
    t, ch, md = df['adtype'], df['ch'], df['md']
    pay = (t == 'DA') & (md.isin(PAY_MEDIA) | (ch == '링크사'))
    out = pd.Series(None, index=df.index, dtype=object)
    out[(t == 'SA') & (ch == '브랜드검색')] = '브랜드검색광고'
    out[(t == 'SA') & ch.isin(['사이트검색광고', '사이트검색'])] = '사이트검색광고'
    out[(t == 'SA') & (ch == '쇼핑검색광고')] = '쇼핑검색광고'
    out[(t == 'DA') & ~pay] = 'DA'
    out[pay] = 'DA(페이먼츠)'
    out[t == 'Message'] = '메시지'
    out[t == 'PA'] = 'PA'
    return out


def prep_row(raw: pd.DataFrame) -> pd.DataFrame:
    df = pd.DataFrame({'date': excel_serial_to_date(raw[ROW_DATE])})
    for src, key in ROW_DIMS.items():
        df[key] = clean_dim(raw[src])
    for src, key in ROW_METRICS.items():
        df[key] = to_num(raw[src])
    bad = df['date'].isna().sum()
    if bad:
        log(f'  ! 날짜를 읽지 못한 행 {bad:,}개 제외')
    return df[df['date'].notna()].reset_index(drop=True)


def latest_wins(frames: list[pd.DataFrame]) -> pd.DataFrame:
    """같은 날짜가 여러 프레임에 있으면 뒤 프레임 것만 남긴다"""
    seen: set = set()
    keep = []
    for f in reversed(frames):
        dates = set(f['date'].unique())
        part = f[~f['date'].isin(seen)]
        if len(part):
            keep.append(part)
        seen |= dates
    return pd.concat(keep[::-1], ignore_index=True) if keep else frames[0].iloc[0:0]


def agg_row(df: pd.DataFrame, dims: list[str]) -> tuple[pd.DataFrame, dict]:
    """분류 → 미분류 제외 → (일자 × 차원) 합계"""
    df = df.copy()
    df['t'] = classify(df)
    un = df[df['t'].isna()]
    unc = {'rows': int(len(un)), 'cost': float(un['cost'].sum()), 'join': float(un['join'].sum()),
           'adtypes': sorted(un['adtype'].unique().tolist())[:20]}
    df = df[df['t'].notna()]
    mets = list(ROW_METRICS.values())
    g = df.groupby(['date', 't', *dims], sort=False, observed=True)[mets].sum().reset_index()
    g = g[(g[mets].abs() > 1e-9).any(axis=1)]
    return g, unc


# ── AF 읽기 ────────────────────────────────────────────────────────────
def read_af_file(path) -> pd.DataFrame:
    path = Path(path)
    for enc in ('utf-16', 'utf-8-sig', 'cp949'):
        try:
            df = pd.read_csv(path, encoding=enc, sep='\t', thousands=',', dtype=str)
            if len(df.columns) > 3:
                break
        except (UnicodeError, UnicodeDecodeError, pd.errors.ParserError):
            continue
    else:
        raise ValueError(f'[AF] {path.name} 을 읽지 못했습니다 (UTF-16 탭 구분 csv 여야 합니다)')
    df.columns = [c.strip() for c in df.columns]
    missing = [c for c in AF_COLS if c not in df.columns]
    if '결제_일자' in missing or '첫구매고객수' in missing:
        raise ValueError(f'[AF] {path.name}: 필수 컬럼 없음 {missing}')
    if missing:
        log(f'  ! {path.name}: 없는 컬럼(0/빈값) {missing}')
    out = pd.DataFrame({'date': pd.to_datetime(df['결제_일자'].astype(str).str.strip().str[:8], format='%Y%m%d', errors='coerce')})
    for src, key in AF_COLS.items():
        if key == 'date':
            continue
        col = df[src] if src in df.columns else pd.Series(None, index=df.index)
        out[key] = to_num(col) if key in AF_METRICS else clean_dim(col)
    out = out[out['date'].notna()]
    out['_file'] = path.name
    return out


def af_sanity(df: pd.DataFrame) -> list[str]:
    """잘못 뽑힌 파일(하루치만 · 첫구매 비정상) 경고"""
    warns = []
    for f, g in df.groupby('_file', sort=False):
        days = g['date'].nunique()
        d = g.groupby('date')[['ord', 'fp']].sum()
        ratio = (d['fp'] / d['ord'].where(d['ord'] > 0)).dropna()
        med = ratio.median() if len(ratio) else float('nan')
        log(f'  {f}: {g["date"].min():%Y-%m-%d} ~ {g["date"].max():%Y-%m-%d}, {days}일, 첫구매/주문 중앙값 {med:.3f}')
        if days <= 2:
            warns.append(f'{f}: 데이터가 {days}일뿐입니다 — 기간을 잘못 뽑았는지 확인하세요')
        low = ratio[ratio < med * 0.4] if med == med else ratio.iloc[0:0]
        low = low[low.index != d.index.max()]   # 최신일은 원래 미확정
        if len(low):
            warns.append(f'{f}: 첫구매/주문 비중이 비정상적으로 낮은 날 {len(low)}일 (예: {", ".join(x.strftime("%m/%d") for x in low.index[:5])})')
    return warns


# ── 인코딩 · 디코딩 ────────────────────────────────────────────────────
def encode(g: pd.DataFrame, dates, dims, mets, fixed: dict | None = None) -> dict:
    """열 단위 + 사전 인덱스로 압축: dims[k] = 값 목록, f[k] = 인덱스 배열"""
    fixed = fixed or {}
    dates = sorted(pd.Timestamp(d) for d in dates)
    date_ix = {d: i for i, d in enumerate(dates)}
    out = {'dates': [d.strftime('%Y-%m-%d') for d in dates], 'dims': {}, 'f': {'d': g['date'].map(date_ix).astype(int).tolist()}}
    for k in dims:
        if k in fixed:
            vals = [v for v in fixed[k] if v in set(g[k])]
        else:
            vals = g.groupby(k)[mets[0]].apply(lambda s: s.abs().sum()).sort_values(ascending=False).index.tolist()
        ix = {v: i for i, v in enumerate(vals)}
        out['dims'][k] = vals
        out['f'][k] = g[k].map(ix).astype(int).tolist()
    for m in mets:
        v = g[m].to_numpy(dtype=float)
        v = np.round(v) if m in MONEY else np.round(v, 3)
        out['f'][m] = [int(x) if float(x).is_integer() else float(x) for x in v]
    out['n'] = int(len(g))
    return out


def decode(sec: dict) -> tuple[pd.DataFrame, list]:
    """백업 섹션 → (집계 DataFrame, 날짜 목록)"""
    dates = [pd.Timestamp(d) for d in sec['dates']]
    df = pd.DataFrame({k: v for k, v in sec['f'].items()})
    df['date'] = pd.Series(dates, dtype='datetime64[ns]').iloc[df.pop('d')].to_numpy()
    for k, vals in sec['dims'].items():
        arr = np.array(vals, dtype=object)
        df[k] = arr[df[k].to_numpy()] if len(arr) else []
    return df, dates


def read_backup(src) -> dict:
    raw = src.read() if hasattr(src, 'read') else Path(src).read_bytes()
    if raw[:2] == b'\x1f\x8b':
        raw = gzip.decompress(raw)
    p = json.loads(raw.decode('utf-8'))
    if p.get('format') != FORMAT:
        raise ValueError('광고 신규 실적 대시보드 백업이 아닙니다')
    return p


# ── 빌드 ───────────────────────────────────────────────────────────────
def build_row_section(row_paths: list, base: dict | None, lite: bool, use_cache: bool) -> tuple[dict, dict]:
    dims = [k for k in ROW_DIMS.values() if k != 'adtype' and not (lite and k in LITE_DROP)]
    frames, files = [], []
    for p in row_paths:
        frames.append(prep_row(load_row_raw(p, use_cache=use_cache)))
        files.append(Path(p).name)
    new = latest_wins(frames) if frames else None
    info_prev = (base or {}).get('source', {}).get('row', {})
    parts, all_dates = [], set()
    unc = {'rows': 0, 'cost': 0.0, 'join': 0.0, 'adtypes': []}
    new_dates = set(new['date'].unique()) if new is not None else set()
    if base and base.get('row'):
        old, old_dates = decode(base['row'])
        for k in dims:                      # 예전 백업에 없던 차원은 '-'
            if k not in old.columns:
                old[k] = '-'
        old = old[~old['date'].isin(new_dates)]
        parts.append(old[['date', 't', *dims, *ROW_METRICS.values()]])
        all_dates |= {d for d in old_dates if d not in new_dates}
        pu = info_prev.get('unclassified') or {}
        unc = {'rows': pu.get('rows', 0), 'cost': pu.get('cost', 0.0), 'join': pu.get('join', 0.0), 'adtypes': pu.get('adtypes', [])}
        log(f'[로우] 기존 백업 {len(old_dates)}일 중 {len(old_dates) - len(set(old_dates) & new_dates)}일 유지')
    if new is not None and len(new):
        g, u = agg_row(new, dims)
        parts.append(g)
        all_dates |= new_dates
        unc = {'rows': unc['rows'] + u['rows'], 'cost': unc['cost'] + u['cost'], 'join': unc['join'] + u['join'],
               'adtypes': sorted(set(unc['adtypes']) | set(u['adtypes']))[:20]}
        log(f'[로우] 새 원천 {len(new):,}행 · {len(new_dates)}일 ({min(new_dates):%Y-%m-%d} ~ {max(new_dates):%Y-%m-%d})')
    if not parts:
        return None, {}
    g = pd.concat(parts, ignore_index=True)
    mets = list(ROW_METRICS.values())
    g = g.groupby(['date', 't', *dims], sort=False, observed=True)[mets].sum().reset_index()
    dates = sorted(all_dates)
    sec = encode(g, dates, ['t', *dims], mets, fixed={'t': TYPES})
    info = {'files': (info_prev.get('files', []) if base else []) + files,
            'rows': int(len(g)), 'from': dates[0].strftime('%Y-%m-%d'), 'to': dates[-1].strftime('%Y-%m-%d'),
            'days': len(dates), 'unclassified': unc}
    info['file'] = ', '.join(info['files'][-3:])
    log(f'[로우] 집계 {len(g):,}행 · {len(dates)}일 ({info["from"]} ~ {info["to"]})')
    return sec, info


def build_af_section(af_paths: list, base: dict | None) -> tuple[dict, dict]:
    frames = [read_af_file(p) for p in af_paths]
    new = pd.concat(frames, ignore_index=True) if frames else None
    warns = af_sanity(new) if new is not None else []
    if new is not None:
        # 같은 날짜가 여러 파일에 있으면 뒤 파일
        new = latest_wins([f for _, f in new.groupby('_file', sort=False)]) if new['_file'].nunique() > 1 else new
    parts, all_dates = [], set()
    new_dates = set(new['date'].unique()) if new is not None else set()
    info_prev = (base or {}).get('source', {}).get('af', {})
    if base and base.get('af'):
        old, old_dates = decode(base['af'])
        old = old[~old['date'].isin(new_dates)]
        parts.append(old[['date', *AF_DIMS, *AF_METRICS]])
        all_dates |= {d for d in old_dates if d not in new_dates}
    if new is not None and len(new):
        parts.append(new.groupby(['date', *AF_DIMS], sort=False)[AF_METRICS].sum().reset_index())
        all_dates |= new_dates
    if not parts:
        return None, {}
    g = pd.concat(parts, ignore_index=True).groupby(['date', *AF_DIMS], sort=False)[AF_METRICS].sum().reset_index()
    g = g[(g[AF_METRICS].abs() > 1e-9).any(axis=1)]
    dates = sorted(all_dates)
    last = dates[-1]
    last_d = g[g['date'] == last][['ord', 'fp']].sum()
    info = {
        'files': (info_prev.get('files', []) if base else []) + [Path(p).name for p in af_paths],
        'rows': int(len(g)), 'from': dates[0].strftime('%Y-%m-%d'), 'to': last.strftime('%Y-%m-%d'), 'days': len(dates),
        'years': {str(y): int(n) for y, n in pd.Series(dates).dt.year.value_counts().sort_index().items()},
        'lastDay': {'ord': float(last_d['ord']), 'fp': float(last_d['fp'])},
        'warnings': warns or (info_prev.get('warnings', []) if not af_paths else []),
    }
    log(f'[AF] 집계 {len(g):,}행 ({info["from"]} ~ {info["to"]}, {len(dates)}일, 연도별 {info["years"]})')
    for w in warns:
        log('  ! ' + w)
    return encode(g, dates, AF_DIMS, AF_METRICS), info


def build(row_paths=(), af_paths=(), base: dict | None = None, lite: bool = False, use_cache: bool = True) -> dict:
    """원천 파일들(+기존 백업) → 백업 payload. 같은 날짜는 새 파일이 기존 백업을 덮어쓴다"""
    row_paths, af_paths = list(row_paths or []), list(af_paths or [])
    payload = {'format': FORMAT, 'version': VERSION, 'created': dt.datetime.now().isoformat(timespec='seconds'), 'source': {}}
    if row_paths or (base and base.get('row')):
        sec, info = build_row_section(row_paths, base, lite, use_cache)
        if sec:
            payload['row'], payload['source']['row'] = sec, info
    if af_paths or (base and base.get('af')):
        sec, info = build_af_section(af_paths, base)
        if sec:
            payload['af'], payload['source']['af'] = sec, info
    if not payload['source']:
        raise ValueError('읽은 원천이 없습니다')
    payload['lastDate'] = payload['source'].get('row', payload['source'].get('af', {})).get('to')
    return payload


def backup_bytes(payload: dict) -> bytes:
    raw = json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode='wb', compresslevel=6, mtime=0) as f:
        f.write(raw)
    return buf.getvalue()


def backup_name(payload: dict) -> str:
    return f'광고신규대시보드_백업_{(payload.get("lastDate") or dt.date.today().isoformat()).replace("-", "")}.json.gz'


def write_backup(payload: dict, stamp: str | None = None) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / (f'광고신규대시보드_백업_{stamp}.json.gz' if stamp else backup_name(payload))
    data = backup_bytes(payload)
    out.write_bytes(data)
    log(f'[저장] {out.relative_to(ROOT) if out.is_relative_to(ROOT) else out}  ({len(data)/1e6:.1f}MB)')
    return out


def by_mtime(paths):
    return sorted(paths, key=lambda p: Path(p).stat().st_mtime)


def main(argv=None):
    ap = argparse.ArgumentParser(description='광고 신규 실적 대시보드 백업 만들기')
    ap.add_argument('--row', type=Path, nargs='*', help='로우 시트 xlsb 들 (기본: data/raw 의 *.xlsb 전부, 수정시각 순)')
    ap.add_argument('--af', type=Path, nargs='*', help='AF 결제 csv 들 (기본: data/raw 의 Sheet_1*.csv 전부)')
    ap.add_argument('--base', type=Path, help='이어 붙일 기존 백업(.json.gz)')
    ap.add_argument('--lite', action='store_true', help='하위캠페인 · 브랜드/기획전 · 디바이스 차원 제외')
    ap.add_argument('--out-stamp', help='파일명 날짜 (기본: 로우 최신일)')
    a = ap.parse_args(argv)

    rows = a.row if a.row is not None else by_mtime(RAW_DIR.glob('*.xlsb'))
    afs = a.af if a.af is not None else by_mtime(RAW_DIR.glob('Sheet_1*.csv'))
    base = read_backup(a.base) if a.base else None
    if not rows and not afs and not base:
        sys.exit('원천 파일이 없습니다. data/raw/ 에 xlsb · AF csv 를 넣거나 --row/--af 로 지정하세요.')
    log(f'로우: {[Path(p).name for p in rows] or "(없음)"} / AF: {[Path(p).name for p in afs] or "(없음)"}' + (f' / 기존 백업: {a.base.name}' if base else ''))
    try:
        payload = build(rows, afs, base=base, lite=a.lite)
    except ValueError as e:
        sys.exit(str(e))
    write_backup(payload, a.out_stamp)


if __name__ == '__main__':
    main()
