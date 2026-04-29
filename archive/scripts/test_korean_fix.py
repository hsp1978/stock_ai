#!/usr/bin/env python3
"""
한글 종목명 인식 개선 테스트
"""

import sys
sys.path.insert(0, 'stock_analyzer')

# 테스트 1: ticker_suggestion
print("=== ticker_suggestion 테스트 ===")
from ticker_suggestion import suggest_ticker

for name in ['루닛', '하림', '삼성에피스']:
    result = suggest_ticker(name)
    if result['found'] and result['best_match']:
        print(f'✅ {name} → {result["best_match"]}')
    elif result['found'] and result['suggestions']:
        ticker = result['suggestions'][0]['ticker']
        score = int(result['suggestions'][0]['score'] * 100)
        print(f'⚠️ {name} → {ticker} ({score}%)')
    else:
        print(f'❌ {name} → 찾을 수 없음')

# 테스트 2: resolve_ticker
print('\n=== resolve_ticker 테스트 ===')
try:
    from webui import resolve_ticker

    for name in ['루닛', '하림', '삼성에피스']:
        ticker, msg = resolve_ticker(name)
        if ticker and ticker != name:
            print(f'✅ {name} → {ticker}')
            if msg:
                print(f'   {msg}')
        else:
            print(f'❌ {name} → 인식 실패')
except Exception as e:
    print(f'오류: {e}')

# 테스트 3: watchlist 로드
print('\n=== watchlist 테스트 ===')
try:
    from webui import load_watchlist
    watchlist = load_watchlist()
    print(f'Watchlist: {watchlist}')
except Exception as e:
    print(f'오류: {e}')