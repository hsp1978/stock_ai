"""데이터 신선도 점검의 **범위**와 포지션 시가평가.

`docs/SYSTEM_OVERVIEW.md` §13.9: `/ops/data-health` 가 상시 `stale` 이었다.
2026-09-14 실측: 24종목 중 17건 stale — 그중 15건은 **워치리스트에서 빠진 지
한 달 넘은 종목**이었다 (마지막 분석 2026-06-20 ~ 08-04). 프로세스가 기억하는
모든 티커를 점검 대상으로 삼았기 때문이다.

경보가 항상 켜져 있으면 경보가 아니다. 그리고 그 15건에 **진짜 두 건이 묻혀
있었다**: 보유 중인 005930.KS / AAPL 이 2026-04-23 진입 이후 144일간
`current_price == entry_price`, `last_updated` 가 None 이었다 — 시가평가가 한
번도 안 됐다.

여기서 고정하는 것:
  1. 대상은 워치리스트 + 보유 포지션 + 최근 N일 내 분석 종목
  2. 제외한 종목은 **숨기지 않는다** — 사유·경과일과 함께 excluded 로 보고
  3. 각 행에 scope 를 싣는다 (왜 이 종목을 보는지)
  4. 보유 포지션은 시가평가까지 본다 — 캐시가 신선해도 포지션에 반영 안 되면
     평가액·손절은 진입가 기준으로 굳는다
  5. 호출자가 티커를 명시하면 그대로 본다 (scope=requested)
"""

import os
import sys
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

_AGENT_DIR = os.path.join(os.path.dirname(__file__), "../../chart_agent_service")
if _AGENT_DIR not in sys.path:  # noqa: E402
    sys.path.insert(0, _AGENT_DIR)

import service  # noqa: E402


def _iso(days_ago: float) -> str:
    return (datetime.now() - timedelta(days=days_ago)).isoformat()


@pytest.fixture
def env(monkeypatch):
    """워치리스트 2 / 포지션 1 / 최근분석 1 / 오래된분석 2."""
    monkeypatch.setattr(service, "_load_watchlist_files", lambda: ["PLTR", "msft"])
    monkeypatch.setattr(
        service, "get_portfolio_status",
        lambda: {"positions": {"AAPL": {"qty": 10, "entry_price": 149.96,
                                        "current_price": 149.96,
                                        "entry_date": _iso(144), "last_updated": None}}},
    )
    monkeypatch.setattr(service, "latest_results", {
        "PLTR": {"timestamp": _iso(0.1)},
        "IONQ": {"timestamp": _iso(1.0)},          # 최근 — 포함
        "241770.KQ": {"timestamp": _iso(86.0)},    # 오래됨 — 제외
        "NC": {"timestamp": _iso(41.0)},           # 오래됨 — 제외
        "GHOST": {},                               # 시각 불명 — 제외
    })
    monkeypatch.setattr(service, "DATA_HEALTH_RECENT_ANALYSIS_DAYS", 3)
    return service


# ── 범위 ──────────────────────────────────────────────────────────


def test_scope_covers_watchlist_positions_and_recent(env):
    targets, scopes, _ = service._collect_data_health_tickers()

    assert set(targets) == {"PLTR", "MSFT", "AAPL", "IONQ"}
    assert scopes["PLTR"] == "watchlist"
    assert scopes["MSFT"] == "watchlist"      # 대소문자 정규화
    assert scopes["AAPL"] == "position"
    assert scopes["IONQ"] == "recent"


def test_stale_legacy_tickers_are_excluded_with_a_reason(env):
    """조용히 빼면 '고쳤다'가 아니라 '숨겼다'가 된다."""
    _, _, excluded = service._collect_data_health_tickers()

    by_ticker = {row["ticker"]: row for row in excluded}
    assert set(by_ticker) == {"241770.KQ", "NC", "GHOST"}
    assert by_ticker["NC"]["reason"] == "analysis_older_than_window"
    assert by_ticker["NC"]["last_analyzed_days_ago"] == pytest.approx(41.0, abs=0.2)
    assert by_ticker["NC"]["window_days"] == 3
    # 시각을 못 읽은 것과 오래된 것을 구분한다
    assert by_ticker["GHOST"]["reason"] == "analysis_time_unknown"
    assert by_ticker["GHOST"]["last_analyzed_days_ago"] is None


def test_watchlist_wins_over_recent_scope(env):
    """PLTR 은 워치리스트이자 최근 분석 — 더 강한 근거로 라벨링한다."""
    _, scopes, _ = service._collect_data_health_tickers()
    assert scopes["PLTR"] == "watchlist"


