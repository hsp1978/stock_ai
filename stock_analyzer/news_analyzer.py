#!/usr/bin/env python3
"""
News Sentiment Analysis Module
- Multi-source news collection
- Sentiment analysis with financial context
- Integration with technical analysis (15% weight)
"""

import yfinance as yf
import requests
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import re
from dataclasses import dataclass
import pandas as pd
import numpy as np
from bs4 import BeautifulSoup
import json
import time


@dataclass
class NewsItem:
    """Individual news item"""
    title: str
    source: str
    published: datetime
    url: str
    sentiment: Optional[float] = None
    relevance: float = 1.0
    summary: Optional[str] = None


@dataclass
class NewsSentiment:
    """Aggregated news sentiment"""
    overall_score: float  # -1 to +1
    confidence: float  # 0 to 1
    volume: str  # 'HIGH', 'MEDIUM', 'LOW'
    trending_topics: List[str]
    key_events: List[Dict]
    recent_news: List[NewsItem]
    analysis_time: str


class NewsAnalyzer:
    """News collection and sentiment analysis"""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })

        # Financial sentiment keywords (영문 + 한글)
        self.positive_keywords = [
            # 영문
            'beat', 'exceed', 'upgrade', 'raise', 'strong', 'growth', 'profit',
            'bullish', 'outperform', 'breakthrough', 'surge', 'rally', 'gain',
            'record', 'expand', 'innovative', 'partner', 'deal', 'acquire',
            'revenue up', 'earnings beat', 'guidance raised', 'buy rating',
            # 한글
            '상승', '강세', '호실적', '돌파', '신고가', '매수', '목표가 상향',
            '실적 개선', '흑자 전환', '수주', '계약', '신제품', '확대', '성장',
            '컨센서스 상회', '어닝 서프라이즈',
        ]

        self.negative_keywords = [
            # 영문
            'miss', 'downgrade', 'cut', 'weak', 'loss', 'decline', 'bearish',
            'underperform', 'concern', 'risk', 'fall', 'drop', 'plunge',
            'layoff', 'lawsuit', 'investigation', 'recall', 'warning',
            'revenue down', 'earnings miss', 'guidance cut', 'sell rating',
            # 한글
            '하락', '약세', '부진', '신저가', '매도', '목표가 하향',
            '실적 악화', '적자', '소송', '리콜', '경고', '우려', '리스크',
            '컨센서스 하회', '어닝 쇼크', '감산', '구조조정',
        ]

        # 부정 수식어 (긍정 키워드 앞에 있으면 부정으로 반전)
        # 예: "급등 우려" → 긍정 키워드 "급등"이 부정으로 반전
        self.negation_modifiers = [
            'no ', 'not ', 'without ', 'lack of ', 'fail to ', 'failed to ',
            '아님', '아니다', '실패', '없음', '부재', '못하',
        ]
        # 강도 약화 수식어 (긍정/부정 강도 줄임)
        self.weakening_modifiers = ['우려', '불확실', '예상', '가능성', '전망', '기대']

        # Source credibility weights
        self.source_weights = {
            'reuters': 1.0,
            'bloomberg': 1.0,
            'wsj': 0.95,
            'cnbc': 0.9,
            'marketwatch': 0.85,
            'yahoo': 0.8,
            'seeking alpha': 0.75,
            'benzinga': 0.7,
            'default': 0.6
        }

    def analyze(self, ticker: str, days: int = 7) -> NewsSentiment:
        """
        Complete news sentiment analysis

        Args:
            ticker: Stock ticker symbol
            days: Number of days to analyze

        Returns:
            NewsSentiment object with analysis results
        """
        # Collect news from multiple sources
        news_items = self._collect_news(ticker, days)

        if not news_items:
            return self._empty_sentiment()

        # Analyze sentiment for each item
        for item in news_items:
            item.sentiment = self._analyze_item_sentiment(item)

        # Calculate aggregate metrics
        overall_score = self._calculate_overall_sentiment(news_items)
        confidence = self._calculate_confidence(news_items)
        volume = self._assess_volume(len(news_items), days)
        trending_topics = self._extract_trending_topics(news_items)
        key_events = self._identify_key_events(news_items)

        return NewsSentiment(
            overall_score=overall_score,
            confidence=confidence,
            volume=volume,
            trending_topics=trending_topics,
            key_events=key_events,
            recent_news=news_items[:10],  # Top 10 most recent
            analysis_time=datetime.now().isoformat()
        )

    def _collect_news(self, ticker: str, days: int) -> List[NewsItem]:
        """Collect news from multiple sources"""
        news_items = []

        # 1. Yahoo Finance News
        yahoo_news = self._fetch_yahoo_news(ticker, days)
        news_items.extend(yahoo_news)

        # 2. Finviz News (if available)
        finviz_news = self._fetch_finviz_news(ticker, days)
        news_items.extend(finviz_news)

        # 3. Alpha Vantage News (if API key available)
        # av_news = self._fetch_alpha_vantage_news(ticker, days)
        # news_items.extend(av_news)

        # Remove duplicates based on title similarity
        news_items = self._remove_duplicates(news_items)

        # Sort by date (most recent first)
        news_items.sort(key=lambda x: x.published, reverse=True)

        return news_items

    def _fetch_yahoo_news(self, ticker: str, days: int) -> List[NewsItem]:
        """Fetch news from Yahoo Finance"""
        news_items = []

        try:
            stock = yf.Ticker(ticker)
            news = stock.news

            if news:
                cutoff_date = datetime.now() - timedelta(days=days)

                for article in news:
                    # Handle nested structure - content is inside 'content' key
                    if 'content' in article:
                        content = article['content']
                    else:
                        content = article

                    # Parse publication time - try different formats
                    pub_time = None
                    if 'pubDate' in content:
                        try:
                            from dateutil import parser
                            pub_time = parser.parse(content['pubDate'])
                            # Make timezone-naive for comparison
                            if pub_time.tzinfo is not None:
                                pub_time = pub_time.replace(tzinfo=None)
                        except:
                            pub_time = datetime.now()
                    elif 'providerPublishTime' in content:
                        pub_time = datetime.fromtimestamp(content.get('providerPublishTime', 0))
                    else:
                        pub_time = datetime.now()

                    if pub_time < cutoff_date:
                        continue

                    # Extract provider/publisher info
                    publisher = 'Yahoo Finance'
                    if 'provider' in content:
                        publisher = content['provider'].get('displayName', 'Yahoo Finance')
                    elif 'publisher' in content:
                        publisher = content.get('publisher', 'Yahoo Finance')

                    # Extract URL
                    url = ''
                    if 'canonicalUrl' in content:
                        url = content['canonicalUrl'].get('url', '')
                    elif 'clickThroughUrl' in content:
                        url = content['clickThroughUrl'].get('url', '')
                    elif 'link' in content:
                        url = content.get('link', '')

                    news_item = NewsItem(
                        title=content.get('title', ''),
                        source=publisher.lower(),
                        published=pub_time,
                        url=url,
                        summary=content.get('summary', content.get('description', ''))
                    )

                    news_items.append(news_item)

        except Exception as e:
            print(f"Error fetching Yahoo news: {e}")
            import traceback
            traceback.print_exc()

        return news_items

    def _fetch_finviz_news(self, ticker: str, days: int) -> List[NewsItem]:
        """Fetch news from Finviz"""
        news_items = []

        try:
            url = f"https://finviz.com/quote.ashx?t={ticker}"
            response = self.session.get(url, timeout=10)

            if response.status_code == 200:
                soup = BeautifulSoup(response.text, 'html.parser')
                news_table = soup.find('table', {'id': 'news-table'})

                if news_table:
                    cutoff_date = datetime.now() - timedelta(days=days)
                    current_date = None

                    for row in news_table.find_all('tr'):
                        cells = row.find_all('td')

                        if len(cells) >= 2:
                            # Parse date/time
                            date_cell = cells[0].text.strip()

                            if len(date_cell.split()) == 3:  # Full date format
                                try:
                                    current_date = datetime.strptime(
                                        date_cell, '%b-%d-%y %I:%M%p'
                                    )
                                except:
                                    continue
                            elif current_date and ':' in date_cell:  # Time only
                                try:
                                    time_obj = datetime.strptime(date_cell, '%I:%M%p').time()
                                    current_date = current_date.replace(
                                        hour=time_obj.hour,
                                        minute=time_obj.minute
                                    )
                                except:
                                    continue

                            if current_date and current_date < cutoff_date:
                                break

                            # Get article info
                            link_cell = cells[1].find('a')
                            if link_cell and current_date:
                                news_item = NewsItem(
                                    title=link_cell.text.strip(),
                                    source='finviz',
                                    published=current_date,
                                    url=link_cell.get('href', '')
                                )
                                news_items.append(news_item)

        except Exception as e:
            print(f"Error fetching Finviz news: {e}")

        return news_items

    def _analyze_item_sentiment(self, item: NewsItem) -> float:
        """
        Analyze sentiment of individual news item

        Returns:
            Sentiment score from -1 (very negative) to +1 (very positive)
        """
        text = f"{item.title} {item.summary or ''}"
        text_lower = text.lower()

        # 부정 수식어 인접 검사: 키워드 앞 30자 이내에 부정 수식어 있으면 반전
        def _is_negated(kw: str, hay: str) -> bool:
            idx = hay.find(kw)
            if idx < 0:
                return False
            window = hay[max(0, idx - 30):idx]
            return any(neg in window for neg in self.negation_modifiers)

        # 약화 수식어 인접 검사: 키워드 주변에 "우려/예상" 등 있으면 강도 낮춤
        def _is_weakened(kw: str, hay: str) -> bool:
            idx = hay.find(kw)
            if idx < 0:
                return False
            window = hay[max(0, idx - 15):min(len(hay), idx + len(kw) + 15)]
            return any(mod in window for mod in self.weakening_modifiers)

        positive_count = 0.0
        negative_count = 0.0
        for kw in self.positive_keywords:
            if kw in text_lower:
                weight = 0.5 if _is_weakened(kw, text_lower) else 1.0
                if _is_negated(kw, text_lower):
                    negative_count += weight
                else:
                    positive_count += weight
        for kw in self.negative_keywords:
            if kw in text_lower:
                weight = 0.5 if _is_weakened(kw, text_lower) else 1.0
                if _is_negated(kw, text_lower):
                    positive_count += weight
                else:
                    negative_count += weight

        # Basic sentiment calculation
        if positive_count + negative_count == 0:
            base_sentiment = 0
        else:
            base_sentiment = (positive_count - negative_count) / (positive_count + negative_count)

        # Adjust for strong signals (단, 부정/약화 수식어 없을 때만)
        if ('upgrade' in text_lower or 'beat' in text_lower) and \
           not _is_negated('upgrade', text_lower) and not _is_negated('beat', text_lower):
            base_sentiment = max(base_sentiment, 0.6)
        elif ('downgrade' in text_lower or 'miss' in text_lower) and \
             not _is_negated('downgrade', text_lower) and not _is_negated('miss', text_lower):
            base_sentiment = min(base_sentiment, -0.6)

        # Apply source weight
        source_weight = self.source_weights.get(item.source, self.source_weights['default'])
        weighted_sentiment = base_sentiment * source_weight

        return np.clip(weighted_sentiment, -1, 1)

    def _calculate_overall_sentiment(self, news_items: List[NewsItem]) -> float:
        """Calculate weighted average sentiment"""
        if not news_items:
            return 0

        total_weight = 0
        weighted_sum = 0

        for i, item in enumerate(news_items):
            # Recent news has higher weight
            recency_weight = 1 / (1 + i * 0.1)

            # Source credibility weight
            source_weight = self.source_weights.get(
                item.source, self.source_weights['default']
            )

            # Combined weight
            weight = recency_weight * source_weight * item.relevance

            if item.sentiment is not None:
                weighted_sum += item.sentiment * weight
                total_weight += weight

        if total_weight > 0:
            return np.clip(weighted_sum / total_weight, -1, 1)
        else:
            return 0

    def _calculate_confidence(self, news_items: List[NewsItem]) -> float:
        """Calculate confidence based on volume and consistency"""
        if not news_items:
            return 0

        # Factor 1: Volume (more news = higher confidence)
        volume_score = min(1.0, len(news_items) / 20)

        # Factor 2: Consistency (similar sentiments = higher confidence)
        sentiments = [item.sentiment for item in news_items if item.sentiment is not None]
        if len(sentiments) > 1:
            std_dev = np.std(sentiments)
            consistency_score = max(0, 1 - std_dev * 2)
        else:
            consistency_score = 0.5

        # Factor 3: Source quality
        avg_source_weight = np.mean([
            self.source_weights.get(item.source, self.source_weights['default'])
            for item in news_items[:10]  # Top 10 news
        ])

        # Combine factors
        confidence = (volume_score * 0.3 + consistency_score * 0.4 + avg_source_weight * 0.3)

        return np.clip(confidence, 0, 1)

    def _assess_volume(self, count: int, days: int) -> str:
        """Assess news volume level"""
        daily_average = count / max(days, 1)

        if daily_average >= 10:
            return 'HIGH'
        elif daily_average >= 3:
            return 'MEDIUM'
        else:
            return 'LOW'

    def _extract_trending_topics(self, news_items: List[NewsItem]) -> List[str]:
        """Extract trending topics from news"""
        topics = []

        # Common topics to look for
        topic_keywords = {
            'earnings': ['earnings', 'revenue', 'profit', 'eps'],
            'product': ['product', 'launch', 'release', 'announce'],
            'merger': ['merger', 'acquisition', 'acquire', 'deal'],
            'analyst': ['analyst', 'rating', 'upgrade', 'downgrade'],
            'legal': ['lawsuit', 'investigation', 'probe', 'fine'],
            'management': ['ceo', 'executive', 'resign', 'appoint'],
            'dividend': ['dividend', 'payout', 'distribution'],
            'buyback': ['buyback', 'repurchase', 'share purchase']
        }

        # Count occurrences
        topic_counts = {}
        for topic, keywords in topic_keywords.items():
            count = 0
            for item in news_items[:20]:  # Check top 20 news
                text = f"{item.title} {item.summary or ''}".lower()
                if any(keyword in text for keyword in keywords):
                    count += 1

            if count > 0:
                topic_counts[topic] = count

        # Sort by frequency and return top topics
        sorted_topics = sorted(topic_counts.items(), key=lambda x: x[1], reverse=True)
        topics = [topic for topic, _ in sorted_topics[:3]]

        return topics

    def _identify_key_events(self, news_items: List[NewsItem]) -> List[Dict]:
        """Identify key events from news"""
        key_events = []

        # Patterns for key events
        event_patterns = [
            (r'beat.*earnings', 'earnings_beat'),
            (r'miss.*earnings', 'earnings_miss'),
            (r'upgrade.*to.*buy', 'analyst_upgrade'),
            (r'downgrade.*to.*sell', 'analyst_downgrade'),
            (r'announce.*acquisition', 'acquisition'),
            (r'file.*lawsuit', 'lawsuit'),
            (r'new.*product', 'product_launch'),
            (r'ceo.*resign', 'management_change')
        ]

        for item in news_items[:20]:  # Check top 20 news
            text_lower = item.title.lower()

            for pattern, event_type in event_patterns:
                if re.search(pattern, text_lower):
                    key_events.append({
                        'type': event_type,
                        'title': item.title,
                        'date': item.published.isoformat(),
                        'sentiment_impact': item.sentiment or 0
                    })
                    break

        return key_events[:5]  # Return top 5 key events

    def _remove_duplicates(self, news_items: List[NewsItem]) -> List[NewsItem]:
        """Remove duplicate news based on title similarity"""
        unique_items = []
        seen_titles = set()

        for item in news_items:
            # Simple duplicate check based on first 50 chars of title
            title_key = item.title[:50].lower()

            if title_key not in seen_titles:
                unique_items.append(item)
                seen_titles.add(title_key)

        return unique_items

    def _empty_sentiment(self) -> NewsSentiment:
        """Return empty sentiment when no news available"""
        return NewsSentiment(
            overall_score=0,
            confidence=0,
            volume='LOW',
            trending_topics=[],
            key_events=[],
            recent_news=[],
            analysis_time=datetime.now().isoformat()
        )


