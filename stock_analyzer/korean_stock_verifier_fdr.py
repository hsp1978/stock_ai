#!/usr/bin/env python3
"""
Korean Stock Verifier with FinanceDataReader
FinanceDataReader를 사용한 개선된 한국 주식 검증 시스템

특징:
- 더 안정적인 데이터 소스
- 정확한 한글 회사명
- KOSPI/KOSDAQ 자동 구분
- 0126Z0 같은 특수 코드 지원
"""

from typing import Dict, Tuple, Optional, List
from datetime import datetime, timedelta
import pandas as pd
import warnings
warnings.filterwarnings('ignore')


def get_korean_stock_info_fdr(ticker: str) -> Tuple[bool, Dict, str]:
    """
    FinanceDataReader를 사용한 한국 주식 정보 조회

    Args:
        ticker: 종목 코드 (6자리 또는 .KS/.KQ 포함)

    Returns:
        (존재여부, 종목정보, 오류메시지)
    """

    try:
        import FinanceDataReader as fdr

        # .KS/.KQ 제거하고 6자리 코드만 추출
        if ticker.endswith('.KS') or ticker.endswith('.KQ'):
            code = ticker[:-3]
            suffix = ticker[-3:]
        else:
            code = ticker
            suffix = None

        # 1. KRX 전체 종목 리스트 가져오기
        krx_list = fdr.StockListing('KRX')

        # 종목 코드로 검색 (Symbol 또는 Code 컬럼)
        if 'Symbol' in krx_list.columns:
            stock_info = krx_list[krx_list['Symbol'] == code]
        elif 'Code' in krx_list.columns:
            stock_info = krx_list[krx_list['Code'] == code]
        else:
            # 컬럼명이 다를 경우 대비
            stock_info = krx_list[krx_list.iloc[:, 0] == code]

        if stock_info.empty:
            # 특수 코드 처리 (0126Z0 같은 경우)
            # 알파벳이 포함된 경우 정확히 매칭
            for col in krx_list.columns:
                if 'Symbol' in col or 'Code' in col or col == krx_list.columns[0]:
                    stock_info = krx_list[krx_list[col].astype(str) == code]
                    if not stock_info.empty:
                        break

        if stock_info.empty:
            return False, {}, f"종목 코드를 찾을 수 없습니다: {ticker}"

        # 첫 번째 매칭 결과 사용
        stock_data = stock_info.iloc[0]

        # 2. 회사명 추출
        company_name = None
        for col in ['Name', '종목명', 'CompanyName']:
            if col in stock_data.index:
                company_name = stock_data[col]
                break

        if not company_name:
            company_name = code  # 회사명을 찾을 수 없으면 코드 사용

        # 3. 시장 구분
        market = None
        for col in ['Market', '시장구분']:
            if col in stock_data.index:
                market = stock_data[col]
                if market and 'KOSDAQ' in str(market):
                    market = 'KOSDAQ'
                elif market and 'KOSPI' in str(market):
                    market = 'KOSPI'
                else:
                    market = 'KOSPI'  # 기본값
                break

        if not market:
            # suffix로 구분
            if suffix == '.KQ':
                market = 'KOSDAQ'
            else:
                market = 'KOSPI'

        # 4. 최근 가격 데이터 가져오기 (5일)
        try:
            end_date = datetime.now()
            start_date = end_date - timedelta(days=10)

            # FDR은 다양한 형식 지원
            price_data = fdr.DataReader(code, start_date, end_date)

            if not price_data.empty:
                latest = price_data.iloc[-1]
                current_price = float(latest['Close'])
                volume = int(latest['Volume']) if 'Volume' in latest else 0
                change = float(latest['Change']) if 'Change' in latest else 0
                change_pct = float(latest['ChangeRatio']) if 'ChangeRatio' in latest else 0
            else:
                current_price = 0
                volume = 0
                change = 0
                change_pct = 0

        except Exception as e:
            current_price = 0
            volume = 0
            change = 0
            change_pct = 0

        # 5. 추가 정보 (섹터 등)
        sector = stock_data.get('Sector') if 'Sector' in stock_data.index else None
        industry = stock_data.get('Industry') if 'Industry' in stock_data.index else None

        # 정보 구성
        info = {
            'ticker': ticker,
            'code': code,
            'company_name': company_name,
            'market': market,
            'exchange': market,
            'current_price': current_price,
            'volume': volume,
            'change': change,
            'change_pct': change_pct,
            'currency': 'KRW',
            'sector': sector,
            'industry': industry,
            'verified': True,
            'data_source': 'FinanceDataReader'
        }

        return True, info, ""

    except ImportError:
        return False, {}, "FinanceDataReader 라이브러리가 설치되지 않았습니다"
    except Exception as e:
        return False, {}, f"종목 정보 조회 실패: {str(e)[:100]}"


