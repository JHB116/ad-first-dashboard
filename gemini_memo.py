# -*- coding: utf-8 -*-
"""메모 '리뷰' 1차 초안 — Gemini (Streamlit 서버에서만 호출, 키는 st.secrets 에만)

- DA 광고 실적 대시보드 v2(jhb116/da-dashboard v2/gemini_memo.py)와 같은 방식. 지시문(PROMPT)만 이 대시보드용.
- 브라우저(dashboard.html)가 공식 산식(calc.js)으로 계산한 지금 화면의 요약 숫자(facts)만 보낸다. 원천 · 백업 데이터는 보내지 않는다.
- 키: Streamlit Cloud → Settings → Secrets 에 GEMINI_API_KEY = "..." (선택: GEMINI_MODEL = "모델 이름")
- 모델: GEMINI_MODEL 이 없으면 'gemini-flash-lite-latest'(늘 최신 Flash-Lite 를 가리키는 이름).
  그 모델이 없다고(404) 하면 이 키로 쓸 수 있는 모델 목록을 받아 Flash-Lite → Flash 순으로 골라 다시 부른다.
- 키가 없으면 화면에 버튼이 꺼져 보이고, 호출이 실패하면 이유를 알림으로 보여 준다(메모는 그대로).
"""
from __future__ import annotations

import json
import re
from typing import Any, Callable, Mapping
from http.client import HTTPException
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

DEFAULT_MODEL = 'gemini-flash-lite-latest'
BASE = 'https://generativelanguage.googleapis.com/v1beta'
MAX_FACTS = 12_000          # 보내는 근거 글자 수 상한

PROMPT = """너는 LF몰 광고 신규(가입 · 첫구매) 실적을 매일 리뷰하는 퍼포먼스 마케터다.
아래 [근거]는 '광고 신규 실적' 대시보드가 공식 산식으로 계산한 지금 화면의 숫자다(분해 · 기여 · 증감도 이미 계산돼 있다).
이것만 써서 메모의 '리뷰'(무슨 일이 있었나) 1차 초안을 한국어로 써라. 판단 기준은 첫구매거래액이다.

형식 — 아래 예시와 같은 모양으로(숫자는 예시일 뿐, 반드시 근거의 숫자를 쓴다). 전체 25줄 이내.
□ 26.mm (1~n일) 전년비 첫구매거래액 x.x백만원/일 (△nn.n%) → 나쁨(감소)
ㄴ 첫구매거래액 = 비회원UV +a% × 가입률 △b% × 가입첫구매전환율 △c% × 첫구매객단가 +d%
→ 가장 크게 끌어내린 요인은 가입률(기여율 nn%)이며, 가입첫구매전환율(기여율 nn%)이 그 다음

□ 매체별
1) 감소
쇼핑검색광고 일 △x.x백만원 (몫 nn%)
브랜드검색광고 일 △x.x백만원 (몫 nn%)
ㄴ 캠페인 ○○(네이버) △x.x백만원 — 주요인 가입첫구매전환율 a%→b%, 직전 두 달 증가 흐름 대비 감소
사이트검색광고 일 △x.x백만원 (몫 nn%)
ㄴ …
2) 증가
메시지 일 +x.x백만원 (몫 -n%)
DA(페이먼츠) 일 +x.x백만원 (몫 -nn%)

→ 확인: 확인해 볼 것 1가지

- '매체별'은 광고유형 단위다(근거의 [2) 광고유형별]). 1) 감소 · 2) 증가 모두 근거의 순서대로 전부 쓴다.
- 전체가 감소면 감소 유형 아래에, 증가면 증가 유형 아래에 근거의 [상세]를 'ㄴ 캠페인 …'으로 1~3줄 쓴다:
  어느 캠페인이 얼마나 움직였는지, 주요인(전→후 값), 흐름(직전 기간 → 이번)이 있으면 '직전 증가 · 감소 흐름 대비'처럼 맥락을 짚는다.
  '캠페인 분석 제외'인 유형(쇼핑검색광고)은 상세 없이 금액 · 몫만 쓴다.
- 둘째 줄의 요인 순위는 '요인별 기여율(큰 순)' 그대로. 전체가 증가면 '끌어올린'으로 쓴다.
- 머리말 · 맺음말 · 마크다운(**, #, -)은 쓰지 마라.

규칙
- 근거에 없는 숫자를 만들거나 계산하지 마라. 숫자 · 증감 표기(+ / △, %)는 근거 그대로 옮기고, 금액은 '일 △x.x백만원'처럼 써도 된다(일평균일 때).
- '문제'는 기여율이 가장 큰 요인으로 판단한다(요인 증감률 크기만으로 판단하지 않는다). 기여율은 첫구매거래액 변화 중 그 요인 몫이고 합이 100%다. 기여율을 요인 증감률과 섞어 쓰지 마라. 기여율이 생략돼 있으면 요인 증감률로만 쓴다.
- 첫구매는 총결제 기준이다. 첫구매 하락 원인으로 '앱 이용자 누적'을 쓰지 마라. 원인은 단정하지 말고 '~로 보임', '(가설)'로 쓴다.
- 쿠폰 정책 변경([이벤트])이나 PAYCO/토스 프로모션 · 테스트 캠페인처럼 이벤트성으로 보이는 항목은 그렇게 짚는다.
- [참고] 이하(실적 요약 · 연도별 · 흐름)는 필요할 때만 한두 개 인용한다.

[근거]
"""

