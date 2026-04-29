#!/usr/bin/env python3
"""
한글 회사명 검색 기능 테스트
"""

from stock_analyzer.ticker_suggestion import suggest_ticker


def test_korean_names():
    """다양한 한글 회사명 테스트"""

    print("="*70)
    print("한글 회사명 검색 테스트")
    print("="*70)

    test_cases = [
        # (입력, 예상 결과)
        ("삼성에피스", "0126Z0.KS - 삼성에피스홀딩스"),
        ("삼성전자", "005930.KS - 삼성전자"),
        ("삼성", "여러 삼성 계열사"),
        ("네이버", "035420.KQ - NAVER"),
        ("카카오", "035720.KS - 카카오"),
        ("카카오뱅크", "323410.KS - 카카오뱅크"),
        ("현대차", "005380.KS - 현대차"),
        ("현대", "여러 현대 계열사"),
        ("LG", "여러 LG 계열사"),
        ("SK", "여러 SK 계열사"),
        ("셀트리온", "068270.KQ - 셀트리온"),
        ("삼성바이오", "207940.KS - 삼성바이오로직스"),
    ]

    for input_text, expected in test_cases:
        print(f"\n입력: '{input_text}'")
        print(f"예상: {expected}")
        print("-"*50)

        result = suggest_ticker(input_text, max_results=3)

        if result['found']:
            if result['best_match']:
                print(f"✅ 자동 선택 가능: {result['best_match']}")
            else:
                print(f"추천 {len(result['suggestions'])}개:")
                for i, s in enumerate(result['suggestions'], 1):
                    score = int(s['score'] * 100)
                    print(f"  {i}. {s['name']} ({s['ticker']}) [{score}%]")
        else:
            print("❌ 추천 없음")


def test_auto_selection():
    """95% 이상 자동 선택되는 케이스 테스트"""

    print("\n" + "="*70)
    print("자동 선택 테스트 (95% 이상)")
    print("="*70)

    from stock_analyzer.multi_agent import MultiAgentOrchestrator
    orchestrator = MultiAgentOrchestrator()

    auto_cases = [
        "삼성에피스",
        "삼성전자",
        "카카오뱅크",
    ]

    for name in auto_cases:
        print(f"\n테스트: {name}")
        print("-"*30)

        result = orchestrator.analyze(name)

        if 'error' in result:
            if result.get('suggestions'):
                print(f"❌ 자동 선택 실패 - 추천 {len(result['suggestions'])}개")
                if result['suggestions']:
                    print(f"   최상위: {result['suggestions'][0]['name']} ({result['suggestions'][0]['score']*100:.0f}%)")
            else:
                print(f"❌ 오류: {result['error']}")
        else:
            print(f"✅ 자동 선택 성공: {result.get('company_name', 'N/A')}")
            if 'warnings' in result and result['warnings']:
                for warn in result['warnings']:
                    if '자동' in warn:
                        print(f"   {warn}")


if __name__ == "__main__":
    # 1. 한글 회사명 검색
    test_korean_names()

    # 2. 자동 선택 테스트
    test_auto_selection()

    print("\n" + "="*70)
    print("✅ 모든 테스트 완료")
    print("="*70)