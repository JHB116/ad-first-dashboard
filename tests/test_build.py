# -*- coding: utf-8 -*-
"""build_data.py — 가짜 원천으로 분류 · 집계 · 이어 붙이기 · AF 읽기를 검증 (모든 숫자는 임의값)"""
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
    return bd.build([sample / 'sample_row.pkl'], [sample / 'Sheet_1_-_sample.csv'])


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
    for m in ['cost', 'join', 'fp', 'fpr', 'nb', 'nrev', 'fpn']:
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
    # 기존 백업(~9/29) + 추가 파일(9/29~10/1): 9/29 는 새 값으로 교체, 나머지 날짜는 유지
    p2 = bd.build([sample / 'sample_row_1001.pkl'], base=json.loads(json.dumps(payload)))
    assert p2['source']['row']['to'] == '2026-10-01' and p2['source']['row']['days'] == 639
    old, new = frame(payload['row']), frame(p2['row'])
    add = bd.prep_row(bd.load_row_raw(sample / 'sample_row_1001.pkl'))
    add['t'] = bd.classify(add)
    add = add[add['t'].notna()]
    d = pd.Timestamp('2026-09-29')
    assert new[new['date'] == d]['cost'].sum() == pytest.approx(add[add['date'] == d]['cost'].sum(), abs=1)
    d = pd.Timestamp('2026-09-28')
    assert new[new['date'] == d]['cost'].sum() == pytest.approx(old[old['date'] == d]['cost'].sum(), abs=1)
    assert p2['source']['row']['files'] == ['sample_row.pkl', 'sample_row_1001.pkl']
    # AF 는 기존 백업 것을 그대로 유지
    assert p2['af']['n'] == payload['af']['n']


def test_multiple_row_files_later_wins(sample):
    p = bd.build([sample / 'sample_row.pkl', sample / 'sample_row_1001.pkl'])
    p_rev = bd.build([sample / 'sample_row_1001.pkl', sample / 'sample_row.pkl'])
    a, b = frame(p['row']), frame(p_rev['row'])
    d = pd.Timestamp('2026-09-29')
    assert a[a['date'] == d]['cost'].sum() != pytest.approx(b[b['date'] == d]['cost'].sum())


def test_af_build(payload):
    src = payload['source']['af']
    assert src['to'] == '2026-10-05' and src['years'] == {'2024': 366, '2026': 278}
    assert src['lastDay']['fp'] == pytest.approx(ms.AF_TARGET[('2026-10-05', '2026-10-05')][1])
    af = frame(payload['af'])
    m = af[(af['date'] >= '2026-07-01') & (af['date'] <= '2026-09-30')]
    days = m['date'].nunique()
    exp_ord, exp_fp = ms.AF_TARGET[('2026-07-01', '2026-09-30')]
    assert m['ord'].sum() / days == pytest.approx(exp_ord, abs=0.05)
    assert m['fp'].sum() / days == pytest.approx(exp_fp, abs=0.05)


def test_af_same_date_later_file_wins(sample, tmp_path):
    a = bd.read_af_file(sample / 'Sheet_1_-_sample.csv')
    one = a[a['date'] == '2026-09-01']
    p = tmp_path / 'Sheet_1_-_new.csv'
    pd.DataFrame({'결제_일자': one['date'].dt.strftime('%Y%m%d'), 'AF중분류명': one['mid'], 'AF소분류명': one['sub'],
                  'AF브랜드': one['brand'], 'AF캠페인상세': one['camp'], '주문고객수': one['ord'] * 2, '거래액': one['rev'],
                  '신규고객수': one['new'], '신규거래액': one['nrev'], '첫구매고객수': one['fp'] * 2, '첫구매거래액': one['fpr']}
                 ).to_csv(p, sep='\t', encoding='utf-16', index=False)
    sec, info = bd.build_af_section([sample / 'Sheet_1_-_sample.csv', p], None)
    af = frame(sec)
    assert af[af['date'] == '2026-09-01']['ord'].sum() == pytest.approx(one['ord'].sum() * 2, rel=1e-6)
    assert af[af['date'] == '2026-09-02']['ord'].sum() == pytest.approx(a[a['date'] == '2026-09-02']['ord'].sum(), rel=1e-6)
    assert any('1일뿐' in w for w in info['warnings'])


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
