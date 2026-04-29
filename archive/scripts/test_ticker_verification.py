#!/usr/bin/env python3
"""
종목 검증 시스템 테스트
"""

import json
from datetime import datetime


def test_ticker_verification():
    """다양한 티커로 검증 시스템 테스트"""

    print("="*60)
    print("종목 검증 시스템 테스트")
    print("="*60)
    print(f"실행 시각: {datetime.now()}")
    print()

    # 테스트할 티커들
    test_cases = [
        # (티커, 예상결과, 설명)
        ("005930.KS", "valid", "삼성전자 - 정상 한국 종목"),
        ("AAPL", "valid", "애플 - 정상 미국 종목"),
        ("0126Z0.KS", "check", "특수 코드 포함 티커 - 실제 존재 확인 필요"),
        ("012620.KS", "check", "일반 한국 티커 - 실제 존재 확인 필요"),
        ("INVALID123", "invalid", "존재하지 않는 티커"),
        ("000000.KS", "invalid", "잘못된 한국 티커 코드"),
        ("FAKE.KS", "invalid", "가짜 한국 티커"),
        ("035420", "format_error", "네이버 - .KS 누락"),
    ]

    from stock_analyzer.ticker_verifier import verify_and_validate

    results = []

    for ticker, expected, description in test_cases:
        print(f"\n테스트: {ticker}")
        print(f"설명: {description}")
        print("-" * 40)

        try:
            result = verify_and_validate(ticker)

            # 결과 출력
            print(f"형식 유효: {'✓' if result['is_valid'] else '✗'}")
            print(f"종목 존재: {'✓' if result['exists'] else '✗'}")

            if result.get('company_name'):
                print(f"회사명: {result['company_name']}")

            if result.get('market_info'):
                info = result['market_info']
                if info.get('current_price'):
                    currency = info.get('currency', '')
                    print(f"현재가: {currency} {info['current_price']:,.0f}")

            if result.get('data_quality'):
                q = result['data_quality']
                print(f"데이터 품질: {q.get('grade', 'N/A')}등급 ({q.get('quality_score', 0)}점)")
                print(f"데이터 일수: {q.get('data_days', 0)}일")

            print(f"분석 가능: {'✓' if result['can_analyze'] else '✗'}")

            # 오류/경고
            if result.get('errors'):
                print("오류:")
                for err in result['errors']:
                    print(f"  ❌ {err}")

            if result.get('warnings'):
                print("경고:")
                for warn in result['warnings']:
                    print(f"  ⚠️ {warn}")

            # 최종 권고
            print(f"\n권고: {result.get('recommendation', 'N/A')}")

            # 예상 결과와 비교
            if expected == "valid":
                status = "✅ PASS" if result['can_analyze'] else "❌ FAIL"
            elif expected == "invalid":
                status = "✅ PASS" if not result['exists'] else "❌ FAIL"
            elif expected == "format_error":
                status = "✅ PASS" if not result['is_valid'] or result.get('warnings') else "❌ FAIL"
            else:  # check
                status = "🔍 CHECK"

            print(f"테스트 결과: {status}")

            results.append({
                'ticker': ticker,
                'expected': expected,
                'actual': {
                    'exists': result['exists'],
                    'can_analyze': result['can_analyze']
                },
                'status': status
            })

        except Exception as e:
            print(f"❌ 테스트 실패: {e}")
            results.append({
                'ticker': ticker,
                'expected': expected,
                'error': str(e),
                'status': '❌ ERROR'
            })

    # 요약
    print("\n" + "="*60)
    print("테스트 요약")
    print("="*60)

    pass_count = sum(1 for r in results if '✅' in r['status'])
    fail_count = sum(1 for r in results if '❌' in r['status'])
    check_count = sum(1 for r in results if '🔍' in r['status'])

    print(f"통과: {pass_count}")
    print(f"실패: {fail_count}")
    print(f"확인필요: {check_count}")
    print(f"총: {len(results)}")

    return results


def test_multi_agent_with_verification():
    """멀티에이전트 시스템의 검증 기능 테스트"""

    print("\n" + "="*60)
    print("멀티에이전트 검증 테스트")
    print("="*60)

    from stock_analyzer.multi_agent import MultiAgentOrchestrator

    orchestrator = MultiAgentOrchestrator()

    # 존재하지 않는 종목 테스트
    test_tickers = [
        "INVALID999",  # 확실히 존재하지 않는 티커
        "0126Z0.KS",   # 실제 존재 여부 확인 필요
    ]

    for ticker in test_tickers:
        print(f"\n테스트: {ticker}")
        print("-" * 40)

        result = orchestrator.analyze(ticker)

        if result.get('error'):
            print(f"✅ 오류 감지: {result['error']}")

            if result.get('details'):
                details = result['details']
                if details.get('errors'):
                    print("상세 오류:")
                    for err in details['errors']:
                        print(f"  - {err}")
                if details.get('recommendation'):
                    print(f"권고사항: {details['recommendation']}")
        else:
            print(f"종목명: {result.get('company_name', 'N/A')}")
            print(f"최종 신호: {result.get('final_decision', {}).get('final_signal', 'N/A')}")


if __name__ == "__main__":
    # 1. 티커 검증 테스트
    results = test_ticker_verification()

    # 2. 멀티에이전트 검증 테스트
    test_multi_agent_with_verification()

    print("\n" + "="*60)
    print("모든 테스트 완료")
    print("="*60)