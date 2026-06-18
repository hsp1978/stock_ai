"""
뉴스 수집 및 감성 분석 모듈
- yfinance 뉴스 + Google News RSS + Naver Finance RSS/HTML fallback
- Ollama LLM 감성 분석
"""

import copy
import os
import threading
from datetime import datetime, timezone
from typing import Any, List, Dict

import feedparser
import requests
import yfinance as yf

from config import settings


_news_cache: dict[tuple[str, bool], dict[str, Any]] = {}
_news_cache_lock = threading.Lock()


def clear_news_cache() -> None:
    """뉴스 TTL 캐시 초기화 (테스트/수동 복구용)."""
    with _news_cache_lock:
        _news_cache.clear()


def _is_korean_ticker(ticker: str) -> bool:
    t = ticker.upper()
    stripped = t.split(".")[0]
    return t.endswith((".KS", ".KQ")) or (stripped.isdigit() and len(stripped) == 6)


def _news_cache_fresh(entry: dict[str, Any]) -> bool:
    fetched_at = entry.get("fetched_at")
    if not isinstance(fetched_at, datetime):
        return False
    ttl = max(1, int(settings.NEWS_TTL_MINUTES)) * 60
    return (datetime.now(timezone.utc) - fetched_at).total_seconds() < ttl


def get_news_cache_status(tickers: list[str] | None = None) -> dict[str, Any]:
    """
    뉴스 TTL 캐시의 freshness 메타데이터를 반환한다.

    네트워크를 호출하지 않는 관측용 함수다. analyze_sentiment=True/False 캐시가
    모두 있을 수 있으므로 티커별 entries 배열로 노출한다.
    """
    with _news_cache_lock:
        snapshot = copy.deepcopy(_news_cache)

    if tickers:
        ticker_list = [t.upper().strip() for t in tickers if t and t.strip()]
    else:
        ticker_list = sorted({key[0] for key in snapshot})

    ttl = max(1, int(settings.NEWS_TTL_MINUTES)) * 60
    result: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "ttl_sec": ttl,
        "tickers": {},
    }

    for ticker in ticker_list:
        entries = []
        for analyze_sentiment in (True, False):
            cache_entry = snapshot.get((ticker, analyze_sentiment))
            if cache_entry is None:
                continue
            fetched_at = cache_entry.get("fetched_at")
            age = (
                max(0.0, (datetime.now(timezone.utc) - fetched_at).total_seconds())
                if isinstance(fetched_at, datetime)
                else None
            )
            data = cache_entry.get("data") or {}
            entries.append(
                {
                    "analyze_sentiment": analyze_sentiment,
                    "present": True,
                    "fetched_at": fetched_at.isoformat() if isinstance(fetched_at, datetime) else None,
                    "age_sec": age,
                    "fresh": bool(age is not None and age < ttl),
                    "sources": data.get("sources") or [],
                    "news_count": data.get("news_count", 0),
                    "overall_sentiment": data.get("overall_sentiment"),
                }
            )

        result["tickers"][ticker] = {
            "present": bool(entries),
            "fresh": any(entry.get("fresh") for entry in entries),
            "entries": entries,
        }

    return result


# ── LiteLLM Router 감성 분석 (Step 9: Ollama 직접 호출 → Router) ──


def _analyze_sentiment_ollama(title: str, text: str) -> Dict:
    """LiteLLM Router를 통해 뉴스 감성 분석. 실패 시 neutral 반환."""
    prompt = (
        f"다음 주식 뉴스를 분석하고 반드시 JSON만 응답하라. 다른 텍스트 없이 JSON만.\n\n"
        f"뉴스 제목: {title}\n"
        f"뉴스 내용: {text[:500]}\n\n"
        f"응답 형식:\n"
        f'{{"sentiment": "bullish|bearish|neutral", '
        f'"score": -10에서 +10 사이 숫자, '
        f'"summary": "한국어 2문장 요약", '
        f'"keywords": ["키워드1", "키워드2", "키워드3"]}}'
    )
    try:
        from llm.router import call_agent_llm, get_router
        from llm.schemas import NewsSentimentResponse

        result = call_agent_llm(
            get_router(), "news sentiment analyzer", prompt, NewsSentimentResponse
        )
        return {
            "sentiment": result.sentiment,
            "score": result.score,
            "summary": result.summary,
            "keywords": result.keywords,
        }
    except Exception:
        pass
    return {"sentiment": "neutral", "score": 0.0, "summary": "", "keywords": []}


