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


def test_fx_is_krw_based():
    """국내 사용자 관점 — '1달러가 몇 원'으로 읽어야 한다."""
    indices = _literal("MARKET_INDICES")
    fx = indices.get("fx")
    assert fx, "FX 그룹 없음"
    syms = [s for s, _, _ in fx["items"]]
    assert syms == ["KRW:USD", "KRW:JPY", "KRW:CNY"]
    names = [n for _, n, _ in fx["items"]]
    assert names == ["원/달러", "원/100엔", "원/위안"]


def test_jpy_uses_100_yen_convention():
    """국내 관례는 100엔 기준 — 1엔(약 9원)으로 표기하면 읽기 어렵다."""
    cross = _literal("KRW_CROSS")
    assert cross["KRW:JPY"]["mult"] == 100
    assert cross["KRW:CNY"]["mult"] == 1


def test_krw_cross_uses_usd_pairs():
    """원화 직접 페어는 못 쓴다 — CNYKRW=X는 1봉뿐이라 등락·차트가 불가하다."""
    cross = _literal("KRW_CROSS")
    bases = {t for spec in cross.values() for t in (spec["num"], spec["den"]) if t}
    assert bases == {"USDKRW=X", "JPY=X", "CNY=X"}
    assert not any("KRW=X" in str(b) and b != "USDKRW=X" for b in bases)


def test_usd_krw_needs_no_denominator():
    cross = _literal("KRW_CROSS")
    assert cross["KRW:USD"]["den"] is None


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
