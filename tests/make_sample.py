# -*- coding: utf-8 -*-
"""가짜 원천(로우 시트) 생성 — 실제 수치 없이 빌드 · 화면을 검증할 때 쓴다. 모든 숫자는 임의값이다.

    python tests/make_sample.py <출력폴더>
      → sample_row.pkl (로우 시트 형태, 2025-01-01~2026-09-29) · sample_row_1001.pkl (2026-09-29~10-04, 추가분)
        · sample_row_2024.pkl (2024년, 24년 원천처럼 일부 지표 컬럼 없음)
    python build_data.py --row <출력폴더>/sample_row.pkl
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

# (광고유형, 채널, 매체, 비용출처, 캠페인, 하위캠페인, 브랜드/기획전, 비중) — 분류 규칙의 모든 갈래를 포함
ROW_SPEC = [
    ('SA', '브랜드검색', '네이버', '거래액확대', '브랜드_PC', '브랜드_A', '브랜드A', .5),
    ('SA', '브랜드검색', '네이버', '신규고객확대', '브랜드_MO', '브랜드_B', '우포스', .3),
    ('SA', '브랜드검색', '구글', '거래액확대', '브랜드_구글', '-', '킨', .2),
    ('SA', '사이트검색광고', '네이버', '거래액확대', '사이트_파워링크', '-', 'LFmall', .7),
    ('SA', '사이트검색', '구글', '거래액확대', '사이트_구글', '-', 'LFmall', .3),
    ('SA', '쇼핑검색광고', '네이버', '거래액확대', '쇼핑검색_신발', '-', '기획전1', 1.),
    ('DA', '포탈', '카카오', '거래액확대', '카카오_기획전', '-', '기획전2', .4),
    ('DA', '포탈', '카카오', '신규고객확대', '카카오_신규행사', '-', '기획전3', .2),
    ('DA', 'SNS', 'FB/IG', '신규고객확대', 'Meta_신규유저', '-', 'LFmall', .25),
    ('DA', 'SNS', 'FB/IG', '신규고객확대', 'Meta_방문유저', '-', 'LFmall', .15),
    ('DA', '네트워크배너', 'PAYCO', '신규고객확대', 'PAYCO_첫구매', '-', 'LFmall', .4),
    ('DA', '생활밀착형앱', '토스', '신규고객확대', '토스_혜택', '-', 'LFmall', .4),
    ('DA', '링크사', '링크프라이스', '거래액확대', '링크프라이스', '-', 'LFmall', .2),
    ('Message', 'DB발송', '카카오', '거래액확대', '알림톡', '-', 'LFmall', 1.),
    ('PA', '상품피드', '크리테오', '거래액확대', '크리테오_DPA', '-', 'LFmall', .6),
    ('PA', '상품피드', 'RTB', '거래액확대', 'RTB_리타겟', '-', 'LFmall', .4),
]
METS = ['지표_광고비', '지표_UV(전체)', '지표_가입회원', '지표_총결제고객수(첫구매)', '지표_총결제거래액(첫구매)',
        '지표_순결제고객수(첫구매)', '지표_당년신규순결제고객수', '지표_당년신규순결제거래액',
        '지표_총결제고객수', '지표_총결제거래액', '지표_총결제고객수(윈백)']
COLS = ['Source.Name', '기간_월', '기간_일자', '구분_AF코드', '구분_광고유형', '구분_채널', '구분_매체명', '구분_비용출처',
        '구분_캠페인', '구분_하위캠페인', '구분_브랜드/기획전', '구분_디바이스', *METS]


def make_row(start='2025-01-01', end='2026-09-29', seed=7, scale_all=1.0, source='sample.xlsx') -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows = []
    zeros = [0] * len(METS)
    for d in pd.date_range(start, end, freq='D'):
        serial = (d - pd.Timestamp('1899-12-30')).days
        for t, ch, md, src, camp, sub, bp, w in ROW_SPEC:
            for dev, dw in (('PC', .3), ('Mobile', .5), ('APP', .2)):
                scale = scale_all * w * dw * (1.3 if d.dayofweek >= 5 else 1.0) * rng.uniform(.7, 1.3)
                fp = int(rng.poisson(10 * scale))
                other = int(rng.poisson(80 * scale))
                rows.append([source, f'{d.year}년{d.month:02d}월', serial, 'AF0', t, ch, md, src, camp, sub, bp, dev,
                             round(2_000_000 * scale), int(rng.poisson(2000 * scale)), int(rng.poisson(30 * scale)), fp,
                             fp * int(rng.integers(40_000, 90_000)), int(fp * .8), int(fp * .7), int(fp * .7) * 60_000,
                             fp + other, (fp + other) * 70_000, int(rng.poisson(5 * scale))])
        # 미분류 행 · 문자열 섞인 숫자 · 음수 조정분
        r = [source, '', serial, '-', 'APP', '-', '-', '-', '-', '-', '-', '-', *zeros]
        r[14] = ' - '
        rows.append(r)
        if d.day == 1:
            r = [source, '', serial, '-', 'DA', '포탈', '카카오', 'E영업', '서비스비용 조정', '-', '-', 'PC', *zeros]
            r[12], r[16] = -300_000, '########'
            rows.append(r)
    return pd.DataFrame(rows, columns=COLS)


# 2024년 원천에는 없는 지표 컬럼 (컬럼 이름이 다르거나 없음)
COLS_2024_MISSING = ['지표_순결제고객수(첫구매)', '지표_당년신규순결제고객수', '지표_당년신규순결제거래액', '지표_총결제고객수(윈백)']


def main(out: Path):
    out.mkdir(parents=True, exist_ok=True)
    make_row().to_pickle(out / 'sample_row.pkl')
    # 추가분: 9/29(기존과 겹침 → 교체) ~ 10/4, 값은 2배
    make_row('2026-09-29', '2026-10-04', seed=11, scale_all=2.0, source='add.xlsx').to_pickle(out / 'sample_row_1001.pkl')
    make_row('2024-01-01', '2024-12-31', seed=3, source='2024.xlsx').drop(columns=COLS_2024_MISSING).to_pickle(out / 'sample_row_2024.pkl')
    print('sample →', out)


if __name__ == '__main__':
    main(Path(sys.argv[1] if len(sys.argv) > 1 else 'data/sample'))
