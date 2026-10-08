# -*- coding: utf-8 -*-
"""실데이터 검증 — raw/ 폴더에 로우 파일이 있고 tests/local/expected.json 이 있을 때만 실행 (없으면 skip)

공개 저장소라 기대값(실제 실적)은 커밋하지 않는다. tests/local/ 은 .gitignore 대상.
expected.json 예시 (값은 일보고서 시트 · 분석 결과에서 옮겨 적는다):
{
  "row_day": {"date": "2026-09-01", "cost": 0, "join": 0, "fpn": 0, "nb": 0},
  "row_month_avg": [
    {"month": "2026-09", "metric": "cost", "value": 0, "scale": 1e6},
    {"month": "2026-09", "metric": "fp", "type": "브랜드검색광고", "value": 0}
  ]
}
값은 소수 1자리 반올림으로 비교한다(row_day 는 정수).
"""
import json
from pathlib import Path

import pandas as pd
import pytest

import build_data as bd

EXP_PATH = Path(__file__).parent / 'local' / 'expected.json'
EXP = json.loads(EXP_PATH.read_text(encoding='utf-8')) if EXP_PATH.exists() else {}
ROWS = bd.by_mtime(p for d in bd.RAW_DIRS for p in d.glob('*') if p.suffix.lower() in bd.ROW_EXT)
need_row = pytest.mark.skipif(not (ROWS and EXP), reason='raw/ 원천 또는 tests/local/expected.json 없음')


@pytest.fixture(scope='module')
def raw():
    return bd.latest_wins([bd.prep_row(bd.load_row_raw(p)) for p in ROWS])


@need_row
def test_row_day(raw):
    e = EXP.get('row_day')
    if not e:
        pytest.skip('row_day 없음')
    d = raw[raw['date'] == e['date']]
    for k in ('cost', 'join', 'fpn', 'nb'):
        if k in e:
            assert round(d[k].sum()) == e[k], k


@need_row
def test_row_month_avg(raw):
    df = raw.copy()
    df['t'] = bd.classify(df)
    df = df[df['t'].notna()]
    for e in EXP.get('row_month_avg', []):
        m = df[df['date'].dt.strftime('%Y-%m') == e['month']]
        days = m['date'].nunique()
        if e.get('type'):
            m = m[m['t'] == e['type']]
        assert round(m[e['metric']].sum() / days / e.get('scale', 1), 1) == e['value'], e
