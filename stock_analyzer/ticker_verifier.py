#!/usr/bin/env python3
"""
Ticker Verifier - 실제 종목 존재 여부 검증

주요 기능:
1. yfinance를 통한 실제 종목 존재 확인
2. 회사명 및 기본 정보 검증
3. 데이터 품질 확인
4. 의심스러운 종목 경고
"""

import yfinance as yf
from typing import Dict, Tuple, Optional
import warnings
warnings.filterwarnings('ignore')


def verify_ticker_exists(ticker: str) -> Tuple[bool, Dict, str]:
    """
    실제 종목 존재 여부 확인

    Args:
        ticker: 검증할 티커

    Returns:
        (존재여부, 종목정보, 오류메시지)
    """

    try:
        # yfinance Ticker 객체 생성
        stock = yf.Ticker(ticker)

        # info 가져오기 시도
        info = stock.info

        # 기본 검증 - info가 비어있거나 기본값만 있는 경우
        if not info or len(info) <= 1:
            return False, {}, f"종목 정보를 찾을 수 없습니다: {ticker}"

        # 회사명 확인
        company_name = info.get('longName') or info.get('shortName')
        if not company_name:
            # 회사명이 없으면 의심스러운 티커
            return False, {}, f"회사명을 확인할 수 없습니다: {ticker}"

        # 시장 정보 확인
        market = info.get('market') or info.get('exchange')

        # 가격 데이터 확인
        current_price = info.get('currentPrice') or info.get('regularMarketPrice')
        if current_price is None or current_price <= 0:
            # 최근 데이터로 한번 더 시도
            history = stock.history(period="5d")
            if history.empty or len(history) == 0:
                return False, {}, f"가격 데이터가 없습니다: {ticker} (거래 정지 또는 상장폐지 가능성)"

            # history에서 마지막 종가 확인
            current_price = history['Close'].iloc[-1] if not history.empty else None

        # 종목 타입 확인
        quote_type = info.get('quoteType', '')

        # 검증된 정보 구성
        verified_info = {
            'ticker': ticker,
            'company_name': company_name,
            'market': market,
            'current_price': current_price,
            'currency': info.get('currency', 'Unknown'),
            'quote_type': quote_type,
            'sector': info.get('sector'),
            'industry': info.get('industry'),
            'market_cap': info.get('marketCap'),
            'verified': True
        }

        # 한국 종목 특별 체크
        if ticker.endswith('.KS') or ticker.endswith('.KQ'):
            # 한국 종목인 경우 추가 검증
            if verified_info['currency'] not in ['KRW', None]:
                return False, {}, f"한국 종목이 아닌 것으로 의심됨: 통화 {verified_info['currency']}"

        return True, verified_info, ""

    except Exception as e:
        error_msg = str(e)

        # 404 또는 찾을 수 없음 관련 에러
        if "404" in error_msg or "not found" in error_msg.lower():
            return False, {}, f"종목을 찾을 수 없습니다: {ticker}"

        # 기타 에러
        return False, {}, f"종목 검증 실패: {error_msg[:100]}"


def get_ticker_data_quality(ticker: str) -> Dict:
    """
    종목 데이터 품질 확인

    Args:
        ticker: 티커

    Returns:
        데이터 품질 정보
    """

    quality = {
        'ticker': ticker,
        'has_price_data': False,
        'has_volume_data': False,
        'has_financial_data': False,
        'data_days': 0,
        'latest_date': None,
        'quality_score': 0,  # 0-100
        'warnings': []
    }

    try:
        stock = yf.Ticker(ticker)

        # 1년치 데이터 가져오기
        history = stock.history(period="1y")

        if not history.empty:
            quality['has_price_data'] = True
            quality['data_days'] = len(history)
            quality['latest_date'] = str(history.index[-1])[:10]

            # Volume 체크
            if 'Volume' in history.columns:
                non_zero_volume = (history['Volume'] > 0).sum()
                quality['has_volume_data'] = non_zero_volume > 0

                # 거래량이 너무 적은 날이 많으면 경고
                zero_volume_ratio = 1 - (non_zero_volume / len(history))
                if zero_volume_ratio > 0.2:  # 20% 이상 거래량 0
                    quality['warnings'].append(f"거래량 없는 날 {zero_volume_ratio:.0%}")

            # 최근 거래일 체크
            import pandas as pd
            from datetime import datetime, timedelta
            import pytz

            last_trade_date = pd.to_datetime(history.index[-1])
            # timezone 제거 (naive로 만들기)
            if last_trade_date.tzinfo is not None:
                last_trade_date = last_trade_date.tz_localize(None)

            days_since_trade = (datetime.now() - last_trade_date).days

            if days_since_trade > 5:  # 5일 이상 거래 없음
                quality['warnings'].append(f"마지막 거래일로부터 {days_since_trade}일 경과")

        # 재무 데이터 체크
        try:
            financials = stock.financials
            if financials is not None and not financials.empty:
                quality['has_financial_data'] = True
        except Exception:
            pass

        # 품질 점수 계산
        score = 0
        if quality['has_price_data']:
            score += 40
        if quality['has_volume_data']:
            score += 30
        if quality['data_days'] >= 100:
            score += 20
        if quality['has_financial_data']:
            score += 10

        # 경고사항에 따라 감점
        score -= len(quality['warnings']) * 10
        quality['quality_score'] = max(0, min(100, score))

        # 품질 등급
        if quality['quality_score'] >= 80:
            quality['grade'] = 'A'
        elif quality['quality_score'] >= 60:
            quality['grade'] = 'B'
        elif quality['quality_score'] >= 40:
            quality['grade'] = 'C'
        else:
            quality['grade'] = 'D'
            quality['warnings'].append("데이터 품질이 낮음")

    except Exception as e:
        quality['warnings'].append(f"품질 검사 실패: {str(e)[:50]}")
        quality['quality_score'] = 0
        quality['grade'] = 'F'

    return quality