# 첫구매 진단 화면의 '리뷰' — 계절요일보정(기대치) 대비를 먼저, 요인 분해 · 매체별 근거
PROMPT_DIAG = """너는 LF몰 광고 신규(가입 · 첫구매) 실적을 매일 리뷰하는 퍼포먼스 마케터다.
아래 [근거]는 '광고 신규 실적' 대시보드 첫구매 진단 화면이 공식 산식으로 계산한 숫자다(최근 일평균 vs 계절요일보정 = 기대치,
계절요일보정이 없으면 베이스라인. 분해 · 기여 · 증감도 이미 계산돼 있다).
이것만 써서 첫구매 진단 '리뷰' 1차 초안을 한국어로 써라. 판단 기준은 첫구매거래액이다.

형식 — 아래 예시와 같은 모양으로(숫자는 예시일 뿐, 반드시 근거의 숫자를 쓴다). 전체 25줄 이내.
□ 최근 mm.dd~mm.dd 계절요일보정 대비 첫구매거래액 x.x백만원/일 (△nn.n%) → 나쁨(감소)
ㄴ 첫구매거래액 = 비회원UV +a% × 가입률 △b% × 가입첫구매전환율 △c% × 첫구매객단가 +d%
> 가장 크게 끌어내린 요인은 가입률(기여율 nn%)이며, 가입첫구매전환율(기여율 nn%)이 그 다음

□ 매체별
1) 감소
쇼핑검색광고 일 △x.x백만원 (몫 nn%)
브랜드검색광고 일 △x.x백만원 (몫 nn%)
ㄴ 캠페인 ○○(네이버) △x.x백만원 — 주요인 가입첫구매전환율 a%→b%, 직전 두 달 증가 흐름 대비 감소
사이트검색광고 일 △x.x백만원 (몫 nn%)
ㄴ …
2) 증가
메시지 일 +x.x백만원 (몫 -n%)
DA(페이먼츠) 일 +x.x백만원 (몫 -nn%)

> 확인: 확인해 볼 것 1가지

- '매체별'은 광고유형 단위다(근거의 [2) 광고유형별]). 1) 감소 · 2) 증가 모두 근거의 순서대로 전부 쓴다.
- 전체가 감소면 감소 유형 아래에, 증가면 증가 유형 아래에 근거의 [상세]를 'ㄴ 캠페인 …'으로 1~3줄 쓴다:
  어느 캠페인이 얼마나 움직였는지, 주요인(전→후 값), 흐름(직전 기간 → 이번)이 있으면 '직전 증가 · 감소 흐름 대비'처럼 맥락을 짚는다.
  '캠페인 분석 제외'인 유형(쇼핑검색광고)은 상세 없이 금액 · 몫만 쓴다.
- 둘째 줄의 요인 순위는 '요인별 기여율(큰 순)' 그대로. 전체가 증가면 '끌어올린'으로 쓴다.
- 머리말 · 맺음말 · 마크다운(**, #, -)은 쓰지 마라.

규칙
- 근거에 없는 숫자를 만들거나 계산하지 마라. 숫자 · 증감 표기(+ / △, %)는 근거 그대로 옮기고, 금액은 '일 △x.x백만원'처럼 써도 된다(일평균일 때).
- "기대치 대비"로 판정한다. "개선 없음"은 "유지"가 아니다 — 계절요일보정을 못 넘으면 "계절요일보정 대비 △x%"로 쓴다.
- '문제'는 기여율이 가장 큰 요인으로 판단한다(요인 증감률 크기만으로 판단하지 않는다). 기여율은 첫구매거래액 변화 중 그 요인 몫이고 합이 100%다. 기여율을 요인 증감률과 섞어 쓰지 마라. 기여율이 생략돼 있으면 요인 증감률로만 쓴다.
- 첫구매는 총결제 기준이다. 첫구매 하락 원인으로 '앱 이용자 누적'을 쓰지 마라. 구성 효과(브랜드/기획전 · 캠페인 · 이벤트)를 먼저 의심하고,
  남는 내부 효과만 트래킹 이슈(앱 결제 귀속 끊김 등) 가능성으로 쓴다. 원인은 단정하지 말고 '~로 보임', '(가설)'로 쓴다.
- PAYCO/토스 프로모션 · 테스트 캠페인 같은 이벤트성 스파이크는 따로 짚는다. * 표시 값은 추정 기대치라고 밝힌다.
- [참고] 이하(카드 · 자동 리뷰)는 필요할 때만 한두 개 인용한다.

[근거]
"""
PROMPTS = {'memo': PROMPT, 'diag': PROMPT_DIAG}

