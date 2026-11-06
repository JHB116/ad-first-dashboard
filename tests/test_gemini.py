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
