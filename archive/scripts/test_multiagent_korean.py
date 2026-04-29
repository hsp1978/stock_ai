#!/usr/bin/env python3
"""
멀티에이전트 한국 주식 테스트 - LLM 장애 시 에러 핸들링 확인
"""
import sys
import json
sys.path.insert(0, 'stock_analyzer')

from multi_agent import MultiAgentOrchestrator

# 테스트할 한국 주식들
test_tickers = ['루닛']  # 한글명 테스트

for ticker in test_tickers:
    print(f"\n{'='*70}")
    print(f"Testing: {ticker}")
    print('='*70)

    try:
        orchestrator = MultiAgentOrchestrator()
        result = orchestrator.analyze(ticker)

        # 주요 결과만 출력
        if 'final_decision' in result:
            print(f"\n최종 신호: {result.get('final_decision', {}).get('final_signal', 'N/A')}")
            print(f"신뢰도: {result.get('final_decision', {}).get('final_confidence', 0)}/10")

        # 에러 체크
        if 'error' in result:
            print(f"에러: {result['error']}")

        # 제안된 종목이 있으면 표시
        if 'suggestions' in result and result['suggestions']:
            print("\n추천 종목:")
            for sug in result['suggestions'][:3]:
                print(f"  - {sug['name']} ({sug['ticker']}) [{sug['score']*100:.0f}%]")

        # 에이전트별 결과 요약
        if 'agent_results' in result:
            print("\n에이전트별 결과:")
            for agent in result['agent_results']:
                status = "✓" if not agent.get('error') else "✗"
                print(f"  {status} {agent['agent']}: {agent['signal']} ({agent['confidence']}/10)")
                if agent.get('error'):
                    # LLM 서비스 장애 메시지를 간단히 표시
                    error_msg = agent['error']
                    if "LLM" in error_msg or "llama" in error_msg:
                        print(f"     -> LLM 서비스 장애")
                    else:
                        print(f"     -> {error_msg[:50]}...")

        # 경고 메시지
        if result.get('warnings'):
            print("\n경고:")
            for warning in result['warnings']:
                print(f"  - {warning}")

    except Exception as e:
        print(f"테스트 실패: {e}")
        import traceback
        traceback.print_exc()