Transport = Callable[[str, str, dict, dict | None, float], dict]


class GeminiError(Exception):
    """사용자에게 보여 줄 수 있는 짧은 오류 (code = HTTP 상태, 없으면 0)"""

    def __init__(self, msg: str, code: int = 0):
        super().__init__(msg)
        self.code = code


def load_config(secrets: Mapping[str, Any] | None) -> tuple[str | None, str]:
    def get(k):
        try:
            v = secrets.get(k) if secrets is not None else None
        except Exception:      # secrets.toml 이 아예 없을 때
            v = None
        return str(v).strip() if v else None
    return get('GEMINI_API_KEY'), get('GEMINI_MODEL') or DEFAULT_MODEL


def _transport(method: str, url: str, headers: dict, payload: dict | None, timeout: float) -> dict:
    data = json.dumps(payload).encode('utf-8') if payload is not None else None
    req = Request(url, data=data, headers=headers, method=method)
    try:
        with urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode('utf-8'))
    except HTTPError as e:
        try:
            body = e.read().decode('utf-8', 'replace')
        except Exception:
            body = ''
        if 'API_KEY_INVALID' in body or 'API key not valid' in body:
            raise GeminiError('Gemini 키가 올바르지 않습니다(Streamlit Secrets 의 GEMINI_API_KEY 확인).', e.code) from None
        if e.code == 429:
            raise GeminiError('Gemini 무료 사용 한도를 잠시 넘었습니다. 1분쯤 뒤에 다시 눌러 주세요.', 429) from None
        if e.code in (401, 403):
            raise GeminiError('Gemini 키에 이 기능 권한이 없습니다(AI Studio 에서 키 · 프로젝트 확인).', e.code) from None
        if e.code == 404:
            raise GeminiError('Gemini 모델을 찾지 못했습니다.', 404) from None
        raise GeminiError(f'Gemini 호출 실패(HTTP {e.code}).', e.code) from None
    except (URLError, TimeoutError, OSError, HTTPException):   # 연결 끊김 · 시간 초과 · SSL 등
        raise GeminiError('Gemini 에 연결하지 못했습니다(네트워크 · 시간 초과). 잠시 뒤 다시 눌러 주세요.') from None
    except ValueError:                                          # 응답이 JSON 이 아님
        raise GeminiError('Gemini 응답을 읽지 못했습니다.') from None


