#!/usr/bin/env python3
"""
종목 추천 기능 테스트
"""

import json
from stock_analyzer.multi_agent import MultiAgentOrchestrator
from stock_analyzer.ticker_suggestion import suggest_ticker


def test_wrong_ticker_suggestions():
    """잘못된 티커 입력 시 추천 기능 테스트"""

    print("="*60)
    print("종목 추천 기능 테스트")
    print("="*60)

    orchestrator = MultiAgentOrchestrator()

    # 테스트 케이스
    test_cases = [
        ("INVALID999", "존재하지 않는 티커"),
        ("삼성", "부분 회사명"),
        ("APPL", "오타 티커 (AAPL이 맞음)"),
        ("네이버", "한국 회사명"),
        ("구글", "미국 회사 한글명"),
        ("005390", "비슷한 코드 (005930이 맞음)"),
    ]

    results = []

    for input_text, description in test_cases:
        print(f"\n테스트: {input_text}")
        print(f"설명: {description}")
        print("-"*40)

        # 멀티에이전트 분석 시도
        result = orchestrator.analyze(input_text)

        if 'error' in result:
            print(f"❌ 오류: {result['error']}")

            # 추천 확인
            if 'suggestions' in result and result['suggestions']:
                print("\n추천 종목:")
                for i, sugg in enumerate(result['suggestions'][:3], 1):
                    score = int(sugg['score'] * 100)
                    print(f"  {i}. {sugg['name']} ({sugg['ticker']}) - {sugg.get('exchange', 'N/A')} [{score}%]")

                # 최고 매치 확인
                if result['suggestions'][0]['score'] >= 0.95:
                    print(f"\n→ 자동 선택 가능: {result['suggestions'][0]['ticker']}")
            else:
                print("추천 종목 없음")
        else:
            print(f"✅ 분석 성공: {result.get('company_name', result['ticker'])}")

        results.append({
            'input': input_text,
            'description': description,
            'has_error': 'error' in result,
            'has_suggestions': 'suggestions' in result and result['suggestions'] is not None,
            'suggestion_count': len(result.get('suggestions', [])) if result.get('suggestions') else 0,
            'best_match': result['suggestions'][0] if result.get('suggestions') else None
        })

    # 결과 요약
    print("\n" + "="*60)
    print("테스트 요약")
    print("="*60)

    for r in results:
        status = "✅" if r['has_suggestions'] else "❌"
        print(f"{status} {r['input']}: {r['suggestion_count']}개 추천")
        if r['best_match']:
            print(f"   최상위: {r['best_match']['name']} ({r['best_match']['score']*100:.0f}%)")

    return results


def test_direct_suggestion_api():
    """직접 추천 API 테스트"""

    print("\n" + "="*60)
    print("직접 추천 API 테스트")
    print("="*60)

    test_inputs = [
        "삼성전자",
        "TSLA",
        "카카오",
        "마이크로소프트",
        "현대",
        "LG",
    ]

    for input_text in test_inputs:
        result = suggest_ticker(input_text, max_results=3)

        print(f"\n입력: {input_text}")
        print(f"찾음: {result['found']}")
        if result['found']:
            print(f"추천 수: {len(result['suggestions'])}")
            if result['best_match']:
                print(f"자동 선택: {result['best_match']}")
            else:
                print(f"최상위: {result['suggestions'][0]['ticker']} ({result['suggestions'][0]['score']*100:.0f}%)")


if __name__ == "__main__":
    # 1. 멀티에이전트 통합 테스트
    test_wrong_ticker_suggestions()

    # 2. 직접 API 테스트
    test_direct_suggestion_api()

    print("\n✅ 모든 테스트 완료")