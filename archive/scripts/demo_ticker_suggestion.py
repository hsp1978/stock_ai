#!/usr/bin/env python3
"""
종목 추천 시스템 데모
"""

from stock_analyzer.multi_agent import MultiAgentOrchestrator
from stock_analyzer.ticker_suggestion import suggest_ticker
import json


def demo():
    """종목 추천 시스템 데모"""

    print("="*70)
    print("종목 추천 시스템 데모")
    print("="*70)
    print("\n다양한 입력으로 종목 추천 기능을 시연합니다.\n")

    orchestrator = MultiAgentOrchestrator()

    # 데모 시나리오
    demos = [
        {
            "input": "삼성",
            "scenario": "부분 회사명으로 검색",
            "expected": "여러 삼성 계열사 추천"
        },
        {
            "input": "APPL",
            "scenario": "오타가 있는 티커",
            "expected": "AAPL (Apple) 추천"
        },
        {
            "input": "카카오뱅크",
            "scenario": "정확한 한국 회사명",
            "expected": "323410.KS 자동 선택"
        },
        {
            "input": "005390",
            "scenario": "비슷한 종목 코드",
            "expected": "005930 (삼성전자) 추천"
        },
    ]

    for demo_case in demos:
        print("-"*70)
        print(f"시나리오: {demo_case['scenario']}")
        print(f"입력: '{demo_case['input']}'")
        print(f"예상: {demo_case['expected']}")
        print("-"*70)

        result = orchestrator.analyze(demo_case['input'])

        if 'error' in result:
            print(f"❌ 분석 실패: {result['error']}")

            if 'suggestions' in result and result['suggestions']:
                print("\n🔍 추천 종목:")
                for i, sugg in enumerate(result['suggestions'][:3], 1):
                    score = int(sugg['score'] * 100)
                    print(f"   {i}. {sugg['name']} ({sugg['ticker']}) [{score}%]")

                # 자동 선택 가능 여부
                if result['suggestions'][0]['score'] >= 0.95:
                    best = result['suggestions'][0]
                    print(f"\n   → 95% 이상 매치: {best['name']} 자동 선택 가능")
            else:
                print("   추천 종목이 없습니다.")

        else:
            print(f"✅ 분석 진행:")
            print(f"   종목: {result.get('company_name', 'N/A')} ({result['ticker']})")

            if 'warnings' in result and result['warnings']:
                print(f"   경고: {result['warnings'][0]}")

            if 'final_decision' in result:
                decision = result['final_decision']
                print(f"   신호: {decision.get('final_signal', 'N/A')}")
                print(f"   신뢰도: {decision.get('final_confidence', 0):.1f}/10")

        print()

    # API 직접 사용 예시
    print("="*70)
    print("API 직접 사용 예시")
    print("="*70)

    test_input = "마이크로소프트"
    print(f"\n입력: '{test_input}'")

    api_result = suggest_ticker(test_input, max_results=3)

    if api_result['found']:
        print(f"찾음: {len(api_result['suggestions'])}개 종목")
        print("\n추천 목록:")
        for i, sugg in enumerate(api_result['suggestions'], 1):
            print(f"  {i}. {sugg['name']} ({sugg['ticker']}) [{sugg['score']*100:.0f}%]")

        if api_result['best_match']:
            print(f"\n자동 선택 가능: {api_result['best_match']}")
    else:
        print("일치하는 종목을 찾을 수 없습니다.")


if __name__ == "__main__":
    demo()