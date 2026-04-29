#!/usr/bin/env python3
"""
Ticker Validator - 한국/미국 주식 티커 검증 및 정규화

주요 기능:
1. 티커 형식 검증 (한국: 6자리.KS/KQ, 미국: 알파벳)
2. 잘못된 티커 감지 및 수정
3. 시장별 통화 및 벤치마크 자동 설정
"""

import re
from typing import Any, Dict, Tuple, Optional

# 한국 주식 6자리 코드 (숫자만) 또는 특수 코드 0126Z0 패턴
_KR_CODE_PATTERN = re.compile(r'^(?:\d{6}|\d{4}[A-Z]\d)$')


def is_korean_ticker(ticker: str) -> bool:
    """
    단일 진입점: 한국 주식 티커 판별.

    True 조건:
      - `.KS` 또는 `.KQ` 접미사가 붙은 6자 코드
      - 6자리 숫자 (예: "005930")
      - 4자리 숫자 + 알파벳 1 + 숫자 1 (예: "0126Z0")

    Args:
        ticker: 검증할 티커 문자열

    Returns:
        True면 한국 주식, False면 한국 주식 아님
    """
    if not ticker or not isinstance(ticker, str):
        return False
    t = ticker.strip().upper()
    if t.endswith('.KS') or t.endswith('.KQ'):
        return bool(_KR_CODE_PATTERN.match(t[:-3]))
    return bool(_KR_CODE_PATTERN.match(t))


def normalize_korean_ticker(ticker: str, default_suffix: str = '.KS') -> Optional[str]:
    """
    한국 주식 코드 정규화: 접미사가 없으면 default_suffix 추가.
    한국 주식이 아니면 None 반환.
    """
    if not is_korean_ticker(ticker):
        return None
    t = ticker.strip().upper()
    if t.endswith('.KS') or t.endswith('.KQ'):
        return t
    return t + default_suffix


def validate_ticker(ticker: str) -> Tuple[bool, Optional[str], str]:
    """
    티커 유효성 검증 및 수정

    Args:
        ticker: 입력 티커 심볼

    Returns:
        (유효여부, 수정된_티커, 오류메시지)
    """

    if not ticker:
        return False, None, "티커가 제공되지 않았습니다"

    ticker = ticker.upper().strip()

    # 한국 주식 패턴 검증
    if ticker.endswith('.KS') or ticker.endswith('.KQ'):
        # 정규식: 6자리 (숫자 또는 알파벳 포함 가능) + .KS 또는 .KQ
        # 예: 005930.KS (일반), 0126Z0.KS (특수)
        pattern = r'^[0-9A-Z]{6}\.(KS|KQ)$'
        if re.match(pattern, ticker):
            return True, ticker, ""
        else:
            return False, None, f"잘못된 한국 주식 티커 형식: {ticker} (6자리 코드 + .KS/.KQ)"

    # 미국 주식 패턴 검증 (1-5자 알파벳/숫자 + 선택적 점/하이픈 + 1자 클래스 표기)
    # 예: AAPL, GOOGL, BRK.B, BF.B, BRK-B
    pattern = r'^[A-Z][A-Z0-9]{0,4}([.\-][A-Z])?$'
    if re.match(pattern, ticker):
        return True, ticker, ""

    # 특수 케이스: 숫자로만 된 티커 (한국 주식인데 .KS 누락 가능성)
    if ticker.isdigit() and len(ticker) == 6:
        # 6자리 숫자면 한국 코스피로 추정
        suggested = f"{ticker}.KS"
        return False, suggested, f"6자리 숫자 티커 '{ticker}'는 한국 주식으로 추정됨. '{suggested}' 사용 권장"

    return False, None, f"알 수 없는 티커 형식: {ticker}"


def get_market_info(ticker: str) -> Dict[str, Any]:
    """
    티커에 따른 시장 정보 반환

    Args:
        ticker: 티커 심볼

    Returns:
        {
            "market": "KR" or "US",
            "currency": "₩" or "$",
            "currency_symbol": "KRW" or "USD",
            "benchmark": 벤치마크 티커,
            "exchange": 거래소 이름
        }
    """

    ticker = ticker.upper().strip()

    # 한국 시장
    if ticker.endswith('.KS'):
        return {
            "market": "KR",
            "currency": "₩",
            "currency_symbol": "KRW",
            "benchmark": "^KS11",  # KOSPI 지수
            "exchange": "KOSPI",
            "trading_hours": "09:00-15:30 KST",
            "settlement": "T+2"
        }
    elif ticker.endswith('.KQ'):
        return {
            "market": "KR",
            "currency": "₩",
            "currency_symbol": "KRW",
            "benchmark": "^KQ11",  # KOSDAQ 지수
            "exchange": "KOSDAQ",
            "trading_hours": "09:00-15:30 KST",
            "settlement": "T+2"
        }

    # 미국 시장 (기본값)
    return {
        "market": "US",
        "currency": "$",
        "currency_symbol": "USD",
        "benchmark": "SPY",
        "exchange": "US",
        "trading_hours": "09:30-16:00 EST",
        "settlement": "T+2"
    }


