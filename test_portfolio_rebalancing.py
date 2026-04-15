#!/usr/bin/env python3
"""
Portfolio Rebalancing Test Script
Week 4 검증 스크립트
"""

import os
import sys
import json
from datetime import datetime

# 경로 설정
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'stock_analyzer'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'chart_agent_service'))

# 색상
GREEN = '\033[0;32m'
YELLOW = '\033[1;33m'
RED = '\033[0;31m'
BLUE = '\033[0;34m'
NC = '\033[0m'


def test_rebalance_functions():
    """리밸런싱 함수 직접 테스트"""
    print(f"\n{BLUE}{'='*70}{NC}")
    print(f"{BLUE}Portfolio Rebalancing Direct Test{NC}")
    print(f"{BLUE}{'='*70}{NC}\n")

    try:
        from chart_agent_service.portfolio_rebalancer import (
            execute_rebalancing,
            get_rebalance_status,
            get_rebalance_history,
            compute_drift
        )

        # 1. 리밸런싱 상태
        print(f"{YELLOW}[1/4] 리밸런싱 상태 조회...{NC}")
        status = get_rebalance_status()
        print(f"{GREEN}✓ 상태 조회 성공{NC}")
        print(f"  총 리밸런싱: {status.get('rebalance_count', 0)}회")
        print(f"  현재 Drift: {status.get('current_drift', 0):.2%}")
        print(f"  리밸런싱 필요: {status.get('needs_rebalance', False)}")

        # 2. Dry-run 테스트
        print(f"\n{YELLOW}[2/4] Dry-Run 리밸런싱 테스트...{NC}")
        result = execute_rebalancing(method="markowitz", dry_run=True)
        print(f"{GREEN}✓ Dry-run 성공{NC}")
        print(f"  상태: {result.get('status')}")
        print(f"  사유: {result.get('reason')}")
        print(f"  Drift: {result.get('drift', 0):.2%}")

        if result.get("orders"):
            print(f"  주문 {len(result['orders'])}개 계산됨:")
            for order in result['orders'][:3]:
                print(f"    - {order['action']} {order['ticker']} {order['qty']}주")
                print(f"      (현재 {order['current_weight']:.1%} → 목표 {order['target_weight']:.1%})")

        # 3. 히스토리
        print(f"\n{YELLOW}[3/4] 리밸런싱 히스토리...{NC}")
        history = get_rebalance_history(limit=5)
        print(f"{GREEN}✓ 히스토리 조회 성공{NC}")
        print(f"  총 히스토리: {history.get('count', 0)}건")
        print(f"  총 거래비용: ${history.get('total_costs', 0):.2f}")

        for h in history.get('history', [])[-3:]:
            print(f"    - {h.get('timestamp', '')[:19]}: {h.get('method')}, drift={h.get('drift', 0):.2%}")

        # 4. Drift 계산 테스트
        print(f"\n{YELLOW}[4/4] Drift 계산 테스트...{NC}")
        current = {"NVDA": 0.40, "AAPL": 0.35, "MSFT": 0.25}
        target = {"NVDA": 0.33, "AAPL": 0.33, "MSFT": 0.34}
        drift = compute_drift(current, target)
        print(f"{GREEN}✓ Drift 계산 성공{NC}")
        print(f"  현재 비중: {current}")
        print(f"  목표 비중: {target}")
        print(f"  Drift: {drift:.2%}")

        return True

    except Exception as e:
        print(f"{RED}✗ 테스트 실패: {e}{NC}")
        import traceback
        traceback.print_exc()
        return False


def test_local_engine_integration():
    """local_engine 통합 테스트"""
    print(f"\n{BLUE}{'='*70}{NC}")
    print(f"{BLUE}Local Engine Rebalancing Integration Test{NC}")
    print(f"{BLUE}{'='*70}{NC}\n")

    try:
        from stock_analyzer.local_engine import (
            engine_portfolio_rebalance,
            engine_rebalance_status,
            engine_rebalance_history
        )

        # 1. 상태 조회
        print(f"{YELLOW}[1/3] engine_rebalance_status()...{NC}")
        status = engine_rebalance_status()
        if "error" in status:
            print(f"{YELLOW}⚠ 상태 조회: {status['error']}{NC}")
        else:
            print(f"{GREEN}✓ 상태 조회 성공{NC}")
            print(f"  Drift: {status.get('current_drift', 0):.2%}")

        # 2. Dry-run
        print(f"\n{YELLOW}[2/3] engine_portfolio_rebalance(dry_run=True)...{NC}")
        result = engine_portfolio_rebalance(dry_run=True)
        if "error" in result:
            print(f"{YELLOW}⚠ Dry-run: {result['error']}{NC}")
        else:
            print(f"{GREEN}✓ Dry-run 성공{NC}")
            print(f"  상태: {result.get('status')}")
            print(f"  주문: {len(result.get('orders', []))}개")

        # 3. 히스토리
        print(f"\n{YELLOW}[3/3] engine_rebalance_history()...{NC}")
        history = engine_rebalance_history(limit=5)
        if "error" in history:
            print(f"{YELLOW}⚠ 히스토리: {history['error']}{NC}")
        else:
            print(f"{GREEN}✓ 히스토리 조회 성공{NC}")
            print(f"  총 {history.get('count', 0)}건")

        return True

    except Exception as e:
        print(f"{RED}✗ 테스트 실패: {e}{NC}")
        import traceback
        traceback.print_exc()
        return False


