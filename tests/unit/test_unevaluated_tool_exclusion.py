"""평가하지 못한 도구를 평균에서 뺀다 — '평가 불가'는 '중립 판단'이 아니다.

2026-09-29. 도구 기여를 `ticker_day` 단위로 집계하다(§7) 발견했다. 최종 신호는
도구 점수의 **평균**을 임계(`+1.3 / -0.5`)와 비교하는데, 평가하지 못한 도구가
`score 0` 으로 그 평균에 들어가고 있었다.

224 ticker_day 전수 조사에서 실제로 발동하는 '평가 불가' 경로는 셋이었다:

    외국인/공매도 복합 분석   US   160/160   한국 주식 전용 도구
    DART 공시 분석            US   160/160   한국 주식 전용 도구
    베타/상관관계 분석        KR     2/64    공통 기간 부족

`NON_DIRECTIONAL_TOOLS` 는 **도구 단위**라 이걸 표현할 수 없다. 한국 전용 도구는
도구 자체는 방향을 내지만 미국 종목에서는 낼 수 없다 — **결과 단위** 판정이 필요하다.

효과는 대칭이 아니다. 0쪽으로 희석하면 매수 임계(1.3)가 매도 임계(-0.5)보다 2.6배
멀기 때문에 **매수가 훨씬 더 억제된다.** 실측: 224 ticker_day 중 16건(7.1%)이 제외만으로
HOLD→BUY 로 바뀐다 (경계값 1.19~1.30 → 1.31~1.43, 전부 미국 종목).

여기서 고정하는 것:
  1. `evaluated is False` 는 평균에서 빠진다
  2. **'중립 관측'은 빠지지 않는다** — 가격 변동 없음, 표준편차 0, 공시 없음은
     근거가 중립이라는 판단이지 근거 부재가 아니다
  3. 제외를 숨기지 않는다 — 몇 개가 왜 빠졌는지 보고한다
  4. 남은 도구가 너무 적으면 알린다 (임계는 22개 기준으로 정합된 값이다)
  5. 희석의 비대칭성 (매수가 더 억제된다)
"""

import os
import sys

import pytest

_AGENT_DIR = os.path.join(os.path.dirname(__file__), "../../chart_agent_service")
if _AGENT_DIR not in sys.path:  # noqa: E402
    sys.path.append(_AGENT_DIR)

import analysis_tools as at  # noqa: E402


# ── 결과 단위 제외 ────────────────────────────────────────────────


def test_unevaluated_result_is_excluded_from_the_average():
    r = at._unevaluated({"tool": "dart_disclosure_analysis"}, "한국 주식 전용 도구")

    assert r["evaluated"] is False
    assert at._is_directional_result(r) is False


def test_evaluated_result_stays_in_the_average():
    assert at._is_directional_result({"tool": "rsi_analysis", "score": 3}) is True


def test_result_without_the_flag_is_included():
    """기존 도구가 플래그를 안 달아도 동작이 바뀌면 안 된다."""
    assert at._is_directional_result({"tool": "whatever"}) is True


def test_tool_level_exclusion_still_applies():
    for tool in at.NON_DIRECTIONAL_TOOLS:
        assert at._is_directional_result({"tool": tool, "score": 5}) is False


def test_unevaluated_keeps_score_zero_for_downstream_safety():
    """하류가 score 를 읽어도 안전해야 한다 — None 을 넣지 않는다."""
    r = at._unevaluated({"tool": "x"}, "데이터 부족")

    assert r["score"] == 0
    assert r["signal"] == "neutral"
    assert r["detail"] == "데이터 부족"
    # 종전 DART 경로가 쓰던 이름 — 호환 유지
    assert r["unavailable"] is True


# ── 중립 관측은 빼지 않는다 ───────────────────────────────────────


