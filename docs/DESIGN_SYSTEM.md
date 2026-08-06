# Stock AI 디자인 시스템 v1.0

> 원본은 `Stock AI 디자인 시스템 (standalone).html` (4.1MB, 폰트 임베드 번들 —
> 리포지토리에는 넣지 않는다). 이 문서는 구현에 필요한 규격만 추린 것이다.
> 토큰 정합은 `tests/unit/test_design_system.py`가 고정한다.

## 설계 원칙

1. **숫자가 주인공** — 가격·등락률은 tabular mono로, 라벨보다 2단계 이상 크고 밝게.
2. **색은 신호일 때만** — 상승·하락·액션 3가지 의미에만. 장식용 색·그라디언트 금지.
3. **면 대신 선** — 카드 남용을 줄이고 1px 구분선과 여백으로 그룹을 만든다. 그림자는 오버레이에만.
4. **예측 가능한 밀도** — 모든 간격은 4px 배수. 컨트롤 높이는 32/36/40 세 가지만.

## 토큰 (`webui.py` `:root`에 이식됨)

```css
/* surface */
--bg-canvas:#0A0C11;  --bg-surface:#11151C;
--bg-raised:#171D26;  --bg-inset:#06080C;
/* text */
--text-hi:#EDF1F7;  --text-mid:#9BA6B5;  --text-low:#6A7482;
/* border */
--border-subtle:#1F2733;  --border-strong:#2C3745;
/* semantic */
--accent:#6D7CFF;  --accent-soft:rgba(109,124,255,.16);
--up:#2BD98A;  --down:#FF6B6B;  --warn:#F5B14C;  --info:#4CB8F5;
/* type */
--font-ui:'Pretendard Variable',Pretendard,sans-serif;
--font-num:'JetBrains Mono',monospace;
/* space (4px base) */
--sp-1:4px; --sp-2:8px; --sp-3:12px; --sp-4:16px; --sp-5:24px; --sp-6:40px; --sp-7:64px;
/* radius */
--r-tag:4px; --r-ctl:6px; --r-card:10px; --r-pill:999px;
/* control height */
--h-sm:32px; --h-md:36px; --h-lg:40px;
/* motion */
--dur:120ms; --ease:cubic-bezier(.2,.6,.2,1);
```

**한국 시장 규칙**: 국내는 상승=적색 관습이 있으나 미국/한국 통합 화면이므로 기본값은
green-up으로 둔다. **색만으로 방향을 전달하지 말고 항상 ▲/▼ 기호를 함께 출력한다.**

### 레거시 별칭

`webui.py`는 6,000줄대 단일 파일이라 CSS를 한 번에 치환하지 않는다(CLAUDE.md #10).
`--L0`, `--on-surface`, `--buy` 등 구 토큰은 새 토큰을 가리키는 별칭으로 남아 있다.
신규 코드는 새 토큰을 쓴다.

## 타이포그래피

| 토큰 | 크기/행간/굵기 | 색 |
|---|---|---|
| display | 28 / 34 / 700 | text-hi |
| heading-lg | 20 / 26 / 700 | text-hi |
| heading-sm | 15 / 20 / 600 | text-hi |
| body | 14 / 22 / 400 | text-mid |
| label | 11 / 16 / 600 · +.1em | text-low |
| num-xl | 30 / 36 / 600 · tabular | text-hi |
| num-md | 17 / 24 / 600 | text-hi / up / down |
| num-sm | 13 / 18 / 500 | text-mid |

UI/본문은 Pretendard Variable(400/500/600/700만), 수치·티커·대문자 라벨은
JetBrains Mono + `font-variant-numeric: tabular-nums` 필수.

## 레이아웃

- 사이드바 264px (접힘 56px), 콘텐츠 최대폭 1440px, 좌우 패딩 32px
- 지수 타일 그리드: `repeat(auto-fit, minmax(180px,1fr))`, gap 12
- KPI 행: 6열 고정, 1280px 이하 3열

## 컴포넌트

| 컴포넌트 | 규격 |
|---|---|
| **IndexTile** | h76 · pad 14/16 · r10 · gap 12 · 라벨 11 / 가격 19 / 등락 12 좌측 정렬 · states default/selected/hover |
| **StatCell** | 카드 대신 1px 분할 행 — 6열, 세로 구분선, 라벨 11 / 값 26 |
| **Button** | h36 · pad 0 16 · r6 · 13/600. Primary는 화면당 1개. 파괴적 액션은 확인 필수 |
| **Input·Select** | h36 · bg-inset · r6 · focus ring 2px accent/40 |
| **TickerChip** | h28 · r4 · **티커 우선**, 시장 코드는 색 배지, 회사명은 툴팁 |
| **StatusBadge** | h24 · r999 · dot 6px |
| **ChartPanel** | 플롯 bg-inset · 그리드 1px #161C25 · 라인 2px · 라벨 12 mono |
| **DataTable** | 행 h44 · 헤더 h40 sticky · 숫자 우측 정렬 tabular · zebra 없음, 1px 구분선 |

**SidebarNav**: 라디오 목록이 아닌 진짜 내비 항목(h36 · 13/500). 3그룹
(ANALYSIS/OPERATIONS/TRADING), 그룹 헤더는 11px mono 대문자, 접기 지원.
선택 = accent-soft 배경 + **좌측 2px accent 바**(색만으로 표현하지 않음).
조작 패널(스캔·GPU·모델)은 사이드바에서 분리해 상단 커맨드바로.

## Streamlit 구현 시 주의

명세를 CSS로 옮길 때 Streamlit 특유의 함정이 있다. 아래는 실제로 겪은 것들이다.

1. **`st.markdown`으로 만든 래퍼 div는 위젯을 감싸지 못한다.** 즉시 닫히고 위젯은
   형제로 붙는다. 위젯 스코프는 **key 클래스**(`.st-key-<key>`)를 쓴다.
   → key는 CSS-safe해야 한다 (`^GSPC` → `_GSPC`).
2. **버튼 라벨은 중간 flex 컨테이너가 가운데 정렬한다.** 버튼의 `justify-content`만으로는
   부족하고, 내부 `div`/`span`/`stMarkdownContainer`/`p`까지 폭 100% + 좌측 정렬해야 한다.
3. **Streamlit 스크립트는 위에서 아래로 실행된다.** `with st.sidebar:`가 호출하는 헬퍼가
   아래에 정의돼 있으면 NameError로 앱이 죽는다 (import만으로는 안 드러난다).
4. **`st.dataframe`은 canvas 렌더**라 CSS로 행 높이를 못 준다 → `row_height` 파라미터.
5. **HTTP 200은 정상을 뜻하지 않는다.** 스크립트가 죽어도, CSS가 안 먹어도 200이다.
   화면 변경 후에는 브라우저로 확인한다.
