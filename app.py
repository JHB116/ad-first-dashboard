# -*- coding: utf-8 -*-
"""광고 신규 실적 대시보드 — Streamlit 배포용 (Main file path: app.py)

dashboard.html 을 화면 가득 띄운다(첫구매 실적 대시보드와 같은 구조). 실적 데이터는 저장소에 없다.
- 백업(.json.gz)을 화면에 끌어다 놓으면 보는 사람의 브라우저(IndexedDB)에만 저장해 조회한다.
- 맨 위 '원천 파일로 백업 만들기'에서 로우 시트 xlsb · AF 결제 csv 를 올리면(기존 백업에 이어 붙이기 가능)
  서버 메모리에서 백업을 만들어 바로 열어 주고 내려받게 한다. 올린 원천은 저장하지 않는다.
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


def run_build(row_files, af_files, base_file, lite):
    """올린 파일 → 백업 bytes. pyxlsb 는 경로가 필요해 임시 폴더에 잠깐 쓴 뒤 지운다"""
    log = io.StringIO()
    with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(log):
        def save(f, k):
            p = Path(tmp) / f'{k:02d}_{Path(f.name).name}'   # 올린 순서 유지 (같은 날짜는 뒤 파일이 이김)
            p.write_bytes(f.getbuffer())
            return p
        rows = [save(f, k) for k, f in enumerate(row_files)]
        afs = [save(f, k) for k, f in enumerate(af_files)]
        base = bd.read_backup(io.BytesIO(base_file.getvalue())) if base_file else None
        payload = bd.build(rows, afs, base=base, lite=lite, use_cache=False)
    return bd.backup_bytes(payload), bd.backup_name(payload), payload['source'], log.getvalue()


with st.expander('📂 원천 파일로 백업 만들기 · 새 날짜 추가', expanded=False):
    st.caption('로우 시트 xlsb(일일보고서 전체든 로우 시트만 뽑은 파일이든 같음) · AF 결제 csv 를 올리면 백업을 만들어 바로 엽니다. '
               '기존 백업을 같이 올리면 새 파일에 있는 날짜만 교체 · 추가합니다. 올린 원천은 서버에 저장하지 않습니다.')
    c1, c2, c3 = st.columns(3)
    row_files = c1.file_uploader('로우 시트 xlsb (여러 개 가능)', type=['xlsb'], accept_multiple_files=True)
    af_files = c2.file_uploader('AF 결제 csv (여러 개 가능)', type=['csv'], accept_multiple_files=True)
    base_file = c3.file_uploader('이어 붙일 기존 백업 (선택)', type=['gz', 'json'])
    lite = st.checkbox('가볍게 (하위캠페인 · 브랜드/기획전 · 디바이스 차원 제외)', value=False)
    if st.button('백업 만들기', type='primary', disabled=not (row_files or af_files)):
        with st.spinner('읽는 중… 큰 xlsb 는 몇 분 걸릴 수 있습니다'):
            try:
                data, name, source, log = run_build(row_files or [], af_files or [], base_file, lite)
                st.session_state['built'] = {'data': data, 'name': name, 'source': source, 'log': log,
                                             'id': hashlib.sha1(data).hexdigest()[:12]}
            except Exception as e:  # 원천 형식 오류를 화면에 보여 준다
                st.session_state.pop('built', None)
                st.error(f'백업을 만들지 못했습니다: {e}')
    built = st.session_state.get('built')
    if built:
        src = built['source']
        parts = []
        if 'row' in src:
            parts.append(f"로우 {src['row']['from']} ~ {src['row']['to']} ({src['row']['days']}일)")
        if 'af' in src:
            parts.append(f"AF {src['af']['from']} ~ {src['af']['to']} ({src['af']['days']}일)")
        st.success('백업을 만들어 아래 대시보드에 열었습니다 · ' + ' · '.join(parts) + f" · {len(built['data']) / 1e6:.1f}MB")
        for w in src.get('af', {}).get('warnings', []):
            st.warning(w)
        st.download_button('백업 내려받기 (다음에 이 파일을 열거나 이어 붙이기)', built['data'], file_name=built['name'], mime='application/gzip')
        with st.expander('빌드 로그'):
            st.code(built['log'] or '(없음)')

stamp = tuple((ROOT / f).stat().st_mtime for f in ('dashboard.html', 'calc.js'))
html = page(stamp)
built = st.session_state.get('built')
if built:
    # 방금 만든 백업을 대시보드가 바로 열도록 넣어 준다 (dashboard.html 의 preload())
    pre = f"<script>window.AD_PRELOAD_ID = '{built['id']}'; window.AD_PRELOAD = '{base64.b64encode(built['data']).decode()}';</script>\n"
    html = html.replace('<script>\n', pre + '<script>\n', 1)
if hasattr(st, 'iframe'):      # Streamlit 1.5x 이후 권장 API
    st.iframe(html, height=900)
else:                          # 이전 버전
    components.html(html, height=900, scrolling=True)
