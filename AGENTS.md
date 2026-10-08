# 광고 신규 실적 대시보드 — 작업 규칙

- 구조: `dashboard.html`(화면) + `calc.js`(공식 산식) + `build_data.py`(원천 → 백업) + `app.py`(Streamlit 래퍼). 화면 틀 · 색 토큰은 ryunj/first-dashboard 와 맞춘다.
- 지표 · 분류 · 기간 규칙은 `docs/METRICS.md`가 기준이다. 산식을 바꾸면 문서 · 화면 '집계 기준' 문구 · `tests/`를 함께 고친다.
- 분석 문구는 `docs/METRICS.md`의 '분석 원칙'을 지킨다(특히 "기대치 대비"를 먼저, '앱 이용자 누적'을 원인으로 쓰지 않음).
- **공개 저장소**: 원천(xlsb · csv), `data/`, `backup/`, `.json.gz`, 실제 실적 수치(문서 · 테스트 · 화면 문구 포함)는 커밋하지 않는다. 실수치 검증값은 `tests/local/expected.json`(gitignore).
- 원천 읽기 · 분류 · 이어 붙이기는 `build_data.build()` 하나로 로컬 CLI와 Streamlit 업로드가 같이 쓴다.
- `app.py`는 `dashboard.html`의 `<script src="calc.js"></script>` 태그를 찾아 인라인한다. 이 태그를 바꾸면 `app.py`도 고친다.
- 백업 형식(`format: ad-new-dashboard-backup`, `version: 1`)을 바꾸면 이전 백업 호환을 확인한다.

## 완료 확인

```bash
python -m compileall -q app.py build_data.py tests
python -m pytest -q tests
node --test tests/*.mjs
python -c "from streamlit.testing.v1 import AppTest; at=AppTest.from_file('app.py'); at.run(); print(at.exception or 'OK')"
```

화면을 바꾸면 `python tests/make_sample.py data/sample && python build_data.py --row data/sample/sample_row.pkl data/sample/sample_row_1001.pkl`로 가짜 백업을 만들어 브라우저에서 해당 상호작용을 확인한다. 업로드를 바꾸면 `python -m streamlit run app.py`에서 원천 업로드 → 저장된 데이터에 합치기 → 새로고침 후 유지까지 확인한다.
- 원천을 올리면 서버(`build_data.build`)는 올린 파일만 백업 형태로 바꾸고, 합치기는 브라우저(`calc.js` `mergeBackup`)가 한다. 두 결과는 '한 번에 빌드'와 같아야 한다(`tests/test_calc.mjs`).
