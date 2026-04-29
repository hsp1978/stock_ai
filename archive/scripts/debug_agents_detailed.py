#!/usr/bin/env python3
"""
Detailed debug for agent NoneType errors
"""
import sys
import traceback
sys.path.insert(0, 'stock_analyzer')

# Test with a Korean stock that causes issues
ticker = "328130.KQ"  # 루닛

# Import agents that are failing
from multi_agent import RiskManager, ValueInvestor, EventAnalyst, MLSpecialist, AnalysisTools
from data_collector import fetch_ohlcv, calculate_indicators

print(f"Testing ticker: {ticker}")
print("="*50)

# Get data
df = fetch_ohlcv(ticker)
if df is not None and not df.empty:
    df = calculate_indicators(df)
    tools = AnalysisTools(ticker, df)

    # Test RiskManager with detailed error catching
    print("\nTesting RiskManager...")
    try:
        agent = RiskManager()
        result = agent.analyze(ticker, tools)
        print(f"✓ Success: {result.signal} ({result.confidence}/10)")
        if result.error:
            print(f"  Error in result: {result.error}")
    except Exception as e:
        print(f"✗ Exception occurred:")
        print(f"  Type: {type(e).__name__}")
        print(f"  Message: {str(e)}")
        print("\n  Full traceback:")
        traceback.print_exc()

    # Test ValueInvestor
    print("\nTesting ValueInvestor...")
    try:
        agent = ValueInvestor()
        # Try to see what yfinance returns for this ticker
        import yfinance as yf
        stock = yf.Ticker(ticker)
        info = stock.info or {}

        print(f"  yfinance info keys: {list(info.keys())[:10]}...")
        print(f"  country: {info.get('country', 'None')}")
        print(f"  sector: {info.get('sector', 'None')}")
        print(f"  currency: {info.get('currency', 'None')}")

        result = agent.analyze(ticker, tools)
        print(f"✓ Success: {result.signal} ({result.confidence}/10)")
        if result.error:
            print(f"  Error in result: {result.error}")
    except Exception as e:
        print(f"✗ Exception occurred:")
        print(f"  Type: {type(e).__name__}")
        print(f"  Message: {str(e)}")
        print("\n  Full traceback:")
        traceback.print_exc()

else:
    print("Failed to fetch data")