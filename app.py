# -*- coding: utf-8 -*-
"""광고 신규 실적 대시보드 — Streamlit 배포용 (Main file path: app.py)

dashboard.html 을 화면 가득 띄운다(첫구매 실적 대시보드와 같은 구조). 실적 데이터는 저장소에 없다.
- PC에서 make_backup.bat 으로 만든 백업(.json.gz)을 화면에 끌어다 놓거나 '백업 파일 열기'로 열면
  보는 사람의 브라우저(IndexedDB)에만 저장해 조회한다. 같은 날짜는 새 백업으로 교체, 나머지 날짜는 유지.
- 서버에는 아무것도 올리지 않는다.
"""
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

ROOT = Path(__file__).resolve().parent
MARKER = '<script src="calc.js"></script>'

st.set_page_config(page_title='광고 신규 실적 대시보드', page_icon='📈', layout='wide', initial_sidebar_state='collapsed')
st.markdown(
    """<style>
    header[data-testid="stHeader"], [data-testid="stToolbar"], [data-testid="stDecoration"], footer {display: none !important;}
    .block-container, [data-testid="stMainBlockContainer"] {padding: 0 !important; max-width: 100% !important;}
    [data-testid="stVerticalBlock"] {gap: 0 !important;}
    iframe {display: block; width: 100% !important; height: 100vh !important; height: 100dvh !important; border: 0;}
    </style>""",
    unsafe_allow_html=True,
)


@st.cache_data(show_spinner=False)
def page(stamp):
    """dashboard.html + calc.js 를 한 장으로 — stamp(수정시각)가 바뀌면 다시 읽는다"""
    html = (ROOT / 'dashboard.html').read_text(encoding='utf-8')
    calc = (ROOT / 'calc.js').read_text(encoding='utf-8')
    if MARKER not in html:
        raise RuntimeError('dashboard.html 에서 calc.js 를 넣을 자리를 찾지 못했습니다')
    return html.replace(MARKER, f'<script>\n{calc}\n</script>', 1)


stamp = tuple((ROOT / f).stat().st_mtime for f in ('dashboard.html', 'calc.js'))
html = page(stamp)
if hasattr(st, 'iframe'):      # Streamlit 1.5x 이후 권장 API
    st.iframe(html, height=900)
else:                          # 이전 버전
    components.html(html, height=900, scrolling=True)
