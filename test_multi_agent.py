#!/usr/bin/env python3
"""
멀티에이전트 시스템 테스트
Week 2-3 검증 스크립트
"""

import os
import sys
import json
import time
from datetime import datetime

# 경로 설정
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'stock_analyzer'))
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from chart_agent_service.config import DEFAULT_TEST_TICKER

# 색상
GREEN = '\033[0;32m'
YELLOW = '\033[1;33m'
RED = '\033[0;31m'
BLUE = '\033[0;34m'
NC = '\033[0m'


def test_direct_multi_agent(ticker=DEFAULT_TEST_TICKER):
    """직접 multi_agent 모듈 테스트"""
    print(f"\n{BLUE}{'='*70}{NC}")
    print(f"{BLUE}Multi-Agent Direct Test: {ticker}{NC}")
    print(f"{BLUE}{'='*70}{NC}\n")

    try:
        from stock_analyzer.multi_agent import MultiAgentOrchestrator

        orchestrator = MultiAgentOrchestrator()
        result = orchestrator.analyze(ticker)

        print(f"\n{BLUE}{'='*70}{NC}")
        print(f"{BLUE}결과 요약{NC}")
        print(f"{BLUE}{'='*70}{NC}")

        # 최종 결정
        if "final_decision" in result:
            decision = result["final_decision"]
            print(f"\n{GREEN}최종 판단:{NC}")
            print(f"  신호: {decision.get('final_signal')}")
            print(f"  신뢰도: {decision.get('final_confidence', 0):.1f}/10")
            print(f"  의견 분포: {decision.get('consensus')}")
            print(f"  핵심 리스크: {decision.get('key_risks', [])}")

        # 에이전트별 의견
        if "agent_results" in result:
            print(f"\n{GREEN}에이전트 의견:{NC}")
            for agent in result["agent_results"]:
                status = f"{GREEN}✓{NC}" if not agent.get('error') else f"{RED}✗{NC}"
                print(f"  {status} {agent['agent']}: {agent['signal']} ({agent['confidence']:.1f}/10) [{agent.get('execution_time', 0):.1f}s]")

        # 실행 시간
        total_time = result.get('total_execution_time', 0)
        print(f"\n총 실행 시간: {total_time:.1f}초")

        return True

    except Exception as e:
        print(f"{RED}✗ 테스트 실패: {e}{NC}")
        import traceback
        traceback.print_exc()
        return False


def test_local_engine_integration(ticker=DEFAULT_TEST_TICKER):
    """local_engine 통합 테스트"""
    print(f"\n{BLUE}{'='*70}{NC}")
    print(f"{BLUE}Local Engine Integration Test: {ticker}{NC}")
    print(f"{BLUE}{'='*70}{NC}\n")

    try:
        from stock_analyzer.local_engine import engine_multi_agent_analyze

        print("engine_multi_agent_analyze() 호출...")
        result = engine_multi_agent_analyze(ticker)

        if "error" in result:
            print(f"{RED}✗ 오류: {result['error']}{NC}")
            return False

        print(f"{GREEN}✓ 성공{NC}")
        print(f"  최종 신호: {result.get('final_decision', {}).get('final_signal')}")
        print(f"  에이전트 수: {result.get('final_decision', {}).get('agent_count', 0)}")

        return True

    except Exception as e:
        print(f"{RED}✗ 테스트 실패: {e}{NC}")
        import traceback
        traceback.print_exc()
        return False


def test_single_vs_multi(ticker=DEFAULT_TEST_TICKER):
    """Single LLM vs Multi-Agent 비교"""
    print(f"\n{BLUE}{'='*70}{NC}")
    print(f"{BLUE}Single LLM vs Multi-Agent Comparison: {ticker}{NC}")
    print(f"{BLUE}{'='*70}{NC}\n")

    try:
        from stock_analyzer.local_engine import engine_scan_ticker, engine_multi_agent_analyze

        # Single LLM
        print(f"{YELLOW}[1/2] Single LLM 분석...{NC}")
        start = time.time()
        single_result = engine_scan_ticker(ticker, ai_mode="ollama")
        single_time = time.time() - start

        # Multi-Agent
        print(f"\n{YELLOW}[2/2] Multi-Agent 분석...{NC}")
        start = time.time()
        multi_result = engine_multi_agent_analyze(ticker)
        multi_time = time.time() - start

        # 비교
        print(f"\n{BLUE}{'='*70}{NC}")
        print(f"{BLUE}비교 결과{NC}")
        print(f"{BLUE}{'='*70}{NC}\n")

        print(f"{'항목':<20} {'Single LLM':<20} {'Multi-Agent'}")
        print(f"{'-'*70}")
        print(f"{'신호':<20} {single_result.get('final_signal', '?'):<20} {multi_result.get('final_decision', {}).get('final_signal', '?')}")
        print(f"{'점수/신뢰도':<20} {single_result.get('composite_score', 0):+.2f} / {single_result.get('confidence', 0)}/10{' ':<8} {multi_result.get('final_decision', {}).get('final_confidence', 0):.1f}/10")
        print(f"{'실행 시간':<20} {single_time:.1f}초{' ':<15} {multi_time:.1f}초")

        return True

    except Exception as e:
        print(f"{RED}✗ 비교 실패: {e}{NC}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """메인 테스트"""
    print(f"\n{BLUE}{'#'*70}{NC}")
    print(f"{BLUE}#  Multi-Agent System Test Suite{NC}")
    print(f"{BLUE}#  Week 2-3 Implementation Verification{NC}")
    print(f"{BLUE}{'#'*70}{NC}")

    ticker = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_TEST_TICKER
    print(f"\n테스트 종목: {ticker}")
    print(f"시작 시간: {datetime.now()}\n")

    results = []

    # 1. 직접 테스트
    print(f"\n{YELLOW}[Test 1] Direct Multi-Agent{NC}")
    results.append(("Direct Multi-Agent", test_direct_multi_agent(ticker)))

    # 2. Local Engine 통합
    print(f"\n{YELLOW}[Test 2] Local Engine Integration{NC}")
    results.append(("Local Engine Integration", test_local_engine_integration(ticker)))

    # 3. Single vs Multi 비교
    print(f"\n{YELLOW}[Test 3] Single vs Multi Comparison{NC}")
    results.append(("Single vs Multi", test_single_vs_multi(ticker)))

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
        return 0
    else:
        print(f"{YELLOW}⚠ 일부 테스트 실패{NC}")
        return 1


if __name__ == "__main__":
    sys.exit(main())