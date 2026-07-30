"""
pykrx 외국인/공매도 + DART 공시 분석 도구 단위 테스트 (P2)

테스트 시나리오:
- 외국인 소진율 높고 상승 → BUY 신호
- 공매도 비율 높고 상승 → SELL 신호
- DART 호재 공시 우세 → BUY 신호
- DART 악재 공시 우세 → SELL 신호
- DART_API_KEY 없음 → neutral 안전 응답
- 미국 주식 → "한국 주식 전용" neutral 반환
"""

import os
import sys
from unittest.mock import patch

import pandas as pd

_AGENT_DIR = os.path.join(os.path.dirname(__file__), "../../chart_agent_service")
if _AGENT_DIR not in sys.path:  # noqa: E402
    sys.path.insert(0, _AGENT_DIR)

from analysis_tools import AnalysisTools  # noqa: E402


def _make_ohlcv(n: int = 50) -> pd.DataFrame:
    idx = pd.date_range("2025-01-01", periods=n, freq="B")
    return pd.DataFrame(
        {"Open": 50_000, "High": 51_000, "Low": 49_000, "Close": 50_000, "Volume": 1_000_000},
        index=idx,
    )


# ── pykrx 외국인/공매도 도구 ─────────────────────────────────────────


def test_institutional_flow_us_stock_neutral():
    """미국 주식 → 한국 전용 도구이므로 neutral."""
    tools = AnalysisTools("AAPL", _make_ohlcv())
    result = tools.institutional_flow_analysis()
    assert result["signal"] == "neutral"
    assert "한국" in result["detail"]


def test_institutional_flow_high_foreign_buy():
    """외국인 소진율 높고 상승 → BUY 신호."""
    mock_foreign = {"exhaustion_rate": 92.0, "rate_change": 1.5, "trend": "increasing", "score": 4}
    mock_short = {"short_balance": 100, "short_ratio": 0.5, "ratio_change": -0.1, "trend": "decreasing", "score": 2}

    tools = AnalysisTools("005930.KS", _make_ohlcv())
    with patch("data_sources.pykrx_source.PykrxSource.get_foreign_holding_info", return_value=mock_foreign), \
         patch("data_sources.pykrx_source.PykrxSource.get_short_selling_info", return_value=mock_short):
        result = tools.institutional_flow_analysis()

    assert result["signal"] == "buy"
    assert result["score"] > 0


def test_institutional_flow_high_short_sell():
    """공매도 비율 높고 상승 → SELL 신호."""
    mock_foreign = {"exhaustion_rate": 40.0, "rate_change": -0.5, "trend": "decreasing", "score": 0}
    mock_short = {"short_balance": 5_000_000, "short_ratio": 6.0, "ratio_change": 0.8, "trend": "increasing", "score": -4}

    tools = AnalysisTools("005380.KS", _make_ohlcv())
    with patch("data_sources.pykrx_source.PykrxSource.get_foreign_holding_info", return_value=mock_foreign), \
         patch("data_sources.pykrx_source.PykrxSource.get_short_selling_info", return_value=mock_short):
        result = tools.institutional_flow_analysis()

    assert result["signal"] == "sell"
    assert result["score"] < 0


# ── DART 공시 분석 도구 ─────────────────────────────────────────────


def test_dart_disclosure_us_stock_neutral():
    """미국 주식 → 한국 전용 도구이므로 neutral."""
    tools = AnalysisTools("AAPL", _make_ohlcv())
    result = tools.dart_disclosure_analysis()
    assert result["signal"] == "neutral"
    assert "한국" in result["detail"]


def test_dart_no_api_key_neutral():
    """DART_API_KEY 없음 → neutral 안전 응답."""
    tools = AnalysisTools("005930.KS", _make_ohlcv())
    with patch.dict(os.environ, {"DART_API_KEY": ""}, clear=False):
        result = tools.dart_disclosure_analysis()
    assert result["signal"] == "neutral"
    assert result["score"] == 0


def test_dart_positive_disclosures_buy():
    """호재 공시 우세 → BUY 신호."""
    mock_disclosures = [
        {"report_nm": "자사주 취득 결정", "classified": "positive", "rcept_no": "1", "rcept_dt": "20260514", "corp_name": "삼성전자"},
        {"report_nm": "신규 계약 체결", "classified": "positive", "rcept_no": "2", "rcept_dt": "20260513", "corp_name": "삼성전자"},
        {"report_nm": "배당금 지급 결정", "classified": "positive", "rcept_no": "3", "rcept_dt": "20260512", "corp_name": "삼성전자"},
        {"report_nm": "사업보고서", "classified": "neutral", "rcept_no": "4", "rcept_dt": "20260511", "corp_name": "삼성전자"},
    ]
    tools = AnalysisTools("005930.KS", _make_ohlcv())
    with patch("dart_client.fetch_recent_disclosures", return_value=mock_disclosures):
        result = tools.dart_disclosure_analysis()

    assert result["signal"] == "buy"
    assert result["score"] > 0
    assert result["positive"] == 3