def _version(name: str) -> tuple:
    """'gemini-3.1-flash-lite-001' → (3, 1) — 높은 버전을 먼저 고르기 위한 정렬 키"""
    m = re.search(r'gemini-(\d+)(?:\.(\d+))?', name)
    return (int(m.group(1)), int(m.group(2) or 0)) if m else (0, 0)


def pick_model(api_key: str, transport: Transport | None = None) -> str:
    """이 키로 generateContent 를 쓸 수 있는 모델 중 Flash-Lite → Flash 순, 정식(미리보기 · 실험 아님) · 높은 버전 우선"""
    data = (transport or _transport)('GET', f'{BASE}/models?pageSize=200', {'x-goog-api-key': api_key}, None, 15)
    names = [m.get('name', '').split('/')[-1] for m in data.get('models', [])
             if 'generateContent' in (m.get('supportedGenerationMethods') or [])]
    names = [n for n in names if n.startswith('gemini') and not any(x in n for x in ('image', 'tts', 'audio', 'live', 'embedding', 'vision'))]
    for want in ('flash-lite', 'flash'):
        cand = [n for n in names if want in n and (want != 'flash' or 'lite' not in n)]
        stable = [n for n in cand if not any(x in n for x in ('preview', 'exp'))]
        pool = stable or cand
        if pool:
            return sorted(pool, key=lambda n: (_version(n), 'latest' in n, -len(n)), reverse=True)[0]
    if names:
        return sorted(names, key=_version, reverse=True)[0]
    raise GeminiError('이 Gemini 키로 쓸 수 있는 텍스트 모델이 없습니다(AI Studio 에서 키 · 프로젝트 확인).', 404)


def _generate(facts: str, api_key: str, model: str, transport: Transport | None, prompt: str = PROMPT) -> str:
    url = f'{BASE}/models/{model}:generateContent'
    headers = {'Content-Type': 'application/json', 'x-goog-api-key': api_key}
    payload = {'contents': [{'role': 'user', 'parts': [{'text': prompt + facts}]}],
               'generationConfig': {'temperature': 0.3, 'maxOutputTokens': 2048}}
    data = (transport or _transport)('POST', url, headers, payload, 30)
    try:
        parts = data['candidates'][0]['content']['parts']
        text = ''.join(p.get('text', '') for p in parts).strip()
    except (KeyError, IndexError, TypeError):
        raise GeminiError('Gemini 응답을 읽지 못했습니다.') from None
    if not text:
        raise GeminiError('Gemini 가 빈 답을 보냈습니다.')
    return text.replace('**', '')


def write_memo(facts: str, api_key: str, model: str = DEFAULT_MODEL,
               transport: Transport | None = None, prompt: str = PROMPT) -> tuple[str, str]:
    """→ (메모 글, 실제로 쓴 모델). 모델이 없으면(404) 쓸 수 있는 모델을 골라 한 번 더 부른다
    prompt: 근거 앞에 붙는 지시문(기본은 v2 요약 시트용). 기존 대시보드(dashboard.py)는 시트별 지시문을 넘긴다."""
    if not api_key:
        raise GeminiError('Gemini 키가 설정되지 않았습니다.')
    facts = str(facts or '')[:MAX_FACTS]
    try:
        return _generate(facts, api_key, model, transport, prompt), model
    except GeminiError as e:
        if e.code != 404:
            raise
    alt = pick_model(api_key, transport)
    if alt == model:
        raise GeminiError(f'Gemini 모델({model})을 쓸 수 없습니다.', 404)
    return _generate(facts, api_key, alt, transport, prompt), alt
