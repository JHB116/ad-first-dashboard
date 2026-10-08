# -*- coding: utf-8 -*-
"""build_data.py — 가짜 원천으로 분류 · 집계 · 이어 붙이기를 검증 (모든 숫자는 임의값)"""
import gzip
import json

import numpy as np
import pandas as pd
import pytest

import build_data as bd
import make_sample as ms


@pytest.fixture(scope='module')
def sample(tmp_path_factory):
    out = tmp_path_factory.mktemp('sample')
    ms.main(out)
    return out


@pytest.fixture(scope='module')
def payload(sample):
    return bd.build([sample / 'sample_row.pkl'])


def frame(sec):
    return bd.decode(sec)[0]


def test_classify_rules():
    df = pd.DataFrame({
        'adtype': ['SA', 'SA', 'SA', 'SA', 'DA', 'DA', 'DA', 'DA', 'DA', 'Message', 'PA', 'APP', 'viral', '-'],
        'ch': ['브랜드검색', '사이트검색광고', '사이트검색', '쇼핑검색광고', '포탈', '네트워크배너', '생활밀착형앱', '링크사', 'SNS', 'DB발송', '상품피드', '-', '-', '-'],
        'md': ['네이버', '네이버', '구글', '네이버', '카카오', 'PAYCO', '토스', '링크프라이스', 'FB/IG', '카카오', '크리테오', '-', '-', '-'],
    })
    got = [None if pd.isna(v) else v for v in bd.classify(df)]
    assert got == ['브랜드검색광고', '사이트검색광고', '사이트검색광고', '쇼핑검색광고', 'DA', 'DA(페이먼츠)', 'DA(페이먼츠)',
                   'DA(페이먼츠)', 'DA', '메시지', 'PA', None, None, None]


def test_to_num_cleans_strings():
    s = pd.Series([' - ', '########', '1,234', 5, None, '-3.5'])
    assert bd.to_num(s).tolist() == [0, 0, 1234, 5, 0, -3.5]


def test_row_totals_match_raw(sample, payload):
    raw = bd.prep_row(bd.load_row_raw(sample / 'sample_row.pkl'))
    raw['t'] = bd.classify(raw)
    raw = raw[raw['t'].notna()]
    got = frame(payload['row'])
    for m in ['cost', 'join', 'fp', 'fpr', 'nb', 'nrev', 'fpn', 'buy', 'rev', 'wb', 'uv']:
        assert np.allclose(raw.groupby('t')[m].sum().sort_index(), got.groupby('t')[m].sum().sort_index(), atol=0.5), m
    # 차원별 합도 보존 (브랜드/기획전 · 디바이스)
    for k in ['bp', 'dev', 'camp']:
        assert np.allclose(raw.groupby(k)['cost'].sum().sort_index(), got.groupby(k)['cost'].sum().sort_index(), atol=0.5), k
    assert (got['cost'] < 0).any()                       # 음수 조정분 합산
    assert payload['row']['dims']['t'] == bd.TYPES       # 유형 순서 고정
    assert set(payload['row']['dims']['dev']) == {'PC', 'Mobile', 'APP'}


def test_row_source_info(payload):
    src = payload['source']['row']
    assert (src['from'], src['to'], src['days']) == ('2025-01-01', '2026-09-29', 637)
    assert src['unclassified']['rows'] > 0 and src['unclassified']['adtypes'] == ['APP']


def test_lite_drops_dims(sample):
    p = bd.build([sample / 'sample_row.pkl'], lite=True)
    assert set(p['row']['dims']) == {'t', 'ch', 'md', 'src', 'camp'}


