"""WebUI 공용 모듈.

`webui.py` 는 6,482 라인 단일 파일이었다 (안티패턴 #1). CLAUDE.md §6-10 대로
**한 번에 쪼개지 않고** 의존성이 낮은 순서로 뗐다 — 2026-09-12~14, 8단계:

  theme.py        CSS 토큰 (순수 문자열, 의존성 0)
  api_client.py   agent-api 호출 + local_engine 이중 경로 + get_chart_url
  format.py       가격·숫자 표기          market.py  지수·환율·기간 프리셋
  tickers.py      워치리스트·티커 해석    components.py  차트 레이아웃·칩·신호 pill
  export.py       리포트 원본 내보내기    korean_optional.py  한국장 모듈 게이트
  pages/          화면 17개

남은 `webui.py` 는 부팅(설정·테마) + 내비게이션 + 커맨드바 + 라우팅이다.

## 새 페이지를 뗄 때

`scripts/extract_webui_page.py` 를 쓴다. 함수의 자유변수를 AST 로 뽑아 필요한
import 만 생성하고, **webui 로컬 함수·전역을 참조하면 거부**한다 (먼저 공용
모듈로 올리라는 신호).

검증은 4단이다 (§13.9a). 2~3단만으로는 부족하다 — 함수가 반토막 나도
`ast.parse` 는 통과했고, import 가 빠져도 모듈 import 는 통과했다:

  1. 분리 전 HEAD 와 최상위 심볼 집합 diff
  2. `pytest` + `ruff check .`
  3. 배포 컨테이너에서 `runpy.run_path('/app/stock_analyzer/webui.py')`
  4. **렌더 함수 직접 호출** — 실행해야만 드러나는 NameError 를 여기서 잡는다

화면 확인도 브라우저로 한다. Streamlit 은 스크립트가 죽어도 HTTP 200 이다 (§13-5).
"""
