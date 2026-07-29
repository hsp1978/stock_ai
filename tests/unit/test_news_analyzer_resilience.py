import time
from unittest.mock import patch


def _article(idx: int) -> dict:
    return {
        "title": f"AAPL headline {idx}",
        "source": "Example",
        "published": "2026-01-01T00:00:00Z",
        "url": f"https://example.com/aapl/{idx}",
        "_text": f"AAPL headline {idx}",
    }


def test_fetch_news_headline_mode_uses_cache():
    import news_analyzer as na

    na.clear_news_cache()
    articles = [
        {
            "title": "AAPL launches new product",
            "source": "Example",
            "published": "2026-01-01T00:00:00Z",
            "url": "https://example.com/aapl",
            "_text": "AAPL launches new product",
        }
    ]

    with patch("news_analyzer._collect_articles", return_value=(articles, ["google_news"])) as collect:
        first = na.fetch_news_with_sentiment("AAPL", analyze_sentiment=False)
        second = na.fetch_news_with_sentiment("AAPL", analyze_sentiment=False)

    assert first["overall_sentiment"] == "headline_only"
    assert first["news_count"] == 1
    assert second["_cache_hit"] is True
    assert collect.call_count == 1
    na.clear_news_cache()


def test_get_news_cache_status_reports_cached_sources():
    import news_analyzer as na

    na.clear_news_cache()
    articles = [
        {
            "title": "AAPL launches new product",
            "source": "Example",
            "published": "2026-01-01T00:00:00Z",
            "url": "https://example.com/aapl",
            "_text": "AAPL launches new product",
        }
    ]

    with patch("news_analyzer._collect_articles", return_value=(articles, ["google_news"])):
        na.fetch_news_with_sentiment("AAPL", analyze_sentiment=False)

    status = na.get_news_cache_status(["AAPL"])
    ticker_status = status["tickers"]["AAPL"]

    assert ticker_status["present"] is True
    assert ticker_status["fresh"] is True
    assert ticker_status["entries"][0]["sources"] == ["google_news"]
    assert ticker_status["entries"][0]["news_count"] == 1
    na.clear_news_cache()


def test_sentiment_phase_stays_within_budget(monkeypatch):
    """LLM이 예산보다 느려도 감성 분석 단계가 예산 안에서 끝난다."""
    import news_analyzer as na

    monkeypatch.setattr(na.settings, "NEWS_SENTIMENT_BUDGET_SEC", 1.0)
    monkeypatch.setattr(na.settings, "NEWS_SENTIMENT_WORKERS", 2)

    def _slow(title, text, timeout_seconds=None):
        # 라우터가 예산을 지키는 상황을 모사: 주어진 시간만큼만 쓰고 반환
        time.sleep(min(timeout_seconds or 5.0, 5.0))
        return dict(na._NEUTRAL_SENTIMENT)

    articles = [_article(i) for i in range(6)]
    started = time.monotonic()
    with patch("news_analyzer._analyze_sentiment_ollama", side_effect=_slow):
        results = na._analyze_articles_bounded(articles)
    elapsed = time.monotonic() - started

    assert len(results) == len(articles)
    assert elapsed < 3.0, f"budget 1.0s 초과: {elapsed:.2f}s"


def test_sentiment_caps_article_count(monkeypatch):
    """감성 분석 대상은 NEWS_SENTIMENT_MAX_ARTICLES로 제한된다."""
    import news_analyzer as na

    na.clear_news_cache()
    monkeypatch.setattr(na.settings, "NEWS_SENTIMENT_MAX_ARTICLES", 3)
    articles = [_article(i) for i in range(10)]

    calls = []

    def _record(title, text, timeout_seconds=None):
        calls.append(title)
        return dict(na._NEUTRAL_SENTIMENT)

    with patch("news_analyzer._collect_articles", return_value=(articles, ["google_news"])):
        with patch("news_analyzer._analyze_sentiment_ollama", side_effect=_record):
            result = na.fetch_news_with_sentiment("AAPL", analyze_sentiment=True)

    assert result["news_count"] == 3
    assert len(calls) == 3
    na.clear_news_cache()
