#!/usr/bin/env python3
"""
Korean Stock Verifier - 한국 주식 전용 검증 시스템

pykrx를 사용하여 정확한 한국 주식 정보 제공
- 정확한 회사명 (한글)
- 실시간 가격
- 상장 상태 확인
- 섹터/업종 정보
"""

from typing import Dict, Tuple, Optional, List
from datetime import datetime, timedelta
import warnings
warnings.filterwarnings('ignore')


def get_korean_stock_info(ticker: str) -> Tuple[bool, Dict, str]:
    """
    pykrx를 사용한 한국 주식 정보 조회

    Args:
        ticker: 종목 코드 (6자리 또는 .KS/.KQ 포함)

    Returns:
        (존재여부, 종목정보, 오류메시지)
    """

    try:
        from pykrx import stock

        # .KS/.KQ 제거하고 6자리 코드만 추출
        if ticker.endswith('.KS') or ticker.endswith('.KQ'):
            code = ticker[:-3]
        else:
            code = ticker

        # 한국 주식 코드는 정확히 6자여야 함. 임의 패딩은 존재하지 않는 코드를 생성하므로 거부.
        if len(code) != 6:
            return False, {}, f"한국 주식 코드는 6자여야 합니다: {ticker} (길이 {len(code)})"

        # 오늘 날짜
        today = datetime.now().strftime('%Y%m%d')

        # 1. 종목명 조회 (KOSPI + KOSDAQ)
        tickers_kospi = stock.get_market_ticker_list(today, market="KOSPI")
        tickers_kosdaq = stock.get_market_ticker_list(today, market="KOSDAQ")
        all_tickers = tickers_kospi + tickers_kosdaq

        if code not in all_tickers:
            # 최근 5영업일 내에서 다시 검색 (최근 상장/상장폐지 고려)
            for i in range(1, 6):
                date = (datetime.now() - timedelta(days=i)).strftime('%Y%m%d')
                try:
                    tickers_kospi = stock.get_market_ticker_list(date, market="KOSPI")
                    tickers_kosdaq = stock.get_market_ticker_list(date, market="KOSDAQ")
                    all_tickers = tickers_kospi + tickers_kosdaq
                    if code in all_tickers:
                        break
                except Exception:
                    continue

        if code not in all_tickers:
            return False, {}, f"종목 코드를 찾을 수 없습니다: {ticker}"

        # 2. 종목명 가져오기
        ticker_name = stock.get_market_ticker_name(code)

        if not ticker_name:
            return False, {}, f"종목명을 확인할 수 없습니다: {ticker}"

        # 3. 시장 구분 (KOSPI/KOSDAQ)
        market = "KOSPI" if code in tickers_kospi else "KOSDAQ"
        exchange = market

        # 4. 현재가 정보 (최근 거래일 기준)
        try:
            # 최근 5일간의 OHLCV 데이터
            end_date = today
            start_date = (datetime.now() - timedelta(days=10)).strftime('%Y%m%d')
            ohlcv = stock.get_market_ohlcv_by_date(start_date, end_date, code)

            if not ohlcv.empty:
                latest = ohlcv.iloc[-1]
                current_price = latest['종가']
                volume = latest['거래량']
                market_cap = latest.get('시가총액', 0)

                # 거래 정지 여부 확인
                is_suspended = volume == 0 and len(ohlcv) > 1
            else:
                current_price = 0
                volume = 0
                market_cap = 0
                is_suspended = True

        except Exception as e:
            current_price = 0
            volume = 0
            market_cap = 0
            is_suspended = False

        # 5. 기본 정보 (섹터, PER, PBR 등)
        try:
            # 가장 최근 거래일의 기본 정보
            fundamental = stock.get_market_fundamental_by_ticker(today, market=market)
            if code in fundamental.index:
                fund_info = fundamental.loc[code]
                per = fund_info.get('PER', 0)
                pbr = fund_info.get('PBR', 0)
                dividend_yield = fund_info.get('DIV', 0)
            else:
                per = pbr = dividend_yield = 0
        except Exception:
            per = pbr = dividend_yield = 0

        # 6. 섹터/업종 정보 (KOSPI만 가능)
        sector = None
        industry = None

        # 정보 구성
        info = {
            'ticker': ticker,
            'code': code,
            'company_name': ticker_name,
            'market': market,
            'exchange': exchange,
            'current_price': float(current_price) if current_price else 0,
            'volume': int(volume) if volume else 0,
            'market_cap': float(market_cap) if market_cap else 0,
            'currency': 'KRW',
            'per': float(per) if per else 0,
            'pbr': float(pbr) if pbr else 0,
            'dividend_yield': float(dividend_yield) if dividend_yield else 0,
            'is_suspended': is_suspended,
            'sector': sector,
            'industry': industry,
            'verified': True,
            'data_source': 'pykrx'
        }

        # 거래 정지 경고
        if is_suspended:
            return True, info, "거래 정지 상태일 수 있습니다"

        return True, info, ""

    except ImportError:
        return False, {}, "pykrx 라이브러리가 설치되지 않았습니다"
    except Exception as e:
        return False, {}, f"한국 주식 정보 조회 실패: {str(e)[:100]}"


