# -*- coding: utf-8 -*-
"""광고 신규 실적 대시보드 — 원천(로우 시트 xlsb) → 백업 파일(.json.gz)

사용법
    python build_data.py                                  # data/raw/ 의 *.xlsb 전부로 새로 빌드
    python build_data.py --row a.xlsb b.xlsb              # 파일 직접 지정 (여러 개 가능)
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
    '지표_총결제고객수': 'buy',             # 구매고객 (첫구매 비중의 분모)
    '지표_총결제거래액': 'rev',             # 거래액
    '지표_총결제고객수(윈백)': 'wb',        # 윈백 구매고객
}
ROW_DATE = '기간_일자'
TYPES = ['브랜드검색광고', '사이트검색광고', '쇼핑검색광고', 'DA', 'DA(페이먼츠)', '메시지', 'PA']
PAY_MEDIA = ['PAYCO', '토스']

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
    s = s.astype(object).where(s.notna(), '-').astype(str).str.strip()
    s = s.str.replace(r'^(-?\d+)\.0$', r'\1', regex=True)          # xlsb 숫자 셀 114293.0 → 114293
    return s.replace({'': '-', 'nan': '-', 'None': '-'})


def excel_serial_to_date(s: pd.Series) -> pd.Series:
    """기간_일자 → 날짜. 엑셀 일련번호(46296) · 20261001 · 2026-10-01 · 2026.10.01 · 2026/10/01 모두 읽는다"""
    num = pd.to_numeric(s, errors='coerce')
    if num.notna().mean() > 0.9:
        med = num.median()
        if med > 1e7:                                   # 20261001
            return pd.to_datetime(num.astype('Int64').astype(str), format='%Y%m%d', errors='coerce')
        return pd.to_datetime(num, unit='D', origin='1899-12-30').dt.normalize()
    t = s.astype(str).str.strip().str.slice(0, 10).str.replace(r'[./]', '-', regex=True)
    return pd.to_datetime(t, format='%Y-%m-%d', errors='coerce').fillna(pd.to_datetime(t, errors='coerce')).dt.normalize()


CHUNK = 20_000                                     # 큰 원천은 이 행 수씩 나눠 읽고 바로 합산 (메모리 절약)
WANT = [ROW_DATE, *ROW_DIMS, *ROW_METRICS]
DIM_KEYS = list(ROW_DIMS.values())


def sniff_csv(path: Path):
    """csv 인코딩(UTF-8 · CP949 · UTF-16) · 구분자(쉼표 · 탭) · 헤더 — 파일을 한꺼번에 메모리에 올리지 않고 판별"""
    import codecs
    import csv

    with open(path, 'rb') as f:
        bom = f.read(2)
    errors = 'strict'
    if bom in (b'\xff\xfe', b'\xfe\xff'):
        enc = 'utf-16'
    else:
        enc = None
        for cand in ('utf-8-sig', 'cp949'):
            dec = codecs.getincrementaldecoder(cand)('strict')
            try:
                with open(path, 'rb') as f:
                    while block := f.read(1 << 22):     # 4MB 씩 — 글자 중간에서 잘려도 증분 디코더가 이어 붙인다
                        dec.decode(block)
                dec.decode(b'', final=True)
                enc = cand
                break
            except UnicodeDecodeError:
                continue
        if enc is None:
            # 둘 다 엄격하게는 안 맞으면(깨진 글자 일부) 덜 깨지는 쪽으로 읽고 깨진 글자만 대체
            cnt = {}
            for cand in ('utf-8-sig', 'cp949'):
                dec, n = codecs.getincrementaldecoder(cand)('replace'), 0
                with open(path, 'rb') as f:
                    while block := f.read(1 << 22):
                        n += dec.decode(block).count('�')
                cnt[cand] = n + dec.decode(b'', final=True).count('�')
            enc = min(cnt, key=cnt.get)
            errors = 'replace'
            log(f'  ! {path.name}: 인코딩이 일부 깨져 있어 {enc} 로 읽고 깨진 글자 {cnt[enc]}개를 대체했습니다')
    with open(path, 'r', encoding=enc, errors='replace', newline='') as f:
        first = f.readline()
    sep = '\t' if first.count('\t') > first.count(',') else ','
    header = [c.strip() for c in next(csv.reader([first], delimiter=sep))]
    return enc, sep, header, errors


def read_csv_any(path: Path) -> pd.DataFrame:
    """csv 전체를 한 번에 (작은 파일 · 테스트용)"""
    enc, sep, _, errors = sniff_csv(Path(path))
    return pd.read_csv(path, encoding=enc, sep=sep, dtype=str, keep_default_na=False, na_values=[''], encoding_errors=errors)


def _norm(df: pd.DataFrame, name: str) -> pd.DataFrame:
    """원천 한 덩어리 → WANT 컬럼(없으면 빈값)"""
    df.columns = [str(c).strip() for c in df.columns]
    if ROW_DATE not in df.columns and '구분_기간' in df.columns:    # 기간_일자가 없으면 구분_기간(YYYYMMDD)
        df[ROW_DATE] = df['구분_기간']
    if ROW_DATE not in df.columns:
        raise ValueError(f'[로우] {name}: 첫 행에 "{ROW_DATE}" 컬럼이 없습니다 (로우 시트 형식인지 확인)')
    for c in WANT:
        if c not in df.columns:
            df[c] = None
    return df[WANT]


def iter_xlsb(path: Path):
    """pyxlsb 로 시트를 직접 순회 — 필요한 컬럼만, CHUNK 행씩 내보낸다"""
    from pyxlsb import open_workbook

    rows, idx = [], None
    with open_workbook(str(path)) as wb:
        if ROW_SHEET not in wb.sheets:
            raise ValueError(f'[로우] {path.name} 에 "{ROW_SHEET}" 시트가 없습니다. 시트: {wb.sheets}')
        with wb.get_sheet(ROW_SHEET) as sh:
            for n, r in enumerate(sh.rows()):
                vals = [c.v for c in r]
                if idx is None:
                    header = [str(v).strip() if v is not None else '' for v in vals]
                    if ROW_DATE not in header and '구분_기간' in header:
                        header[header.index('구분_기간')] = ROW_DATE
                    if ROW_DATE not in header:
                        raise ValueError(f'[로우] {path.name}: 첫 행에 "{ROW_DATE}" 컬럼이 없습니다 (로우 시트 형식인지 확인)')
                    idx = [header.index(c) if c in header else None for c in WANT]
                    continue
                rows.append(tuple(vals[i] if i is not None and i < len(vals) else None for i in idx))
                if len(rows) >= CHUNK:
                    log(f'  … {n:,}행')
                    yield pd.DataFrame(rows, columns=WANT)
                    rows = []
    if rows or idx is None:
        yield pd.DataFrame(rows, columns=WANT)


def iter_raw(path: Path):
    """원천 파일 → WANT 컬럼 DataFrame 덩어리들 (xlsb · csv 는 CHUNK 행씩)"""
    path = Path(path)
    ext = path.suffix.lower()
    if ext == '.xlsb':
        yield from iter_xlsb(path)
    elif ext == '.pkl':                                   # 테스트용
        yield _norm(pd.read_pickle(path), path.name)
    elif ext in ('.xlsx', '.xlsm'):
        xl = pd.ExcelFile(path)
        yield _norm(xl.parse(ROW_SHEET if ROW_SHEET in xl.sheet_names else xl.sheet_names[0], dtype=str), path.name)
    else:
        enc, sep, header, errors = sniff_csv(path)
        use = [c for c in header if c in WANT or c == '구분_기간']   # 필요한 컬럼만 읽는다
        if ROW_DATE not in use and '구분_기간' not in use:
            raise ValueError(f'[로우] {path.name}: 첫 행에 "{ROW_DATE}" 컬럼이 없습니다 (로우 시트 형식인지 확인)')
        reader = pd.read_csv(path, encoding=enc, sep=sep, usecols=use, dtype=str, keep_default_na=False, na_values=[''],
                             chunksize=CHUNK, encoding_errors=errors)
        for k, chunk in enumerate(reader):
            if k:
                log(f'  … {k * CHUNK:,}행')
            yield _norm(chunk, path.name)


def concat_cat(frames: list[pd.DataFrame]) -> pd.DataFrame:
    """범주형 차원을 유지한 채 이어 붙인다 (범주가 달라도 object 로 풀리지 않게 범주를 합친다)"""
    frames = [f for f in frames if len(f)] or frames[:1]
    if len(frames) == 1:
        return frames[0].reset_index(drop=True)
    cat_cols = [c for c in frames[0].columns if isinstance(frames[0][c].dtype, pd.CategoricalDtype)]
    for c in cat_cols:
        cats = pd.api.types.union_categoricals([f[c] for f in frames]).categories
        for f in frames:
            f[c] = f[c].cat.set_categories(cats)
    return pd.concat(frames, ignore_index=True)


ROW_EXT = ('.xlsb', '.csv', '.xlsx', '.xlsm')


def unpack_upload(name: str, src, out_dir: Path) -> list[Path]:
    """올린 파일 → 디스크의 원천 파일들. zip 은 안의 xlsb · csv · xlsx 를, gz 는 풀어서. 조금씩 복사해 메모리를 아낀다"""
    import shutil
    import zipfile

    out_dir = Path(out_dir)
    lower = name.lower()
    if lower.endswith('.zip'):
        paths = []
        with zipfile.ZipFile(src) as z:
            for i, info in enumerate(m for m in z.infolist() if not m.is_dir()):
                fname = info.filename
                if not info.flag_bits & 0x800:          # 윈도우 압축(CP949 파일명) 깨짐 복구
                    try:
                        fname = fname.encode('cp437').decode('cp949')
                    except (UnicodeEncodeError, UnicodeDecodeError):
                        pass
                base = Path(fname).name
                if base.startswith('.') or Path(base).suffix.lower() not in ROW_EXT:
                    continue
                p = out_dir / f'{i:03d}_{base}' if (out_dir / base).exists() else out_dir / base
                with z.open(info) as r, open(p, 'wb') as w:
                    shutil.copyfileobj(r, w, 1 << 20)
                paths.append(p)
        if not paths:
            raise ValueError(f'{name}: 압축 안에 xlsb · csv · xlsx 파일이 없습니다')
        return sorted(paths)
    if lower.endswith('.gz'):
        p = out_dir / name[:-3]
        with gzip.open(src) as r, open(p, 'wb') as w:
            shutil.copyfileobj(r, w, 1 << 20)
        return [p]
    p = out_dir / name
    with open(p, 'wb') as w:
        if hasattr(src, 'getbuffer'):
            w.write(src.getbuffer())
        else:
            shutil.copyfileobj(src, w, 1 << 20)
    return [p]


def load_row_raw(path: Path, use_cache: bool = True) -> pd.DataFrame:
    """원천 전체를 한 번에 (작은 파일 · 테스트용). 큰 파일은 load_prepped 를 쓴다"""
    return pd.concat(list(iter_raw(path)), ignore_index=True)


def load_prepped(path: Path, use_cache: bool = True) -> tuple[pd.DataFrame, list[str]]:
    """원천 → 정제 · (일자 × 차원) 합산 DataFrame, 원천에 없는 지표 키.
    덩어리마다 바로 합산해 메모리를 원천 크기의 일부만 쓴다. xlsb · csv 는 data/cache/ 에 결과를 캐시"""
    path = Path(path)
    cache = CACHE_DIR / f'{path.name}.v2.pkl'
    cacheable = use_cache and path.suffix.lower() in ('.xlsb', '.csv')
    if cacheable and cache.exists() and cache.stat().st_mtime >= path.stat().st_mtime:
        log(f'[로우] 캐시 사용: {cache.name}')
        c = pd.read_pickle(cache)
        return c['df'], c['missing']
    log(f'[로우] {path.name} 읽는 중 (큰 파일은 몇 분)…')
    mets = list(ROW_METRICS.values())
    seen = {key: False for key in mets}
    parts = []
    for raw in iter_raw(path):
        for src, key in ROW_METRICS.items():
            seen[key] = seen[key] or bool(raw[src].notna().any())
        p = prep_row(raw)
        del raw
        for k in DIM_KEYS:                      # 문자열 차원은 범주형(코드 + 값 목록)으로 — 메모리를 크게 줄인다
            p[k] = p[k].astype('category')
        parts.append(p.groupby(['date', *DIM_KEYS], sort=False, observed=True)[mets].sum().reset_index())
        del p
    df = concat_cat(parts)
    if len(parts) > 1:
        df = df.groupby(['date', *DIM_KEYS], sort=False, observed=True)[mets].sum().reset_index()
    missing = [k for k, v in seen.items() if not v]
    if cacheable:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        pd.to_pickle({'df': df, 'missing': missing}, cache)
    return df, missing


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
    return concat_cat(keep[::-1]) if keep else frames[0].iloc[0:0]


def agg_row(df: pd.DataFrame, dims: list[str]) -> tuple[pd.DataFrame, dict]:
    """분류 → 미분류 제외 → (일자 × 차원) 합계"""
    t = classify(df)
    ok = t.notna().to_numpy()
    un = df.loc[~ok, ['adtype', 'cost', 'join']]
    unc = {'rows': int(len(un)), 'cost': float(un['cost'].sum()), 'join': float(un['join'].sum()),
           'adtypes': sorted(map(str, un['adtype'].unique().tolist()))[:20]}
    del un
    mets = list(ROW_METRICS.values())
    sub = df.loc[ok, ['date', *dims, *mets]]                 # 전체 복사 대신 필요한 열만
    sub.insert(1, 't', pd.Categorical(t[ok]))
    del t
    g = sub.groupby(['date', 't', *dims], sort=False, observed=True)[mets].sum().reset_index()
    del sub
    g = g[(g[mets].abs() > 1e-9).any(axis=1)]
    return g, unc


# ── 인코딩 · 디코딩 ────────────────────────────────────────────────────
def encode(g: pd.DataFrame, dates, dims, mets, fixed: dict | None = None) -> dict:
    """열 단위 + 사전 인덱스로 압축: dims[k] = 값 목록, f[k] = 인덱스 배열 (numpy — to_json 이 그대로 쓴다)"""
    fixed = fixed or {}
    dates = sorted(pd.Timestamp(d) for d in dates)
    dcodes = pd.Categorical(g['date'], categories=dates).codes
    out = {'dates': [d.strftime('%Y-%m-%d') for d in dates], 'dims': {}, 'f': {'d': dcodes.astype(np.int32)}}
    weight = np.abs(g[mets[0]].to_numpy(dtype=float))
    for k in dims:
        c = g[k] if isinstance(g[k].dtype, pd.CategoricalDtype) else g[k].astype('category')
        codes = c.cat.codes.to_numpy()
        cats = [str(v) for v in c.cat.categories]
        present = np.bincount(codes, minlength=len(cats)) > 0
        if k in fixed:
            pos = {v: i for i, v in enumerate(cats)}
            order = [pos[v] for v in fixed[k] if v in pos and present[pos[v]]]
        else:
            sums = np.bincount(codes, weights=weight, minlength=len(cats))
            order = [i for i in np.argsort(-sums, kind='stable') if present[i]]
        newix = np.full(len(cats), -1, dtype=np.int32)
        newix[order] = np.arange(len(order), dtype=np.int32)
        out['dims'][k] = [cats[i] for i in order]
        out['f'][k] = newix[codes]
    for m in mets:
        v = g[m].to_numpy(dtype=float)
        out['f'][m] = np.round(v) if m in MONEY else np.round(v, 3)
    out['n'] = int(len(g))
    return out


def _json_default(o):
    if isinstance(o, np.ndarray):
        return o.tolist()
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.floating):
        return float(o)
    raise TypeError(type(o))


def _arr_json(a: np.ndarray) -> str:
    """숫자 배열 → JSON 배열 문자열 (정수값은 정수로). 한 컬럼씩만 문자열로 만들어 메모리를 아낀다"""
    a = np.asarray(a)
    if a.dtype.kind in 'iu' or (a.dtype.kind == 'f' and np.all(np.isfinite(a)) and np.array_equal(a, np.round(a))):
        return '[' + ','.join(map(str, a.astype(np.int64).tolist())) + ']'
    return '[' + ','.join(str(int(x)) if float(x).is_integer() else repr(float(x)) for x in a.tolist()) + ']'


def to_json(payload: dict) -> str:
    """백업 payload → JSON 문자열 (numpy 배열 포함)"""
    def enc(o):
        if isinstance(o, np.ndarray):
            return _arr_json(o)
        if isinstance(o, dict):
            return '{' + ','.join(json.dumps(str(k), ensure_ascii=False) + ':' + enc(v) for k, v in o.items()) + '}'
        if isinstance(o, (list, tuple)):
            return '[' + ','.join(enc(v) for v in o) + ']'
        return json.dumps(o, ensure_ascii=False, default=_json_default)
    return enc(payload)


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
    frames, files, miss = [], [], []
    for p in row_paths:
        df, ms = load_prepped(p, use_cache=use_cache)
        frames.append(df)
        miss.append(ms)
        files.append(Path(p).name)
        if miss[-1]:
            log(f'  ! {Path(p).name}: 없는 지표 → 그 날짜들은 "데이터 없음" {miss[-1]}')
    new = latest_wins(frames) if frames else None
    mets = list(ROW_METRICS.values())
    na: dict[str, set] = {m: set() for m in mets}     # 지표별 '데이터 없음' 날짜
    seen: set = set()
    for f, ms in zip(reversed(frames), reversed(miss)):   # 날짜마다 실제로 쓰인(뒤) 파일 기준
        own = set(f['date'].unique()) - seen
        seen |= own
        for m in ms:
            na[m] |= own
    info_prev = (base or {}).get('source', {}).get('row', {})
    parts, all_dates = [], set()
    unc = {'rows': 0, 'cost': 0.0, 'join': 0.0, 'adtypes': []}
    new_dates = set(new['date'].unique()) if new is not None else set()
    if base and base.get('row'):
        old, old_dates = decode(base['row'])
        for k in dims:                      # 예전 백업에 없던 차원은 '-'
            if k not in old.columns:
                old[k] = '-'
        keep_dates = {d for d in old_dates if d not in new_dates}
        prev_na = base['row'].get('na', {})
        for m in mets:
            if m not in old.columns:        # 예전 백업에 없던 지표는 그 날짜 전부 '데이터 없음'
                old[m] = 0.0
                na[m] |= keep_dates
            else:
                na[m] |= {pd.Timestamp(d) for d in prev_na.get(m, [])} & keep_dates
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
    g = g.groupby(['date', 't', *dims], sort=False, observed=True)[mets].sum().reset_index()
    dates = sorted(all_dates)
    sec = encode(g, dates, ['t', *dims], mets, fixed={'t': TYPES})
    sec['na'] = {m: sorted(d.strftime('%Y-%m-%d') for d in ds) for m, ds in na.items() if ds}
    info = {'files': (info_prev.get('files', []) if base else []) + files,
            'rows': int(len(g)), 'from': dates[0].strftime('%Y-%m-%d'), 'to': dates[-1].strftime('%Y-%m-%d'),
            'days': len(dates), 'unclassified': unc,
            'na': {m: {'from': v[0], 'to': v[-1], 'days': len(v)} for m, v in sec['na'].items()}}
    info['file'] = ', '.join(info['files'][-3:])
    log(f'[로우] 집계 {len(g):,}행 · {len(dates)}일 ({info["from"]} ~ {info["to"]})')
    return sec, info


def build(row_paths=(), base: dict | None = None, lite: bool = False, use_cache: bool = True) -> dict:
    """로우 원천 파일들(+기존 백업) → 백업 payload. 같은 날짜는 새 파일이 기존 백업을 덮어쓴다"""
    row_paths = list(row_paths or [])
    payload = {'format': FORMAT, 'version': VERSION, 'created': dt.datetime.now().isoformat(timespec='seconds'), 'source': {}}
    if row_paths or (base and base.get('row')):
        sec, info = build_row_section(row_paths, base, lite, use_cache)
        if sec:
            payload['row'], payload['source']['row'] = sec, info
    if not payload['source']:
        raise ValueError('읽은 원천이 없습니다')
    payload['lastDate'] = payload['source']['row']['to']
    return payload


def backup_bytes(payload: dict) -> bytes:
    raw = to_json(payload).encode('utf-8')
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
    ap.add_argument('--base', type=Path, help='이어 붙일 기존 백업(.json.gz)')
    ap.add_argument('--lite', action='store_true', help='하위캠페인 · 브랜드/기획전 · 디바이스 차원 제외')
    ap.add_argument('--out-stamp', help='파일명 날짜 (기본: 로우 최신일)')
    a = ap.parse_args(argv)

    rows = a.row if a.row is not None else by_mtime(RAW_DIR.glob('*.xlsb'))
    base = read_backup(a.base) if a.base else None
    if not rows and not base:
        sys.exit('원천 파일이 없습니다. data/raw/ 에 로우 시트 xlsb 를 넣거나 --row 로 지정하세요.')
    log(f'로우: {[Path(p).name for p in rows] or "(없음)"}' + (f' / 기존 백업: {a.base.name}' if base else ''))
    try:
        payload = build(rows, base=base, lite=a.lite)
    except ValueError as e:
        sys.exit(str(e))
    write_backup(payload, a.out_stamp)


if __name__ == '__main__':
    main()
