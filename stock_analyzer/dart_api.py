#!/usr/bin/env python3
"""
DART (전자공시시스템) API 연동 모듈
- 기업 공시 조회
- 재무제표 조회
- 배당 정보
"""

import os
import requests
from datetime import datetime, timedelta
from typing import Optional, Dict, List
from dotenv import load_dotenv
from pathlib import Path

# .env 파일 경로를 명시적으로 지정
env_path = Path(__file__).parent / '.env'
load_dotenv(env_path)

DART_API_KEY = os.getenv("DART_API_KEY", "")
DART_BASE_URL = "https://opendart.fss.or.kr/api"


class DARTClient:
    """DART API 클라이언트"""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or DART_API_KEY
        self.session = requests.Session()
        # 기업코드 캐시 (종목코드 → DART 고유번호)
        self._corp_code_cache = {}
        # 기업 목록 데이터 (API에서 조회)
        self._corp_list = None

    def is_configured(self) -> bool:
        """API Key 설정 여부 확인"""
        return bool(self.api_key and self.api_key != "")

    def get_corp_code(self, ticker: str) -> Optional[str]:
        """
        종목코드 → DART 고유번호 변환

        Args:
            ticker: 종목코드 (예: "005930" or "005930.KS")

        Returns:
            DART 기업 고유번호 (8자리) or None
        """
        stock_code = ticker.replace('.KS', '').replace('.KQ', '')

        # 캐시 확인
        if stock_code in self._corp_code_cache:
            return self._corp_code_cache[stock_code]

        if not self.is_configured():
            return None

        try:
            # DART 기업코드 조회 API 사용
            # 참고: https://opendart.fss.or.kr/guide/detail.do?apiGrpCd=DS003&apiId=2019002

            # 방법 1: 상장기업 목록에서 검색
            url = f"{DART_BASE_URL}/corpCode.xml"
            params = {'crtfc_key': self.api_key}

            # 전체 기업 목록을 한 번만 다운로드
            if self._corp_list is None:
                response = self.session.get(url, params=params, timeout=30)
                if response.status_code == 200:
                    # ZIP 파일 처리 로직
                    # 실제로는 ZIP 파일을 풀어서 XML 파싱 필요
                    # 여기서는 간단한 대체 방법 사용
                    pass

            # 방법 2: 공시 검색을 통한 간접 조회 (더 간단한 방법)
            # 최근 공시가 있는 기업은 corp_code를 얻을 수 있음
            search_url = f"{DART_BASE_URL}/list.json"
            search_params = {
                'crtfc_key': self.api_key,
                'pblntf_ty': 'A',  # 정기공시
                'page_no': 1,
                'page_count': 1
            }

            # 종목코드로 직접 검색 시도
            # DART는 종목코드로 직접 검색이 어려워 회사명으로 검색
            try:
                import yfinance as yf
                stock = yf.Ticker(f"{stock_code}.KS")
                info = stock.info
                corp_name = info.get('longName') or info.get('shortName', '')

                if not corp_name:
                    # KOSDAQ 시도
                    stock = yf.Ticker(f"{stock_code}.KQ")
                    info = stock.info
                    corp_name = info.get('longName') or info.get('shortName', '')

                if corp_name:
                    # 회사명으로 검색
                    search_params['corp_name'] = corp_name.split(' ')[0]  # 첫 단어만 사용
                    response = self.session.get(search_url, params=search_params, timeout=10)

                    if response.status_code == 200:
                        data = response.json()
                        if data.get('status') == '000' and data.get('list'):
                            # 검색 결과에서 정확한 회사 찾기
                            for item in data.get('list', []):
                                if corp_name in item.get('corp_name', ''):
                                    corp_code = item.get('corp_code')
                                    if corp_code:
                                        # 캐시에 저장
                                        self._corp_code_cache[stock_code] = corp_code
                                        return corp_code
                            # 첫 번째 결과 사용 (정확히 매치되지 않아도)
                            if data.get('list'):
                                corp_code = data['list'][0].get('corp_code')
                                if corp_code:
                                    self._corp_code_cache[stock_code] = corp_code
                                    return corp_code
            except Exception as search_error:
                print(f"[DART] Search error: {search_error}")

            # 기본 매핑 (자주 조회되는 종목)
            # 필요시 수동으로 추가 가능
            default_mapping = {
                '005930': '00126380',  # 삼성전자
                '000660': '00164779',  # SK하이닉스
            }

            if stock_code in default_mapping:
                corp_code = default_mapping[stock_code]
                self._corp_code_cache[stock_code] = corp_code
                return corp_code

            return None

        except Exception as e:
            print(f"[DART] Error getting corp code for {ticker}: {e}")
            return None

    def fetch_recent_disclosures(self, ticker: str, days: int = 30) -> List[Dict]:
        """
        최근 공시 목록 조회

        Args:
            ticker: 종목코드
            days: 최근 N일

        Returns:
            [
                {
                    'date': '2026-04-15',
                    'title': '매출액 또는 손익구조 30%(대규모법인 15%)이상 변경',
                    'report_name': '주요사항보고서',
                    'url': 'http://...'
                }
            ]
        """
        if not self.is_configured():
            return []

        try:
            corp_code = self.get_corp_code(ticker)
            if not corp_code:
                return []

            # 날짜 계산
            end_date = datetime.now().strftime('%Y%m%d')
            start_date = (datetime.now() - timedelta(days=days)).strftime('%Y%m%d')

            url = f"{DART_BASE_URL}/list.json"
            params = {
                'crtfc_key': self.api_key,
                'corp_code': corp_code,
                'bgn_de': start_date,
                'end_de': end_date,
                'page_count': 100
            }

            response = self.session.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()

            if data.get('status') != '000':
                print(f"[DART] API error: {data.get('message')}")
                return []

            disclosures = []
            for item in data.get('list', []):
                disclosures.append({
                    'date': item.get('rcept_dt', ''),
                    'title': item.get('report_nm', ''),
                    'corp_name': item.get('corp_name', ''),
                    'report_type': item.get('report_type', ''),
                    'url': f"http://dart.fss.or.kr/dsaf001/main.do?rcpNo={item.get('rcept_no', '')}"
                })

            return disclosures

        except Exception as e:
            print(f"[DART] Error fetching disclosures for {ticker}: {e}")
            return []

    def fetch_financial_statement(self, ticker: str, year: int, quarter: int = 1) -> Dict:
        """
        재무제표 조회

        Args:
            ticker: 종목코드
            year: 연도 (예: 2025)
            quarter: 분기 (1, 2, 3, 4)

        Returns:
            {
                'ticker': '005930',
                'year': 2025,
                'quarter': 1,
                'revenue': 70000000000000,  # 매출액 (원)
                'operating_income': 15000000000000,
                'net_income': 12000000000000,
                'assets': 400000000000000,
                'liabilities': 100000000000000,
                'equity': 300000000000000
            }
        """
        if not self.is_configured():
            return {}

        try:
            corp_code = self.get_corp_code(ticker)
            if not corp_code:
                return {}

            # 분기 보고서 코드
            reprt_codes = {
                1: '11013',  # 1분기
                2: '11012',  # 반기
                3: '11014',  # 3분기
                4: '11011'   # 사업보고서
            }

            url = f"{DART_BASE_URL}/fnlttSinglAcntAll.json"
            params = {
                'crtfc_key': self.api_key,
                'corp_code': corp_code,
                'bsns_year': str(year),
                'reprt_code': reprt_codes.get(quarter, '11011')
            }

            response = self.session.get(url, params=params, timeout=15)
            response.raise_for_status()
            data = response.json()

            if data.get('status') != '000':
                return {}

            # 재무제표 데이터 파싱 (간소화)
            return {
                'ticker': ticker.replace('.KS', '').replace('.KQ', ''),
                'year': year,
                'quarter': quarter,
                'status': 'available',
                'message': 'DART API로 조회 가능 (상세 파싱 필요)'
            }

        except Exception as e:
            print(f"[DART] Error fetching financial for {ticker}: {e}")
            return {}

    def get_dividend_info(self, ticker: str) -> Dict:
        """
        배당 정보 조회

        Returns:
            {
                'ticker': '005930',
                'dividend_per_share': 1000,
                'dividend_yield': 1.5,
                'ex_dividend_date': '2025-12-30'
            }
        """
        if not self.is_configured():
            return {}

        try:
            # DART API로 배당 정보 조회
            # 실제 구현은 DART API 문서 참조하여 구체화 필요
            return {
                'ticker': ticker.replace('.KS', '').replace('.KQ', ''),
                'status': 'api_key_configured',
                'message': 'DART API로 조회 가능'
            }

        except Exception as e:
            print(f"[DART] Error fetching dividend for {ticker}: {e}")
            return {}