def test_append_to_base_replaces_overlap(sample, payload):
    # 기존 백업(~9/29) + 추가 파일(9/29~10/4): 9/29 는 새 값으로 교체, 나머지 날짜는 유지
    p2 = bd.build([sample / 'sample_row_1001.pkl'], base=json.loads(bd.to_json(payload)))
    assert p2['source']['row']['to'] == '2026-10-04' and p2['source']['row']['days'] == 642
    old, new = frame(payload['row']), frame(p2['row'])
    add = bd.prep_row(bd.load_row_raw(sample / 'sample_row_1001.pkl'))
    add['t'] = bd.classify(add)
    add = add[add['t'].notna()]
    d = pd.Timestamp('2026-09-29')
    assert new[new['date'] == d]['cost'].sum() == pytest.approx(add[add['date'] == d]['cost'].sum(), abs=1)
    d = pd.Timestamp('2026-09-28')
    assert new[new['date'] == d]['cost'].sum() == pytest.approx(old[old['date'] == d]['cost'].sum(), abs=1)
    assert p2['source']['row']['files'] == ['sample_row.pkl', 'sample_row_1001.pkl']


def test_multiple_row_files_later_wins(sample):
    p = bd.build([sample / 'sample_row.pkl', sample / 'sample_row_1001.pkl'])
    p_rev = bd.build([sample / 'sample_row_1001.pkl', sample / 'sample_row.pkl'])
    a, b = frame(p['row']), frame(p_rev['row'])
    d = pd.Timestamp('2026-09-29')
    assert a[a['date'] == d]['cost'].sum() != pytest.approx(b[b['date'] == d]['cost'].sum())


def test_old_backup_without_new_metrics(sample, payload):
    # 구매고객(buy) 등이 없던 예전 백업에 이어 붙이면, 예전 날짜는 그 지표가 '데이터 없음'
    old = json.loads(bd.to_json(payload))
    for m in ('buy', 'rev', 'wb'):
        del old['row']['f'][m]
    p2 = bd.build([sample / 'sample_row_1001.pkl'], base=old)
    na = p2['row']['na']
    assert set(na) == {'buy', 'rev', 'wb'}
    assert na['buy'][0] == '2025-01-01' and na['buy'][-1] == '2026-09-28'
    f = frame(p2['row'])
    assert f[f['date'] >= '2026-09-29']['buy'].sum() > 0


def test_2024_file_missing_columns_marked_na(sample):
    p = bd.build([sample / 'sample_row_2024.pkl', sample / 'sample_row.pkl'])
    na = p['row']['na']
    assert set(na) == {'fpn', 'nb', 'nrev', 'wb'}
    for m in na:
        assert na[m][0] == '2024-01-01' and na[m][-1] == '2024-12-31' and len(na[m]) == 366
    assert p['source']['row']['na']['nb'] == {'from': '2024-01-01', 'to': '2024-12-31', 'days': 366}
    assert p['source']['row']['from'] == '2024-01-01'
    # 있는 지표(첫구매 · 구매고객)는 2024년도 들어온다
    f = frame(p['row'])
    y24 = f[f['date'] < '2025-01-01']
    assert y24['fp'].sum() > 0 and y24['buy'].sum() > 0
    # 이어 붙여도 '데이터 없음' 날짜가 유지된다
    p2 = bd.build([sample / 'sample_row_1001.pkl'], base=json.loads(bd.to_json(p)))
    assert p2['row']['na']['nb'] == na['nb']


def test_backup_roundtrip(payload, tmp_path, monkeypatch):
    monkeypatch.setattr(bd, 'OUT_DIR', tmp_path)
    p = bd.write_backup(payload)
    assert p.name == '광고신규대시보드_백업_20260929.json.gz'
    back = bd.read_backup(p)
    assert back['format'] == 'ad-new-dashboard-backup' and back['version'] == 1
    assert back['row']['n'] == len(back['row']['f']['d'])
    with gzip.open(p) as f:
        assert json.load(f)['lastDate'] == '2026-09-29'


def test_missing_date_column_is_error(tmp_path):
    p = tmp_path / 'bad.csv'
    pd.DataFrame({'a': [1]}).to_csv(p, index=False)
    with pytest.raises(Exception):
        bd.build([p])


@pytest.mark.parametrize('enc,sep,fmt', [('utf-8-sig', ',', '%Y-%m-%d'), ('cp949', '\t', '%Y.%m.%d'),
                                         ('utf-8-sig', ',', '%Y%m%d'), ('utf-16', '\t', None)])