def get_korean_stock_financials(ticker: str) -> Dict:
    """
    한국 주식 재무정보 조회

    Args:
        ticker: 종목 코드

    Returns:
        재무 정보 딕셔너리
    """

    try:
        from pykrx import stock

        # 코드 추출
        if ticker.endswith('.KS') or ticker.endswith('.KQ'):
            code = ticker[:-3]
        else:
            code = ticker

        # 정확히 6자가 아니면 재무정보 조회 불가
        if len(code) != 6:
            return {}

        today = datetime.now().strftime('%Y%m%d')

        # 재무정보 조회
        financials = {}

        try:
            # 최근 분기 재무제표
            fundamental = stock.get_market_fundamental_by_ticker(today)
            if code in fundamental.index:
                fund_data = fundamental.loc[code]
                financials['per'] = float(fund_data.get('PER', 0))
                financials['pbr'] = float(fund_data.get('PBR', 0))
                financials['eps'] = float(fund_data.get('EPS', 0))
                financials['bps'] = float(fund_data.get('BPS', 0))
                financials['dividend_yield'] = float(fund_data.get('DIV', 0))
        except Exception:
            pass

        return financials

    except Exception:
        return {}


def verify_korean_stock(ticker: str) -> Dict:
    """
    한국 주식 종합 검증

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
        'data_source': 'pykrx'
    }

    # pykrx로 정보 조회
    exists, info, error_msg = get_korean_stock_info(ticker)

    if not exists:
        result['errors'].append(error_msg)

        # yfinance로 폴백 시도
        result['warnings'].append("pykrx에서 찾을 수 없어 yfinance로 시도합니다")

        try:
            import yfinance as yf
            stock = yf.Ticker(ticker)
            hist = stock.history(period="5d")

            if not hist.empty:
                result['exists'] = True
                result['company_name'] = ticker  # yfinance는 한국 주식 이름을 잘 못 가져옴
                result['current_price'] = float(hist['Close'].iloc[-1])
                result['can_analyze'] = True
                result['data_source'] = 'yfinance'
                result['warnings'].append("yfinance 데이터 사용 (정확도 낮을 수 있음)")
        except Exception:
            pass

        return result

    # pykrx 정보 사용
    result['exists'] = True
    result['company_name'] = info.get('company_name')
    result['market'] = info.get('market')
    result['current_price'] = info.get('current_price', 0)
    result['volume'] = info.get('volume', 0)
    result['market_cap'] = info.get('market_cap', 0)
    result['per'] = info.get('per', 0)
    result['pbr'] = info.get('pbr', 0)
    result['info'] = info

    # 거래 정지 확인
    if info.get('is_suspended'):
        result['warnings'].append("거래 정지 상태일 수 있습니다")
        result['can_analyze'] = False
    else:
        result['can_analyze'] = True

    # 가격이 0인 경우
    if result['current_price'] == 0:
        result['warnings'].append("현재가 정보가 없습니다")
        result['can_analyze'] = False

    return result


def get_korean_market_list(market: str = "ALL") -> List[Dict]:
    """
    한국 시장 전체 종목 리스트 조회

    Args:
        market: "KOSPI", "KOSDAQ", "ALL"

    Returns:
        종목 리스트
    """

    try:
        from pykrx import stock

        today = datetime.now().strftime('%Y%m%d')
        stocks = []

        if market in ["KOSPI", "ALL"]:
            kospi_tickers = stock.get_market_ticker_list(today, market="KOSPI")
            for ticker in kospi_tickers:
                name = stock.get_market_ticker_name(ticker)
                stocks.append({
                    'code': ticker,
                    'name': name,
                    'market': 'KOSPI'
                })

        if market in ["KOSDAQ", "ALL"]:
            kosdaq_tickers = stock.get_market_ticker_list(today, market="KOSDAQ")
            for ticker in kosdaq_tickers:
                name = stock.get_market_ticker_name(ticker)
                stocks.append({
                    'code': ticker,
                    'name': name,
                    'market': 'KOSDAQ'
                })

        return stocks

    except Exception:
        return []


# 테스트 코드
if __name__ == "__main__":
    print("=" * 60)
    print("한국 주식 검증 시스템 (pykrx)")
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

        result = verify_korean_stock(ticker)

        print(f"존재: {'✓' if result['exists'] else '✗'}")
        if result['company_name']:
            print(f"회사명: {result['company_name']}")
        if result['market']:
            print(f"시장: {result['market']}")
        if result['current_price']:
            print(f"현재가: ₩{result['current_price']:,.0f}")
        if result.get('per'):
            print(f"PER: {result['per']:.2f}")
        if result.get('pbr'):
            print(f"PBR: {result['pbr']:.2f}")
        print(f"분석 가능: {'✓' if result['can_analyze'] else '✗'}")
        print(f"데이터 소스: {result['data_source']}")

        if result['errors']:
            print("오류:", result['errors'])
        if result['warnings']:
            print("경고:", result['warnings'])