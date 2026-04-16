#!/usr/bin/env python3
"""
한국 주식 데이터 수집 모듈
- Yahoo Finance .KS/.KQ 티커 지원
- 네이버 금융 데이터 보조
- 한국 시장 특화 기능
- 즐겨찾기 관리
"""

import yfinance as yf
import pandas as pd
import requests
from datetime import datetime, timedelta
from typing import Optional, Dict, List
import re
from bs4 import BeautifulSoup
import json
import os


class KoreanStockData:
    """한국 주식 데이터 수집기"""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        # 캐시 - 이미 조회한 종목명 저장
        self._name_cache = {}
        # 즐겨찾기 파일 경로
        self.favorites_file = os.path.join(os.path.dirname(__file__), 'korean_stock_favorites.json')
        # 즐겨찾기 로드
        self.favorites = self.load_favorites()

    def normalize_ticker(self, ticker: str) -> tuple[str, str, str]:
        """
        티커 정규화
        - 입력: "005930" 또는 "005930.KS"
        - 출력: (yahoo_ticker, stock_code, market)
        """
        ticker = ticker.strip().upper()

        # 이미 .KS 또는 .KQ 형식
        if '.KS' in ticker or '.KQ' in ticker:
            stock_code = ticker.split('.')[0]
            market = 'KOSPI' if '.KS' in ticker else 'KOSDAQ'
            return ticker, stock_code, market

        # 6자리 숫자 (종목코드)
        if re.match(r'^\d{6}$', ticker):
            # 먼저 KOSPI 시도, 실패하면 KOSDAQ
            yahoo_ticker = f"{ticker}.KS"
            return yahoo_ticker, ticker, 'KOSPI'

        # 기본값 (숫자가 아닌 경우도 처리)
        return f"{ticker}.KS", ticker, 'KOSPI'

    def get_stock_name(self, ticker: str) -> str:
        """종목코드 → 종목명 (동적으로 가져오기)"""
        stock_code = ticker.replace('.KS', '').replace('.KQ', '')

        # 캐시 확인
        if stock_code in self._name_cache:
            return self._name_cache[stock_code]

        try:
            # Yahoo Finance에서 종목명 가져오기
            yahoo_ticker, _, _ = self.normalize_ticker(ticker)
            stock = yf.Ticker(yahoo_ticker)
            info = stock.info

            # longName 또는 shortName 사용
            name = info.get('longName') or info.get('shortName') or stock_code

            # 캐시에 저장
            self._name_cache[stock_code] = name
            return name
        except:
            # 실패시 종목코드 그대로 반환
            return stock_code

    def fetch_ohlcv(self, ticker: str, period: str = '1y') -> Optional[pd.DataFrame]:
        """
        OHLCV 데이터 수집

        Args:
            ticker: 종목코드 (예: "005930" or "005930.KS")
            period: 기간 (1mo, 3mo, 6mo, 1y, 2y, 5y)

        Returns:
            DataFrame with OHLCV data
        """
        try:
            yahoo_ticker, stock_code, market = self.normalize_ticker(ticker)
            print(f"[KR Stock] Fetching {yahoo_ticker} ({self.get_stock_name(stock_code)})")

            stock = yf.Ticker(yahoo_ticker)
            df = stock.history(period=period)

            if df.empty:
                print(f"[KR Stock] No data for {yahoo_ticker}, trying .KQ")
                # KOSPI에서 못 찾으면 KOSDAQ 시도
                yahoo_ticker = f"{stock_code}.KQ"
                stock = yf.Ticker(yahoo_ticker)
                df = stock.history(period=period)

            if df.empty:
                print(f"[KR Stock] Failed to fetch data for {ticker}")
                return None

            # 컬럼명 표준화
            df = df.rename(columns={
                'Open': 'Open',
                'High': 'High',
                'Low': 'Low',
                'Close': 'Close',
                'Volume': 'Volume'
            })

            df['Ticker'] = yahoo_ticker
            df['Market'] = market

            print(f"[KR Stock] Success: {len(df)} days of data")
            return df

        except Exception as e:
            print(f"[KR Stock] Error fetching {ticker}: {e}")
            return None

    def fetch_naver_info(self, ticker: str) -> Dict:
        """
        네이버 금융에서 추가 정보 수집
        - 외국인 보유율
        - 시가총액
        - PER, PBR
        """
        try:
            stock_code = ticker.replace('.KS', '').replace('.KQ', '')
            url = f"https://finance.naver.com/item/main.naver?code={stock_code}"

            response = self.session.get(url, timeout=10)
            response.raise_for_status()

            soup = BeautifulSoup(response.text, 'html.parser')

            info = {
                'ticker': stock_code,
                'name': self.get_stock_name(stock_code),
                'market_cap': None,
                'foreign_ratio': None,
                'per': None,
                'pbr': None,
            }

            # 외국인 보유율 파싱 (네이버 금융 구조에 따라 수정 필요)
            # 실제 스크래핑 코드는 네이버 금융 HTML 구조 분석 후 구현

            return info

        except Exception as e:
            print(f"[Naver] Error fetching info for {ticker}: {e}")
            return {}

    def fetch_institutional_trading(self, ticker: str, days: int = 5) -> Dict:
        """
        외인/기관/개인 매매동향 (pykrx 사용)

        Args:
            ticker: 종목코드 (예: "005930" or "005930.KS")
            days: 최근 N일 데이터

        Returns:
            {
                'ticker': '005930',
                'period': '2026-04-10 ~ 2026-04-15',
                'summary': {
                    'foreign_net': 1000,  # 외국인 순매수 (주)
                    'institution_net': -500,
                    'individual_net': -500
                },
                'daily': [
                    {
                        'date': '2026-04-15',
                        'foreign': {'buy': 1000, 'sell': 500, 'net': 500},
                        'institution': {'buy': 800, 'sell': 1200, 'net': -400},
                        'individual': {'buy': 2000, 'sell': 2100, 'net': -100}
                    }
                ]
            }
        """
        try:
            stock_code = ticker.replace('.KS', '').replace('.KQ', '')

            # FinanceDataReader 사용하여 실제 데이터 수집
            try:
                import FinanceDataReader as fdr

                # 날짜 계산
                end_date = datetime.now()
                start_date = end_date - timedelta(days=days+10)

                # 투자주체별 매매동향 조회
                df = fdr.DataReader(stock_code, start_date, end_date, data_source='krx-투자자')

                # 데이터가 없거나 필요한 컬럼이 없으면 fallback
                if df is None or df.empty or '외국인' not in df.columns:
                    if df is not None and not df.empty and '외국인' not in df.columns:
                        print(f"[FDR] API changed - investor columns not available for {stock_code}")
                    else:
                        print(f"[FDR] No institutional data for {stock_code}")
                    # Fallback: Yahoo Finance에서 가져온 데이터로 추정
                    return self._estimate_institutional_from_volume(stock_code, days)

                # 최근 N일 데이터만 추출
                df = df.tail(days)

                # 일별 데이터 구성
                daily_data = []
                for date, row in df.iterrows():
                    # FinanceDataReader 컬럼: 외국인, 기관, 개인 (단위: 주)
                    daily_data.append({
                        'date': date.strftime('%Y-%m-%d') if hasattr(date, 'strftime') else str(date),
                        'foreign': {
                            'net': int(row.get('외국인', 0))
                        },
                        'institution': {
                            'net': int(row.get('기관', 0))
                        },
                        'individual': {
                            'net': int(row.get('개인', 0))
                        }
                    })

                # 전체 기간 합계
                foreign_net_total = df['외국인'].sum() if '외국인' in df.columns else 0
                institution_net_total = df['기관'].sum() if '기관' in df.columns else 0
                individual_net_total = df['개인'].sum() if '개인' in df.columns else 0

                return {
                    'ticker': stock_code,
                    'period': f"{daily_data[0]['date']} ~ {daily_data[-1]['date']}" if daily_data else "N/A",
                    'summary': {
                        'foreign_net': int(foreign_net_total),
                        'institution_net': int(institution_net_total),
                        'individual_net': int(individual_net_total)
                    },
                    'daily': daily_data
                }

            except ImportError:
                print(f"[Institutional] FinanceDataReader not available")
                return {}
            except Exception as fetch_error:
                print(f"[Institutional] FDR fetch error: {fetch_error}")
                # Fallback
                return self._estimate_institutional_from_volume(stock_code, days)

        except Exception as e:
            print(f"[Institutional] Error fetching trading data for {ticker}: {e}")
            import traceback
            traceback.print_exc()
            return {}

    def _estimate_institutional_from_volume(self, stock_code: str, days: int) -> Dict:
        """
        외국인/기관 데이터를 구할 수 없을 때 거래량 기반 추정
        (실제 데이터는 아니지만 시스템 테스트용)
        """
        try:
            ticker = f"{stock_code}.KS"
            stock = yf.Ticker(ticker)
            hist = stock.history(period=f"{days+5}d")

            if hist.empty:
                return {}

            hist = hist.tail(days)

            # 거래량 기반 간단한 추정 (실제 데이터 아님!)
            daily_data = []
            total_foreign = 0
            total_inst = 0
            total_indiv = 0

            for date, row in hist.iterrows():
                volume = int(row['Volume'])
                # 추정: 외국인 30%, 기관 20%, 개인 50%
                est_foreign = int(volume * 0.3 * (1 if row['Close'] > row['Open'] else -1))
                est_inst = int(volume * 0.2 * (1 if row['Close'] > row['Open'] else -1))
                est_indiv = -est_foreign - est_inst

                total_foreign += est_foreign
                total_inst += est_inst
                total_indiv += est_indiv

                daily_data.append({
                    'date': date.strftime('%Y-%m-%d'),
                    'foreign': {'net': est_foreign},
                    'institution': {'net': est_inst},
                    'individual': {'net': est_indiv}
                })

            return {
                'ticker': stock_code,
                'period': f"{daily_data[0]['date']} ~ {daily_data[-1]['date']}" if daily_data else "N/A",
                'summary': {
                    'foreign_net': total_foreign,
                    'institution_net': total_inst,
                    'individual_net': total_indiv
                },
                'daily': daily_data,
                'estimated': True  # 추정 데이터 표시
            }

        except Exception as e:
            print(f"[Estimate] Error: {e}")
            return {}

    def get_market_index(self, index: str = 'KOSPI') -> Dict:
        """
        시장 지수 정보

        Args:
            index: 'KOSPI' or 'KOSDAQ'

        Returns:
            {
                'current': 2500.0,
                'change': 10.5,
                'change_pct': 0.42
            }
        """
        try:
            ticker = '^KS11' if index == 'KOSPI' else '^KQ11'

            stock = yf.Ticker(ticker)
            hist = stock.history(period='5d')

            if hist.empty:
                return {}

            current = hist['Close'].iloc[-1]
            prev = hist['Close'].iloc[-2] if len(hist) > 1 else current
            change = current - prev
            change_pct = (change / prev) * 100

            return {
                'index': index,
                'current': round(current, 2),
                'change': round(change, 2),
                'change_pct': round(change_pct, 2)
            }

        except Exception as e:
            print(f"[Market Index] Error fetching {index}: {e}")
            return {}

    def verify_ticker(self, ticker: str) -> bool:
        """
        티커가 유효한지 확인

        Args:
            ticker: 종목코드 또는 Yahoo 티커

        Returns:
            bool: 유효한 티커 여부
        """
        try:
            yahoo_ticker, _, _ = self.normalize_ticker(ticker)
            stock = yf.Ticker(yahoo_ticker)
            hist = stock.history(period='5d')

            # 데이터가 없으면 KOSDAQ 시도
            if hist.empty and '.KS' in yahoo_ticker:
                yahoo_ticker = yahoo_ticker.replace('.KS', '.KQ')
                stock = yf.Ticker(yahoo_ticker)
                hist = stock.history(period='5d')

            return not hist.empty
        except:
            return False

    def load_favorites(self) -> Dict[str, str]:
        """즐겨찾기 목록 로드"""
        if os.path.exists(self.favorites_file):
            try:
                with open(self.favorites_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except:
                return {}
        return {}

    def save_favorites(self):
        """즐겨찾기 목록 저장"""
        try:
            with open(self.favorites_file, 'w', encoding='utf-8') as f:
                json.dump(self.favorites, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            print(f"[Favorites] 저장 실패: {e}")
            return False

    def add_favorite(self, code: str, name: str = None) -> bool:
        """즐겨찾기 추가"""
        if not name:
            name = self.get_stock_name(code)
        self.favorites[code] = name
        return self.save_favorites()

    def remove_favorite(self, code: str) -> bool:
        """즐겨찾기 제거"""
        if code in self.favorites:
            del self.favorites[code]
            return self.save_favorites()
        return False

    def get_favorites(self) -> Dict[str, str]:
        """즐겨찾기 목록 반환"""
        return self.favorites.copy()

    def search_stock_by_code(self, code: str) -> Optional[Dict]:
        """
        종목코드로 정보 조회

        Args:
            code: 6자리 종목코드

        Returns:
            {'code': '072130', 'name': '유엔젤', 'market': 'KOSDAQ'} or None
        """
        if not re.match(r'^\d{6}$', code):
            return None

        # 먼저 KOSPI 확인
        try:
            ticker_ks = f"{code}.KS"
            stock = yf.Ticker(ticker_ks)
            hist = stock.history(period='5d')

            if not hist.empty:
                info = stock.info
                name = info.get('longName') or info.get('shortName') or code
                return {'code': code, 'name': name, 'market': 'KOSPI', 'ticker': ticker_ks}

            # KOSDAQ 확인
            ticker_kq = f"{code}.KQ"
            stock = yf.Ticker(ticker_kq)
            hist = stock.history(period='5d')

            if not hist.empty:
                info = stock.info
                name = info.get('longName') or info.get('shortName') or code
                return {'code': code, 'name': name, 'market': 'KOSDAQ', 'ticker': ticker_kq}

        except:
            pass

        return None

    def search_stock_by_name(self, name: str) -> Optional[str]:
        """
        종목명으로 종목코드 검색
        먼저 즐겨찾기에서 검색, 없으면 동적 검색

        Args:
            name: 종목명 (예: "유엔젤", "삼성전자")

        Returns:
            종목코드 (예: "072130") or None
        """
        name_upper = name.upper().strip()

        # 1. 즐겨찾기에서 검색
        for code, stock_name in self.favorites.items():
            if name_upper in stock_name.upper():
                return code

        # 2. 종목코드인지 확인 (6자리 숫자)
        if re.match(r'^\d{6}$', name):
            return name

        # 3. 동적 검색 시도 - 주요 한국 종목 매핑
        # 사용자가 자주 검색하는 종목은 즐겨찾기에 추가하도록 유도
        basic_mapping = {
            # 대형주
            '삼성전자': '005930',
            '삼전': '005930',
            'SK하이닉스': '000660',
            '하이닉스': '000660',
            'LG화학': '051910',
            '엘지화학': '051910',
            'NAVER': '035420',
            '네이버': '035420',
            '현대차': '005380',
            '현대자동차': '005380',
            '기아': '000270',
            '기아자동차': '000270',
            '카카오': '035720',
            '삼성바이오로직스': '207940',
            '삼바': '207940',
            '셀트리온': '068270',
            'LG에너지솔루션': '373220',
            '엘지에너지': '373220',
            'LGES': '373220',
            '삼성SDI': '006400',
            '삼성에스디아이': '006400',
            '포스코홀딩스': '005490',
            '포스코': '005490',
            'POSCO': '005490',
            '현대모비스': '012330',
            '모비스': '012330',
            'KB금융': '105560',
            '국민은행': '105560',
            '신한지주': '055550',
            '신한금융': '055550',
            '하나금융지주': '086790',
            '하나금융': '086790',
            '삼성물산': '028260',
            'SK이노베이션': '096770',
            'SK이노': '096770',
            'LG전자': '066570',
            '엘지전자': '066570',
            '삼성생명': '032830',
            'SK텔레콤': '017670',
            'SKT': '017670',
            'KT': '030200',
            'LG': '003550',
            '엘지': '003550',
            'SK': '034730',
            '에스케이': '034730',
            '한국전력': '015760',
            '한전': '015760',

            # 중형주
            '엔씨소프트': '036570',
            'NCSOFT': '036570',
            '넷마블': '251270',
            '펄어비스': '263750',
            '크래프톤': '259960',
            '배틀그라운드': '259960',
            '카카오게임즈': '293490',
            '위메이드': '112040',
            '넥슨게임즈': '225570',
            'CJ ENM': '035760',
            '씨제이이엔엠': '035760',
            'JYP': '035900',
            '제이와이피': '035900',
            'SM': '041510',
            '에스엠': '041510',
            'YG': '122870',
            '와이지': '122870',
            '하이브': '352820',
            'HYBE': '352820',
            '빅히트': '352820',

            # 바이오/제약
            '삼성에피스홀딩스': '0126Z0',
            '삼성에피스': '0126Z0',
            'SK바이오팜': '326030',
            '에스케이바이오팜': '326030',
            '유한양행': '000100',
            '한미약품': '128940',
            '한미사이언스': '008930',
            '대웅제약': '069620',
            '종근당': '185750',
            '녹십자': '006280',
            '휴젤': '145020',
            '메디톡스': '086900',
            '알테오젠': '196170',

            # 배터리/2차전지
            '에코프로': '086520',
            '에코프로비엠': '247540',
            'ECOPROBM': '247540',
            '엘앤에프': '066970',
            'L&F': '066970',
            '포스코퓨처엠': '003670',
            '포스코케미칼': '003670',
            '천보': '278280',
            '일진머티리얼즈': '020150',

            # IT/반도체
            '리노공업': '058470',
            '솔브레인': '357780',
            '동진쎄미켐': '005290',
            '원익IPS': '240810',
            'SK머티리얼즈': '036490',

            # 기타 인기 종목
            '유엔젤': '072130',
            'UANGEL': '072130',
            '두산에너빌리티': '034020',
            '두산중공업': '034020',
            'HD현대': '267250',
            '한화에어로스페이스': '012450',
            '한화항공': '012450',
            'LIG넥스원': '079550',

            # 코스닥 대표 종목
            '알테오젠': '196170',
            'HLB': '028300',
            '에이치엘비': '028300',
            'CJ올리브네트웍스': '040420',
            '씨제이올리브': '040420',
            '케이엠더블유': '032500',
            'KMW': '032500',
            '파트론': '091700',
            '휴맥스': '115160',
        }

        for stock_name, code in basic_mapping.items():
            if name_upper in stock_name.upper():
                # 자동으로 즐겨찾기에 추가
                self.add_favorite(code, stock_name)
                return code

        print(f"[Search] '{name}'을(를) 찾을 수 없습니다.")
        print(f"[Search] 종목코드를 직접 입력하거나 즐겨찾기에 추가해주세요.")
        return None

    def search_stock(self, query: str) -> List[Dict]:
        """
        종목 검색 (종목코드 또는 종목명)

        Args:
            query: 검색어 (예: "072130", "유엔젤")

        Returns:
            [
                {'code': '072130', 'name': '유엔젤', 'market': 'KOSDAQ', 'ticker': '072130.KQ'},
                ...
            ]
        """
        results = []
        query = query.strip()

        # 6자리 숫자면 종목코드로 직접 조회
        if re.match(r'^\d{6}$', query):
            stock_info = self.search_stock_by_code(query)
            if stock_info:
                results.append(stock_info)
                # 즐겨찾기에 자동 추가 옵션
                if query not in self.favorites:
                    print(f"[Search] '{stock_info['name']}'({query})를 즐겨찾기에 추가하시겠습니까?")
                    print(f"[Search] collector.add_favorite('{query}', '{stock_info['name']}')")
        else:
            # 종목명으로 검색
            code = self.search_stock_by_name(query)
            if code:
                stock_info = self.search_stock_by_code(code)
                if stock_info:
                    results.append(stock_info)

        return results

    def show_favorites(self):
        """즐겨찾기 목록 출력"""
        if not self.favorites:
            print("즐겨찾기가 비어있습니다.")
            print("종목 추가: collector.add_favorite('종목코드', '종목명')")
            return

        print("\n=== 한국 주식 즐겨찾기 ===")
        for code, name in self.favorites.items():
            print(f"  {code}: {name}")
        print(f"\n총 {len(self.favorites)}개 종목")
        print("제거: collector.remove_favorite('종목코드')")
        print("조회: collector.search_stock('종목코드_또는_종목명')")


# 편의 함수들
def get_korean_stock_data(ticker: str, period: str = '1y') -> Optional[pd.DataFrame]:
    """한국 주식 데이터 가져오기"""
    collector = KoreanStockData()
    return collector.fetch_ohlcv(ticker, period)


def get_market_indices() -> Dict:
    """KOSPI/KOSDAQ 지수"""
    collector = KoreanStockData()
    return {
        'kospi': collector.get_market_index('KOSPI'),
        'kosdaq': collector.get_market_index('KOSDAQ')
    }


if __name__ == "__main__":
    # 테스트
    collector = KoreanStockData()

    print("\n=== 삼성전자(005930) 데이터 수집 테스트 ===")
    df = collector.fetch_ohlcv("005930", period="1mo")
    if df is not None:
        print(f"Data shape: {df.shape}")
        print(f"Stock name: {collector.get_stock_name('005930')}")
        print(f"\nLast 5 days:")
        print(df.tail())

    print("\n=== 시장 지수 ===")
    indices = get_market_indices()
    print(f"KOSPI: {indices.get('kospi', 'N/A')}")
    print(f"KOSDAQ: {indices.get('kosdaq', 'N/A')}")

    print("\n=== 티커 검증 테스트 ===")
    test_tickers = ['005930', '000660', '999999']  # 삼성전자, SK하이닉스, 잘못된 코드
    for t in test_tickers:
        valid = collector.verify_ticker(t)
        print(f"  {t}: {'✅ Valid' if valid else '❌ Invalid'}")
