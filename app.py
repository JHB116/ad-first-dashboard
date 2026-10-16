# -*- coding: utf-8 -*-
"""광고 신규 실적 대시보드 — Streamlit 배포용 (Main file path: app.py)

dashboard.html 을 화면 가득 띄운다(첫구매 실적 대시보드와 같은 구조). 실적 데이터는 저장소에 없다.
- 백업(.json.gz)을 화면에 끌어다 놓으면 보는 사람의 브라우저(IndexedDB)에만 저장해 조회한다.
- 맨 위 '원천 파일 올리기'에서 로우 파일(xlsb · csv · xlsx)을 올리면 서버 메모리에서 백업 형태로 바꿔 넘기고,
  대시보드가 브라우저에 저장된 데이터에 날짜 단위로 합친다(같은 날짜는 교체). 올린 원천은 서버에 저장하지 않는다.
"""
import base64
import contextlib
import gc
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
    .stApp, [data-testid="stAppViewContainer"] {{background: #eaf0f7;}}   /* 대시보드 배경과 같은 푸른 회색 — 첫구매 대시보드와 구분 */
    @media (prefers-color-scheme: dark) {{ .stApp, [data-testid="stAppViewContainer"] {{background: #0b1119;}} }}
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


def run_build(files):
    """올린 파일들 → 대시보드에 합칠 백업들(gzip bytes, 올린 순서).
    원천(xlsb · csv · xlsx · zip)은 한 백업으로 만들고, 백업 파일(.json.gz)은 그대로 넘긴다.
    pyxlsb 는 경로가 필요해 임시 폴더에 잠깐 쓴 뒤 지운다"""
    log = io.StringIO()
    items, rows, row_pos, sources = [], [], None, []
    with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(log):
        for k, f in enumerate(files):
            d = Path(tmp) / f'{k:02d}'                      # 올린 순서 유지 (같은 날짜는 뒤 파일이 이김)
            d.mkdir()
            for p in bd.unpack_upload(Path(f.name).name, f, d):
                if bd.is_backup(p):                         # 백업 파일 → 원천으로 읽지 않고 그대로 합치기
                    payload = bd.read_backup(p)
                    items.append(bd.backup_bytes(payload))
                    sources.append(payload['source'].get('row', {}))
                    print(f'[백업] {f.name}: {sources[-1].get("from")} ~ {sources[-1].get("to")} 그대로 합칩니다')
                else:
                    if row_pos is None:
                        row_pos = len(items)
                        items.append(None)
                    rows.append(p)
        if rows:
            payload = bd.build(rows, use_cache=False)
            items[row_pos] = bd.backup_bytes(payload)
            sources.insert(row_pos, payload['source']['row'])
    return items, sources, log.getvalue()


with st.expander('📂 원천 파일 올리기 (처음 한 번 전체 · 이후 새 날짜만)', expanded=st.session_state.pop('just_built', False)):
    st.caption('로우 파일(xlsb · csv · xlsx, 첫 행 헤더)을 올리면 이 브라우저에 저장된 데이터에 합칩니다. '
               '큰 csv(수십 MB 이상)는 zip 으로 압축해 올리면 서버 메모리를 훨씬 덜 씁니다(압축 안의 파일을 그대로 읽음). '
               '올린 파일에 있는 날짜는 새 값으로 바뀌고, 나머지 날짜(예: 2024년)는 그대로 남습니다. '
               '데이터는 서버가 아니라 이 브라우저에만 저장됩니다 — 다른 PC에서 보려면 대시보드의 \'백업 내려받기\'로 옮기세요.')
    up_key = f"rows_{st.session_state.get('up_n', 0)}"     # 처리 후 키를 바꿔 올린 파일을 서버 메모리에서 비운다
    row_files = st.file_uploader('로우 파일 또는 백업 파일(.json.gz) — 여러 개 가능 · 같은 날짜는 뒤 파일이 이김', type=['xlsb', 'csv', 'xlsx', 'zip', 'gz', 'json'], accept_multiple_files=True, key=up_key)
    if st.button('올리기', type='primary', disabled=not row_files):
        ok = False
        with st.spinner('읽는 중… 큰 파일은 몇 분 걸릴 수 있습니다'):
            try:
                items, sources, log = run_build(row_files)
                st.session_state['built'] = {'items': items, 'sources': sources, 'log': log,
                                             'id': hashlib.sha1(b''.join(items)).hexdigest()[:12]}
                ok = True
            except Exception as e:  # 원천 형식 오류를 화면에 보여 준다
                st.session_state.pop('built', None)
                st.error(f'읽지 못했습니다: {e}')
        if ok:
            st.session_state['up_n'] = st.session_state.get('up_n', 0) + 1
            st.session_state['just_built'] = True
            del row_files
            gc.collect()
            st.rerun()
    built = st.session_state.get('built')
    if built:
        rng = ' · '.join(f"{r.get('from')} ~ {r.get('to')} ({r.get('days')}일)" for r in built['sources'])
        st.success(f"{rng}을 아래 대시보드의 저장된 데이터에 합쳤습니다")
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
    arr = ','.join(f"'{base64.b64encode(x).decode()}'" for x in built['items'])
    pre = f"<script>window.AD_PRELOAD_ID = '{built['id']}'; window.AD_PRELOAD = [{arr}];</script>\n"
    html = html.replace('<script>\n', pre + '<script>\n', 1)
if hasattr(st, 'iframe'):      # Streamlit 1.5x 이후 권장 API
    st.iframe(html, height=900)
else:                          # 이전 버전
    components.html(html, height=900, scrolling=True)
