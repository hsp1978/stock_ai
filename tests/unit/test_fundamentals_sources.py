"""펀더멘털 다중 소스 — 죽은 소스를 '폴백'이라 부르지 않는다.

2026-09-14, 로깅을 켜자 드러난 것(#61 후속). `fundamentals failed via fmp: 403` 을
따라가 보니 문제는 FMP 하나가 아니었다. **5개 소스 중 4개가 죽어 있었다**:

  naver         `finance.naver.com/item/main.naver` 가 클라이언트 렌더링으로 바뀌어
                HTML 에 PER·PBR·EPS 문자열이 아예 없다 (HTTP 200, 119KB, 마커 0건)
  finnhub       키 미설정 → 빈 dict
  alphavantage  키 미설정 → 빈 dict
  fmp           `/api/v3/` 가 legacy 로 폐기 (유효한 키로도 403)
  yfinance      유일하게 동작 (KR 은 16/20 부분)

빈 결과는 `continue` 로 흘려서 아무 기록도 남지 않았다. 그래서 '다중 소스 폴백'이
실제로는 **yfinance 단일 소스**였다.

여기서 고정하는 것:
  1. 소스별 결말을 남긴다 — ok / not_configured / plan_restricted / no_data / error
  2. 플랜 제한(402)은 장애가 아니다 — 오류로 쌓지 않는다
  3. FMP 는 `/stable/` 엔드포인트를 쓴다
  4. naver 는 JSON API 를 쓴다
  5. dividend_yield 는 **분수로 통일**한다 (소스마다 단위가 달랐다)
"""

import os
import sys
from unittest.mock import patch

import pytest

_AGENT_DIR = os.path.join(os.path.dirname(__file__), "../../chart_agent_service")
if _AGENT_DIR not in sys.path:  # noqa: E402
    sys.path.insert(0, _AGENT_DIR)

import data_collector as dc  # noqa: E402


@pytest.fixture(autouse=True)
def clear_cache():
    dc._fundamental_cache.clear()
    yield
    dc._fundamental_cache.clear()


# ── 소스별 결말 보고 ──────────────────────────────────────────────


def _chain(monkeypatch, **outcomes):
    """각 소스의 동작을 지정한다. 값은 dict 또는 예외."""
    def make(name):
        def fetcher(ticker):
            outcome = outcomes.get(name, {})
            if isinstance(outcome, Exception):
                raise outcome
            return outcome
        return fetcher

    for name, attr in (("naver", "_fetch_naver_fundamentals"),
                       ("yfinance", "_fetch_yfinance_fundamentals"),
                       ("finnhub", "_fetch_finnhub_fundamentals"),
                       ("alphavantage", "_fetch_alphavantage_fundamentals"),
                       ("fmp", "_fetch_fmp_fundamentals")):
        monkeypatch.setattr(dc, attr, make(name))


def _full():
    """quality='full' 이 되는 최소 집합 — _FUNDAMENTAL_QUALITY_FIELDS 5개 이상."""
    return {"market_cap": 1, "pe_ratio": 2, "eps": 3, "beta": 4,
            "sector": "반도체", "industry": "메모리"}


def test_dead_sources_are_named_not_hidden(monkeypatch):
    """4개가 죽어도 '다중 소스'처럼 보이던 게 문제였다."""
    _chain(monkeypatch,
           naver={},                                   # 파서 무효화
           yfinance={"market_cap": 10, "pe_ratio": 5},  # 부분
           finnhub={},
           alphavantage={},
           fmp=dc.PlanRestricted("KRX 미포함"))
    monkeypatch.setattr(dc, "_source_needs_key", lambda name: name in ("finnhub", "alphavantage"))

    result = dc.fetch_fundamentals("005930.KS")
    status = result["_source_status"]

    assert status["yfinance"] == "ok"
    assert status["naver"] == "no_data"
    assert status["finnhub"] == "not_configured"
    assert status["alphavantage"] == "not_configured"
    assert status["fmp"] == "plan_restricted"
    assert result["_sources_ok"] == 1            # 실제로 기여한 소스는 하나뿐
    assert result["_source"] == "yfinance"


