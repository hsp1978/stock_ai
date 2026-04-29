#!/usr/bin/env python3
"""
멀티에이전트 시스템 한국 주식 종목명 표시 테스트
하림, 루닛 등 개별 종목명 인식 포함
"""

import sys
import os
import json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'stock_analyzer'))

def test_korean_name_search():
    """한글 종목명 검색 및 인식 테스트"""

    print("=" * 70)
    print("한글 종목명 검색 테스트 (ticker_suggestion)")
    print("=" * 70)

    from ticker_suggestion import suggest_ticker

    # 테스트할 한글명 목록 (하림, 루닛 포함)
    test_names = [
        "하림",          # 136480
        "루닛",          # 328130
        "삼성전자",      # 005930
        "카카오",        # 035720
        "네이버",        # 035420
        "셀트리온",      # 068270
        "LG에너지솔루션", # 373220
        "에코프로",      # 086520
        "크래프톤",      # 259960
        "하이브",        # 352820
    ]

    print("\n한글명 → 티커 변환:")
    print("-" * 40)

    success_count = 0
    fail_count = 0

    for name in test_names:
        try:
            result = suggest_ticker(name, max_results=5)

            if result['found']:
                # 최상위 매치 또는 첫 번째 제안
                if result['best_match']:
                    ticker = result['best_match']
                    print(f"✅ {name:15} → {ticker:12} (자동 선택)")
                elif result['suggestions']:
                    ticker = result['suggestions'][0]['ticker']
                    score = int(result['suggestions'][0]['score'] * 100)
                    print(f"✅ {name:15} → {ticker:12} ({score}% 매치)")
                else:
                    ticker = '알 수 없음'
                    print(f"❌ {name:15} → {ticker}")

                success_count += 1

                # 첫 번째 제안 표시
                if result.get('suggestions'):
                    suggestion = result['suggestions'][0]
                    print(f"   └─ {suggestion.get('name', '')} ({suggestion.get('ticker', '')})")
            else:
                print(f"❌ {name:15} → 인식 실패")
                print(f"   └─ 일치하는 종목 없음")
                fail_count += 1

        except Exception as e:
            print(f"❌ {name:15} → 오류: {str(e)}")
            fail_count += 1

    print(f"\n결과: 성공 {success_count}/{len(test_names)}, 실패 {fail_count}/{len(test_names)}")
    return success_count, fail_count

def test_stock_name_display():
    """한국 주식 종목명 표시 테스트"""

    print("\n" + "=" * 70)
    print("멀티에이전트 종목명 표시 테스트")
    print("=" * 70)

    # 테스트할 종목들 (하림, 루닛 추가)
    test_tickers = [
        "136480.KS",   # 하림
        "328130.KQ",   # 루닛
        "005930",      # 삼성전자
        "005930.KS",   # 삼성전자 (Yahoo 형식)
        "000660",      # SK하이닉스
        "035720.KQ",   # 카카오 (코스닥)
        "068270",      # 셀트리온
        "373220",      # LG에너지솔루션
    ]

    from multi_agent import MultiAgentOrchestrator
    orchestrator = MultiAgentOrchestrator()

    print("\n종목명 조회 테스트:")
    print("-" * 40)

    for ticker in test_tickers:
        stock_name = orchestrator._get_stock_name(ticker)
        if stock_name:
            print(f"✓ {ticker:10} → {stock_name}")
        else:
            print(f"✗ {ticker:10} → [종목명 없음]")

    print("\n" + "=" * 70)
    print("멀티에이전트 분석 시작 메시지 테스트")
    print("=" * 70)

    # 실제 분석 시작 메시지 확인 (분석은 실행하지 않음)
    test_ticker = "005930.KS"
    stock_name = orchestrator._get_stock_name(test_ticker)

    if stock_name:
        print(f"\n[예상 출력]")
        print(f"[MultiAgent] {stock_name}({test_ticker}) 분석 시작...")
    else:
        print(f"\n[예상 출력]")
        print(f"[MultiAgent] {test_ticker} 분석 시작...")

    print("\n" + "=" * 70)
    print("프롬프트 내 종목명 표시 테스트")
    print("=" * 70)

    # BaseAgent 테스트
    from multi_agent import TechnicalAnalyst
    agent = TechnicalAnalyst()

    test_ticker = "000660.KS"
    stock_name = agent._get_stock_name_for_agent(test_ticker)

    if stock_name:
        print(f"\n[에이전트 프롬프트에 표시될 종목]")
        print(f"{stock_name}({test_ticker})")
    else:
        print(f"\n[에이전트 프롬프트에 표시될 종목]")
        print(f"{test_ticker}")

    print("\n" + "=" * 70)
    print("테스트 완료!")
    print("=" * 70)


def check_database_file():
    """데이터베이스 파일 확인"""

    print("\n" + "=" * 70)
    print("데이터베이스 파일 확인")
    print("=" * 70)

    db_path = os.path.join(os.path.dirname(__file__), 'stock_analyzer', 'korean_stocks_database.json')

    if os.path.exists(db_path):
        with open(db_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            stocks = data.get('stocks', {})
            print(f"✅ korean_stocks_database.json 존재 (총 {len(stocks)}개 종목)")

            # 하림과 루닛 확인
            if '136480' in stocks:
                harim = stocks['136480']
                print(f"   ✓ 하림: {harim}")
            else:
                print(f"   ✗ 하림 (136480) 없음")

            if '328130' in stocks:
                lunit = stocks['328130']
                print(f"   ✓ 루닛: {lunit}")
            else:
                print(f"   ✗ 루닛 (328130) 없음")
    else:
        print(f"❌ korean_stocks_database.json 파일 없음")
        print(f"   경로: {db_path}")


if __name__ == "__main__":
    # 1. 데이터베이스 파일 확인
    check_database_file()

    # 2. 한글명 검색 테스트
    success, fail = test_korean_name_search()

    # 3. 멀티에이전트 표시 테스트
    if success > 0:
        test_stock_name_display()

    print("\n" + "=" * 70)
    print("모든 테스트 완료!")
    print("=" * 70)