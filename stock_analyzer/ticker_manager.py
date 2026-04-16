#!/usr/bin/env python3
"""
통합 티커 관리 시스템
- 한국/미국 주식 자동 감지
- 티커 정규화 및 변환
- 시장별 메타데이터 관리
"""

import re
from typing import Tuple, Optional, Dict
from datetime import datetime
import pytz


class TickerManager:
    """통합 티커 관리자"""

    # 한국 주식 메타데이터 캐시 (동적으로 추가됨)
    KOREAN_STOCKS = {}

    @classmethod
    def _fetch_korean_stock_info(cls, stock_code: str) -> Optional[Dict]:
        """
        Yahoo Finance에서 한국 주식 정보를 동적으로 가져오기

        Args:
            stock_code: 6자리 종목코드 (예: "005930")

        Returns:
            {'name': '...', 'name_en': '...', 'market': 'KOSPI', 'sector': '...'}
        """
        try:
            import yfinance as yf

            # KOSPI 먼저 시도
            ticker = f"{stock_code}.KS"
            stock = yf.Ticker(ticker)
            info = stock.info

            # 데이터가 없으면 KOSDAQ 시도
            if not info or 'longName' not in info:
                ticker = f"{stock_code}.KQ"
                stock = yf.Ticker(ticker)
                info = stock.info

            if info and ('longName' in info or 'shortName' in info):
                name_en = info.get('longName') or info.get('shortName', stock_code)
                sector = info.get('sector', 'Unknown')
                market = 'KOSDAQ' if ticker.endswith('.KQ') else 'KOSPI'

                stock_info = {
                    'name': name_en,  # Yahoo에서 한글명을 제공하지 않으면 영문명 사용
                    'name_en': name_en,
                    'market': market,
                    'sector': sector
                }

                # 캐시에 저장
                cls.KOREAN_STOCKS[stock_code] = stock_info
                return stock_info

        except Exception as e:
            pass

        return None

    @classmethod
    def detect_market(cls, ticker: str) -> str:
        """
        티커로 시장 자동 감지

        Returns:
            'KR' (한국) or 'US' (미국) or 'UNKNOWN'
        """
        ticker = ticker.strip().upper()

        # .KS, .KQ로 끝나면 한국
        if ticker.endswith('.KS') or ticker.endswith('.KQ'):
            return 'KR'

        # 6자리 숫자면 한국 (종목코드)
        if re.match(r'^\d{6}$', ticker):
            return 'KR'

        # 한글이 포함되면 한국
        if re.search(r'[가-힣]', ticker):
            return 'KR'

        # 그 외는 미국
        return 'US'

    @classmethod
    def normalize_ticker(cls, ticker: str, market: Optional[str] = None) -> Tuple[str, str]:
        """
        티커 정규화

        Args:
            ticker: 입력 티커 (예: "005930", "삼성전자", "AAPL")
            market: 강제 시장 지정 (None이면 자동 감지)

        Returns:
            (normalized_ticker, market)
            - 한국: "005930.KS", "KR"
            - 미국: "AAPL", "US"
        """
        if market is None:
            market = cls.detect_market(ticker)

        ticker = ticker.strip().upper()

        if market == 'KR':
            # 이미 .KS 또는 .KQ 형식
            if '.KS' in ticker or '.KQ' in ticker:
                return ticker, 'KR'

            # 6자리 숫자 (종목코드)
            if re.match(r'^\d{6}$', ticker):
                # KOSPI 기본, 실제로는 KRX API로 확인 필요
                return f"{ticker}.KS", 'KR'

            # 한글 종목명으로 검색 (캐시에 있는 경우만)
            if re.search(r'[가-힣]', ticker):
                for code, info in cls.KOREAN_STOCKS.items():
                    if info.get('name') == ticker or info.get('name_en', '').upper() == ticker:
                        return f"{code}.KS", 'KR'

            # 기본값
            return f"{ticker}.KS", 'KR'

        else:  # US
            # 미국 주식은 그대로 반환
            ticker = ticker.replace('.US', '')  # 혹시 .US가 붙어있으면 제거
            return ticker, 'US'

    @classmethod
    def get_stock_info(cls, ticker: str) -> Dict:
        """
        종목 정보 조회

        Returns:
            {
                'ticker': '005930.KS',
                'code': '005930',
                'name': '삼성전자',
                'name_en': 'Samsung Electronics',
                'market': 'KR',
                'exchange': 'KOSPI',
                'currency': 'KRW',
                'timezone': 'Asia/Seoul'
            }
        """
        normalized, market = cls.normalize_ticker(ticker)

        if market == 'KR':
            stock_code = normalized.replace('.KS', '').replace('.KQ', '')

            # 캐시 확인 후 없으면 동적으로 가져오기
            info = cls.KOREAN_STOCKS.get(stock_code)
            if not info:
                info = cls._fetch_korean_stock_info(stock_code)

            # 여전히 없으면 기본값 사용
            if not info:
                info = {}

            return {
                'ticker': normalized,
                'code': stock_code,
                'name': info.get('name', stock_code),
                'name_en': info.get('name_en', stock_code),
                'market': 'KR',
                'exchange': info.get('market', 'KOSPI'),
                'sector': info.get('sector', 'Unknown'),
                'currency': 'KRW',
                'timezone': 'Asia/Seoul',
                'trading_hours': '09:00-15:30 KST'
            }

        else:  # US
            return {
                'ticker': normalized,
                'code': normalized,
                'name': normalized,
                'name_en': normalized,
                'market': 'US',
                'exchange': 'NASDAQ/NYSE',
                'sector': 'Unknown',
                'currency': 'USD',
                'timezone': 'US/Eastern',
                'trading_hours': '09:30-16:00 EST'
            }

    @classmethod
    def format_price(cls, price: float, market: str) -> str:
        """시장별 가격 포맷"""
        if market == 'KR':
            return f"₩{price:,.0f}"
        else:
            return f"${price:,.2f}"

    @classmethod
    def get_timezone(cls, market: str) -> pytz.timezone:
        """시장별 시간대"""
        if market == 'KR':
            return pytz.timezone('Asia/Seoul')
        else:
            return pytz.timezone('US/Eastern')

    @classmethod
    def convert_time(cls, dt: datetime, from_market: str, to_market: str) -> datetime:
        """시장 간 시간 변환"""
        from_tz = cls.get_timezone(from_market)
        to_tz = cls.get_timezone(to_market)

        if dt.tzinfo is None:
            dt = from_tz.localize(dt)

        return dt.astimezone(to_tz)

    @classmethod
    def is_trading_hours(cls, market: str, dt: Optional[datetime] = None) -> bool:
        """현재 거래 시간인지 확인"""
        if dt is None:
            dt = datetime.now(cls.get_timezone(market))

        # 주말 제외
        if dt.weekday() >= 5:
            return False

        hour = dt.hour
        minute = dt.minute

        if market == 'KR':
            # 09:00-15:30 KST
            if hour < 9 or hour > 15:
                return False
            if hour == 15 and minute > 30:
                return False
            return True

        else:  # US
            # 09:30-16:00 EST
            if hour < 9 or hour > 16:
                return False
            if hour == 9 and minute < 30:
                return False
            return True

    @classmethod
    def search_korean_stocks(cls, query: str) -> list:
        """
        한국 주식 검색 (캐시 및 즐겨찾기 기반)

        Note: 전체 검색을 위해서는 korean_stocks.KoreanStockData.search_stock() 사용 권장
        """
        query = query.upper()
        results = []

        # 캐시에서만 검색
        for code, info in cls.KOREAN_STOCKS.items():
            if (query in code or
                query in info.get('name', '').upper() or
                query in info.get('name_en', '').upper()):
                results.append({
                    'code': code,
                    'ticker': f"{code}.KS",
                    'name': info.get('name', code),
                    'name_en': info.get('name_en', code),
                    'market': info.get('market', 'KOSPI'),
                    'sector': info.get('sector', 'Unknown')
                })

        # 즐겨찾기에서도 검색
        try:
            from korean_stocks import KoreanStockData
            collector = KoreanStockData()
            favorites = collector.get_favorites()

            for code, name in favorites.items():
                if query in code or query in name.upper():
                    # 캐시에 추가
                    if code not in cls.KOREAN_STOCKS:
                        info = cls._fetch_korean_stock_info(code)
                        if info:
                            results.append({
                                'code': code,
                                'ticker': f"{code}.KS",
                                'name': info.get('name', name),
                                'name_en': info.get('name_en', name),
                                'market': info.get('market', 'KOSPI'),
                                'sector': info.get('sector', 'Unknown')
                            })
        except ImportError:
            pass

        return results


