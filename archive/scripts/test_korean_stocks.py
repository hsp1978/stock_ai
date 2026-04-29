#!/usr/bin/env python3
"""
한국 주식 통합 테스트 스크립트
"""

import sys
import os
sys.path.insert(0, '/home/ubuntu/stock_auto/stock_analyzer')

from korean_stocks import KoreanStockData, get_market_indices
from ticker_manager import TickerManager, normalize_ticker, detect_market, get_stock_info


def test_korean_data_collector():
    """한국 주식 데이터 수집 테스트"""
    print("\n" + "="*70)
    print("1. 한국 주식 데이터 수집 테스트")
    print("="*70)

    collector = KoreanStockData()

    # 삼성전자 데이터 수집
    print("\n[Test 1-1] 삼성전자 (005930) 데이터 수집")
    df = collector.fetch_ohlcv("005930", period="1mo")

    if df is not None and not df.empty:
        print(f"✅ 성공: {len(df)}일 데이터 수집")
        print(f"   최신 종가: ₩{df['Close'].iloc[-1]:,.0f}")
        print(f"   거래량: {df['Volume'].iloc[-1]:,.0f}주")
    else:
        print("❌ 실패: 데이터 수집 불가")

    # 시장 지수 조회
    print("\n[Test 1-2] KOSPI/KOSDAQ 지수 조회")
    indices = get_market_indices()

    if indices.get('kospi'):
        kospi = indices['kospi']
        print(f"✅ KOSPI: {kospi.get('current', 0):,.2f} ({kospi.get('change_pct', 0):+.2f}%)")
    else:
        print("❌ KOSPI 조회 실패")

    if indices.get('kosdaq'):
        kosdaq = indices['kosdaq']
        print(f"✅ KOSDAQ: {kosdaq.get('current', 0):,.2f} ({kosdaq.get('change_pct', 0):+.2f}%)")
    else:
        print("❌ KOSDAQ 조회 실패")

    # 종목 검색
    print("\n[Test 1-3] 종목 검색 (삼성)")
    results = collector.search_stock("삼성")

    if results:
        print(f"✅ 검색 결과: {len(results)}개")
        for r in results[:3]:
            print(f"   - {r['code']} {r['name']} ({r['market']})")
    else:
        print("❌ 검색 결과 없음")


def test_ticker_manager():
    """티커 관리자 테스트"""
    print("\n" + "="*70)
    print("2. 티커 관리자 테스트")
    print("="*70)

    test_cases = [
        ("005930", "KR", "삼성전자"),
        ("삼성전자", "KR", "005930"),
        ("005930.KS", "KR", "이미 Yahoo 형식"),
        ("AAPL", "US", "Apple"),
        ("MSFT", "US", "Microsoft"),
    ]

    print("\n[Test 2-1] 시장 감지 및 티커 정규화")
    for ticker, expected_market, description in test_cases:
        detected_market = detect_market(ticker)
        normalized, market = normalize_ticker(ticker)

        status = "✅" if market == expected_market else "❌"
        print(f"{status} {ticker:15} → {normalized:15} | Market: {market:2} | {description}")

    print("\n[Test 2-2] 종목 정보 조회")
    test_tickers = ["005930", "AAPL"]

    for ticker in test_tickers:
        info = get_stock_info(ticker)
        print(f"\n종목: {ticker}")
        print(f"  정규화: {info['ticker']}")
        print(f"  종목명: {info['name']} ({info['name_en']})")
        print(f"  시장: {info['market']} - {info['exchange']}")
        print(f"  통화: {info['currency']}")
        print(f"  거래시간: {info['trading_hours']}")


def test_webui_integration():
    """WebUI 통합 테스트"""
    print("\n" + "="*70)
    print("3. WebUI 통합 테스트")
    print("="*70)

    print("\n[Test 3-1] WebUI 모듈 import 테스트")
    try:
        # webui.py는 streamlit 의존성 때문에 직접 실행 불가
        # 대신 모듈 파일 존재 여부 확인
        webui_path = "/home/ubuntu/stock_auto/stock_analyzer/webui.py"

        if os.path.exists(webui_path):
            with open(webui_path, 'r') as f:
                content = f.read()

                # 한국 주식 관련 코드 확인
                checks = [
                    ("korean_stocks import", "from korean_stocks import" in content),
                    ("ticker_manager import", "from ticker_manager import" in content),
                    ("render_korean_market_home", "def render_korean_market_home():" in content),
                    ("Korean Market tab", "🇰🇷 Korean Market" in content),
                ]

                for name, passed in checks:
                    status = "✅" if passed else "❌"
                    print(f"  {status} {name}")

        else:
            print("  ❌ webui.py 파일을 찾을 수 없습니다")

    except Exception as e:
        print(f"  ❌ 오류: {e}")


def test_data_quality():
    """데이터 품질 테스트"""
    print("\n" + "="*70)
    print("4. 데이터 품질 테스트")
    print("="*70)

    collector = KoreanStockData()

    test_tickers = [
        ("005930", "삼성전자"),
        ("000660", "SK하이닉스"),
        ("035420", "NAVER"),
    ]

    print("\n[Test 4-1] 여러 종목 데이터 품질 확인")
    for code, name in test_tickers:
        df = collector.fetch_ohlcv(code, period="5d")

        if df is not None and not df.empty:
            # 데이터 무결성 확인
            has_ohlcv = all(col in df.columns for col in ['Open', 'High', 'Low', 'Close', 'Volume'])
            has_data = len(df) > 0
            no_nulls = not df[['Close', 'Volume']].isnull().any().any()

            all_good = has_ohlcv and has_data and no_nulls
            status = "✅" if all_good else "❌"

            print(f"{status} {code} {name:10} | {len(df):2}일 | 최신가: ₩{df['Close'].iloc[-1]:,.0f}")

            if not all_good:
                if not has_ohlcv:
                    print(f"     ⚠️ OHLCV 컬럼 누락")
                if not no_nulls:
                    print(f"     ⚠️ NULL 값 존재")
        else:
            print(f"❌ {code} {name:10} | 데이터 없음")


def run_all_tests():
    """전체 테스트 실행"""
    print("\n")
    print("╔" + "="*68 + "╗")
    print("║" + " "*15 + "한국 주식 통합 테스트 스위트" + " "*15 + "║")
    print("╚" + "="*68 + "╝")

    try:
        test_korean_data_collector()
        test_ticker_manager()
        test_webui_integration()
        test_data_quality()

        print("\n" + "="*70)
        print("✅ 전체 테스트 완료!")
        print("="*70)
        print("\n다음 단계:")
        print("  1. WebUI 실행: streamlit run stock_analyzer/webui.py")
        print("  2. Home 페이지에서 🇰🇷 Korean Market 탭 확인")
        print("  3. Sidebar에서 한국 주식 코드 입력 (예: 005930)")
        print("\n")

        return True

    except Exception as e:
        print(f"\n❌ 테스트 실패: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