@pytest.mark.parametrize("reason", ["가격 변동 없음", "표준편차 0", "최근 30일 공시 없음"])
def test_genuine_neutral_observations_are_not_marked_unevaluated(reason):
    """이건 근거 부재가 아니라 '근거가 중립'이라는 판단이다.

    소스에서 이 세 경로가 `_unevaluated()` 로 바뀌지 않았는지 확인한다 — 바뀌면
    '안 움직였다'가 '못 봤다'로 기록되어 정보가 사라진다.
    """
    import ast
    import inspect

    src = inspect.getsource(at)
    tree = ast.parse(src)
    # 주석·docstring 을 지운 실제 코드만 본다 (설명문이 자기 자신을 만족시키지 않게)
    body = ast.unparse(tree)

    idx = body.find(reason)
    assert idx > 0, f"{reason} 경로를 찾지 못했다"
    window = body[max(0, idx - 400):idx]
    assert "_unevaluated" not in window.split("result.update")[-1], (
        f"{reason} 이 _unevaluated 로 바뀌었다 — 중립 관측을 평가 불가로 기록하면 안 된다"
    )


def test_the_three_observations_are_still_plain_updates():
    """위 테스트의 보강 — 소스에 `result.update` 형태로 남아 있어야 한다."""
    import ast
    import inspect

    body = ast.unparse(ast.parse(inspect.getsource(at)))

    for reason in ("가격 변동 없음", "표준편차 0", "최근 30일 공시 없음"):
        assert f"'detail': '{reason}'" in body or f'"detail": "{reason}"' in body, reason


# ── 희석 효과와 비대칭성 ──────────────────────────────────────────


def _avg(scores):
    return sum(scores) / len(scores) if scores else 0.0


def _signal(avg):
    if avg > at.SIGNAL_BUY_THRESHOLD:
        return "BUY"
    if avg < at.SIGNAL_SELL_THRESHOLD:
        return "SELL"
    return "HOLD"


def test_excluding_two_zeros_can_flip_hold_to_buy():
    """실측 재현 — MSFT 2026-09-05: 1.30 → 1.43, HOLD→BUY."""
    real = [1.43] * 20                       # 평가된 20개
    with_zeros = real + [0.0, 0.0]           # 한국 전용 2개가 0으로 섞인다

    assert _signal(_avg(with_zeros)) == "HOLD"
    assert _signal(_avg(real)) == "BUY"


def test_dilution_suppresses_buy_more_than_sell():
    """임계가 +1.3/-0.5 라 0쪽 희석은 매수를 2.6배 더 억제한다.

    같은 비율로 희석했을 때 임계를 넘는 데 필요한 '진짜 평균'이 얼마나 커지는지
    비교한다 — 매수 쪽이 훨씬 크다.
    """
    n, zeros = 20, 2
    keep = n / (n + zeros)                   # 희석 계수

    buy_needed = at.SIGNAL_BUY_THRESHOLD / keep
    sell_needed = at.SIGNAL_SELL_THRESHOLD / keep

    buy_gap = buy_needed - at.SIGNAL_BUY_THRESHOLD
    sell_gap = abs(sell_needed - at.SIGNAL_SELL_THRESHOLD)

    assert buy_gap > sell_gap
    ratio = buy_gap / sell_gap
    assert ratio == pytest.approx(
        abs(at.SIGNAL_BUY_THRESHOLD / at.SIGNAL_SELL_THRESHOLD), rel=1e-6
    )
    assert ratio > 2.5          # 실측 2.6배


# ── 제외를 숨기지 않는다 ──────────────────────────────────────────


def test_composite_reports_what_was_excluded():
    """몇 개로 계산한 평균인지 보이지 않으면 3개와 20개가 같아 보인다."""
    import inspect

    src = inspect.getsource(at)

    for field in ("unevaluated_tool_count", "unevaluated_tools",
                  "evaluated_sufficient", "min_evaluated_tools"):
        assert f'"{field}"' in src, f"{field} 를 보고하지 않는다"


def test_minimum_is_configurable_and_reported():
    from config import SIGNAL_MIN_EVALUATED_TOOLS

    assert 1 <= SIGNAL_MIN_EVALUATED_TOOLS <= 64


def test_insufficient_does_not_block_the_signal():
    """부족을 **알리기만** 한다 — 신호를 막으면 종목이 조용히 사라진다.

    §13 의 반대 실수를 피한다: 알림 없이 막는 것도 은폐다.
    """
    import ast
    import inspect

    body = ast.unparse(ast.parse(inspect.getsource(at)))

    assert "evaluated_sufficient" in body
    # final_signal 계산이 insufficient 를 조건으로 쓰지 않아야 한다
    assert "if insufficient" not in body
    assert "not insufficient and" not in body
