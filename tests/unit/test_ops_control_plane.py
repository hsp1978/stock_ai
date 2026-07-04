import os
import sys

_AGENT_DIR = os.path.join(os.path.dirname(__file__), "../../chart_agent_service")
if _AGENT_DIR not in sys.path:  # noqa: E402
    sys.path.insert(0, _AGENT_DIR)


def test_job_status_records_success(monkeypatch):
    import service

    monkeypatch.setattr(service, "set_app_state", lambda *args, **kwargs: None)
    service._JOB_STATUS.clear()
    started = service._record_job_start("data_health_check", "Data Health Check")
    service._record_job_success(
        "data_health_check",
        started,
        {"status": "ok", "ticker_count": 3, "stale_count": 0},
    )

    status = {item["job_id"]: item for item in service._job_status_snapshot()}

    assert status["data_health_check"]["status"] == "completed"
    assert status["data_health_check"]["run_count"] == 1
    assert status["data_health_check"]["error_count"] == 0
    assert status["data_health_check"]["last_result_summary"]["status"] == "ok"


def test_build_data_health_marks_missing_ohlcv_as_stale(monkeypatch):
    import service

    monkeypatch.setattr(service, "set_app_state", lambda *args, **kwargs: None)
    monkeypatch.setattr(service, "_load_watchlist_files", lambda: ["AAPL"])
    monkeypatch.setattr(service, "latest_results", {})
    monkeypatch.setattr(service, "get_portfolio_status", lambda: {"positions": {}})
    monkeypatch.setattr(
        service,
        "get_data_cache_status",
        lambda tickers, period: {
            "tickers": {
                "AAPL": {
                    "ohlcv": {
                        "present": False,
                        "fresh": False,
                        "source": None,
                        "age_sec": None,
                        "fetched_at": None,
                        "latest_bar_date": None,
                    },
                    "fundamentals": {
                        "present": False,
                        "fresh": False,
                        "source": None,
                        "age_sec": None,
                        "fetched_at": None,
                        "data_quality": "missing",
                    },
                }
            }
        },
    )
    monkeypatch.setattr(
        service,
        "get_news_cache_status",
        lambda tickers: {"tickers": {"AAPL": {"present": False, "fresh": False}}},
    )

    result = service.build_data_health()

    assert result["status"] == "stale"
    assert result["stale_count"] == 1
    assert result["rows"][0]["reasons"] == [
        "ohlcv_missing",
        "fundamentals_missing",
        "news_not_cached",
    ]