# 편의 함수들
def normalize_ticker(ticker: str, market: Optional[str] = None) -> Tuple[str, str]:
    """티커 정규화"""
    return TickerManager.normalize_ticker(ticker, market)


def detect_market(ticker: str) -> str:
    """시장 감지"""
    return TickerManager.detect_market(ticker)


def get_stock_info(ticker: str) -> Dict:
    """종목 정보"""
    return TickerManager.get_stock_info(ticker)


def format_price(price: float, market: str) -> str:
    """가격 포맷"""
    return TickerManager.format_price(price, market)


if __name__ == "__main__":
    # 테스트
    print("=== 티커 정규화 테스트 ===")

    test_tickers = [
        "005930",       # 삼성전자 코드
        "삼성전자",      # 한글명
        "005930.KS",    # Yahoo 형식
        "AAPL",         # 미국 주식
        "MSFT",         # 미국 주식
    ]

    for ticker in test_tickers:
        normalized, market = normalize_ticker(ticker)
        info = get_stock_info(ticker)
        print(f"\n입력: {ticker}")
        print(f"  정규화: {normalized}")
        print(f"  시장: {market}")
        print(f"  종목명: {info['name']} ({info['name_en']})")
        print(f"  통화: {info['currency']}")
        print(f"  거래시간: {info['trading_hours']}")

    print("\n=== 가격 포맷 테스트 ===")
    print(f"한국: {format_price(75000, 'KR')}")
    print(f"미국: {format_price(175.50, 'US')}")

    print("\n=== 한국 주식 검색 ===")
    results = TickerManager.search_korean_stocks("삼성")
    for r in results[:3]:
        print(f"  {r['code']} - {r['name']} ({r['name_en']})")