def test_dart_negative_disclosures_sell():
    """악재 공시 우세 → SELL 신호."""
    mock_disclosures = [
        {"report_nm": "유상증자 결정", "classified": "negative", "rcept_no": "1", "rcept_dt": "20260514", "corp_name": "테스트"},
        {"report_nm": "횡령 사실 확인", "classified": "negative", "rcept_no": "2", "rcept_dt": "20260513", "corp_name": "테스트"},
        {"report_nm": "영업정지 처분", "classified": "negative", "rcept_no": "3", "rcept_dt": "20260512", "corp_name": "테스트"},
    ]
    tools = AnalysisTools("005380.KS", _make_ohlcv())
    with patch("dart_client.fetch_recent_disclosures", return_value=mock_disclosures):
        result = tools.dart_disclosure_analysis()

    assert result["signal"] == "sell"
    assert result["score"] < 0
    assert result["negative"] == 3


# ── DART classify_disclosure 단위 테스트 ─────────────────────────────

def test_classify_disclosure_positive():
    """호재 키워드 포함 → positive."""
    from dart_client import classify_disclosure
    assert classify_disclosure("자사주 취득 결정") == "positive"
    assert classify_disclosure("배당금 지급 결정") == "positive"


def test_classify_disclosure_negative():
    """악재 키워드 포함 → negative."""
    from dart_client import classify_disclosure
    assert classify_disclosure("불성실공시법인 지정") == "negative"
    assert classify_disclosure("유상증자 결정") == "negative"


def test_classify_disclosure_neutral():
    """키워드 없으면 → neutral."""
    from dart_client import classify_disclosure
    assert classify_disclosure("사업보고서") == "neutral"
    assert classify_disclosure("주요사항보고서") == "neutral"


# ── 도구 등록 검증 ────────────────────────────────────────────────────

def test_new_tools_in_tool_map():
    """2개 신규 도구가 _tool_map에 등록됨."""
    from analysis_tools import ChartAnalysisAgent
    agent = ChartAnalysisAgent("005930.KS", _make_ohlcv())
    assert "institutional_flow_analysis" in agent._tool_map
    assert "dart_disclosure_analysis" in agent._tool_map


# ── fetch_recent_disclosures 자체 검증 (2026-07-30) ─────────────────
#
# 위 도구 테스트들은 fetch_recent_disclosures를 통째로 mock하기 때문에
# 라이브러리 호출 규약이 틀려도 통과한다. 실제로 `odr.OpenDartReader(...)`가
# 항상 AttributeError였고, 컨테이너에서는 라이브러리 자체가 없었는데도
# 둘 다 빈 리스트('공시 없음')로 뭉개져 8주간 드러나지 않았다.


class _FakeOpenDartReader:
    """실제 패키지 규약 재현: sys.modules 항목이 '클래스'다.

    따라서 `import OpenDartReader; OpenDartReader(key)`만 유효하고,
    `odr.OpenDartReader(key)`는 AttributeError가 되어야 한다.
    """

    last_kwargs: dict = {}

    def __init__(self, api_key):
        assert api_key, "api_key 없이 생성되면 안 된다"
        self.api_key = api_key

    def list(self, code, start=None, end=None, kind=None):
        type(self).last_kwargs = {"code": code, "start": start, "end": end, "kind": kind}
        if kind == "A":
            return pd.DataFrame()  # 정기공시 없음 → kind 없는 재조회로 폴백해야 한다
        return pd.DataFrame(
            [
                {
                    "rcept_no": "20260730000001",
                    "rcept_dt": "20260730",
                    "corp_name": "삼성전자",
                    "report_nm": "자사주 취득 결정",
                },
                {
                    "rcept_no": "20260730000002",
                    "rcept_dt": "20260729",
                    "corp_name": "삼성전자",
                    "report_nm": "유상증자 결정",
                },
            ]
        )


def test_fetch_disclosures_uses_correct_library_contract():
    """`import OpenDartReader` 결과를 그대로 호출해야 한다 (모듈 취급 금지)."""
    import dart_client

    with patch.dict(os.environ, {"DART_API_KEY": "dummy-key"}, clear=False), \
            patch.dict(sys.modules, {"OpenDartReader": _FakeOpenDartReader}):
        rows = dart_client.fetch_recent_disclosures("005930.KS", days_back=30)

    assert len(rows) == 2, "정기공시 0건일 때 kind 없는 재조회로 폴백해야 한다"
    assert rows[0]["classified"] == "positive"
    assert rows[1]["classified"] == "negative"
    assert _FakeOpenDartReader.last_kwargs["code"] == "005930", "'.KS' 접미사를 떼야 한다"


