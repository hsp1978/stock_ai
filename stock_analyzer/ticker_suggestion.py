#!/usr/bin/env python3
"""
Ticker Suggestion Module - 잘못된 종목 입력 시 유사 종목 추천

주요 기능:
1. 회사명/티커 퍼지 매칭
2. 한국/미국 주식 검색
3. 유사도 기반 추천
4. 인터랙티브 선택 지원
"""

from typing import List, Dict, Tuple, Optional
import difflib
import logging
import re
import json

logger = logging.getLogger(__name__)


class TickerSuggestion:
    """종목 추천 시스템"""

    def __init__(self):
        self.korean_stocks = []
        self.us_stocks = []
        self._load_stock_lists()

    def _load_stock_lists(self):
        """주식 목록 로드"""
        try:
            # 한국 주식 목록 로드
            self._load_korean_stocks()
            # 미국 주식 목록 로드
            self._load_us_stocks()
        except Exception as e:
            logger.error("주식 목록 로드 실패: %s", e)

    def _load_korean_stocks(self):
        """한국 주식 목록 로드 (Database + FinanceDataReader)"""

        # 1. 먼저 로컬 데이터베이스에서 로드
        try:
            import os
            db_file = os.path.join(os.path.dirname(__file__), 'korean_stocks_database.json')
            if os.path.exists(db_file):
                with open(db_file, 'r', encoding='utf-8') as f:
                    db_data = json.load(f)
                    stocks = db_data.get('stocks', {})

                    for code, info in stocks.items():
                        name = info['name']
                        market = info['market']
                        aliases = info.get('aliases', [])

                        # KOSPI/KOSDAQ 구분
                        if market == 'KOSDAQ':
                            ticker_with_suffix = f"{code}.KQ"
                        else:
                            ticker_with_suffix = f"{code}.KS"

                        # 검색 텍스트 생성
                        search_text_parts = [code, name, ticker_with_suffix] + aliases
                        search_text = ' '.join(search_text_parts).lower()

                        self.korean_stocks.append({
                            'ticker': ticker_with_suffix,
                            'code': code,
                            'name': name,
                            'market': 'KR',
                            'exchange': market,
                            'search_text': search_text,
                            'aliases': aliases
                        })

                    logger.debug("데이터베이스에서 한국 주식 %d개 로드 완료", len(self.korean_stocks))

                    # 데이터베이스 로드 성공 시 FinanceDataReader 스킵
                    return

        except Exception as e:
            logger.warning("데이터베이스 로드 실패, FinanceDataReader 시도: %s", e)

        # 2. 데이터베이스가 없으면 FinanceDataReader 시도
        try:
            import FinanceDataReader as fdr

            # KRX 전체 종목 가져오기
            krx_list = fdr.StockListing('KRX')

            for _, row in krx_list.iterrows():
                code = str(row.get('Symbol', row.get('Code', '')))
                name = str(row.get('Name', row.get('종목명', '')))
                market = str(row.get('Market', 'KRX'))

                if code and name:
                    # KOSPI/KOSDAQ 구분
                    if 'KOSDAQ' in market:
                        ticker_with_suffix = f"{code}.KQ"
                    else:
                        ticker_with_suffix = f"{code}.KS"

                    # 별칭 추가 (NAVER → 네이버 등)
                    aliases = []
                    if name == 'NAVER':
                        aliases.append('네이버')
                    elif name == 'POSCO홀딩스':
                        aliases.append('포스코')
                    elif name == 'LG에너지솔루션':
                        aliases.append('LG에너지')
                    elif name == 'SK하이닉스':
                        aliases.append('SK하이닉스')
                        aliases.append('하이닉스')

                    search_text_parts = [code, name, ticker_with_suffix] + aliases
                    search_text = ' '.join(search_text_parts).lower()

                    self.korean_stocks.append({
                        'ticker': ticker_with_suffix,
                        'code': code,
                        'name': name,
                        'market': 'KR',
                        'exchange': market,
                        'search_text': search_text,
                        'aliases': aliases  # 별칭 저장
                    })

            logger.debug("FinanceDataReader에서 한국 주식 %d개 로드 완료", len(self.korean_stocks))

        except ImportError:
            logger.warning("FinanceDataReader 미설치 - 한국 주식 검색 제한적")
            # 대표 종목만 하드코딩
            self.korean_stocks = [
                {'ticker': '005930.KS', 'code': '005930', 'name': '삼성전자', 'market': 'KR', 'exchange': 'KOSPI', 'search_text': '005930 삼성전자 samsung electronics'},
                {'ticker': '000660.KS', 'code': '000660', 'name': 'SK하이닉스', 'market': 'KR', 'exchange': 'KOSPI', 'search_text': '000660 sk하이닉스 sk hynix'},
                {'ticker': '035420.KQ', 'code': '035420', 'name': 'NAVER', 'market': 'KR', 'exchange': 'KOSDAQ', 'search_text': '035420 naver 네이버'},
                {'ticker': '035720.KQ', 'code': '035720', 'name': '카카오', 'market': 'KR', 'exchange': 'KOSDAQ', 'search_text': '035720 kakao 카카오'},
                {'ticker': '051910.KS', 'code': '051910', 'name': 'LG화학', 'market': 'KR', 'exchange': 'KOSPI', 'search_text': '051910 lg화학 lg chem'},
                {'ticker': '006400.KS', 'code': '006400', 'name': '삼성SDI', 'market': 'KR', 'exchange': 'KOSPI', 'search_text': '006400 삼성sdi samsung sdi'},
                {'ticker': '005380.KS', 'code': '005380', 'name': '현대차', 'market': 'KR', 'exchange': 'KOSPI', 'search_text': '005380 현대차 hyundai motor'},
                {'ticker': '207940.KS', 'code': '207940', 'name': '삼성바이오로직스', 'market': 'KR', 'exchange': 'KOSPI', 'search_text': '207940 삼성바이오로직스 samsung biologics'},
                {'ticker': '000270.KS', 'code': '000270', 'name': '기아', 'market': 'KR', 'exchange': 'KOSPI', 'search_text': '000270 기아 kia'},
                {'ticker': '068270.KQ', 'code': '068270', 'name': '셀트리온', 'market': 'KR', 'exchange': 'KOSDAQ', 'search_text': '068270 셀트리온 celltrion'},
                {'ticker': '0126Z0.KS', 'code': '0126Z0', 'name': '삼성에피스홀딩스', 'market': 'KR', 'exchange': 'KOSPI', 'search_text': '0126z0 삼성에피스 samsung epis'},
            ]
        except Exception as e:
            logger.error("한국 주식 로드 오류: %s", e)

    def _load_us_stocks(self):
        """미국 주요 주식 목록 (하드코딩)"""
        # S&P 500 대표 종목들
        self.us_stocks = [
            {'ticker': 'AAPL', 'name': 'Apple Inc.', 'market': 'US', 'exchange': 'NASDAQ', 'search_text': 'aapl apple'},
            {'ticker': 'MSFT', 'name': 'Microsoft Corporation', 'market': 'US', 'exchange': 'NASDAQ', 'search_text': 'msft microsoft'},
            {'ticker': 'AMZN', 'name': 'Amazon.com Inc.', 'market': 'US', 'exchange': 'NASDAQ', 'search_text': 'amzn amazon'},
            {'ticker': 'NVDA', 'name': 'NVIDIA Corporation', 'market': 'US', 'exchange': 'NASDAQ', 'search_text': 'nvda nvidia'},
            {'ticker': 'GOOGL', 'name': 'Alphabet Inc. Class A', 'market': 'US', 'exchange': 'NASDAQ', 'search_text': 'googl google alphabet'},
            {'ticker': 'META', 'name': 'Meta Platforms Inc.', 'market': 'US', 'exchange': 'NASDAQ', 'search_text': 'meta facebook'},
            {'ticker': 'BRK.B', 'name': 'Berkshire Hathaway Inc.', 'market': 'US', 'exchange': 'NYSE', 'search_text': 'brk.b berkshire hathaway'},
            {'ticker': 'TSLA', 'name': 'Tesla Inc.', 'market': 'US', 'exchange': 'NASDAQ', 'search_text': 'tsla tesla'},
            {'ticker': 'JPM', 'name': 'JPMorgan Chase & Co.', 'market': 'US', 'exchange': 'NYSE', 'search_text': 'jpm jpmorgan chase'},
            {'ticker': 'JNJ', 'name': 'Johnson & Johnson', 'market': 'US', 'exchange': 'NYSE', 'search_text': 'jnj johnson'},
            {'ticker': 'V', 'name': 'Visa Inc.', 'market': 'US', 'exchange': 'NYSE', 'search_text': 'v visa'},
            {'ticker': 'WMT', 'name': 'Walmart Inc.', 'market': 'US', 'exchange': 'NYSE', 'search_text': 'wmt walmart'},
            {'ticker': 'PG', 'name': 'Procter & Gamble', 'market': 'US', 'exchange': 'NYSE', 'search_text': 'pg procter gamble'},
            {'ticker': 'MA', 'name': 'Mastercard Inc.', 'market': 'US', 'exchange': 'NYSE', 'search_text': 'ma mastercard'},
            {'ticker': 'HD', 'name': 'Home Depot Inc.', 'market': 'US', 'exchange': 'NYSE', 'search_text': 'hd home depot'},
            {'ticker': 'DIS', 'name': 'Walt Disney Company', 'market': 'US', 'exchange': 'NYSE', 'search_text': 'dis disney'},
            {'ticker': 'PYPL', 'name': 'PayPal Holdings Inc.', 'market': 'US', 'exchange': 'NASDAQ', 'search_text': 'pypl paypal'},
            {'ticker': 'NFLX', 'name': 'Netflix Inc.', 'market': 'US', 'exchange': 'NASDAQ', 'search_text': 'nflx netflix'},
            {'ticker': 'INTC', 'name': 'Intel Corporation', 'market': 'US', 'exchange': 'NASDAQ', 'search_text': 'intc intel'},
            {'ticker': 'AMD', 'name': 'Advanced Micro Devices', 'market': 'US', 'exchange': 'NASDAQ', 'search_text': 'amd advanced micro'},
            {'ticker': 'CRM', 'name': 'Salesforce Inc.', 'market': 'US', 'exchange': 'NYSE', 'search_text': 'crm salesforce'},
            {'ticker': 'ORCL', 'name': 'Oracle Corporation', 'market': 'US', 'exchange': 'NYSE', 'search_text': 'orcl oracle'},
            {'ticker': 'CSCO', 'name': 'Cisco Systems Inc.', 'market': 'US', 'exchange': 'NASDAQ', 'search_text': 'csco cisco'},
            {'ticker': 'PEP', 'name': 'PepsiCo Inc.', 'market': 'US', 'exchange': 'NASDAQ', 'search_text': 'pep pepsi pepsico'},
            {'ticker': 'KO', 'name': 'Coca-Cola Company', 'market': 'US', 'exchange': 'NYSE', 'search_text': 'ko coca cola coke'},
            {'ticker': 'BA', 'name': 'Boeing Company', 'market': 'US', 'exchange': 'NYSE', 'search_text': 'ba boeing'},
            {'ticker': 'GS', 'name': 'Goldman Sachs', 'market': 'US', 'exchange': 'NYSE', 'search_text': 'gs goldman sachs'},
            {'ticker': 'MS', 'name': 'Morgan Stanley', 'market': 'US', 'exchange': 'NYSE', 'search_text': 'ms morgan stanley'},
        ]
        logger.debug("미국 주식 %d개 로드 완료", len(self.us_stocks))

    def find_suggestions(self, input_text: str, max_results: int = 5) -> List[Dict]:
        """
        입력된 텍스트와 유사한 종목 찾기

        Args:
            input_text: 사용자 입력 (티커 또는 회사명)
            max_results: 최대 결과 수

        Returns:
            추천 종목 리스트
        """
        input_lower = input_text.lower().strip()

        # 특수문자 제거
        input_clean = re.sub(r'[^\w\s]', '', input_lower)

        suggestions = []

        # 한국 주식 검색
        for stock in self.korean_stocks:
            # 완전 일치 (티커, 코드, 회사명)
            if input_lower in [stock['ticker'].lower(), stock['code'].lower(), stock['name'].lower()]:
                stock['score'] = 1.0
                stock['match_type'] = 'exact'
                suggestions.append(stock.copy())
                continue

            # 별칭 완전 일치 (네이버, 포스코 등)
            if 'aliases' in stock and input_lower in [alias.lower() for alias in stock.get('aliases', [])]:
                stock_copy = stock.copy()
                stock_copy['score'] = 0.99  # 별칭 일치는 99% 점수 (자동 선택됨)
                stock_copy['match_type'] = 'alias'
                suggestions.append(stock_copy)
                continue

            # 회사명이 입력값으로 시작하는 경우 (예: 삼성에피스 → 삼성에피스홀딩스)
            if stock['name'].lower().startswith(input_lower) and len(input_lower) >= 3:
                stock_copy = stock.copy()
                # 길이 비율에 따라 점수 조정
                length_ratio = len(input_lower) / len(stock['name'])
                # 80% 이상 일치하면 95% 이상 점수 부여
                if length_ratio >= 0.6:  # 60% 이상 일치
                    stock_copy['score'] = 0.95
                else:
                    stock_copy['score'] = 0.85 + (length_ratio * 0.15)
                stock_copy['match_type'] = 'starts_with'
                suggestions.append(stock_copy)
                continue

            # 입력값이 회사명에 포함되는 경우
            if input_lower in stock['name'].lower() and len(input_lower) >= 3:
                stock_copy = stock.copy()
                stock_copy['score'] = 0.85
                stock_copy['match_type'] = 'contains'
                suggestions.append(stock_copy)
                continue

            # 부분 일치 (search_text)
            if input_clean in stock['search_text']:
                stock['score'] = 0.8
                stock['match_type'] = 'partial'
                suggestions.append(stock.copy())
                continue

            # 유사도 계산
            name_similarity = difflib.SequenceMatcher(None, input_lower, stock['name'].lower()).ratio()
            ticker_similarity = difflib.SequenceMatcher(None, input_lower, stock['ticker'].lower()).ratio()
            code_similarity = difflib.SequenceMatcher(None, input_clean, stock['code'].lower()).ratio()

            max_similarity = max(name_similarity, ticker_similarity, code_similarity)

            if max_similarity > 0.6:  # 60% 이상 유사도
                stock_copy = stock.copy()
                stock_copy['score'] = max_similarity
                stock_copy['match_type'] = 'fuzzy'
                suggestions.append(stock_copy)

        # 미국 주식 검색
        for stock in self.us_stocks:
            # 완전 일치
            if input_lower in [stock['ticker'].lower(), stock['name'].lower()]:
                stock['score'] = 1.0
                stock['match_type'] = 'exact'
                suggestions.append(stock.copy())
                continue

            # 부분 일치
            if input_clean in stock['search_text']:
                stock['score'] = 0.8
                stock['match_type'] = 'partial'
                suggestions.append(stock.copy())
                continue

            # 유사도 계산
            name_similarity = difflib.SequenceMatcher(None, input_lower, stock['name'].lower()).ratio()
            ticker_similarity = difflib.SequenceMatcher(None, input_lower, stock['ticker'].lower()).ratio()

            max_similarity = max(name_similarity, ticker_similarity)

            if max_similarity > 0.6:
                stock_copy = stock.copy()
                stock_copy['score'] = max_similarity
                stock_copy['match_type'] = 'fuzzy'
                suggestions.append(stock_copy)

        # 점수순 정렬
        suggestions.sort(key=lambda x: x['score'], reverse=True)

        # 중복 제거 (같은 티커)
        seen = set()
        unique_suggestions = []
        for s in suggestions:
            if s['ticker'] not in seen:
                seen.add(s['ticker'])
                unique_suggestions.append(s)

        return unique_suggestions[:max_results]

    def format_suggestions(self, suggestions: List[Dict]) -> str:
        """추천 목록을 보기 좋게 포맷"""
        if not suggestions:
            return "일치하는 종목을 찾을 수 없습니다."

        lines = ["비슷한 종목을 찾았습니다:\n"]

        for i, stock in enumerate(suggestions, 1):
            score_percent = int(stock['score'] * 100)
            match_icon = "✓" if stock['match_type'] == 'exact' else "≈"

            if stock['market'] == 'KR':
                lines.append(f"{i}. {match_icon} {stock['name']} ({stock['ticker']}) - {stock['exchange']} [{score_percent}%]")
            else:
                lines.append(f"{i}. {match_icon} {stock['name']} ({stock['ticker']}) - {stock['exchange']} [{score_percent}%]")

        return "\n".join(lines)

    def suggest_and_select(self, input_text: str, auto_select_threshold: float = 0.95) -> Optional[str]:
        """
        종목 추천 및 선택 (자동/수동)

        Args:
            input_text: 사용자 입력
            auto_select_threshold: 자동 선택 임계값 (기본 95%)

        Returns:
            선택된 티커 또는 None
        """
        suggestions = self.find_suggestions(input_text)

        if not suggestions:
            return None

        # 최고 점수가 임계값 이상이면 자동 선택
        if suggestions[0]['score'] >= auto_select_threshold:
            best = suggestions[0]
            print(f"✅ 자동 선택: {best['name']} ({best['ticker']})")
            return best['ticker']

        # 수동 선택 필요
        print("\n" + self.format_suggestions(suggestions))
        print("\n번호를 입력하여 선택하거나, 0을 입력하여 취소하세요.")

        # CLI 환경에서 선택 (API에서는 다른 방식 필요)
        try:
            choice = input("선택: ").strip()
            if choice == '0':
                return None

            idx = int(choice) - 1
            if 0 <= idx < len(suggestions):
                selected = suggestions[idx]
                print(f"✅ 선택됨: {selected['name']} ({selected['ticker']})")
                return selected['ticker']
        except (ValueError, IndexError, EOFError):
            pass

        return None