def test_plan_restriction_is_not_counted_as_an_error(monkeypatch):
    """402 는 장애가 아니다 — 오류 목록에 쌓이면 진짜 장애가 묻힌다."""
    _chain(monkeypatch, yfinance=_full(), fmp=dc.PlanRestricted("KRX 미포함"))

    result = dc.fetch_fundamentals("005930.KS")

    assert result["_errors"] == []


def test_real_errors_are_still_reported(monkeypatch):
    _chain(monkeypatch,
           naver=RuntimeError("timeout"),
           yfinance={"market_cap": 1})

    result = dc.fetch_fundamentals("005930.KS")

    assert result["_source_status"]["naver"] == "error"
    assert any("naver" in e and "timeout" in e for e in result["_errors"])


def test_source_returning_only_unusable_fields_is_marked(monkeypatch):
    """응답은 왔는데 우리가 쓰는 필드가 하나도 없는 경우 — 빈 응답과 다르다."""
    _chain(monkeypatch, naver={"someOtherField": 1}, yfinance=_full())

    status = dc.fetch_fundamentals("005930.KS")["_source_status"]

    assert status["naver"] == "no_usable_fields"     # '없음'과 구분된다


def test_sector_only_source_still_counts_as_contributing(monkeypatch):
    """sector·industry 는 품질 점수엔 안 들어가지만 리포트에 쓰인다."""
    _chain(monkeypatch, naver={"sector": "반도체"}, yfinance=_full())

    result = dc.fetch_fundamentals("005930.KS")

    assert result["_source_status"]["naver"] == "ok"
    assert result["sector"] == "반도체"


def test_chain_stops_once_quality_is_full(monkeypatch):
    _chain(monkeypatch, naver=_full(), yfinance=_full())

    status = dc.fetch_fundamentals("005930.KS")["_source_status"]

    assert status["naver"] == "ok"
    assert "finnhub" not in status                   # 더 부르지 않는다


# ── FMP stable ────────────────────────────────────────────────────


def test_fmp_uses_the_stable_endpoints(monkeypatch):
    """/api/v3/ 는 legacy 로 폐기됐다 — 유효한 키로도 403 이다."""
    called = []

    def fake_get(url, params=None, timeout=None):
        called.append(url)

        class R:
            status_code = 200

            def raise_for_status(self): pass

            def json(self): return [{"symbol": "AAPL", "marketCap": 100, "price": 5.0}]

        return R()

    monkeypatch.setattr(dc.settings, "FMP_API_KEY", "k" * 32)
    monkeypatch.setattr(dc.requests, "get", fake_get)

    dc._fetch_fmp_fundamentals("AAPL")

    assert called and all("/stable/" in url for url in called)
    assert not any("/api/v3/" in url for url in called)


def test_fmp_402_becomes_plan_restricted(monkeypatch):
    class R:
        status_code = 402

        def raise_for_status(self): raise AssertionError("402 인데 raise_for_status 로 갔다")

        def json(self): return {}

    monkeypatch.setattr(dc.settings, "FMP_API_KEY", "k" * 32)
    monkeypatch.setattr(dc.requests, "get", lambda *a, **k: R())

    with pytest.raises(dc.PlanRestricted):
        dc._fetch_fmp_fundamentals("AAPL")


def test_fmp_skips_korean_tickers_without_calling(monkeypatch):
    """KRX 심볼은 현재 플랜에서 402 확정 — 매번 때리지 않는다."""
    monkeypatch.setattr(dc.settings, "FMP_API_KEY", "k" * 32)
    monkeypatch.setattr(dc.requests, "get",
                        lambda *a, **k: pytest.fail("KR 티커로 FMP 를 호출했다"))

    with pytest.raises(dc.PlanRestricted):
        dc._fetch_fmp_fundamentals("005930.KS")


def test_fmp_without_key_returns_empty(monkeypatch):
    monkeypatch.setattr(dc.settings, "FMP_API_KEY", "")
    monkeypatch.delenv("FMP_API_KEY", raising=False)

    assert dc._fetch_fmp_fundamentals("AAPL") == {}


# ── 네이버 JSON ───────────────────────────────────────────────────