class IntegratedAnalyzer:
    """
    Integrated Technical + News Analysis
    Weight: 85% Technical, 15% News
    """

    def __init__(self):
        from enhanced_technical_analyzer import EnhancedTechnicalAnalyzer
        self.technical_analyzer = EnhancedTechnicalAnalyzer()
        self.news_analyzer = NewsAnalyzer()

        # Weights
        self.TECHNICAL_WEIGHT = 0.85
        self.NEWS_WEIGHT = 0.15

    def analyze(self, ticker: str, period: str = "3mo", news_days: int = 7) -> Dict:
        """
        Complete integrated analysis

        Returns:
            {
                'ticker': str,
                'recommendation': 'BUY/SELL/HOLD',
                'confidence': 0-10,
                'technical': {...},
                'news': {...},
                'integrated_score': float,
                'reasoning': str
            }
        """
        # Get technical analysis
        technical = self.technical_analyzer.analyze(ticker, period)

        # Get news sentiment
        news_sentiment = self.news_analyzer.analyze(ticker, news_days)

        # Convert to common format
        news_analysis = self._process_news_sentiment(news_sentiment)

        # Integrate signals
        integrated_rec, integrated_conf, integrated_score = self._integrate_signals(
            technical, news_analysis
        )

        # Generate reasoning
        reasoning = self._generate_reasoning(technical, news_analysis, integrated_rec)

        return {
            'ticker': ticker,
            'recommendation': integrated_rec,
            'confidence': round(integrated_conf, 1),
            'integrated_score': round(integrated_score, 3),
            'technical': {
                'recommendation': technical['recommendation'],
                'confidence': technical['confidence'],
                'weight': f"{self.TECHNICAL_WEIGHT*100:.0f}%",
                'signals': len(technical.get('signals', [])),
                'conflicts': technical.get('conflicts', []),
                'risk_factors': technical.get('risk_factors', [])
            },
            'news': {
                'sentiment': news_analysis['sentiment'],
                'confidence': news_analysis['confidence'],
                'weight': f"{self.NEWS_WEIGHT*100:.0f}%",
                'volume': news_analysis['volume'],
                'trending_topics': news_analysis['trending_topics'],
                'key_events': news_analysis['key_events']
            },
            'reasoning': reasoning,
            'analysis_time': datetime.now().isoformat()
        }

    def _process_news_sentiment(self, sentiment: NewsSentiment) -> Dict:
        """Process news sentiment to standard format"""
        # Convert sentiment score to recommendation
        if sentiment.overall_score > 0.2:
            news_rec = 'BUY'
        elif sentiment.overall_score < -0.2:
            news_rec = 'SELL'
        else:
            news_rec = 'HOLD'

        # Convert confidence to 0-10 scale
        news_conf = sentiment.confidence * 10

        return {
            'recommendation': news_rec,
            'confidence': news_conf,
            'sentiment': sentiment.overall_score,
            'volume': sentiment.volume,
            'trending_topics': sentiment.trending_topics,
            'key_events': sentiment.key_events,
            'recent_news': [
                {
                    'title': item.title,
                    'source': item.source,
                    'sentiment': item.sentiment
                }
                for item in sentiment.recent_news[:5]
            ]
        }

    def _integrate_signals(self, technical: Dict, news: Dict) -> Tuple[str, float, float]:
        """
        Integrate technical and news signals with 85:15 weighting

        Returns:
            (recommendation, confidence, integrated_score)
        """
        # Convert recommendations to scores
        rec_to_score = {'BUY': 1, 'HOLD': 0, 'SELL': -1}

        tech_score = rec_to_score.get(technical['recommendation'], 0)
        news_score = rec_to_score.get(news['recommendation'], 0)

        # Apply weights
        integrated_score = (
            tech_score * self.TECHNICAL_WEIGHT +
            news_score * self.NEWS_WEIGHT
        )

        # Convert back to recommendation
        if integrated_score > 0.3:
            integrated_rec = 'BUY'
        elif integrated_score < -0.3:
            integrated_rec = 'SELL'
        else:
            integrated_rec = 'HOLD'

        # Calculate integrated confidence
        tech_conf = technical['confidence']
        news_conf = news['confidence']

        # Weighted average confidence
        base_confidence = (
            tech_conf * self.TECHNICAL_WEIGHT +
            news_conf * self.NEWS_WEIGHT
        )

        # Adjust confidence based on agreement
        if technical['recommendation'] == news['recommendation']:
            # Boost confidence when signals agree
            agreement_bonus = 1.0
        elif (technical['recommendation'] == 'BUY' and news['recommendation'] == 'SELL') or \
             (technical['recommendation'] == 'SELL' and news['recommendation'] == 'BUY'):
            # Reduce confidence when signals conflict
            agreement_bonus = -2.0
        else:
            # Neutral when one is HOLD
            agreement_bonus = 0

        integrated_confidence = np.clip(base_confidence + agreement_bonus, 1, 10)

        return integrated_rec, integrated_confidence, integrated_score

    def _generate_reasoning(self, technical: Dict, news: Dict, recommendation: str) -> str:
        """Generate explanation for integrated recommendation"""
        reasons = []

        # Technical reasoning
        tech_rec = technical['recommendation']
        tech_conf = technical['confidence']
        reasons.append(
            f"Technical analysis ({self.TECHNICAL_WEIGHT*100:.0f}% weight): "
            f"{tech_rec} with {tech_conf:.1f}/10 confidence"
        )

        # News reasoning
        news_rec = news['recommendation']
        news_sentiment = news['sentiment']
        news_volume = news['volume']
        reasons.append(
            f"News sentiment ({self.NEWS_WEIGHT*100:.0f}% weight): "
            f"{news_rec} (score: {news_sentiment:.2f}, volume: {news_volume})"
        )

        # Key factors
        if news.get('key_events'):
            event = news['key_events'][0]
            reasons.append(f"Key event: {event['type'].replace('_', ' ')}")

        if technical.get('conflicts'):
            reasons.append(f"Note: {len(technical['conflicts'])} technical indicator conflicts detected")

        # Agreement/Disagreement
        if tech_rec == news_rec:
            reasons.append("✓ Technical and news signals are aligned")
        elif (tech_rec == 'BUY' and news_rec == 'SELL') or \
             (tech_rec == 'SELL' and news_rec == 'BUY'):
            reasons.append("⚠ Technical and news signals conflict - reduced confidence")

        # Final recommendation
        reasons.append(f"Integrated recommendation: {recommendation}")

        return " | ".join(reasons)


# Example usage
if __name__ == "__main__":
    # Test integrated analyzer
    analyzer = IntegratedAnalyzer()

    # Analyze a stock
    result = analyzer.analyze("AAPL", period="3mo", news_days=7)

    print("\n=== Integrated Analysis (85% Technical + 15% News) ===")
    print(f"Ticker: {result['ticker']}")
    print(f"Recommendation: {result['recommendation']}")
    print(f"Confidence: {result['confidence']}/10")
    print(f"Integrated Score: {result['integrated_score']}")

    print("\n--- Technical Component (85%) ---")
    tech = result['technical']
    print(f"Technical: {tech['recommendation']} (confidence: {tech['confidence']}/10)")
    print(f"Signals analyzed: {tech['signals']}")
    if tech['conflicts']:
        print(f"Conflicts: {len(tech['conflicts'])}")

    print("\n--- News Component (15%) ---")
    news = result['news']
    print(f"Sentiment: {news['sentiment']:.2f} ({news['volume']} volume)")
    if news['trending_topics']:
        print(f"Trending: {', '.join(news['trending_topics'])}")
    if news['key_events']:
        print(f"Key event: {news['key_events'][0]['type']}")

    print("\n--- Reasoning ---")
    print(result['reasoning'])