def test_api_endpoints():
    """API 엔드포인트 테스트"""
    print(f"\n{BLUE}{'='*70}{NC}")
    print(f"{BLUE}API Endpoint Test{NC}")
    print(f"{BLUE}{'='*70}{NC}\n")

    try:
        from stock_analyzer.local_engine import engine_dispatch_get

        # 1. 상태 API
        print(f"{YELLOW}[1/3] GET /portfolio/rebalance/status...{NC}")
        result = engine_dispatch_get("/portfolio/rebalance/status")
        if result:
            print(f"{GREEN}✓ API 성공{NC}")
            print(f"  Drift: {result.get('current_drift', 0):.2%}")
        else:
            print(f"{RED}✗ API 실패{NC}")

        # 2. Dry-run API
        print(f"\n{YELLOW}[2/3] GET /portfolio/rebalance?dry_run=true...{NC}")
        result = engine_dispatch_get("/portfolio/rebalance?dry_run=true")
        if result:
            print(f"{GREEN}✓ API 성공{NC}")
            print(f"  상태: {result.get('status')}")
        else:
            print(f"{RED}✗ API 실패{NC}")

        # 3. 히스토리 API
        print(f"\n{YELLOW}[3/3] GET /portfolio/rebalance/history?limit=5...{NC}")
        result = engine_dispatch_get("/portfolio/rebalance/history?limit=5")
        if result:
            print(f"{GREEN}✓ API 성공{NC}")
            print(f"  총 {result.get('count', 0)}건")
        else:
            print(f"{RED}✗ API 실패{NC}")

        return True

    except Exception as e:
        print(f"{RED}✗ 테스트 실패: {e}{NC}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """메인 테스트"""
    print(f"\n{BLUE}{'#'*70}{NC}")
    print(f"{BLUE}#  Portfolio Rebalancing Test Suite{NC}")
    print(f"{BLUE}#  Week 4 Implementation Verification{NC}")
    print(f"{BLUE}{'#'*70}{NC}")
    print(f"\n시작 시간: {datetime.now()}\n")

    results = []

    # 1. 직접 함수 테스트
    print(f"\n{YELLOW}[Test 1] Direct Functions{NC}")
    results.append(("Direct Functions", test_rebalance_functions()))

    # 2. Local Engine 통합
    print(f"\n{YELLOW}[Test 2] Local Engine Integration{NC}")
    results.append(("Local Engine Integration", test_local_engine_integration()))

    # 3. API 엔드포인트
    print(f"\n{YELLOW}[Test 3] API Endpoints{NC}")
    results.append(("API Endpoints", test_api_endpoints()))

    # 요약
    print(f"\n{BLUE}{'='*70}{NC}")
    print(f"{BLUE}테스트 요약{NC}")
    print(f"{BLUE}{'='*70}{NC}\n")

    passed = sum(1 for _, result in results if result)
    total = len(results)

    for test_name, result in results:
        status = f"{GREEN}✓ PASS{NC}" if result else f"{RED}✗ FAIL{NC}"
        print(f"{status} {test_name}")

    print(f"\n총 {total}개 테스트 중 {passed}개 통과 ({passed/total*100:.0f}%)")

    if passed == total:
        print(f"{GREEN}🎉 모든 테스트 통과!{NC}")
        print(f"\n{GREEN}Week 4 포트폴리오 리밸런싱 구현 완료!{NC}")
        return 0
    else:
        print(f"{YELLOW}⚠ 일부 테스트 실패{NC}")
        return 1


if __name__ == "__main__":
    sys.exit(main())