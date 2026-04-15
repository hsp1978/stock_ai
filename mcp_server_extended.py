#!/usr/bin/env python3
"""
Stock AI Agent MCP Server - Extended Version
21개 도구 (5개 핵심 + 16개 개별 분석 도구) 노출
Week 1 Day 3-4: 전체 도구 노출
"""

import os
import sys
import json
import asyncio
from typing import Dict, Any, Optional, List
from datetime import datetime

# 프로젝트 경로 추가
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'stock_analyzer'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'chart_agent_service'))

# MCP 서버
from mcp.server import Server, NotificationOptions
from mcp.server.models import InitializationOptions
import mcp.server.stdio
import mcp.types as types

# 로컬 엔진 import
from stock_analyzer.local_engine import (
    engine_scan_ticker,
    engine_ml_predict,
    engine_backtest_optimize,
    engine_backtest_walk_forward,
    engine_portfolio_optimize,
    engine_info,
    engine_health,
)

# 개별 분석 도구를 위한 import
from chart_agent_service.data_collector import fetch_ohlcv, calculate_indicators
from chart_agent_service.analysis_tools import AnalysisTools


class StockAIServerExtended:
    """Stock AI Agent MCP 서버 - 확장 버전"""

    def __init__(self):
        self.server = Server("stock-ai-agent-extended")
        self.setup_handlers()

    def setup_handlers(self):
        """핸들러 설정"""

        @self.server.list_tools()
        async def handle_list_tools() -> list[types.Tool]:
            """21개 도구 목록 반환"""
            tools = []

            # === 5개 핵심 도구 ===
            tools.extend([
                types.Tool(
                    name="analyze_stock",
                    description="Comprehensive analysis using 16 technical tools with buy/sell signal",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "ticker": {"type": "string", "description": "Stock ticker (e.g., NVDA)"}
                        },
                        "required": ["ticker"]
                    }
                ),
                types.Tool(
                    name="predict_ml",
                    description="ML ensemble prediction (LightGBM, XGBoost, LSTM) with SHAP",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "ticker": {"type": "string"},
                            "ensemble": {"type": "boolean", "default": True}
                        },
                        "required": ["ticker"]
                    }
                ),
                types.Tool(
                    name="optimize_strategy",
                    description="Optimize strategy parameters using Optuna",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "ticker": {"type": "string"},
                            "strategy": {"type": "string", "default": "rsi_reversion"},
                            "n_trials": {"type": "integer", "default": 30}
                        },
                        "required": ["ticker"]
                    }
                ),
                types.Tool(
                    name="walk_forward_test",
                    description="Walk-forward backtest for overfitting detection",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "ticker": {"type": "string"},
                            "strategy": {"type": "string", "default": "rsi_reversion"},
                            "n_splits": {"type": "integer", "default": 3}
                        },
                        "required": ["ticker"]
                    }
                ),
                types.Tool(
                    name="optimize_portfolio",
                    description="Portfolio optimization (Markowitz/Risk Parity)",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "method": {"type": "string", "default": "markowitz"}
                        }
                    }
                ),
            ])

            # === 16개 개별 분석 도구 ===
            individual_tools = [
                ("trend_ma", "Moving average trend analysis (SMA/EMA crossover)"),
                ("rsi_divergence", "RSI divergence detection for reversal signals"),
                ("bollinger_squeeze", "Bollinger Bands squeeze for volatility breakout"),
                ("macd_momentum", "MACD momentum and signal crossover"),
                ("adx_trend_strength", "ADX trend strength measurement"),
                ("volume_profile", "Volume profile and accumulation analysis"),
                ("fibonacci_retracement", "Fibonacci retracement levels"),
                ("volatility_regime", "Volatility regime classification"),
                ("mean_reversion", "Mean reversion opportunity detection"),
                ("momentum_rank", "Momentum ranking and strength"),
                ("support_resistance", "Dynamic support/resistance levels"),
                ("correlation_regime", "Market correlation analysis"),
                ("risk_position_sizing", "Risk-based position sizing"),
                ("kelly_criterion", "Kelly criterion for optimal bet size"),
                ("beta_correlation", "Beta and market correlation"),
                ("event_driven", "Event-driven analysis (earnings, news)"),
            ]

            for tool_name, description in individual_tools:
                tools.append(
                    types.Tool(
                        name=f"analyze_{tool_name}",
                        description=description,
                        inputSchema={
                            "type": "object",
                            "properties": {
                                "ticker": {"type": "string", "description": "Stock ticker"}
                            },
                            "required": ["ticker"]
                        }
                    )
                )

            # 시스템 정보 도구
            tools.append(
                types.Tool(
                    name="get_system_info",
                    description="Get system information and capabilities",
                    inputSchema={"type": "object", "properties": {}}
                )
            )

            return tools

        @self.server.call_tool()
        async def handle_call_tool(name: str, arguments: Dict[str, Any]) -> list[types.TextContent]:
            """도구 실행"""
            try:
                result = await self.execute_tool(name, arguments)
                return [types.TextContent(
                    type="text",
                    text=json.dumps(result, indent=2, ensure_ascii=False)
                )]
            except Exception as e:
                return [types.TextContent(
                    type="text",
                    text=json.dumps({"error": str(e), "tool": name}, indent=2)
                )]

    async def execute_tool(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """도구 실행 로직"""

        # === 핵심 도구 실행 ===
        if name == "analyze_stock":
            ticker = arguments.get("ticker", "").upper()
            return engine_scan_ticker(ticker)

        elif name == "predict_ml":
            ticker = arguments.get("ticker", "").upper()
            ensemble = arguments.get("ensemble", True)
            return engine_ml_predict(ticker, ensemble=ensemble)

        elif name == "optimize_strategy":
            ticker = arguments.get("ticker", "").upper()
            strategy = arguments.get("strategy", "rsi_reversion")
            n_trials = arguments.get("n_trials", 30)
            return engine_backtest_optimize(ticker, strategy, n_trials)

        elif name == "walk_forward_test":
            ticker = arguments.get("ticker", "").upper()
            strategy = arguments.get("strategy", "rsi_reversion")
            n_splits = arguments.get("n_splits", 3)
            return engine_backtest_walk_forward(
                ticker, strategy,
                train_window=200, test_window=50, n_splits=n_splits
            )

        elif name == "optimize_portfolio":
            method = arguments.get("method", "markowitz")
            return engine_portfolio_optimize(method)

        elif name == "get_system_info":
            return {
                "system": engine_info(),
                "health": engine_health(),
                "mcp_version": "1.0",
                "total_tools": 22,
                "core_tools": 5,
                "analysis_tools": 16,
                "ml_models": 5,
                "strategies": 4
            }

        # === 개별 분석 도구 실행 ===
        elif name.startswith("analyze_"):
            ticker = arguments.get("ticker", "").upper()
            if not ticker:
                return {"error": "ticker is required"}

            # 데이터 가져오기
            try:
                df = fetch_ohlcv(ticker)
                df = calculate_indicators(df)
                tools = AnalysisTools(ticker, df)
            except Exception as e:
                return {"error": f"Failed to fetch data: {str(e)}"}

            # 도구명 파싱 (analyze_ 제거)
            tool_method = name.replace("analyze_", "")

            # 도구별 실행
            tool_methods = {
                "trend_ma": tools.trend_ma_analysis,
                "rsi_divergence": tools.rsi_divergence_analysis,
                "bollinger_squeeze": tools.bollinger_squeeze_analysis,
                "macd_momentum": tools.macd_momentum_analysis,
                "adx_trend_strength": tools.adx_trend_strength_analysis,
                "volume_profile": tools.volume_profile_analysis,
                "fibonacci_retracement": tools.fibonacci_retracement_analysis,
                "volatility_regime": tools.volatility_regime_analysis,
                "mean_reversion": tools.mean_reversion_analysis,
                "momentum_rank": tools.momentum_rank_analysis,
                "support_resistance": tools.support_resistance_analysis,
                "correlation_regime": tools.correlation_regime_analysis,
                "risk_position_sizing": tools.risk_position_sizing,
                "kelly_criterion": tools.kelly_criterion_analysis,
                "beta_correlation": tools.beta_correlation_analysis,
                "event_driven": tools.event_driven_analysis,
            }

            if tool_method in tool_methods:
                try:
                    return tool_methods[tool_method]()
                except Exception as e:
                    return {
                        "error": f"Tool execution failed: {str(e)}",
                        "tool": name,
                        "ticker": ticker
                    }
            else:
                return {"error": f"Unknown analysis tool: {tool_method}"}

        else:
            return {"error": f"Unknown tool: {name}"}

    async def run(self):
        """서버 실행"""
        async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
            await self.server.run(
                read_stream,
                write_stream,
                InitializationOptions(
                    server_name="stock-ai-agent-extended",
                    server_version="1.0.0",
                    capabilities=self.server.get_capabilities(
                        notification_options=NotificationOptions(),
                        experimental_capabilities={}
                    )
                )
            )


def main():
    """메인 실행"""
    print("=" * 70)
    print("Stock AI Agent MCP Server - Extended v1.0")
    print("=" * 70)
    print(f"Started at: {datetime.now()}")
    print("\nAvailable tools (21 total):")
    print("\n[Core Tools - 5]")
    print("  • analyze_stock      - Comprehensive 16-tool analysis")
    print("  • predict_ml         - ML ensemble prediction")
    print("  • optimize_strategy  - Backtest optimization")
    print("  • walk_forward_test  - Walk-forward validation")
    print("  • optimize_portfolio - Portfolio optimization")

    print("\n[Individual Analysis Tools - 16]")
    tools = [
        "trend_ma", "rsi_divergence", "bollinger_squeeze", "macd_momentum",
        "adx_trend_strength", "volume_profile", "fibonacci_retracement",
        "volatility_regime", "mean_reversion", "momentum_rank",
        "support_resistance", "correlation_regime", "risk_position_sizing",
        "kelly_criterion", "beta_correlation", "event_driven"
    ]
    for i, tool in enumerate(tools, 1):
        print(f"  {i:2}. analyze_{tool}")

    print("\n[System Tool - 1]")
    print("  • get_system_info    - System status and capabilities")
    print("=" * 70)

    server = StockAIServerExtended()
    asyncio.run(server.run())


if __name__ == "__main__":
    main()