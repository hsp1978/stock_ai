"""디자인 시스템 토큰 정합 테스트 (Stock AI 디자인 시스템 v1.0).

명세서의 CSS 변수 블록을 그대로 이식했는지 검증한다. 토큰은 손으로 고치기
쉬운 값이라, 명세와 어긋나면 화면 전체의 대비·밀도가 조용히 무너진다.
"""

import os
import re

_WEBUI = os.path.join(os.path.dirname(__file__), "../../stock_analyzer/webui.py")


def _css() -> str:
    return open(_WEBUI, encoding="utf-8").read()


def _token(name: str) -> str:
    m = re.search(rf"--{re.escape(name)}:\s*([^;]+);", _css())
    assert m, f"토큰 --{name} 정의 없음"
    return m.group(1).strip()


# ── 컬러 토큰 (DS §02) ──────────────────────────────────────────


def test_surface_tokens():
    assert _token("bg-canvas").upper() == "#0A0C11"
    assert _token("bg-surface").upper() == "#11151C"
    assert _token("bg-raised").upper() == "#171D26"
    assert _token("bg-inset").upper() == "#06080C"


def test_text_tokens():
    assert _token("text-hi").upper() == "#EDF1F7"
    assert _token("text-mid").upper() == "#9BA6B5"
    assert _token("text-low").upper() == "#6A7482"


def test_border_tokens():
    assert _token("border-subtle").upper() == "#1F2733"
    assert _token("border-strong").upper() == "#2C3745"


def test_semantic_tokens():
    assert _token("accent").upper() == "#6D7CFF"
    assert _token("up").upper() == "#2BD98A"
    assert _token("down").upper() == "#FF6B6B"
    assert _token("warn").upper() == "#F5B14C"
    assert _token("info").upper() == "#4CB8F5"


# ── 타이포 (DS §03) ─────────────────────────────────────────────


def test_font_tokens():
    assert "Pretendard" in _token("font-ui")
    assert "JetBrains Mono" in _token("font-num")


def test_inter_font_fully_replaced():
    """명세는 Pretendard/JetBrains만 쓴다 — Inter 잔재가 남으면 혼용된다."""
    assert "'Inter'" not in _css()


# ── 스페이싱·라운딩 (DS §04) ────────────────────────────────────


def test_spacing_is_4px_multiples():
    for i, expected in enumerate(["4px", "8px", "12px", "16px", "24px", "40px", "64px"], start=1):
        assert _token(f"sp-{i}") == expected, f"--sp-{i} 불일치"


def test_radius_tokens():
    assert _token("r-tag") == "4px"
    assert _token("r-ctl") == "6px"
    assert _token("r-card") == "10px"
    assert _token("r-pill") == "999px"


def test_control_heights_are_three():
    assert _token("h-sm") == "32px"
    assert _token("h-md") == "36px"
    assert _token("h-lg") == "40px"


# ── 레거시 별칭 (점진 이행) ─────────────────────────────────────


def test_legacy_aliases_map_to_new_tokens():
    """webui.py는 5,100 라인 단일 파일이라 CSS를 한 번에 치환하지 않는다.

    기존 규칙이 계속 동작하도록 별칭이 새 토큰을 가리켜야 한다.
    """
    for legacy in ("L0", "L1", "on-surface", "buy", "sell", "hold", "primary"):
        value = _token(legacy)
        assert value.startswith("var(--"), f"--{legacy}가 새 토큰을 가리키지 않음: {value}"


def test_no_hardcoded_old_palette():
    """이전 팔레트 색이 남아 있으면 신·구 색이 섞인다."""
    css = _css()
    for stale in ("#0b0e14", "#02d4a1", "#fd526f", "#aec6ff"):
        assert stale not in css, f"구 팔레트 잔존: {stale}"


# ── 컴포넌트 규격 (DS §05) ──────────────────────────────────────


def test_index_tile_height_and_radius():
    css = _css()
    assert "height: 76px" in css, "IndexTile 높이 76 규격 불일치"
    assert "padding: 14px 16px" in css, "IndexTile 패딩 14/16 규격 불일치"


def test_index_tile_css_scoped_to_widget_key():
    """`.idx-grid` 래퍼는 DOM에서 버튼을 감싸지 못한다 — st.markdown이 만든
    div는 즉시 닫히고 버튼은 형제로 붙는다. 위젯 key 클래스로 스코프해야 한다.
    실제로 이 스코프 오류 때문에 타일 CSS가 전혀 적용되지 않았다 (2026-08-06)."""
    css = _css()
    assert "idx-grid" not in css, "감싸지 못하는 래퍼 클래스 잔존"
    assert '[class*="st-key-idx_btn_"] button' in css


def test_statcell_row_is_six_columns():
    assert "grid-template-columns: repeat(6, 1fr)" in _css()


def test_period_uses_segmented_control():
    """DS §05: 기간 선택은 라디오 대신 세그먼트 컨트롤."""
    css = _css()
    assert "st.segmented_control" in css
    assert 'st.radio(\n        "기간"' not in css


# ── SidebarNav (DS §05 · §06) ───────────────────────────────────


def _webui():
    return open(_WEBUI, encoding="utf-8").read()


def test_nav_has_three_groups():
    """14개 항목을 ANALYSIS / OPERATIONS / TRADING 3그룹으로 분류."""
    src = _webui()
    for group in ("ANALYSIS", "OPERATIONS", "TRADING"):
        assert f'"{group}"' in src, f"{group} 그룹 없음"