def _naver_payload():
    return {
        "stockName": "삼성전자",
        "totalInfos": [
            {"code": "lastClosePrice", "key": "전일", "value": "259,500"},
            {"code": "marketValue", "key": "시총", "value": "1,455조 7,234억"},
            {"code": "per", "key": "PER", "value": "11.17배"},
            {"code": "pbr", "key": "PBR", "value": "2.89배"},
            {"code": "eps", "key": "EPS", "value": "22,292원"},
            {"code": "dividendYieldRatio", "key": "배당수익률", "value": "0.67%"},
            {"code": "highPriceOf52Weeks", "key": "52주 최고", "value": "380,000"},
            {"code": "lowPriceOf52Weeks", "key": "52주 최저", "value": "75,300"},
        ],
    }


def _patch_naver(monkeypatch, payload):
    class R:
        def raise_for_status(self): pass

        def json(self): return payload

    monkeypatch.setattr(dc.requests, "get", lambda *a, **k: R())


def test_naver_json_fields_are_parsed(monkeypatch):
    _patch_naver(monkeypatch, _naver_payload())

    result = dc._fetch_naver_fundamentals("005930.KS")

    assert result["pe_ratio"] == 11.17
    assert result["price_to_book"] == 2.89
    assert result["eps"] == 22292.0
    assert result["dividend_yield"] == pytest.approx(0.0067)
    assert result["52w_high"] == 380000.0
    assert result["company_name"] == "삼성전자"


def test_korean_market_cap_notation_is_parsed(monkeypatch):
    """'1,455조 7,234억' — 한국 시총은 이 형태로만 온다."""
    _patch_naver(monkeypatch, _naver_payload())

    cap = dc._fetch_naver_fundamentals("005930.KS")["market_cap"]

    assert cap == 1_455_000_000_000_000 + 7_234 * 100_000_000


@pytest.mark.parametrize("raw,expected", [
    ("11.17배", 11.17),
    ("22,292원", 22292.0),
    ("0.67%", 0.67),
    ("1,455조 7,234억", 1_455_000_000_000_000 + 7_234 * 100_000_000),
    ("3억", 300_000_000),
    ("", None),
    (None, None),
])
def test_korean_number_parser(raw, expected):
    assert dc._parse_korean_number(raw) == expected


def test_naver_is_skipped_for_non_korean_tickers():
    assert dc._fetch_naver_fundamentals("AAPL") == {}


# ── 배당수익률 단위 통일 ──────────────────────────────────────────


@pytest.mark.parametrize("raw,unit,expected", [
    (0.33, "percent", 0.0033),     # yfinance: AAPL 0.33 = 0.33%
    (0.67, "percent", 0.0067),     # naver: 1% 미만 배당은 흔하다
    (1.5, "percent", 0.015),
    (0.0044, "fraction", 0.0044),  # alphavantage
    (0, "percent", 0.0),
    (None, "percent", None),
    (-1, "percent", None),
])
def test_dividend_yield_is_normalized_to_a_fraction(raw, unit, expected):
    assert dc._as_yield_fraction(raw, unit) == expected


def test_unit_is_declared_not_guessed():
    """값 크기로 추측하면 0.67% 가 67% 로 읽힌다 — 실제로 그렇게 틀렸다."""
    assert dc._as_yield_fraction(0.67, "percent") == pytest.approx(0.0067)
    assert dc._as_yield_fraction(0.67, "fraction") == 0.67
    with pytest.raises(ValueError):
        dc._as_yield_fraction(0.67, "auto")


def test_fmp_no_longer_reports_a_dividend_amount_as_yield(monkeypatch):
    """lastDividend 는 금액($1.06)이다 — 종전엔 수익률 106% 로 보고됐다."""
    class R:
        status_code = 200

        def raise_for_status(self): pass

        def json(self): return [{"symbol": "AAPL", "marketCap": 100,
                                 "lastDividend": 1.06, "price": 5.0}]

    monkeypatch.setattr(dc.settings, "FMP_API_KEY", "k" * 32)
    monkeypatch.setattr(dc.requests, "get", lambda *a, **k: R())

    assert "dividend_yield" not in dc._fetch_fmp_fundamentals("AAPL")
