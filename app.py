# -*- coding: utf-8 -*-
"""광고 신규 실적 대시보드 — Streamlit 배포용 (Main file path: app.py)

dashboard.html 을 화면 가득 띄운다(첫구매 실적 대시보드와 같은 구조). 실적 데이터는 저장소에 없다.
- PC에서 make_backup.bat 으로 만든 백업(.json.gz)을 화면에 끌어다 놓거나 '백업 파일 열기'로 열면
  보는 사람의 브라우저(IndexedDB)에만 저장해 조회한다. 같은 날짜는 새 백업으로 교체, 나머지 날짜는 유지.
- 서버에는 아무것도 올리지 않는다.
- 메모 '리뷰' Gemini 초안: Streamlit Secrets 에 GEMINI_API_KEY 가 있으면, 화면이 계산한 요약 숫자만 받아
  서버가 Gemini 로 초안을 써서 돌려준다(streamlit_component/ 가 화면 ↔ 서버 중계). 키는 서버에만 있다.
"""
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

try:
    import gemini_memo as gm
except Exception:          # update.bat 로 받기 전의 PC 등 — Gemini 없이 화면만
    gm = None

ROOT = Path(__file__).resolve().parent
MARKER = '<script src="calc.js"></script>'
COMPONENT = ROOT / 'streamlit_component'

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

if (COMPONENT / 'index.html').exists():
    api_key, model = gm.load_config(st.secrets) if gm else (None, None)
    dashboard = components.declare_component('ad_new_dashboard', path=str(COMPONENT))
    request = dashboard(
        html=html, pageStamp='|'.join(map(str, stamp)),
        gemini={'configured': bool(api_key), 'model': st.session_state.get('gemini_model', model)},
        memoResponse=st.session_state.get('memo_response'),
        key='ad-new-dashboard', default=None,
    )
    if isinstance(request, dict) and request.get('type') == 'gemini_memo' and request.get('id'):
        rid = str(request['id'])[:100]
        if rid != st.session_state.get('memo_last_id'):
            try:
                # 설정한 모델이 없으면(404) 쓸 수 있는 모델로 바꿔 부르고, 그 모델을 이 세션 동안 기억한다
                # kind: 'memo' = 추이 메모 리뷰 칸 · 'diag' = 첫구매 진단 리뷰
                text, used = gm.write_memo(request.get('facts', ''), api_key,
                                           model=st.session_state.get('gemini_model', model),
                                           prompt=gm.PROMPTS.get(request.get('kind'), gm.PROMPT))
                st.session_state['gemini_model'] = used
                resp = {'id': rid, 'ok': True, 'text': text, 'model': used}
            except gm.GeminiError as e:
                resp = {'id': rid, 'ok': False, 'message': str(e)}
            except Exception as e:   # 예상 못 한 오류도 화면으로 돌려보낸다(안 그러면 '쓰는 중…'에 멈춤)
                resp = {'id': rid, 'ok': False, 'message': f'Gemini 초안 중 오류({type(e).__name__}) — 잠시 뒤 다시 눌러 주세요.'}
            st.session_state['memo_last_id'] = rid
            st.session_state['memo_response'] = resp
            st.rerun()
elif hasattr(st, 'iframe'):    # 중계 폴더가 없으면(예전 PC 사본) 화면만 — Streamlit 1.5x 이후 권장 API
    st.iframe(html, height=900)
else:                          # 이전 버전
    components.html(html, height=900, scrolling=True)
