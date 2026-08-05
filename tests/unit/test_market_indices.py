"""시장 지수 바 구성 테스트 (엔/위안 환율 추가 + 차트 기간).

webui.py는 streamlit 의존이라 import가 무겁다. 순수 상수/맵만 뽑아 검증한다.
"""

import ast
import os

_WEBUI = os.path.join(os.path.dirname(__file__), "../../stock_analyzer/webui.py")


def _literal(name: str):
    """webui.py를 실행하지 않고 모듈 최상위 리터럴 대입을 읽는다."""
    tree = ast.parse(open(_WEBUI, encoding="utf-8").read())
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == name:
                    return ast.literal_eval(node.value)
    raise AssertionError(f"{name} 정의를 찾지 못함")


def _all_items():
    indices = _literal("MARKET_INDICES")
    return [item for group in indices.values() for item in group["items"]]


def _symbols():
    return [sym for sym, _, _ in _all_items()]


# ── 신규 환율 ───────────────────────────────────────────────────


def test_jpy_included():
    assert "JPY=X" in _symbols(), "엔화 환율 누락"


def test_cny_included():
    assert "CNY=X" in _symbols(), "위안화 환율 누락"


def test_krw_still_present():
    """기존 원달러가 사라지면 안 된다."""
    assert "USDKRW=X" in _symbols()


def test_fx_group_holds_currencies():
    indices = _literal("MARKET_INDICES")
    fx = indices.get("fx")
    assert fx, "FX 그룹 없음"
    syms = [s for s, _, _ in fx["items"]]
    assert syms == ["USDKRW=X", "JPY=X", "CNY=X"]


def test_cny_uses_finer_decimals():
    """USD/CNY는 7.x 대라 소수 2자리면 변동이 뭉갠다."""
    decimals = {sym: d for sym, _, d in _all_items()}
    assert decimals["CNY=X"] >= 3
    assert decimals["JPY=X"] == 2


def test_kr_indices_intact():
    """지수는 지수 그룹에 그대로 남아야 한다."""
    indices = _literal("MARKET_INDICES")
    kr = [s for s, _, _ in indices["kr_market"]["items"]]
    assert kr == ["^KS11", "^KQ11"]


def test_no_duplicate_symbols():
    syms = _symbols()
    assert len(syms) == len(set(syms)), f"중복 심볼: {syms}"


def test_every_item_is_symbol_name_decimals():
    for item in _all_items():
        assert len(item) == 3, f"형식 불일치: {item}"
        sym, name, decimals = item
        assert isinstance(sym, str) and sym
        assert isinstance(name, str) and name
        assert isinstance(decimals, int) and 0 <= decimals <= 6


# ── 차트 기간 ───────────────────────────────────────────────────


def test_chart_periods_valid_for_yfinance():
    periods = _literal("_INDEX_PERIODS")
    valid = {"1d", "5d", "1mo", "3mo", "6mo", "1y", "2y", "5y", "10y", "ytd", "max"}
    assert set(periods.values()) <= valid, f"yfinance 미지원 기간: {periods}"


def test_chart_period_labels_are_korean():
    periods = _literal("_INDEX_PERIODS")
    assert "6개월" in periods and periods["6개월"] == "6mo"