# ── yfinance 뉴스 수집 ────────────────────────────────────────────


def _fetch_yfinance_news(ticker: str) -> List[Dict]:
    """yfinance에서 최신 뉴스 수집."""
    articles = []
    try:
        t = yf.Ticker(ticker)
        news_list = t.news or []
        for item in news_list[:10]:
            content = item.get("content", {})
            # yfinance 1.x / 2.x 모두 대응
            title = content.get("title") or item.get("title", "")
            pub_raw = content.get("pubDate") or item.get("providerPublishTime")
            if isinstance(pub_raw, int):
                pub_str = datetime.fromtimestamp(pub_raw, tz=timezone.utc).isoformat()
            elif isinstance(pub_raw, str):
                pub_str = pub_raw
            else:
                pub_str = datetime.now(tz=timezone.utc).isoformat()

            url = content.get("canonicalUrl", {}).get("url") or item.get("link", "")
            source = content.get("provider", {}).get("displayName") or item.get(
                "publisher", "Yahoo Finance"
            )
            summary_text = content.get("summary") or content.get("body") or title

            if title:
                articles.append(
                    {
                        "title": title,
                        "source": source,
                        "published": pub_str,
                        "url": url,
                        "_text": summary_text,
                    }
                )
    except Exception:
        pass
    return articles


# ── Google News RSS 수집 ─────────────────────────────────────────


def _fetch_google_news(ticker: str) -> List[Dict]:
    """Google News RSS에서 뉴스 수집."""
    articles = []
    try:
        url = (
            f"https://news.google.com/rss/search"
            f"?q={ticker}+stock&hl=en&gl=US&ceid=US:en"
        )
        feed = feedparser.parse(url)
        for entry in feed.entries[:10]:
            pub_str = datetime.now(tz=timezone.utc).isoformat()
            if hasattr(entry, "published_parsed") and entry.published_parsed:
                import time as _time

                pub_str = datetime.fromtimestamp(
                    _time.mktime(entry.published_parsed), tz=timezone.utc
                ).isoformat()
            articles.append(
                {
                    "title": entry.get("title", ""),
                    "source": entry.get("source", {}).get("title", "Google News")
                    if hasattr(entry, "source")
                    else "Google News",
                    "published": pub_str,
                    "url": entry.get("link", ""),
                    "_text": entry.get("summary", entry.get("title", "")),
                }
            )
    except Exception:
        pass
    return articles


def _fetch_naver_news(ticker: str) -> List[Dict]:
    """Naver Finance 종목 뉴스 수집 (한국 종목 전용)."""
    if not _is_korean_ticker(ticker):
        return []

    articles = []
    code = ticker.upper().split(".")[0]
    try:
        response = requests.get(
            "https://finance.naver.com/item/news_news.naver",
            params={"code": code, "page": 1},
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=8,
        )
        response.raise_for_status()
        response.encoding = response.apparent_encoding or "euc-kr"

        try:
            from bs4 import BeautifulSoup
        except Exception:
            return []

        soup = BeautifulSoup(response.text, "html.parser")
        for row in soup.select("table.type5 tr")[:20]:
            link = row.select_one("td.title a")
            if not link:
                continue
            title = link.get_text(" ", strip=True)
            href = link.get("href", "")
            source_cell = row.select_one("td.info")
            date_cell = row.select_one("td.date")
            source = source_cell.get_text(" ", strip=True) if source_cell else "Naver Finance"
            published = date_cell.get_text(" ", strip=True) if date_cell else ""
            url = f"https://finance.naver.com{href}" if href.startswith("/") else href
            if title:
                articles.append(
                    {
                        "title": title,
                        "source": source or "Naver Finance",
                        "published": published or datetime.now(tz=timezone.utc).isoformat(),
                        "url": url,
                        "_text": title,
                    }
                )
    except Exception:
        pass
    return articles