def test_csv_row_file(tmp_path, enc, sep, fmt):
    # 엑셀에서 저장한 csv: 인코딩 · 구분자 · 날짜 형식 · 천단위 콤마가 달라도 같은 결과
    df = ms.make_row('2024-01-01', '2024-01-10')
    d = df.copy()
    if fmt:
        d['기간_일자'] = pd.to_datetime(d['기간_일자'], unit='D', origin='1899-12-30').dt.strftime(fmt)
    d['지표_광고비'] = d['지표_광고비'].map(lambda v: f'{v:,}' if isinstance(v, (int, float)) else v)
    p = tmp_path / 'row.csv'
    d.to_csv(p, index=False, encoding=enc, sep=sep)
    got = bd.build([p])
    ref = bd.build([_pkl(tmp_path, df)])
    assert got['row']['dates'] == ref['row']['dates'] == [f'2024-01-{i:02d}' for i in range(1, 11)]
    assert sum(got['row']['f']['cost']) == sum(ref['row']['f']['cost'])
    assert sum(got['row']['f']['fp']) == sum(ref['row']['f']['fp'])


def _pkl(tmp_path, df):
    p = tmp_path / 'ref.pkl'
    df.to_pickle(p)
    return p


@pytest.mark.parametrize('enc', ['utf-8-sig', 'utf-8', 'cp949'])
@pytest.mark.parametrize('shift', range(4))
def test_csv_korean_at_byte_boundary(tmp_path, enc, shift):
    # 판별용으로 앞부분을 바이트 수로 자르면 한글 글자 중간이 잘려 '인코딩을 읽지 못했습니다'가 나던 문제
    hdr = '기간_일자,구분_광고유형,구분_채널,구분_매체명,구분_캠페인,지표_광고비\n'
    body = ''.join(f'2024-01-{(i % 28) + 1:02d},SA,브랜드검색,네이버,{"x" * shift}가나다라마바사캠페인{i},1000\n' for i in range(400))
    p = tmp_path / 'row.csv'
    p.write_bytes((hdr + body).encode(enc))
    df = bd.read_csv_any(p)
    assert len(df) == 400 and df.columns[0] == '기간_일자' and df.iloc[0, 4].endswith('가나다라마바사캠페인0')


def test_csv_partly_broken_bytes_still_reads(tmp_path):
    hdr = '기간_일자,구분_광고유형,구분_채널,구분_매체명,구분_캠페인,지표_광고비\n'
    body = ''.join(f'2024-01-{(i % 28) + 1:02d},SA,브랜드검색,네이버,캠페인{i},1000\n' for i in range(300)).encode('utf-8')
    p = tmp_path / 'row.csv'
    p.write_bytes(hdr.encode('utf-8') + body[:3000] + b'\xff\xfe' + body[3000:])
    df = bd.read_csv_any(p)
    assert len(df) == 300 and df.columns[0] == '기간_일자'


def test_unpack_upload_zip_gz(tmp_path):
    import gzip as gz
    import io
    import zipfile
    df = ms.make_row('2024-01-01', '2024-01-05')
    df['기간_일자'] = pd.to_datetime(df['기간_일자'], unit='D', origin='1899-12-30').dt.strftime('%Y-%m-%d')
    csv = df.to_csv(index=False).encode('utf-8-sig')
    zbuf = io.BytesIO()
    with zipfile.ZipFile(zbuf, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('로우_2024.csv', csv)
        z.writestr('__MACOSX/._x', b'junk')
        z.writestr('설명.txt', b'x')
    zbuf.seek(0)
    (tmp_path / 'z').mkdir()
    ps = bd.unpack_upload('rows.zip', zbuf, tmp_path / 'z')
    assert [p.name for p in ps] == ['로우_2024.csv']
    (tmp_path / 'g').mkdir()
    pg = bd.unpack_upload('로우_2024.csv.gz', io.BytesIO(gz.compress(csv)), tmp_path / 'g')
    assert [p.name for p in pg] == ['로우_2024.csv']
    a, b = bd.build(ps), bd.build(pg)
    assert a['row']['dates'] == b['row']['dates'] == [f'2024-01-0{i}' for i in range(1, 6)]
    assert sum(a['row']['f']['cost']) == sum(b['row']['f']['cost'])