def test_zero_window_keeps_only_watchlist_and_positions(env, monkeypatch):
    monkeypatch.setattr(service, "DATA_HEALTH_RECENT_ANALYSIS_DAYS", 0)
    targets, scopes, excluded = service._collect_data_health_tickers()

    assert set(targets) == {"PLTR", "MSFT", "AAPL"}
    assert "IONQ" in {row["ticker"] for row in excluded}


def test_explicit_tickers_bypass_scoping(env):
    targets, scopes, excluded = service._collect_data_health_tickers(["nc", "NC", "AMD"])

    assert targets == ["NC", "AMD"]           # 정규화 + 중복 제거
    assert scopes == {"NC": "requested", "AMD": "requested"}
    assert excluded == []


def test_watchlist_failure_does_not_empty_the_scope(env, monkeypatch):
    """워치리스트 로드가 깨져도 포지션 점검은 계속돼야 한다."""
    def boom():
        raise OSError("watchlist.txt unreadable")

    monkeypatch.setattr(service, "_load_watchlist_files", boom)
    targets, scopes, _ = service._collect_data_health_tickers()

    assert "AAPL" in targets and scopes["AAPL"] == "position"


# ── payload ───────────────────────────────────────────────────────


def _build(env, monkeypatch):
    monkeypatch.setattr(service, "get_data_cache_status",
                        lambda tickers, period=None: {"tickers": {
                            t: {"ohlcv": {"present": True, "fresh": True, "age_sec": 60,
                                          "source": "yfinance"},
                                "fundamentals": {"present": True, "fresh": True,
                                                 "data_quality": "ok"}}
                            for t in tickers}})
    monkeypatch.setattr(service, "get_news_cache_status",
                        lambda tickers: {"tickers": {t: {"present": True, "fresh": True}
                                                     for t in tickers}})
    monkeypatch.setattr(service, "_price_verification_for", lambda t: None)
    monkeypatch.setattr(service, "_persist_data_health", lambda: None)
    return service.build_data_health()


def test_payload_reports_scope_counts_and_exclusions(env, monkeypatch):
    payload = _build(env, monkeypatch)

    scope = payload["scope"]
    assert scope["counts"] == {"position": 1, "recent": 1, "watchlist": 2}
    assert scope["recent_analysis_window_days"] == 3
    assert scope["excluded_count"] == 3
    assert {row["ticker"] for row in scope["excluded"]} == {"241770.KQ", "NC", "GHOST"}
    assert payload["ticker_count"] == 4


def test_each_row_carries_its_scope(env, monkeypatch):
    rows = {row["ticker"]: row for row in _build(env, monkeypatch)["rows"]}

    assert rows["PLTR"]["scope"] == "watchlist"
    assert rows["IONQ"]["scope"] == "recent"


# ── 포지션 시가평가 ───────────────────────────────────────────────


def test_never_marked_position_is_stale_even_with_fresh_cache(env, monkeypatch):
    """캐시가 전부 신선해도 포지션에 반영 안 됐으면 신선한 게 아니다."""
    payload = _build(env, monkeypatch)
    aapl = [r for r in payload["rows"] if r["ticker"] == "AAPL"][0]

    assert aapl["severity"] == "stale"
    assert "position_never_marked_to_market" in aapl["reasons"]
    assert aapl["position_price"]["never_marked"] is True
    assert aapl["position_price"]["entry_price"] == 149.96
    # 워치리스트 종목은 멀쩡하다 — 경보가 2건으로 좁혀진다
    assert [r["ticker"] for r in payload["rows"] if r["severity"] == "stale"] == ["AAPL"]


def test_stale_position_price_is_flagged(env, monkeypatch):
    monkeypatch.setattr(
        service, "get_portfolio_status",
        lambda: {"positions": {"AAPL": {"qty": 10, "entry_price": 1.0,
                                        "current_price": 2.0,
                                        "last_updated": _iso(9.0)}}})
    aapl = [r for r in _build(env, monkeypatch)["rows"] if r["ticker"] == "AAPL"][0]

    assert aapl["severity"] == "stale"
    assert "position_price_stale" in aapl["reasons"]


def test_freshly_marked_position_is_ok(env, monkeypatch):
    monkeypatch.setattr(
        service, "get_portfolio_status",
        lambda: {"positions": {"AAPL": {"qty": 10, "entry_price": 1.0,
                                        "current_price": 2.0,
                                        "last_updated": _iso(0.01)}}})
    payload = _build(env, monkeypatch)
    aapl = [r for r in payload["rows"] if r["ticker"] == "AAPL"][0]

    assert aapl["severity"] == "ok"
    assert payload["status"] in ("ok", "degraded")   # 포지션 사유로는 안 떨어진다


def test_non_position_tickers_are_not_checked_for_mark_to_market(env, monkeypatch):
    rows = {r["ticker"]: r for r in _build(env, monkeypatch)["rows"]}

    assert rows["PLTR"]["position_price"] is None
    assert not any("position_" in reason for reason in rows["PLTR"]["reasons"])


