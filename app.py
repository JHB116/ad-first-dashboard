# -*- coding: utf-8 -*-
"""광고 신규 실적 대시보드 — Streamlit 배포용 (Main file path: app.py)

dashboard.html 을 화면 가득 띄운다(첫구매 실적 대시보드와 같은 구조). 실적 데이터는 저장소에 없다.
- 백업(.json.gz)을 화면에 끌어다 놓으면 보는 사람의 브라우저(IndexedDB)에만 저장해 조회한다.
- 맨 위 '원천 파일 올리기'에서 로우 파일(xlsb · csv · xlsx)을 올리면 서버 메모리에서 백업 형태로 바꿔 넘기고,
  대시보드가 브라우저에 저장된 데이터에 날짜 단위로 합친다(같은 날짜는 교체). 올린 원천은 서버에 저장하지 않는다.
"""
import base64
import contextlib
import hashlib
import io
import tempfile
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

import build_data as bd

ROOT = Path(__file__).resolve().parent
MARKER = '<script src="calc.js"></script>'
BAR_H = 56   # 위쪽 '원천 파일로 백업 만들기' 줄 높이(px)

st.set_page_config(page_title='광고 신규 실적 대시보드', page_icon='📈', layout='wide', initial_sidebar_state='collapsed')
st.markdown(
    f"""<style>
    header[data-testid="stHeader"], [data-testid="stToolbar"], [data-testid="stDecoration"], footer {{display: none !important;}}
    .block-container, [data-testid="stMainBlockContainer"] {{padding: 0 !important; max-width: 100% !important;}}
    [data-testid="stVerticalBlock"] {{gap: 0 !important;}}
    [data-testid="stExpander"] {{margin: 6px 12px;}}
    iframe {{display: block; width: 100% !important; height: calc(100vh - {BAR_H}px) !important; height: calc(100dvh - {BAR_H}px) !important; border: 0;}}
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


def run_build(row_files):
    """올린 원천 → 백업 bytes. pyxlsb 는 경로가 필요해 임시 폴더에 잠깐 쓴 뒤 지운다"""
    log = io.StringIO()
    with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(log):
        def save(f, k):
            p = Path(tmp) / f'{k:02d}' / Path(f.name).name   # 올린 순서 유지 (같은 날짜는 뒤 파일이 이김)
            p.parent.mkdir()
            p.write_bytes(f.getbuffer())
            return p
        rows = [save(f, k) for k, f in enumerate(row_files)]
        payload = bd.build(rows, use_cache=False)
    return bd.backup_bytes(payload), payload['source'], log.getvalue()


with st.expander('📂 원천 파일 올리기 (처음 한 번 전체 · 이후 새 날짜만)', expanded=False):
    st.caption('로우 파일(xlsb · csv · xlsx, 첫 행 헤더)을 올리면 이 브라우저에 저장된 데이터에 합칩니다. '
               '올린 파일에 있는 날짜는 새 값으로 바뀌고, 나머지 날짜(예: 2024년)는 그대로 남습니다. '
               '데이터는 서버가 아니라 이 브라우저에만 저장됩니다 — 다른 PC에서 보려면 대시보드의 \'백업 내려받기\'로 옮기세요.')
    row_files = st.file_uploader('로우 파일 (여러 개 가능 · 같은 날짜는 뒤 파일이 이김)', type=['xlsb', 'csv', 'xlsx'], accept_multiple_files=True)
    if st.button('올리기', type='primary', disabled=not row_files):
        with st.spinner('읽는 중… 큰 파일은 몇 분 걸릴 수 있습니다'):
            try:
                data, source, log = run_build(row_files)
                st.session_state['built'] = {'data': data, 'source': source, 'log': log,
                                             'id': hashlib.sha1(data).hexdigest()[:12]}
            except Exception as e:  # 원천 형식 오류를 화면에 보여 준다
                st.session_state.pop('built', None)
                st.error(f'읽지 못했습니다: {e}')
    built = st.session_state.get('built')
    if built:
        r = built['source']['row']
        st.success(f"{r['from']} ~ {r['to']} ({r['days']}일)을 읽어 아래 대시보드의 저장된 데이터에 합쳤습니다")
        for line in built['log'].splitlines():      # 읽기 중 경고(없는 컬럼 · 깨진 글자 등)
            if line.strip().startswith('!'):
                st.warning(line.strip().lstrip('! '))
        with st.expander('읽기 로그'):
            st.code(built['log'] or '(없음)')

stamp = tuple((ROOT / f).stat().st_mtime for f in ('dashboard.html', 'calc.js'))
html = page(stamp)
built = st.session_state.get('built')
if built:
    # 방금 올린 원천을 대시보드가 저장된 데이터에 합치도록 넣어 준다 (dashboard.html 의 preload())
    pre = f"<script>window.AD_PRELOAD_ID = '{built['id']}'; window.AD_PRELOAD = '{base64.b64encode(built['data']).decode()}';</script>\n"
    html = html.replace('<script>\n', pre + '<script>\n', 1)
if hasattr(st, 'iframe'):      # Streamlit 1.5x 이후 권장 API
    st.iframe(html, height=900)
else:                          # 이전 버전
    components.html(html, height=900, scrolling=True)
