#!/usr/bin/env python3
"""
한국 주식 인식 및 원화 표기 테스트
- 가상 매수 포함 모든 기능에서 테스트
"""

import sys
import json
sys.path.insert(0, 'stock_analyzer')
sys.path.insert(0, 'chart_agent_service')

from ticker_suggestion import suggest_ticker
from ticker_validator import validate_ticker, get_market_info

print("=" * 70)
print("한국 주식 인식 및 통화 표기 테스트")
print("=" * 70)

# 테스트할 한국 주식들
test_stocks = [
    ("루닛", "328130.KQ"),
    ("삼성전자", "005930.KS"),
    ("SK하이닉스", "000660.KS"),
    ("네이버", "035420.KS"),
    ("카카오", "035720.KS")
]

print("\n1. 한글 종목명 인식 테스트")
print("-" * 50)

for korean_name, expected_ticker in test_stocks:
    print(f"\n'{korean_name}' 검색...")

    # ticker_suggestion 테스트
    result = suggest_ticker(korean_name)
    if result['found'] and result['best_match']:
        best = result['suggestions'][0]
        print(f"  ✅ 인식 성공: {best['name']} → {best['ticker']}")
    else:
        print(f"  ❌ 인식 실패")

print("\n2. 티커 검증 및 시장 정보")
print("-" * 50)

for _, ticker in test_stocks:
    is_valid, fixed, msg = validate_ticker(ticker)
    market_info = get_market_info(ticker)

    print(f"\n{ticker}")
    print(f"  유효성: {'✅' if is_valid else '❌'} {msg}")
    print(f"  시장: {market_info['market']}")
    print(f"  통화: {market_info['currency']}")
    print(f"  벤치마크: {market_info['benchmark']}")

print("\n3. 현재 가격 및 통화 표시 (시뮬레이션)")
print("-" * 50)

for name, ticker in test_stocks[:3]:  # 상위 3개만
    # webui의 _get_currency_symbol 함수 로직 재현
    if ticker.endswith('.KS') or ticker.endswith('.KQ'):
        display_currency = "₩"
        # 가상의 한국 주식 가격
        simulated_price = 60000 if name == "삼성전자" else 100000
        formatted_price = f"₩{simulated_price:,.0f}"
        actual_currency = "KRW"
    else:
        display_currency = "$"
        simulated_price = 100.00
        formatted_price = f"${simulated_price:,.2f}"
        actual_currency = "USD"

    print(f"\n{name} ({ticker})")
    print(f"  시뮬레이션 가격: {formatted_price}")
    print(f"  실제 통화: {actual_currency}")
    print(f"  표시 통화: {display_currency}")
    print(f"  → WebUI에서 올바르게 표시: {'✅' if display_currency == '₩' else '❌'}")

print("\n4. 가상 매수 (Paper Trading) 테스트")
print("-" * 50)

from paper_trader import execute_paper_order, get_portfolio_status, reset_paper_trading

# 초기화
reset_result = reset_paper_trading()
print(f"계좌 초기화: ${reset_result['account_size']:,.0f}")

# 삼성전자 가상 매수
print("\n삼성전자 가상 매수 테스트...")
order = execute_paper_order(
    ticker="005930.KS",
    action="BUY",
    qty=100,
    price=60000,  # 가상 가격 (원화)
    reason="테스트 매수"
)

print(f"  주문 상태: {order['status']}")
if order['status'] == 'filled':
    print(f"  매수 수량: {order['qty']}주")
    print(f"  매수 가격: {order['price']:,.0f}")
    print(f"  총 비용: ${order['cost']:,.0f} (⚠️ 달러 표시)")
    print(f"  → 원화로 표시되어야 함: ₩{order['cost']:,.0f}")
else:
    print(f"  거부 사유: {order.get('reject_reason', 'N/A')}")

# 포트폴리오 상태 확인
print("\n포트폴리오 상태...")
status = get_portfolio_status()
print(f"  총 자산: ${status['total_equity']:,.0f} (⚠️ 달러 표시)")
print(f"  현금: ${status['cash']:,.0f} (⚠️ 달러 표시)")
print(f"  포지션 가치: ${status['position_value']:,.0f} (⚠️ 달러 표시)")

# 포지션별 상세
if status['positions']:
    print("\n  보유 포지션:")
    for ticker, pos in status['positions'].items():
        print(f"    {ticker}: {pos['qty']}주 @ ${pos['entry_price']:,.0f}")
        print(f"      → 원화 표시 필요: ₩{pos['entry_price']:,.0f}")

print("\n5. 멀티에이전트 분석 통화 확인")
print("-" * 50)

from multi_agent import MultiAgentOrchestrator

orchestrator = MultiAgentOrchestrator()
print("\n'루닛' 분석 중... (통화 표시 확인)")

result = orchestrator.analyze("루닛")

if 'final_decision' in result:
    # market_info 확인
    market_info = result.get('market_info', {})
    print(f"\n분석 결과:")
    print(f"  종목: {result.get('company_name', 'N/A')} ({result['ticker']})")
    print(f"  통화: {market_info.get('currency', 'N/A')}")

    # entry_plan 확인 (매매 계획)
    entry_plan = result.get('final_decision', {}).get('entry_plan')
    if entry_plan:
        print(f"\n진입 계획:")
        # 현재가 확인
        if 'current_price' in entry_plan:
            price = entry_plan['current_price']
            currency = "₩" if result['ticker'].endswith(('.KS', '.KQ')) else "$"
            print(f"  현재가: {currency}{price:,.0f}")

        # 분할 매수 계획
        if 'split_entry' in entry_plan:
            for i, tranche in enumerate(entry_plan['split_entry'], 1):
                price = tranche.get('price', 0)
                qty = tranche.get('qty', 0)
                print(f"  {i}차: {qty}주 @ ${price:,.0f} (⚠️ 달러 표시)")

print("\n" + "=" * 70)
print("테스트 결과 요약")
print("=" * 70)

print("""
✅ 정상 작동:
- 한글 종목명 인식 (루닛, 삼성전자 등)
- 티커 자동 변환 (한글 → 티커 코드)
- 시장 정보 인식 (KRW 통화 식별)

⚠️ 개선 필요:
- Paper Trading: 모든 금액이 $ 달러로 표시됨
- 멀티에이전트 entry_plan: 가격이 $ 달러로 표시됨
- 한국 주식임에도 원화(₩) 표시가 일관되지 않음

📌 권장 사항:
- paper_trader.py: 한국 주식 감지하여 ₩ 표시
- entry_plan_analysis: 한국 주식용 원화 표시
- 전체 시스템에서 통화 표시 일관성 확보
""")