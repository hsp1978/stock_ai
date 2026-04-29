#!/usr/bin/env python3
"""
루닛, 하림 종목 검색 테스트
"""

import sys
sys.path.insert(0, 'stock_analyzer')

def test_ticker_suggestion():
    """ticker_suggestion 직접 테스트"""
    from ticker_suggestion import suggest_ticker

    print("=" * 60)
    print("1. ticker_suggestion 모듈 테스트")
    print("=" * 60)

    test_names = ["루닛", "하림", "삼성전자"]

    for name in test_names:
        result = suggest_ticker(name)
        if result['found'] and result['best_match']:
            print(f"✅ {name:10} → {result['best_match']:12} (자동 선택)")
            if result['suggestions']:
                print(f"                   {result['suggestions'][0]['name']}")
        else:
            print(f"❌ {name:10} → 찾을 수 없음")


def test_webui_validation():
    """webui.py의 validate_ticker_webui 테스트"""
    from webui import validate_ticker_webui

    print("\n" + "=" * 60)
    print("2. webui.py validate_ticker_webui 테스트")
    print("=" * 60)

    test_names = ["루닛", "하림", "삼성전자"]

    for name in test_names:
        try:
            is_valid, message = validate_ticker_webui(name)
            if is_valid:
                print(f"✅ {name:10} → 유효함")
                print(f"                   {message}")
            else:
                print(f"❌ {name:10} → {message}")
        except Exception as e:
            print(f"❌ {name:10} → 오류: {str(e)}")


def test_multiagent():
    """멀티에이전트 종목명 표시 테스트"""
    from multi_agent import MultiAgentOrchestrator

    print("\n" + "=" * 60)
    print("3. 멀티에이전트 종목명 표시 테스트")
    print("=" * 60)

    orchestrator = MultiAgentOrchestrator()

    test_tickers = ["136480.KQ", "328130.KQ", "005930.KS"]

    for ticker in test_tickers:
        name = orchestrator._get_stock_name(ticker)
        if name:
            print(f"✅ {ticker:12} → {name}")
        else:
            print(f"❌ {ticker:12} → 종목명 없음")


if __name__ == "__main__":
    print("\n🔍 루닛, 하림 종목 검색 테스트\n")

    # 1. ticker_suggestion 테스트
    test_ticker_suggestion()

    # 2. webui 검증 테스트
    try:
        test_webui_validation()
    except ImportError as e:
        print(f"\n⚠️ WebUI 테스트 스킵 (Streamlit 미실행): {e}")

    # 3. 멀티에이전트 테스트
    test_multiagent()

    print("\n✅ 모든 테스트 완료!")