def verify_korean_stock_fdr(ticker: str) -> Dict:
    """
    FinanceDataReader를 사용한 한국 주식 종합 검증

    Args:
        ticker: 종목 코드

    Returns:
        종합 검증 결과
    """

    result = {
        'ticker': ticker,
        'exists': False,
        'company_name': None,
        'market': None,
        'current_price': 0,
        'can_analyze': False,
        'is_korean': True,
        'errors': [],
        'warnings': [],
        'data_source': 'FinanceDataReader'
    }

    # FinanceDataReader로 정보 조회
    exists, info, error_msg = get_korean_stock_info_fdr(ticker)

    if not exists:
        result['errors'].append(error_msg)

        # yfinance로 최후 폴백
        result['warnings'].append("FDR에서 찾을 수 없어 yfinance로 시도합니다")

        try:
            import yfinance as yf

            # yfinance 형식으로 변환
            if not ticker.endswith('.KS') and not ticker.endswith('.KQ'):
                yf_ticker = ticker + '.KS'
            else:
                yf_ticker = ticker

            stock = yf.Ticker(yf_ticker)
            hist = stock.history(period="5d")

            if not hist.empty:
                result['exists'] = True
                result['company_name'] = stock.info.get('longName') or ticker
                result['current_price'] = float(hist['Close'].iloc[-1])
                result['can_analyze'] = True
                result['data_source'] = 'yfinance (fallback)'
                result['warnings'].append("yfinance 데이터 사용 (정확도 낮을 수 있음)")
        except Exception:
            pass

        return result

    # FDR 정보 사용
    result['exists'] = True
    result['company_name'] = info.get('company_name')
    result['market'] = info.get('market')
    result['current_price'] = info.get('current_price', 0)
    result['volume'] = info.get('volume', 0)
    result['change'] = info.get('change', 0)
    result['change_pct'] = info.get('change_pct', 0)
    result['info'] = info

    # 가격이 있으면 분석 가능
    if result['current_price'] > 0:
        result['can_analyze'] = True
    else:
        result['warnings'].append("현재가 정보가 없습니다")
        result['can_analyze'] = False

    return result


def search_korean_stocks(keyword: str) -> List[Dict]:
    """
    한국 주식 검색 (회사명 또는 코드)

    Args:
        keyword: 검색어

    Returns:
        매칭되는 종목 리스트
    """

    try:
        import FinanceDataReader as fdr

        krx_list = fdr.StockListing('KRX')
        keyword = keyword.upper()

        results = []

        # 회사명으로 검색
        for col in ['Name', '종목명', 'CompanyName']:
            if col in krx_list.columns:
                matches = krx_list[krx_list[col].str.contains(keyword, case=False, na=False)]
                for _, row in matches.iterrows():
                    results.append({
                        'code': row.get('Symbol', row.get('Code', '')),
                        'name': row[col],
                        'market': row.get('Market', 'KRX')
                    })
                break

        # 코드로도 검색
        for col in ['Symbol', 'Code']:
            if col in krx_list.columns:
                matches = krx_list[krx_list[col].str.contains(keyword, case=False, na=False)]
                for _, row in matches.iterrows():
                    code = row[col]
                    # 중복 제거
                    if not any(r['code'] == code for r in results):
                        results.append({
                            'code': code,
                            'name': row.get('Name', row.get('종목명', '')),
                            'market': row.get('Market', 'KRX')
                        })
                break

        return results[:10]  # 최대 10개 반환

    except Exception:
        return []


# 테스트 코드
if __name__ == "__main__":
    print("=" * 60)
    print("한국 주식 검증 시스템 (FinanceDataReader)")
    print("=" * 60)

    test_tickers = [
        "005930",     # 삼성전자
        "005930.KS",  # 삼성전자 (yfinance 형식)
        "0126Z0",     # 특수 코드
        "0126Z0.KS",  # 특수 코드 (yfinance 형식)
        "000000",     # 존재하지 않는 종목
    ]

    for ticker in test_tickers:
        print(f"\n테스트: {ticker}")
        print("-" * 40)

        result = verify_korean_stock_fdr(ticker)

        print(f"존재: {'✓' if result['exists'] else '✗'}")
        if result['company_name']:
            print(f"회사명: {result['company_name']}")
        if result['market']:
            print(f"시장: {result['market']}")
        if result['current_price']:
            print(f"현재가: ₩{result['current_price']:,.0f}")
        if result.get('change_pct'):
            sign = '+' if result['change_pct'] > 0 else ''
            print(f"변동률: {sign}{result['change_pct']:.2f}%")
        print(f"분석 가능: {'✓' if result['can_analyze'] else '✗'}")
        print(f"데이터 소스: {result['data_source']}")

        if result['errors']:
            print("오류:", result['errors'])
        if result['warnings']:
            print("경고:", result['warnings'])

    # 검색 테스트
    print("\n" + "=" * 60)
    print("종목 검색 테스트")
    print("=" * 60)

    search_terms = ["삼성", "NAVER"]
    for term in search_terms:
        print(f"\n검색: {term}")
        results = search_korean_stocks(term)
        for r in results[:3]:  # 상위 3개만
            print(f"  - {r['code']}: {r['name']} ({r['market']})")