def fix_common_ticker_errors(ticker: str) -> Optional[str]:
    """
    일반적인 티커 오류 자동 수정

    Args:
        ticker: 오류가 있을 수 있는 티커

    Returns:
        수정된 티커 또는 None
    """

    if not ticker:
        return None

    ticker = ticker.upper().strip()

    # 케이스 1: 한국 티커 형식 확인 (6자리 + .KS/.KQ)
    if ticker.endswith('.KS') or ticker.endswith('.KQ'):
        # 이미 올바른 형식인지 확인
        if validate_ticker(ticker)[0]:
            return ticker

        # 길이가 맞지 않으면 수정 시도
        code_part = ticker[:-3]  # .KS/.KQ 제외한 부분
        suffix = ticker[-3:]  # .KS 또는 .KQ

        if len(code_part) != 6:
            # 6자리 맞추기 (앞에 0 패딩 또는 자르기)
            if len(code_part) < 6:
                code_part = code_part.zfill(6)
            else:
                code_part = code_part[:6]

            fixed = code_part + suffix
            if validate_ticker(fixed)[0]:
                return fixed

    # 케이스 2: 6자리 코드인데 .KS 누락
    if len(ticker) == 6 and not ticker.endswith('.KS') and not ticker.endswith('.KQ'):
        # 한국 주식으로 추정 (.KS 추가)
        return f"{ticker}.KS"

    # 케이스 3: 소문자로 입력된 티커
    if ticker.islower():
        upper_ticker = ticker.upper()
        if validate_ticker(upper_ticker)[0]:
            return upper_ticker

    return None


def sanitize_ticker_list(tickers: list) -> list:
    """
    티커 리스트 정리 및 검증

    Args:
        tickers: 티커 리스트

    Returns:
        검증된 티커 리스트와 경고 메시지
    """

    valid_tickers = []
    warnings = []

    for ticker in tickers:
        is_valid, fixed_ticker, error_msg = validate_ticker(ticker)

        if is_valid:
            valid_tickers.append(ticker)
        elif fixed_ticker:
            # 자동 수정된 경우
            valid_tickers.append(fixed_ticker)
            warnings.append(f"'{ticker}' → '{fixed_ticker}' (자동 수정)")
        else:
            # 수정 시도
            auto_fixed = fix_common_ticker_errors(ticker)
            if auto_fixed:
                valid_tickers.append(auto_fixed)
                warnings.append(f"'{ticker}' → '{auto_fixed}' (자동 수정)")
            else:
                warnings.append(f"'{ticker}' 제외: {error_msg}")

    return valid_tickers, warnings


# 테스트 코드
if __name__ == "__main__":
    test_tickers = [
        "005930.KS",     # 삼성전자 (정상)
        "0126Z0.KS",     # 오류 티커
        "012620.KS",     # 수정된 티커
        "AAPL",          # 애플 (정상)
        "035420",        # 네이버 (suffix 누락)
        "tsla",          # 테슬라 (소문자)
        "INVALID123",    # 잘못된 형식
    ]

    print("=" * 60)
    print("티커 검증 테스트")
    print("=" * 60)

    for ticker in test_tickers:
        is_valid, fixed, error = validate_ticker(ticker)
        market_info = get_market_info(ticker if is_valid else (fixed or ticker))

        print(f"\n티커: {ticker}")
        print(f"  유효성: {'✓' if is_valid else '✗'}")
        if fixed:
            print(f"  수정안: {fixed}")
        if error:
            print(f"  오류: {error}")
        print(f"  시장: {market_info['market']}, 통화: {market_info['currency']}")

    print("\n" + "=" * 60)
    print("리스트 정리 테스트")
    print("=" * 60)

    valid_list, warn_list = sanitize_ticker_list(test_tickers)
    print(f"\n유효 티커: {valid_list}")
    print(f"경고:")
    for w in warn_list:
        print(f"  - {w}")