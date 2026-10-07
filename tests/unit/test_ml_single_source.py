"""ML 단일 소스 테스트 — 화면(/ml)과 판정(ML Specialist)이 같은 결과를 본다.

2026-10-02 GLW: 멀티에이전트 판정은 ml_pipeline_fix 의 DOWN 41.4% 로 매도 표를
냈는데, 같은 시각 /ml(화면·내보내기)은 ml_predictor 의 UP 75.1% 를 보여줬다.
두 파이프라인은 피처·하이퍼파라미터가 달라 같은 데이터에서 방향이 갈린다.
"""

import os
import sys

import pandas as pd

_ANALYZER_DIR = os.path.join(os.path.dirname(__file__), "../../stock_analyzer")
_AGENT_DIR = os.path.join(os.path.dirname(__file__), "../../chart_agent_service")
for _d in (_ANALYZER_DIR, _AGENT_DIR):
    if _d not in sys.path:  # noqa: E402
        sys.path.insert(0, _d)

import ml_pipeline_fix  # noqa: E402
import ml_predictor  # noqa: E402
import service  # noqa: E402


def _empty(ticker, df, debug=False):
    return {"ticker": ticker, "models": {}, "ensemble": {"model_count": 0},
            "warnings": ["학습 데이터 부족: 10개"]}


def _ok(ticker, df, debug=False):
    return {"ticker": ticker, "models": {}, "warnings": [],
            "ensemble": {"model_count": 4, "prediction": "DOWN", "up_probability": 0.414}}


def test_primary_pipeline_result_is_tagged(monkeypatch):
    monkeypatch.setattr(ml_pipeline_fix, "enhanced_ml_ensemble", _ok)
    result = ml_pipeline_fix.decision_ml_prediction("GLW", pd.DataFrame())
    assert result["pipeline"] == "ml_pipeline_fix"
    assert result["ensemble"]["prediction"] == "DOWN"


def test_fallback_is_tagged_with_reason(monkeypatch):
    """모델 0개 폴백은 숨기지 않는다 — 어느 파이프라인이 답했는지와 사유를 남긴다."""
    monkeypatch.setattr(ml_pipeline_fix, "enhanced_ml_ensemble", _empty)
    monkeypatch.setattr(
        ml_predictor, "run_ml_prediction",
        lambda t, df, ensemble=True: {"models": {}, "ensemble": {"model_count": 5}},
    )
    result = ml_pipeline_fix.decision_ml_prediction("GLW", pd.DataFrame())
    assert result["pipeline"] == "ml_predictor_fallback"
    assert result["fallback_reason"] == ["학습 데이터 부족: 10개"]
    assert any("폴백" in w for w in result["warnings"])


def test_failed_fallback_returns_primary_result(monkeypatch):
    monkeypatch.setattr(ml_pipeline_fix, "enhanced_ml_ensemble", _empty)
    monkeypatch.setattr(
        ml_predictor, "run_ml_prediction",
        lambda t, df, ensemble=True: {"models": {}, "ensemble": {"model_count": 0}},
    )
    result = ml_pipeline_fix.decision_ml_prediction("GLW", pd.DataFrame())
    assert result["pipeline"] == "ml_pipeline_fix"
    assert result["ensemble"]["model_count"] == 0


def test_ml_endpoint_uses_decision_pipeline(monkeypatch):
    """/ml 이 판정과 다른 함수를 부르면 화면과 판정이 다시 갈라진다."""
    calls = []

    def fake(ticker, df):
        calls.append(ticker)
        return {"pipeline": "ml_pipeline_fix", "ensemble": {"prediction": "DOWN"}}

    monkeypatch.setattr(service, "fetch_ohlcv", lambda t: pd.DataFrame())
    monkeypatch.setattr(service, "calculate_indicators", lambda df: df)
    monkeypatch.setattr(service, "decision_ml_prediction", fake)
    result = service.get_ml_prediction("glw")
    assert calls == ["GLW"]
    assert result["pipeline"] == "ml_pipeline_fix"


def test_ml_specialist_uses_decision_pipeline():
    """MLSpecialist 가 같은 함수를 import 한다 — 소스 수준 고정."""
    import inspect

    import multi_agent

    src = inspect.getsource(multi_agent.MLSpecialist.analyze)
    assert "decision_ml_prediction" in src
    assert "enhanced_ml_ensemble(" not in src
