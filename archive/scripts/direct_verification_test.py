#!/usr/bin/env python3
"""
한글 회사명 검색 직접 검증 테스트
"""

from stock_analyzer.multi_agent import MultiAgentOrchestrator
import time


def test_korean_company(company_name):
    """한 회사 테스트"""

    o = MultiAgentOrchestrator()
    print(f"\n{'='*60}")
    print(f"테스트: {company_name}")
    print('='*60)

    start_time = time.time()
    result = o.analyze(company_name)
    elapsed_time = time.time() - start_time

    if 'error' in result:
        print(f"❌ 분석 실패: {result['error']}")
        if result.get('suggestions'):
            print(f"   추천 종목 {len(result['suggestions'])}개:")
            for i, s in enumerate(result['suggestions'][:3], 1):
                print(f"     {i}. {s['name']} ({s['ticker']}) [{s['score']*100:.0f}%]")
        return False
    else:
        print(f"✅ 분석 성공!")
        print(f"   회사명: {result.get('company_name', 'N/A')}")
        print(f"   티커: {result['ticker']}")

        # 자동 매칭 경고 확인
        if result.get('warnings'):
            for w in result['warnings']:
                if '자동' in w or '매칭' in w:
                    print(f"   자동매칭: {w}")

        # 최종 결과
        if 'final_decision' in result:
            decision = result['final_decision']
            print(f"   최종신호: {decision.get('final_signal', 'N/A')}")
            print(f"   신뢰도: {decision.get('final_confidence', 0):.1f}/10")

        print(f"   소요시간: {elapsed_time:.1f}초")
        return True


def main():
    """메인 테스트"""

    print("="*70)
    print("한글 회사명 직접 검증 테스트")
    print("="*70)

    # 테스트할 회사들
    test_companies = [
        # 완전 일치 케이스
        ("삼성전자", "005930.KS"),
        ("카카오", "035720.KS"),
        ("현대차", "005380.KS"),

        # StartsWith 매칭 케이스
        ("삼성에피스", "0126Z0.KS"),
        ("삼성바이오", "207940.KS"),

        # 별칭 매칭 케이스
        ("네이버", "035420.KS"),
        ("포스코", "005490.KS"),
        ("하이닉스", "000660.KS"),
    ]

    success_count = 0
    fail_count = 0

    for company_name, expected_ticker in test_companies:
        success = test_korean_company(company_name)
        if success:
            success_count += 1
        else:
            fail_count += 1

        # API 부하 방지를 위한 대기
        time.sleep(2)

    # 결과 요약
    print("\n" + "="*70)
    print("테스트 결과 요약")
    print("="*70)
    print(f"총 테스트: {len(test_companies)}개")
    print(f"성공: {success_count}개")
    print(f"실패: {fail_count}개")
    print(f"성공률: {(success_count/len(test_companies)*100):.1f}%")

    if fail_count == 0:
        print("\n✅ 모든 테스트 통과!")
    else:
        print("\n⚠️ 일부 테스트 실패")


if __name__ == "__main__":
    main()