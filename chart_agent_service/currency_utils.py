"""
통화 유틸리티 함수들
한국 주식과 미국 주식을 구분하여 적절한 통화 기호와 포맷을 적용
"""

def is_korean_stock(ticker: str) -> bool:
    """한국 주식 여부 확인"""
    if not ticker:
        return False
    ticker = ticker.upper()
    return ticker.endswith('.KS') or ticker.endswith('.KQ') or ticker.endswith('.KRX')

def get_currency_symbol(ticker: str) -> str:
    """티커에 맞는 통화 기호 반환"""
    return "₩" if is_korean_stock(ticker) else "$"

def format_price(price: float, ticker: str, decimals: int = None) -> str:
    """가격을 통화에 맞게 포맷"""
    if price is None:
        return "N/A"

    currency = get_currency_symbol(ticker)

    if decimals is None:
        # 한국 주식은 소수점 없이, 미국 주식은 2자리
        decimals = 0 if is_korean_stock(ticker) else 2

    return f"{currency}{price:,.{decimals}f}"

def format_amount(amount: float, ticker: str) -> str:
    """금액을 통화에 맞게 포맷 (항상 정수)"""
    if amount is None:
        return "N/A"

    currency = get_currency_symbol(ticker)
    return f"{currency}{amount:,.0f}"

def parse_korean_amount(amount_str: str) -> float:
    """한국식 금액 문자열을 숫자로 변환
    예: "1억", "5천만", "100만원" → float
    """
    if not amount_str:
        return 0.0

    # 숫자만 있는 경우
    try:
        # 콤마 제거
        clean_str = amount_str.replace(',', '').replace('₩', '').replace('원', '')
        return float(clean_str)
    except:
        pass

    # 한국식 표현 파싱
    amount_str = amount_str.replace(' ', '').replace(',', '')
    amount_str = amount_str.replace('원', '').replace('₩', '')

    total = 0.0

    # 억 처리
    if '억' in amount_str:
        parts = amount_str.split('억')
        total += float(parts[0]) * 100000000
        amount_str = parts[1] if len(parts) > 1 else ''

    # 천만 처리
    if '천만' in amount_str:
        parts = amount_str.split('천만')
        if parts[0]:
            total += float(parts[0]) * 10000000
        else:
            total += 10000000
        amount_str = parts[1] if len(parts) > 1 else ''

    # 백만 처리
    elif '백만' in amount_str:
        parts = amount_str.split('백만')
        if parts[0]:
            total += float(parts[0]) * 1000000
        else:
            total += 1000000
        amount_str = parts[1] if len(parts) > 1 else ''

    # 만 처리
    elif '만' in amount_str:
        parts = amount_str.split('만')
        if parts[0]:
            total += float(parts[0]) * 10000
        amount_str = parts[1] if len(parts) > 1 else ''

    # 나머지 숫자
    if amount_str and amount_str.replace('.', '').isdigit():
        total += float(amount_str)

    return total

def get_market_from_ticker(ticker: str) -> str:
    """티커에서 시장 정보 추출"""
    if is_korean_stock(ticker):
        if ticker.endswith('.KS'):
            return "KOSPI"
        elif ticker.endswith('.KQ'):
            return "KOSDAQ"
        else:
            return "KR"
    else:
        return "US"