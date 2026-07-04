from unittest.mock import patch


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