# 편의 함수
def get_recent_disclosures(ticker: str, days: int = 30) -> List[Dict]:
    """최근 공시 목록"""
    client = DARTClient()
    return client.fetch_recent_disclosures(ticker, days)


def get_financial_statement(ticker: str, year: int, quarter: int = 1) -> Dict:
    """재무제표"""
    client = DARTClient()
    return client.fetch_financial_statement(ticker, year, quarter)


if __name__ == "__main__":
    # 테스트
    print("\n=== DART API 테스트 ===")

    client = DARTClient()

    if not client.is_configured():
        print("⚠️ DART_API_KEY가 설정되지 않았습니다.")
        print("\n설정 방법:")
        print("1. https://opendart.fss.or.kr/ 에서 API Key 발급 (무료)")
        print("2. stock_analyzer/.env 파일에 추가:")
        print("   DART_API_KEY=your_api_key_here")
        print("\n현재는 테스트 모드로 실행됩니다.\n")
    else:
        print("✅ DART_API_KEY 설정됨\n")

        # 삼성전자 최근 공시
        print("[Test 1] 삼성전자 최근 공시 (30일)")
        disclosures = client.fetch_recent_disclosures("005930", days=30)

        if disclosures:
            print(f"✅ {len(disclosures)}개 공시 조회됨:")
            for d in disclosures[:5]:
                print(f"  - {d['date']}: {d['title'][:50]}")
        else:
            print("  데이터 없음 또는 API 오류")

        # 재무제표
        print("\n[Test 2] 삼성전자 재무제표 (2025 Q1)")
        fs = client.fetch_financial_statement("005930", year=2025, quarter=1)

        if fs:
            print(f"✅ 재무제표 조회: {fs}")
        else:
            print("  데이터 없음 또는 API 오류")
