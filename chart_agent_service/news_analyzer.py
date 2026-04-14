"""
뉴스 수집 및 감성 분석 모듈
- yfinance 뉴스 + Google News RSS (feedparser)
- Ollama LLM 감성 분석
"""
import json
import re
from datetime import datetime, timezone
from typing import List, Dict, Optional

import feedparser
import httpx
import yfinance as yf

from config import OLLAMA_BASE_URL, OLLAMA_MODEL


# ── Ollama 감성 분석 ─────────────────────────────────────────────

def _analyze_sentiment_ollama(title: str, text: str) -> Dict:
    """Ollama로 단일 뉴스 감성 분석. 실패 시 neutral 반환."""
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
        resp = httpx.post(
            f"{OLLAMA_BASE_URL}/api/generate",
            json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False},
            timeout=30,
        )
        raw = resp.json().get("response", "{}")
        # JSON 블록 추출
        match = re.search(r'\{.*\}', raw, re.DOTALL)
        if match:
            data = json.loads(match.group())
            return {
                "sentiment": data.get("sentiment", "neutral"),
                "score": float(data.get("score", 0)),
                "summary": data.get("summary", ""),
                "keywords": data.get("keywords", []),
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
            title = (
                content.get("title")
                or item.get("title", "")
            )
            pub_raw = (
                content.get("pubDate")
                or item.get("providerPublishTime")
            )
            if isinstance(pub_raw, int):
                pub_str = datetime.fromtimestamp(pub_raw, tz=timezone.utc).isoformat()
            elif isinstance(pub_raw, str):
                pub_str = pub_raw
            else:
                pub_str = datetime.now(tz=timezone.utc).isoformat()

            url = (
                content.get("canonicalUrl", {}).get("url")
                or item.get("link", "")
            )
            source = (
                content.get("provider", {}).get("displayName")
                or item.get("publisher", "Yahoo Finance")
            )
            summary_text = content.get("summary") or content.get("body") or title

            if title:
                articles.append({
                    "title": title,
                    "source": source,
                    "published": pub_str,
                    "url": url,
                    "_text": summary_text,
                })
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
            articles.append({
                "title": entry.get("title", ""),
                "source": entry.get("source", {}).get("title", "Google News") if hasattr(entry, "source") else "Google News",
                "published": pub_str,
                "url": entry.get("link", ""),
                "_text": entry.get("summary", entry.get("title", "")),
            })
    except Exception:
        pass
    return articles


# ── 메인 함수 ────────────────────────────────────────────────────

def fetch_news_with_sentiment(ticker: str) -> Dict:
    """종목 뉴스 수집 + Ollama 감성 분석 통합."""
    ticker = ticker.upper()

    # 두 소스에서 뉴스 수집 후 중복 제거 (제목 기준)
    yf_articles = _fetch_yfinance_news(ticker)
    gn_articles = _fetch_google_news(ticker)

    seen_titles = set()
    combined = []
    for a in yf_articles + gn_articles:
        key = a["title"].strip().lower()[:60]
        if key and key not in seen_titles:
            seen_titles.add(key)
            combined.append(a)

    combined = combined[:15]  # 최대 15건

    # 감성 분석
    analyzed = []
    for a in combined:
        sentiment_data = _analyze_sentiment_ollama(a["title"], a["_text"])
        analyzed.append({
            "title": a["title"],
            "source": a["source"],
            "published": a["published"],
            "url": a["url"],
            "summary": sentiment_data["summary"] or a["_text"][:200],
            "sentiment": sentiment_data["sentiment"],
            "score": sentiment_data["score"],
            "keywords": sentiment_data["keywords"],
        })

    # 종합 감성 계산
    scores = [a["score"] for a in analyzed]
    overall_score = round(sum(scores) / len(scores), 2) if scores else 0.0
    if overall_score >= 2:
        overall_sentiment = "bullish"
    elif overall_score <= -2:
        overall_sentiment = "bearish"
    else:
        overall_sentiment = "neutral"

    return {
        "ticker": ticker,
        "news_count": len(analyzed),
        "overall_sentiment": overall_sentiment,
        "overall_score": overall_score,
        "articles": analyzed,
        "analyzed_at": datetime.now(tz=timezone.utc).isoformat(),
    }
