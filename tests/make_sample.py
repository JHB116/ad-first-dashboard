# -*- coding: utf-8 -*-
"""가짜 원천(로우 · AF) 생성 — 실제 수치 없이 빌드 · 화면을 검증할 때 쓴다. 모든 숫자는 임의값이다.

    python tests/make_sample.py <출력폴더>
      → sample_row.pkl (로우 시트 형태, 2025-01-01~2026-09-29) · sample_row_1001.pkl (2026-09-29~10-01, 추가분)
        · Sheet_1_-_sample.csv (AF, UTF-16 탭)
    python build_data.py --row <출력폴더>/sample_row.pkl --af <출력폴더>/Sheet_1_-_sample.csv

AF 쪽은 AF_TARGET 일평균이 정확히 나오도록 하루 값을 고정해 만든다 (베이스라인 계산 검증용).
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

# (광고유형, 채널, 매체, 비용출처, 캠페인, 하위캠페인, 브랜드/기획전, 비중) — 분류 규칙의 모든 갈래를 포함
ROW_SPEC = [
    ('SA', '브랜드검색', '네이버', '거래액확대', '브랜드_PC', '브랜드_A', '브랜드A', .5),
    ('SA', '브랜드검색', '네이버', '신규고객확대', '브랜드_MO', '브랜드_B', '브랜드B', .3),
    ('SA', '브랜드검색', '구글', '거래액확대', '브랜드_구글', '-', 'LFmall', .2),
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
        '지표_순결제고객수(첫구매)', '지표_당년신규순결제고객수', '지표_당년신규순결제거래액']
COLS = ['Source.Name', '기간_월', '기간_일자', '구분_AF코드', '구분_광고유형', '구분_채널', '구분_매체명', '구분_비용출처',
        '구분_캠페인', '구분_하위캠페인', '구분_브랜드/기획전', '구분_디바이스', *METS]


def make_row(start='2025-01-01', end='2026-09-29', seed=7, scale_all=1.0, source='sample.xlsx') -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows = []
    for d in pd.date_range(start, end, freq='D'):
        serial = (d - pd.Timestamp('1899-12-30')).days
        for t, ch, md, src, camp, sub, bp, w in ROW_SPEC:
            for dev, dw in (('PC', .3), ('Mobile', .5), ('APP', .2)):
                scale = scale_all * w * dw * (1.3 if d.dayofweek >= 5 else 1.0) * rng.uniform(.7, 1.3)
                fp = int(rng.poisson(10 * scale))
                rows.append([source, f'{d.year}년{d.month:02d}월', serial, 'AF0', t, ch, md, src, camp, sub, bp, dev,
                             round(2_000_000 * scale), int(rng.poisson(2000 * scale)), int(rng.poisson(30 * scale)), fp,
                             fp * int(rng.integers(40_000, 90_000)), int(fp * .8), int(fp * .7), int(fp * .7) * 60_000])
        # 미분류 행 · 문자열 섞인 숫자 · 음수 조정분
        rows.append([source, '', serial, '-', 'APP', '-', '-', '-', '-', '-', '-', '-', 0, 0, ' - ', 0, 0, 0, 0, 0])
        if d.day == 1:
            rows.append([source, '', serial, '-', 'DA', '포탈', '카카오', 'E영업', '서비스비용 조정', '-', '-', 'PC', -300_000, 0, 0, 0, '########', 0, 0, 0])
    return pd.DataFrame(rows, columns=COLS)


# AF — 구간별 하루 고정값(주문, 첫구매). 임의값
AF_TARGET = {
    ('2024-01-01', '2024-06-30'): (1000.0, 120.0),
    ('2024-07-01', '2024-09-30'): (1000.0, 125.0),
    ('2024-10-01', '2024-12-31'): (1100.0, 150.0),   # 7~9월 대비 +10% / +20%
    ('2026-01-01', '2026-06-30'): (1050.0, 110.0),
    ('2026-07-01', '2026-09-30'): (1200.0, 100.0),
    ('2026-10-01', '2026-10-04'): (1500.0, 114.0),   # 베이스라인 대비 +25% / +14%
    ('2026-10-05', '2026-10-05'): (1800.0, 3.0),     # 당일 미확정
}
AF_MID = [('BSA', '네이버', .30), ('SA', '네이버', .20), ('Shopping', '네이버', .20), ('DA', 'Payco', .10),
          ('DA', '토스', .08), ('DA', 'Daum/카카오', .05), ('PA', '크리테오', .05), ('Message', '카카오', .02)]
SEASON = ['우포스', '킨', '아일랜드슬리퍼']
SEASON_FP_SHARE = .25   # 7~9월 BSA 첫구매 중 시즌 3브랜드 비중 (임의값)


def make_af() -> pd.DataFrame:
    rows = []
    for (a, b), (ord_, fp) in AF_TARGET.items():
        summer = a.startswith('2026-07')
        for d in pd.date_range(a, b, freq='D'):
            for mid, sub, w in AF_MID:
                o, f = ord_ * w, fp * w
                if mid == 'BSA':
                    s = SEASON_FP_SHARE
                    split = [(SEASON[0], .03, s * .4), (SEASON[1], .04, s * .4), (SEASON[2], .02, s * .2), ('브랜드A', .91, 1 - s)] if summer \
                        else [(SEASON[1], .02, .05), ('브랜드A', .98, .95)]
                    for br, wo, wf in split:
                        rows.append([d.strftime('%Y%m%d'), '광고', mid, sub, '-', f'{br}_브랜드', br, '-', 'AF1', '코드', o * wo, o * wo * 80000, f * wf, 0, f * wf, f * wf * 70000])
                else:
                    rows.append([d.strftime('%Y%m%d'), '광고', mid, sub, '-', f'{mid}_상시', '-', '-', 'AF2', '코드', o, o * 80000, f, 0, f, f * 70000])
    cols = ['결제_일자', 'AF대분류명', 'AF중분류명', 'AF소분류명', 'AF세분류명', 'AF캠페인상세', 'AF브랜드', 'AF브랜드구분', 'AF코드', 'AF코드명',
            '주문고객수', '거래액', '신규고객수', '신규거래액', '첫구매고객수', '첫구매거래액']
    return pd.DataFrame(rows, columns=cols)


def main(out: Path):
    out.mkdir(parents=True, exist_ok=True)
    make_row().to_pickle(out / 'sample_row.pkl')
    # 추가분: 9/29(기존과 겹침 → 교체) ~ 10/1, 값은 2배
    make_row('2026-09-29', '2026-10-01', seed=11, scale_all=2.0, source='add.xlsx').to_pickle(out / 'sample_row_1001.pkl')
    af = make_af()
    for c in ['주문고객수', '거래액', '신규고객수', '신규거래액', '첫구매고객수', '첫구매거래액']:
        af[c] = af[c].map(lambda v: f'{v:,.4f}')
    af.to_csv(out / 'Sheet_1_-_sample.csv', sep='\t', encoding='utf-16', index=False)
    print('sample →', out)


if __name__ == '__main__':
    main(Path(sys.argv[1] if len(sys.argv) > 1 else 'data/sample'))