def test_fetch_disclosures_raises_when_library_missing():
    """라이브러리 미설치는 '공시 0건'이 아니라 DartUnavailable이어야 한다."""
    import pytest

    import dart_client

    with patch.dict(os.environ, {"DART_API_KEY": "dummy-key"}, clear=False), \
            patch.dict(sys.modules, {"OpenDartReader": None}):
        with pytest.raises(dart_client.DartUnavailable, match="미설치"):
            dart_client.fetch_recent_disclosures("005930.KS")


def test_fetch_disclosures_raises_without_api_key():
    import pytest

    import dart_client

    with patch.dict(os.environ, {"DART_API_KEY": ""}, clear=False):
        with pytest.raises(dart_client.DartUnavailable, match="DART_API_KEY"):
            dart_client.fetch_recent_disclosures("005930.KS")


def test_tool_reports_unavailable_distinctly():
    """도구 detail이 '조회 불가'와 '공시 없음'을 구분해야 한다."""
    import dart_client

    tools = AnalysisTools("005930.KS", _make_ohlcv())
    with patch.dict(os.environ, {"DART_API_KEY": "dummy-key"}, clear=False), \
            patch.object(
                dart_client,
                "fetch_recent_disclosures",
                side_effect=dart_client.DartUnavailable("OpenDartReader 미설치"),
            ):
        result = tools.dart_disclosure_analysis()

    assert result["unavailable"] is True
    assert "조회 불가" in result["detail"]
    assert result["score"] == 0

    with patch.dict(os.environ, {"DART_API_KEY": "dummy-key"}, clear=False), \
            patch.object(dart_client, "fetch_recent_disclosures", return_value=[]):
        empty = tools.dart_disclosure_analysis()

    assert empty.get("unavailable") is not True
    assert empty["detail"] == "최근 30일 공시 없음"


class _NotFoundDart:
    """DART 기업목록에 없는 종목(ETF/ETN 등) — 라이브러리가 ValueError를 낸다."""

    def __init__(self, api_key):
        pass

    def list(self, code, start=None, end=None, kind=None):
        raise ValueError(f'could not find "{code}"')


def test_unlisted_ticker_is_empty_not_unavailable():
    """ETF 등 DART 미등록 종목은 '조회 불가'가 아니라 공시 0건이어야 한다.

    영구 상태를 장애로 보고하면 매 스캔 경보가 떠 실제 장애를 가린다.
    """
    import dart_client

    with patch.dict(os.environ, {"DART_API_KEY": "dummy-key"}, clear=False), \
            patch.dict(sys.modules, {"OpenDartReader": _NotFoundDart}):
        rows = dart_client.fetch_recent_disclosures("481050.KS")

    assert rows == []


class _AuthErrorDart:
    def __init__(self, api_key):
        pass

    def list(self, code, start=None, end=None, kind=None):
        raise ValueError("invalid api key")


def test_other_value_errors_still_unavailable():
    """'could not find'가 아닌 ValueError는 여전히 조회 불가로 올린다."""
    import pytest

    import dart_client

    with patch.dict(os.environ, {"DART_API_KEY": "dummy-key"}, clear=False), \
            patch.dict(sys.modules, {"OpenDartReader": _AuthErrorDart}):
        with pytest.raises(dart_client.DartUnavailable, match="invalid api key"):
            dart_client.fetch_recent_disclosures("005930.KS")


def test_corp_code_cache_pruned(tmp_path, monkeypatch):
    """docs_cache/의 날짜별 corpCode 스냅샷(약 8MB/일)이 무한 누적되면 안 된다."""
    import dart_client

    cache = tmp_path / "docs_cache"
    cache.mkdir()
    for day in ("20260725", "20260726", "20260727", "20260728", "20260729", "20260730"):
        (cache / f"opendartreader_corp_codes_{day}.pkl").write_bytes(b"x")
    (cache / "unrelated.pkl").write_bytes(b"x")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(dart_client, "_cache_pruned", False)
    dart_client._prune_corp_code_cache()

    left = sorted(p.name for p in cache.glob("opendartreader_corp_codes_*.pkl"))
    assert left == [
        "opendartreader_corp_codes_20260729.pkl",
        "opendartreader_corp_codes_20260730.pkl",
    ], "최신 2개만 남아야 한다"
    assert (cache / "unrelated.pkl").exists(), "무관한 파일은 건드리면 안 된다"


def test_cache_prune_runs_once_per_process(tmp_path, monkeypatch):
    """정리는 프로세스당 1회 — 스캔마다 디렉터리를 훑지 않는다."""
    import dart_client

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(dart_client, "_cache_pruned", False)
    dart_client._prune_corp_code_cache()
    assert dart_client._cache_pruned is True

    calls = []
    monkeypatch.setattr(dart_client.Path, "glob", lambda self, pat: calls.append(pat) or iter(()))
    dart_client._prune_corp_code_cache()
    assert calls == [], "두 번째 호출은 즉시 반환해야 한다"