_shared_suggester: Optional[TickerSuggestion] = None


def _get_suggester() -> TickerSuggestion:
    global _shared_suggester
    if _shared_suggester is None:
        _shared_suggester = TickerSuggestion()
    return _shared_suggester


def suggest_ticker(input_text: str, max_results: int = 5) -> Dict:
    """
    티커 추천 API 인터페이스

    Args:
        input_text: 사용자 입력
        max_results: 최대 결과 수

    Returns:
        {
            'found': bool,
            'suggestions': List[Dict],
            'formatted': str,
            'best_match': Optional[str]
        }
    """
    suggester = _get_suggester()
    suggestions = suggester.find_suggestions(input_text, max_results)

    result = {
        'found': len(suggestions) > 0,
        'suggestions': suggestions,
        'formatted': suggester.format_suggestions(suggestions),
        'best_match': suggestions[0]['ticker'] if suggestions and suggestions[0]['score'] >= 0.95 else None
    }

    return result


# 테스트 코드
if __name__ == "__main__":
    print("="*60)
    print("종목 추천 시스템 테스트")
    print("="*60)

    suggester = TickerSuggestion()

    test_cases = [
        "삼성전자",      # 정확한 한국 종목명
        "samsung",       # 영문 검색
        "네이버",        # 한글 종목명
        "0126Z0",        # 특수 코드
        "애플",          # 한글로 미국 주식
        "APPL",          # 오타 (AAPL이 맞음)
        "테슬라",        # 한글 미국 주식
        "카카오뱅크",    # 부분 일치
        "005390",        # 틀린 코드 (005930이 맞음)
        "구글",          # 한글 검색
        "INVALID123",    # 존재하지 않는 종목
    ]

    for test in test_cases:
        print(f"\n입력: '{test}'")
        print("-" * 40)

        suggestions = suggester.find_suggestions(test, max_results=3)

        if suggestions:
            print(suggester.format_suggestions(suggestions))
            if suggestions[0]['score'] >= 0.95:
                print(f"→ 자동 선택 가능: {suggestions[0]['ticker']}")
        else:
            print("일치하는 종목을 찾을 수 없습니다.")

    print("\n" + "="*60)
    print("API 테스트")
    print("="*60)

    # API 함수 테스트
    api_result = suggest_ticker("삼성", max_results=3)
    print(f"\nAPI 결과:")
    print(f"찾음: {api_result['found']}")
    print(f"최상위 매치: {api_result['best_match']}")
    print(f"추천 수: {len(api_result['suggestions'])}")