def test_nav_covers_all_pages():
    """그룹 분류에서 페이지가 누락되면 접근 불가가 된다."""
    import ast as _ast

    tree = _ast.parse(_webui())
    groups = None
    for node in tree.body:
        if isinstance(node, _ast.Assign) and any(
            getattr(t, "id", "") == "NAV_GROUPS" for t in node.targets
        ):
            groups = _ast.literal_eval(node.value)
    assert groups, "NAV_GROUPS 정의 없음"

    pages = {p for items in groups.values() for p in items}
    routed = set(re.findall(r'page == "([^"]+)"', _webui()))
    assert routed <= pages, f"라우팅에는 있으나 내비에 없는 페이지: {routed - pages}"


def test_nav_pages_not_duplicated():
    import ast as _ast

    tree = _ast.parse(_webui())
    for node in tree.body:
        if isinstance(node, _ast.Assign) and any(
            getattr(t, "id", "") == "NAV_GROUPS" for t in node.targets
        ):
            groups = _ast.literal_eval(node.value)
            flat = [p for items in groups.values() for p in items]
            assert len(flat) == len(set(flat)), "중복 항목"
            return
    raise AssertionError("NAV_GROUPS 없음")


def test_sidebar_is_nav_only():
    """DS §06: 스캔·GPU·워치리스트 조작은 사이드바에서 분리한다."""
    src = _webui()
    sidebar_block = src[src.index("with st.sidebar:"):]
    sidebar_block = sidebar_block[: sidebar_block.index("\n\n\n")]
    for banned in ("Scan All", "GPU 사용 중지", "Restart Agent", "wl_add"):
        assert banned not in sidebar_block, f"사이드바에 조작 패널 잔존: {banned}"


def test_sidebar_width_264():
    assert "width: 264px" in _webui()


def test_selected_nav_uses_left_accent_bar():
    """선택 상태를 색만으로 표현하지 않는다 — 좌측 2px accent 바."""
    src = _webui()
    assert "border-left: 2px solid transparent" in src
    assert "border-left-color: var(--accent)" in src


def test_command_bar_exists():
    src = _webui()
    assert "def render_command_bar" in src
    assert "render_command_bar(api_get(\"/health\")" in src


# ── TickerChip · DataTable (DS §05, 3단계) ──────────────────────


def test_ticker_chip_puts_ticker_first():
    """회사 명칭을 칩 본문에 넣으면 폭이 들쭉날쭉해진다 — 명칭은 툴팁."""
    src = _webui()
    assert "def ticker_chip_html" in src
    fn = src[src.index("def ticker_chip_html"):]
    fn = fn[: fn.index("\n\ndef ")]
    assert 'title="{title}"' in fn, "명칭 툴팁 없음"
    assert "{ticker}</span>" in fn, "티커가 칩 본문에 없음"


def test_ticker_chip_has_market_badge():
    src = _webui()
    fn = src[src.index("def ticker_chip_html"):]
    fn = fn[: fn.index("\n\ndef ")]
    assert '"KR" if is_kr else "US"' in fn


def test_ticker_chip_spec_dimensions():
    css = _css()
    assert "height: 28px" in css, "TickerChip h28 규격 불일치"
    assert ".wl-chip .tc-badge" in css, "시장 배지 스타일 없음"


def test_datatable_row_height():
    """DS §05 DataTable: 행 h44."""
    assert "row_height=44" in _webui()


# ── 모듈 실행 순서 (2026-08-05 회귀) ────────────────────────────
#
# Streamlit 스크립트는 위에서 아래로 실행된다. `with st.sidebar:`가 호출하는
# 헬퍼가 그 아래에 정의돼 있으면 NameError로 앱 전체가 죽는다.
# 실제로 _css_key가 사이드바보다 아래에 있어 화면이 뜨지 않았다.


def _module_level_exec_line(src: str, marker: str) -> int:
    for i, line in enumerate(src.splitlines(), start=1):
        if line.startswith(marker):
            return i
    raise AssertionError(f"{marker} 없음")


def test_sidebar_helpers_defined_before_execution():
    import ast as _ast

    src = _webui()
    exec_line = _module_level_exec_line(src, "with st.sidebar:")
    tree = _ast.parse(src)

    defs = {
        node.name: node.lineno
        for node in tree.body
        if isinstance(node, _ast.FunctionDef)
    }

    target = next(
        (n for n in tree.body
         if isinstance(n, _ast.FunctionDef) and n.name == "render_sidebar_nav"),
        None,
    )
    assert target, "render_sidebar_nav 정의 없음"

    called = {
        n.func.id for n in _ast.walk(target)
        if isinstance(n, _ast.Call) and isinstance(n.func, _ast.Name)
    }
    late = {
        name: defs[name] for name in called
        if name in defs and defs[name] > exec_line
    }
    assert not late, (
        f"사이드바 실행({exec_line}행)보다 늦게 정의된 헬퍼: {late} — NameError로 앱이 죽는다"
    )


def test_sidebar_nav_labels_left_aligned():
    """DS §05: 내비 항목은 좌측 정렬. Streamlit 기본은 가운데라 라벨(<p>)까지
    돌려야 한다 — 버튼의 justify-content만으로는 라벨이 가운데에 남는다."""
    css = _css()
    marker = 'section[data-testid="stSidebar"] div[data-testid="stButton"] > button p'
    assert marker in css, "사이드바 버튼 라벨 정렬 규칙 없음"
    rule = css[css.index(marker):]
    rule = rule[: rule.index("}")]
    assert "text-align: left" in rule
