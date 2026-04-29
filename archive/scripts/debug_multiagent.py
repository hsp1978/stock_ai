#!/usr/bin/env python3
"""
Debug script to find NoneType errors
"""
import sys
import traceback
sys.path.insert(0, 'stock_analyzer')

from multi_agent import ValueInvestor, EventAnalyst, RiskManager, MLSpecialist, AnalysisTools
from data_collector import fetch_ohlcv, calculate_indicators

ticker = "328130.KQ"  # 루닛

# Get data
df = fetch_ohlcv(ticker)
if df is not None and not df.empty:
    df = calculate_indicators(df)
    tools = AnalysisTools(ticker, df)

    # Test each failing agent
    agents = [
        ('ValueInvestor', ValueInvestor()),
        ('EventAnalyst', EventAnalyst()),
        ('RiskManager', RiskManager()),
        ('MLSpecialist', MLSpecialist())
    ]

    for name, agent in agents:
        print(f"\n{'='*50}")
        print(f"Testing {name}")
        print('='*50)
        try:
            result = agent.analyze(ticker, tools)
            print(f"✓ Success: {result.signal} ({result.confidence}/10)")
        except Exception as e:
            print(f"✗ Error: {e}")
            traceback.print_exc()
else:
    print("Failed to fetch data")