def _fetch_alphavantage_news(ticker: str) -> List[Dict]:
    """Alpha Vantage News Sentiment API fallback (API key 설정 시)."""
    api_key = (
        settings.ALPHAVANTAGE_API_KEY
        or os.getenv("ALPHAVANTAGE_API_KEY", "")
        or os.getenv("ALPHA_VANTAGE_API_KEY", "")
    )
    if not api_key:
        return []

    articles = []
    try:
        response = requests.get(
            "https://www.alphavantage.co/query",
            params={
                "function": "NEWS_SENTIMENT",
                "tickers": ticker.upper(),
                "limit": 10,
                "apikey": api_key,
            },
            timeout=8,
        )
        response.raise_for_status()
        payload = response.json()
        for item in (payload.get("feed") or [])[:10]:
            title = item.get("title", "")
            if not title:
                continue
            articles.append(
                {
                    "title": title,
                    "source": item.get("source") or "Alpha Vantage",
                    "published": item.get("time_published") or datetime.now(tz=timezone.utc).isoformat(),
                    "url": item.get("url", ""),
                    "_text": item.get("summary") or title,
                }
            )
    except Exception:
        pass
    return articles


def _collect_articles(ticker: str) -> tuple[list[dict], list[str]]:
    sources = [
        ("yfinance", _fetch_yfinance_news),
        ("google_news", _fetch_google_news),
        ("alphavantage", _fetch_alphavantage_news),
    ]
    if _is_korean_ticker(ticker):
        sources.insert(1, ("naver", _fetch_naver_news))

    seen_titles = set()
    combined = []
    used_sources = []
    for source_name, fetcher in sources:
        articles = fetcher(ticker)
        if articles:
            used_sources.append(source_name)
        for article in articles:
            key = (article.get("title") or "").strip().lower()[:80]
            if key and key not in seen_titles:
                seen_titles.add(key)
                combined.append(article)

    return combined[:15], used_sources


# ── 메인 함수 ────────────────────────────────────────────────────


def fetch_news_with_sentiment(ticker: str, analyze_sentiment: bool = True) -> Dict:
    """종목 뉴스 수집 + Ollama 감성 분석 통합."""
    ticker = ticker.upper()
    cache_key = (ticker, analyze_sentiment)

    with _news_cache_lock:
        cached = _news_cache.get(cache_key)
    if cached is not None and _news_cache_fresh(cached):
        result = copy.deepcopy(cached["data"])
        result["_cache_hit"] = True
        return result

    combined, used_sources = _collect_articles(ticker)

    # 감성 분석
    analyzed = []
    for a in combined:
        sentiment_data = (
            _analyze_sentiment_ollama(a["title"], a["_text"])
            if analyze_sentiment
            else {"sentiment": "neutral", "score": 0.0, "summary": "", "keywords": []}
        )
        analyzed.append(
            {
                "title": a["title"],
                "source": a["source"],
                "published": a["published"],
                "url": a["url"],
                "summary": sentiment_data["summary"] or a["_text"][:200],
                "sentiment": sentiment_data["sentiment"],
                "score": sentiment_data["score"],
                "keywords": sentiment_data["keywords"],
            }
        )

    # 종합 감성 계산
    scores = [a["score"] for a in analyzed]
    overall_score = round(sum(scores) / len(scores), 2) if scores and analyze_sentiment else None
    if overall_score is None:
        overall_sentiment = "headline_only" if analyzed else "neutral"
    elif overall_score >= 2:
        overall_sentiment = "bullish"
    elif overall_score <= -2:
        overall_sentiment = "bearish"
    else:
        overall_sentiment = "neutral"

    result = {
        "ticker": ticker,
        "news_count": len(analyzed),
        "overall_sentiment": overall_sentiment,
        "overall_score": overall_score,
        "articles": analyzed,
        "sources": used_sources,
        "_cache_hit": False,
        "analyzed_at": datetime.now(tz=timezone.utc).isoformat(),
    }
    with _news_cache_lock:
        _news_cache[cache_key] = {
            "fetched_at": datetime.now(timezone.utc),
            "data": copy.deepcopy(result),
        }
    return result
