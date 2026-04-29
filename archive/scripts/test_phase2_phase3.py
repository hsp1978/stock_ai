#!/usr/bin/env python3
"""
Phase 2 (외국인/기관 매매) & Phase 3 (DART 공시) 테스트
"""

import sys
sys.path.insert(0, '/home/ubuntu/stock_auto/stock_analyzer')

from korean_stocks import KoreanStockData
from dart_api import DARTClient


def test_phase2_institutional_trading():
    """Phase 2: 외국인/기관 매매 동향 테스트"""
    print("\n" + "="*70)
    print("Phase 2: 외국인/기관/개인 매매 동향 테스트 (pykrx)")
    print("="*70)

    collector = KoreanStockData()

    test_tickers = [
        ("005930", "삼성전자"),
        ("000660", "SK하이닉스"),
    ]

    for ticker, name in test_tickers:
        print(f"\n[Test] {name} ({ticker}) 매매 동향")
        print("-" * 50)

        trading_data = collector.fetch_institutional_trading(ticker, days=5)

        if trading_data and 'summary' in trading_data:
            print(f"✅ 성공: {trading_data.get('period', 'N/A')}")

            summary = trading_data['summary']
            print(f"\n📊 최근 5일 합계:")
            print(f"  외국인 순매수: {summary['foreign_net']:>15,}주")
            print(f"  기관 순매수:   {summary['institution_net']:>15,}주")
            print(f"  개인 순매수:   {summary['individual_net']:>15,}주")

            # 최근 2일만 출력
            if 'daily' in trading_data and trading_data['daily']:
                print(f"\n📅 일별 데이터 (최근 2일):")
                for day in trading_data['daily'][-2:]:
                    print(f"  {day['date']}:")
                    print(f"    외국인: {day['foreign']['net']:>10,}주")
                    print(f"    기관:   {day['institution']['net']:>10,}주")
                    print(f"    개인:   {day['individual']['net']:>10,}주")

        else:
            print("❌ 실패: pykrx 데이터 없음")
            print("   원인: pykrx 미설치 또는 KRX 데이터 없음")


def test_phase3_dart_api():
    """Phase 3: DART API 공시 조회 테스트"""
    print("\n" + "="*70)
    print("Phase 3: DART 전자공시 API 테스트")
    print("="*70)

    dart_client = DARTClient()

    print("\n[Test 1] DART API Key 설정 확인")
    print("-" * 50)

    if dart_client.is_configured():
        print("✅ DART_API_KEY 설정됨")
        print(f"   Key 길이: {len(dart_client.api_key)}자")

        # 삼성전자 공시 조회
        print("\n[Test 2] 삼성전자 최근 공시 조회 (30일)")
        print("-" * 50)

        disclosures = dart_client.fetch_recent_disclosures("005930", days=30)

        if disclosures:
            print(f"✅ {len(disclosures)}건 공시 조회됨\n")

            print("최근 5건:")
            for d in disclosures[:5]:
                print(f"  - {d['date']}: {d['title'][:60]}")
                print(f"    유형: {d.get('report_type', 'N/A')}")

        else:
            print("❌ 공시 데이터 없음")
            print("   원인: API 오류 또는 해당 기간 공시 없음")

    else:
        print("⚠️ DART_API_KEY가 설정되지 않았습니다.")
        print("\n설정 방법:")
        print("  1. https://opendart.fss.or.kr/ 에서 무료 회원가입")
        print("  2. API Key 발급 (즉시)")
        print("  3. stock_analyzer/.env 파일에 추가:")
        print("     DART_API_KEY=your_api_key_here")
        print("\n상세 가이드: DART_API_SETUP.md 참조")


def run_all_tests():
    """전체 테스트 실행"""
    print("\n")
    print("╔" + "="*68 + "╗")
    print("║" + " "*10 + "Phase 2 & Phase 3 통합 테스트 스위트" + " "*11 + "║")
    print("╚" + "="*68 + "╝")

    test_phase2_institutional_trading()
    test_phase3_dart_api()

    print("\n" + "="*70)
    print("테스트 완료!")
    print("="*70)

    print("\n📋 요약:")
    print("  Phase 2: pykrx를 통한 외국인/기관 매매 동향")
    print("  Phase 3: DART API를 통한 전자공시 조회")
    print("\n🔧 다음 단계:")
    print("  1. DART API Key 발급 (https://opendart.fss.or.kr/)")
    print("  2. stock_analyzer/.env에 DART_API_KEY 추가")
    print("  3. WebUI에서 🇰🇷 Korean Market 탭 확인")
    print("  4. 투자자별 매매 동향 및 최근 공시 기능 사용")
    print()


if __name__ == "__main__":
    run_all_tests()