def verify_and_validate(ticker: str) -> Dict:
    """
    종목 존재 여부 + 데이터 품질 종합 검증
    한국 주식은 FinanceDataReader, 미국 주식은 yfinance 사용

    Args:
        ticker: 티커

    Returns:
        종합 검증 결과
    """

    result = {
        'ticker': ticker,
        'is_valid': False,
        'exists': False,
        'company_name': None,
        'data_quality': None,
        'can_analyze': False,
        'errors': [],
        'warnings': []
    }

    # 1단계: 티커 형식 검증
    from ticker_validator import validate_ticker
    format_valid, fixed_ticker, format_error = validate_ticker(ticker)

    if not format_valid:
        result['errors'].append(f"티커 형식 오류: {format_error}")
        if fixed_ticker:
            result['warnings'].append(f"수정 제안: {fixed_ticker}")
            ticker = fixed_ticker  # 수정된 티커로 계속 진행
        else:
            return result

    result['is_valid'] = True

    # 2단계: 한국 주식 여부 확인 (단일 헬퍼 사용)
    from ticker_validator import is_korean_ticker
    is_korean = is_korean_ticker(ticker)

    if is_korean:
        # 한국 주식: FinanceDataReader 사용
        try:
            from korean_stock_verifier_fdr import verify_korean_stock_fdr

            kr_result = verify_korean_stock_fdr(ticker)

            if kr_result['exists']:
                result['exists'] = True
                result['company_name'] = kr_result.get('company_name')
                result['market_info'] = kr_result.get('info', {})
                result['can_analyze'] = kr_result.get('can_analyze', False)

                if kr_result.get('warnings'):
                    result['warnings'].extend(kr_result['warnings'])

                info = result['market_info']
            else:
                result['errors'].append(f"종목을 찾을 수 없습니다: {ticker}")
                result['warnings'].append("⚠️ 한국 종목을 찾을 수 없습니다. 티커를 다시 확인해주세요.")
                return result

        except ImportError:
            # FDR이 없으면 yfinance로 폴백
            result['warnings'].append("FinanceDataReader를 사용할 수 없어 yfinance를 사용합니다")
            exists, info, exist_error = verify_ticker_exists(ticker)
            if not exists:
                result['errors'].append(exist_error)
                result['warnings'].append("⚠️ 종목을 찾을 수 없습니다. 티커를 다시 확인해주세요.")
                return result
            result['exists'] = True
            result['company_name'] = info.get('company_name')
            result['market_info'] = info

    else:
        # 미국 주식: yfinance 사용
        exists, info, exist_error = verify_ticker_exists(ticker)

        if not exists:
            result['errors'].append(exist_error)
            result['warnings'].append("⚠️ 종목을 찾을 수 없습니다. 티커를 다시 확인해주세요.")
            return result

        result['exists'] = True
        result['company_name'] = info.get('company_name')
        result['market_info'] = info

    # 3단계: 데이터 품질 확인
    quality = get_ticker_data_quality(ticker)
    result['data_quality'] = quality

    # 분석 가능 여부 판단
    if quality['quality_score'] >= 40 and quality['data_days'] >= 50:
        result['can_analyze'] = True
    else:
        result['warnings'].append("⚠️ 데이터 품질이 낮아 정확한 분석이 어려울 수 있습니다")
        if quality['data_days'] < 50:
            result['errors'].append(f"데이터 부족: {quality['data_days']}일 (최소 50일 필요)")

    # 품질 경고 추가
    if quality.get('warnings'):
        result['warnings'].extend(quality['warnings'])

    # 최종 권고
    if result['can_analyze']:
        result['recommendation'] = f"✅ {result['company_name']} ({ticker}) 분석 가능"
    else:
        result['recommendation'] = f"❌ {ticker} 분석 불가 - 데이터 부족 또는 잘못된 종목"

    return result


# 테스트 코드
if __name__ == "__main__":
    test_tickers = [
        "005930.KS",  # 삼성전자 (정상)
        "0126Z0.KS",  # 의심스러운 티커
        "AAPL",       # 애플 (정상)
        "INVALID",    # 존재하지 않는 티커
        "000000.KS",  # 존재하지 않을 가능성 높은 티커
    ]

    print("=" * 60)
    print("종목 검증 테스트")
    print("=" * 60)

    for ticker in test_tickers:
        print(f"\n테스트: {ticker}")
        print("-" * 40)

        result = verify_and_validate(ticker)

        print(f"형식 유효: {'✓' if result['is_valid'] else '✗'}")
        print(f"종목 존재: {'✓' if result['exists'] else '✗'}")

        if result['company_name']:
            print(f"회사명: {result['company_name']}")

        if result['data_quality']:
            q = result['data_quality']
            print(f"데이터 품질: {q['grade']}등급 ({q['quality_score']}점)")
            print(f"데이터 일수: {q['data_days']}일")

        print(f"분석 가능: {'✓' if result['can_analyze'] else '✗'}")

        if result['errors']:
            print(f"오류:")
            for err in result['errors']:
                print(f"  - {err}")

        if result['warnings']:
            print(f"경고:")
            for warn in result['warnings']:
                print(f"  - {warn}")

        print(f"\n권고: {result.get('recommendation', 'N/A')}")