# ── 기동 직후 워밍업 ──────────────────────────────────────────────
#
# OHLCV/뉴스 캐시는 인메모리다 (`data_collector._entry_cache`). 재시작하면
# 비워지므로, 첫 스캔 주기가 지나기 전까지 '캐시 없음'은 장애가 아니다.
# 이걸 stale 로 부르면 **재시작할 때마다 거짓 경보**가 난다.


def _empty_cache_env(monkeypatch):
    monkeypatch.setattr(service, "get_data_cache_status",
                        lambda tickers, period=None: {"tickers": {
                            t: {"ohlcv": {"present": False},
                                "fundamentals": {"present": False,
                                                 "data_quality": "missing"}}
                            for t in tickers}})
    monkeypatch.setattr(service, "get_news_cache_status",
                        lambda tickers: {"tickers": {t: {"present": False} for t in tickers}})
    monkeypatch.setattr(service, "_price_verification_for", lambda t: None)
    monkeypatch.setattr(service, "_persist_data_health", lambda t=None: None)
    monkeypatch.setattr(service, "SCAN_INTERVAL_MINUTES", 30)


def test_empty_cache_right_after_restart_is_warming_not_stale(env, monkeypatch):
    _empty_cache_env(monkeypatch)
    monkeypatch.setattr(service, "SERVICE_STARTED_AT", datetime.now() - timedelta(minutes=2))

    payload = service.build_data_health(["PLTR"])
    row = payload["rows"][0]

    assert payload["status"] == "warming"
    assert row["severity"] == "warming"
    assert "cache_not_warmed" in row["reasons"]
    assert "ohlcv_missing" not in row["reasons"]
    assert payload["warmup"]["warming"] is True
    assert payload["warming_count"] == 1


def test_empty_cache_after_the_first_scan_window_is_stale(env, monkeypatch):
    """첫 주기가 지나도 비어 있으면 그건 스캔이 안 도는 것이다."""
    _empty_cache_env(monkeypatch)
    monkeypatch.setattr(service, "SERVICE_STARTED_AT", datetime.now() - timedelta(hours=3))

    payload = service.build_data_health(["PLTR"])
    row = payload["rows"][0]

    assert payload["status"] == "stale"
    assert "ohlcv_missing" in row["reasons"]
    assert payload["warmup"]["warming"] is False


def test_warming_does_not_mask_a_never_marked_position(env, monkeypatch):
    """포지션 시가평가는 인메모리 캐시와 무관하다 — 워밍업으로 가려지면 안 된다."""
    _empty_cache_env(monkeypatch)
    monkeypatch.setattr(service, "SERVICE_STARTED_AT", datetime.now() - timedelta(minutes=1))

    payload = service.build_data_health()
    aapl = [r for r in payload["rows"] if r["ticker"] == "AAPL"][0]

    assert aapl["severity"] == "stale"
    assert "position_never_marked_to_market" in aapl["reasons"]
    assert payload["status"] == "stale"


def test_warming_status_does_not_page_the_operator(env, monkeypatch):
    """알림은 stale/degraded 에만 나간다 — 재시작마다 울리면 안 본다."""
    _empty_cache_env(monkeypatch)
    monkeypatch.setattr(service, "SERVICE_STARTED_AT", datetime.now() - timedelta(minutes=1))
    monkeypatch.setattr(service, "get_portfolio_status", lambda: {"positions": {}})
    monkeypatch.setattr(service, "_record_job_start", lambda *a, **k: "t0")
    monkeypatch.setattr(service, "_record_job_success", lambda *a, **k: None)

    sent = []
    monkeypatch.setattr(service, "_send_ops_alert",
                        lambda *a, **k: sent.append((a, k)))

    result = service.run_data_health_check()

    assert result["status"] == "warming"
    assert sent == []


def test_alert_names_the_offending_tickers(env, monkeypatch):
    """개수만 보내면 '17건 stale' 이 무시된다 — 어떤 종목이 왜인지 싣는다."""
    _empty_cache_env(monkeypatch)
    monkeypatch.setattr(service, "SERVICE_STARTED_AT", datetime.now() - timedelta(hours=3))
    monkeypatch.setattr(service, "_record_job_start", lambda *a, **k: "t0")
    monkeypatch.setattr(service, "_record_job_success", lambda *a, **k: None)

    sent = []
    monkeypatch.setattr(service, "_send_ops_alert",
                        lambda title, detail, **k: sent.append(detail))

    service.run_data_health_check()

    assert sent, "stale 인데 알림이 안 나갔다"
    assert "AAPL(position:" in sent[0]
    assert "position_never_marked_to_market" in sent[0]
