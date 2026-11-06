# -*- coding: utf-8 -*-
"""gemini_memo — 키 · 요청 모양 · 응답 읽기 · 404 때 모델 바꿔 다시 부르기 · 오류 (실제 호출 없이 가짜 transport)"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import gemini_memo as gm  # noqa: E402

OK = {'candidates': [{'content': {'parts': [{'text': '■ 26년 10월\n• **광고비** 268.5백만원'}]}}]}


def test_write_memo_request_and_parse():
    seen = {}

    def fake(method, url, headers, payload, timeout):
        seen.update(method=method, url=url, headers=headers, payload=payload)
        return OK
    out, used = gm.write_memo('광고비 268.5백만원 (+23.4%)', 'KEY', model='m1', transport=fake)
    assert out.startswith('■') and '**' not in out and used == 'm1'
    assert seen['method'] == 'POST' and seen['url'].endswith('/models/m1:generateContent') and seen['headers']['x-goog-api-key'] == 'KEY'
    assert '광고비 268.5백만원 (+23.4%)' in seen['payload']['contents'][0]['parts'][0]['text']


def test_404_picks_available_model():
    calls = []
    models = {'models': [
        {'name': 'models/gemini-2.0-flash', 'supportedGenerationMethods': ['generateContent']},
        {'name': 'models/gemini-3.1-flash-lite-preview', 'supportedGenerationMethods': ['generateContent']},
        {'name': 'models/gemini-3.0-flash-lite', 'supportedGenerationMethods': ['generateContent']},
        {'name': 'models/gemini-3.0-flash-lite-image', 'supportedGenerationMethods': ['generateContent']},
        {'name': 'models/text-embedding-005', 'supportedGenerationMethods': ['embedContent']},
    ]}

    def fake(method, url, headers, payload, timeout):
        calls.append(url)
        if method == 'GET':
            return models
        if '/models/old-model:' in url:
            raise gm.GeminiError('없음', 404)
        return OK
    out, used = gm.write_memo('x', 'K', model='old-model', transport=fake)
    assert used == 'gemini-3.0-flash-lite' and out.startswith('■')
    assert any(u.endswith('/models?pageSize=200') for u in calls)


def test_errors():
    with pytest.raises(gm.GeminiError):
        gm.write_memo('x', '', transport=lambda *a: {})
    with pytest.raises(gm.GeminiError):
        gm.write_memo('x', 'K', transport=lambda *a: {'candidates': []})
    with pytest.raises(gm.GeminiError):       # 404 인데 쓸 수 있는 모델도 없음
        def fake(method, *a):
            if method == 'GET':
                return {'models': []}
            raise gm.GeminiError('없음', 404)
        gm.write_memo('x', 'K', transport=fake)


def test_config():
    assert gm.load_config({}) == (None, gm.DEFAULT_MODEL)
    assert gm.load_config({'GEMINI_API_KEY': ' k ', 'GEMINI_MODEL': 'x'}) == ('k', 'x')


def test_custom_prompt():
    """prompt 를 넘기면 그 지시문, 안 넘기면 PROMPT"""
    seen = {}

    def fake(method, url, headers, payload, timeout):
        seen['text'] = payload['contents'][0]['parts'][0]['text']
        return OK
    gm.write_memo('근거숫자', 'K', model='m1', transport=fake, prompt='지시문\n')
    assert seen['text'] == '지시문\n근거숫자'
    gm.write_memo('근거숫자', 'K', model='m1', transport=fake)       # 기본 = 이 대시보드 리뷰 지시문
    assert seen['text'].startswith(gm.PROMPT) and '앱 이용자 누적' in gm.PROMPT


def test_prompts():
    """메모(추이) · 첫구매 진단 리뷰 지시문 — app.py 가 요청 kind 로 고른다"""
    assert gm.PROMPTS['memo'] is gm.PROMPT and gm.PROMPTS['diag'] is gm.PROMPT_DIAG
    for p in gm.PROMPTS.values():
        assert p.rstrip().endswith('[근거]') and '앱 이용자 누적' in p
    assert '계절요일보정' in gm.PROMPT_DIAG and '> 확인:' in gm.PROMPT_DIAG and '→ 확인:' in gm.PROMPT
    for p in gm.PROMPTS.values():   # 형식: 판정 → 매체별(광고유형) 1) 감소 · 2) 증가, 예시는 자리표시 숫자만(공개 저장소)
        assert '□ 매체별' in p and '1) 감소' in p and '2) 증가' in p and '□ 믹스 효과' in p and '쇼핑검색광고' in p and 'x.x백만원' in p and '몫 ' not in p


def test_network_errors_become_gemini_error(monkeypatch):
    """연결 끊김 · 이상한 응답도 GeminiError 로 — app.py 가 화면에 알림을 돌려보낼 수 있게"""
    import http.client

    def boom(exc):
        def f(*a, **k):
            raise exc
        return f
    for exc in (ConnectionResetError('reset'), http.client.RemoteDisconnected('x'), TimeoutError()):
        monkeypatch.setattr(gm, 'urlopen', boom(exc))
        with pytest.raises(gm.GeminiError):
            gm.write_memo('x', 'K', model='m1')

    class R:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return b'<html>not json</html>'
    monkeypatch.setattr(gm, 'urlopen', lambda *a, **k: R())
    with pytest.raises(gm.GeminiError):
        gm.write_memo('x', 'K', model='m1')
