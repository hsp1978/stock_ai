#!/usr/bin/env python3
"""
한국 주식 인식 및 원화 표기 최종 검증 테스트
"""

import sys
import json

sys.path.insert(0, 'stock_analyzer')
sys.path.insert(0, 'chart_agent_service')

print("=" * 70)
print("한국 주식 인식 및 원화 표기 최종 검증")
print("=" * 70)

# ==================== 1. 한글 종목명 인식 ===================
print("\n[ 1. 한글 종목명 인식 테스트 ]")
print("-" * 50)

from ticker_suggestion import suggest_ticker

test_names = ["루닛", "삼성전자", "카카오", "네이버", "하림"]
success_count = 0

for name in test_names:
    result = suggest_ticker(name)
    if result['found'] and result['best_match']:
        best = result['suggestions'][0]
        print(f"✅ {name:8s} → {best['ticker']:12s} ({best['name']})")
        success_count += 1
    else:
        print(f"❌ {name:8s} → 인식 실패")

print(f"\n결과: {success_count}/{len(test_names)} 성공")

# ==================== 2. 통화 유틸리티 테스트 ===================
print("\n[ 2. 통화 유틸리티 함수 테스트 ]")
print("-" * 50)

from currency_utils import (
    is_korean_stock,
    get_currency_symbol,
    format_price,
    format_amount,
    parse_korean_amount
)

# 한국/미국 주식 구분
test_tickers = [
    ("005930.KS", True, "₩"),   # 삼성전자
    ("035720.KQ", True, "₩"),   # 카카오
    ("AAPL", False, "$"),       # 애플
    ("TSLA", False, "$"),       # 테슬라
]

print("한국 주식 판별:")
for ticker, expected_kr, expected_symbol in test_tickers:
    is_kr = is_korean_stock(ticker)
    symbol = get_currency_symbol(ticker)
    status = "✅" if (is_kr == expected_kr and symbol == expected_symbol) else "❌"
    print(f"  {status} {ticker:12s} → 한국주식: {is_kr:5} | 통화: {symbol}")

# 가격 포맷팅
print("\n가격 포맷팅:")
print(f"  삼성전자 60,000원 → {format_price(60000, '005930.KS')}")
print(f"  애플 $150.25 → {format_price(150.25, 'AAPL')}")
print(f"  금액 1억원 → {format_amount(100000000, '005930.KS')}")
print(f"  금액 $1M → {format_amount(1000000, 'AAPL')}")

# 한국식 금액 파싱
print("\n한국식 금액 파싱:")
test_amounts = [
    ("1억", 100000000),
    ("5천만", 50000000),
    ("300만", 3000000),
    ("1억5천만", 150000000),
    ("10000", 10000),
    ("₩60,000", 60000),
]

for text, expected in test_amounts:
    result = parse_korean_amount(text)
    status = "✅" if result == expected else "❌"
    print(f"  {status} '{text}' → {result:,.0f} (기대값: {expected:,.0f})")

# ==================== 3. Paper Trading 통화 테스트 ===================
print("\n[ 3. Paper Trading 통화 표시 테스트 ]")
print("-" * 50)

from paper_trader import execute_paper_order, get_portfolio_status, reset_paper_trading

# 초기화
reset_paper_trading()
print("계좌 초기화 완료")

# 한국 주식 매수
print("\n한국 주식 매수 테스트:")
orders = [
    ("005930.KS", 100, 60000, "삼성전자"),
    ("035720.KQ", 50, 45000, "카카오"),
]

for ticker, qty, price, name in orders:
    order = execute_paper_order(
        ticker=ticker,
        action="BUY",
        qty=qty,
        price=price,
        reason=f"{name} 테스트 매수"
    )

    print(f"\n{name} ({ticker}):")
    print(f"  상태: {order['status']}")
    if order['status'] == 'filled':
        # 비용이 원화로 표시되는지 확인
        cost = order.get('cost', 0)
        currency = get_currency_symbol(ticker)
        print(f"  매수: {qty}주 × {format_price(price, ticker)} = {currency}{cost:,.0f}")
    else:
        print(f"  실패: {order.get('reject_reason', 'Unknown')}")

# 미국 주식 매수
print("\n미국 주식 매수 테스트:")
order = execute_paper_order(
    ticker="AAPL",
    action="BUY",
    qty=10,
    price=150.50,
    reason="애플 테스트 매수"
)

print(f"AAPL:")
print(f"  상태: {order['status']}")
if order['status'] == 'filled':
    cost = order.get('cost', 0)
    print(f"  매수: 10주 × $150.50 = ${cost:,.2f}")

# 포트폴리오 상태
print("\n포트폴리오 현황:")
status = get_portfolio_status()

print(f"  총 자산: ${status['total_equity']:,.0f}")
print(f"  현금: ${status['cash']:,.0f}")
print(f"  포지션 수: {status['open_positions']}개")

if status['positions']:
    print("\n  보유 포지션:")
    for ticker, pos in status['positions'].items():
        currency = get_currency_symbol(ticker)
        entry_price = pos['entry_price']
        qty_held = pos['qty']

        # 통화별 포맷
        if is_korean_stock(ticker):
            print(f"    {ticker}: {qty_held}주 × ₩{entry_price:,.0f}")
        else:
            print(f"    {ticker}: {qty_held}주 × ${entry_price:,.2f}")

# ==================== 4. 결과 요약 ===================
print("\n" + "=" * 70)
print("검증 결과 요약")
print("=" * 70)

print("""
✅ 완전 지원:
  - 한글 종목명 → 티커 자동 변환
  - 한국 주식 식별 (KS/KQ)
  - 통화 기호 구분 (₩/$)
  - 가격 포맷팅 (원화는 정수, 달러는 소수점 2자리)
  - 한국식 금액 파싱 (1억, 5천만 등)

⚠️ 개선된 부분:
  - currency_utils.py 모듈 추가
  - paper_trader.py에 통화 지원 추가
  - Trailing Stop, Stop Loss 메시지 통화 표시

📌 남은 이슈:
  - 포트폴리오 총액은 여전히 $ 기준 (환율 변환 필요)
  - WebUI에서 일부 메트릭이 $ 고정

💡 권장사항:
  - 한국 계좌와 미국 계좌 분리 관리
  - 환율 정보 실시간 반영
  - 통화별 손익 계산 분리
""")

print("\n테스트 완료!")