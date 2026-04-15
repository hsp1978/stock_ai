#!/usr/bin/env python3
"""
Stock AI Agent MCP Server
Model Context Protocol 서버로 16개 기술 분석 도구 + ML/백테스트 기능 노출
Week 1 Day 1-2: 기본 구조 + 5개 핵심 tool
"""

import os
import sys
import json
import asyncio
from typing import Dict, Any, Optional
from datetime import datetime

# 프로젝트 경로 추가
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'stock_analyzer'))

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


class StockAIServer:
    """Stock AI Agent MCP 서버"""

    def __init__(self):
        self.server = Server("stock-ai-agent")
        self.setup_handlers()
        self.setup_tools()

    def setup_handlers(self):
        """기본 핸들러 설정"""

        @self.server.list_tools()
        async def handle_list_tools() -> list[types.Tool]:
            """사용 가능한 도구 목록 반환"""
            return [
                # 1. 종합 분석
                types.Tool(
                    name="analyze_stock",
                    description="Analyze a stock using 16 technical analysis tools and get buy/sell/neutral signal",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "ticker": {
                                "type": "string",
                                "description": "Stock ticker symbol (e.g., NVDA, AAPL)"
                            }
                        },
                        "required": ["ticker"]
                    }
                ),

                # 2. ML 예측
                types.Tool(
                    name="predict_ml",
                    description="Predict stock direction using ML ensemble (LightGBM, XGBoost, LSTM) with SHAP explainability",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "ticker": {
                                "type": "string",
                                "description": "Stock ticker symbol"
                            },
                            "ensemble": {
                                "type": "boolean",
                                "description": "Use ensemble of all models (default: true)",
                                "default": True
                            }
                        },
                        "required": ["ticker"]
                    }
                ),

                # 3. 백테스트 최적화
                types.Tool(
                    name="optimize_strategy",
                    description="Optimize trading strategy parameters using Optuna (HyperOpt)",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "ticker": {
                                "type": "string",
                                "description": "Stock ticker symbol"
                            },
                            "strategy": {
                                "type": "string",
                                "description": "Strategy name: rsi_reversion, sma_cross, bollinger_reversion",
                                "default": "rsi_reversion"
                            },
                            "n_trials": {
                                "type": "integer",
                                "description": "Number of optimization trials",
                                "default": 30
                            }
                        },
                        "required": ["ticker"]
                    }
                ),

                # 4. Walk-Forward 백테스트
                types.Tool(
                    name="walk_forward_test",
                    description="Walk-forward backtest to detect overfitting",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "ticker": {
                                "type": "string",
                                "description": "Stock ticker symbol"
                            },
                            "strategy": {
                                "type": "string",
                                "description": "Strategy name",
                                "default": "rsi_reversion"
                            },
                            "n_splits": {
                                "type": "integer",
                                "description": "Number of walk-forward splits",
                                "default": 3
                            }
                        },
                        "required": ["ticker"]
                    }
                ),

                # 5. 포트폴리오 최적화
                types.Tool(
                    name="optimize_portfolio",
                    description="Optimize portfolio allocation using Markowitz or Risk Parity",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "method": {
                                "type": "string",
                                "description": "Optimization method: markowitz or risk_parity",
                                "default": "markowitz"
                            }
                        }
                    }
                ),

                # 6. 시스템 정보
                types.Tool(
                    name="get_system_info",
                    description="Get Stock AI Agent system information and capabilities",
                    inputSchema={
                        "type": "object",
                        "properties": {}
                    }
                ),
            ]

        @self.server.call_tool()
        async def handle_call_tool(name: str, arguments: Dict[str, Any]) -> list[types.TextContent]:
            """도구 실행 핸들러"""

            try:
                result = await self.execute_tool(name, arguments)

                # JSON 형태로 결과 반환
                return [types.TextContent(
                    type="text",
                    text=json.dumps(result, indent=2, ensure_ascii=False)
                )]

            except Exception as e:
                error_result = {
                    "error": str(e),
                    "tool": name,
                    "arguments": arguments
                }
                return [types.TextContent(
                    type="text",
                    text=json.dumps(error_result, indent=2)
                )]

    def setup_tools(self):
        """도구 초기화"""
        print("Stock AI Agent MCP Server initialized")
        print("Available tools: 6 core functions")

    async def execute_tool(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """도구 실행"""

        print(f"Executing tool: {name} with args: {arguments}")

        # 1. 종합 분석
        if name == "analyze_stock":
            ticker = arguments.get("ticker", "").upper()
            if not ticker:
                return {"error": "ticker is required"}
            return engine_scan_ticker(ticker)

        # 2. ML 예측
        elif name == "predict_ml":
            ticker = arguments.get("ticker", "").upper()
            ensemble = arguments.get("ensemble", True)
            if not ticker:
                return {"error": "ticker is required"}
            return engine_ml_predict(ticker, ensemble=ensemble)

        # 3. 백테스트 최적화
        elif name == "optimize_strategy":
            ticker = arguments.get("ticker", "").upper()
            strategy = arguments.get("strategy", "rsi_reversion")
            n_trials = arguments.get("n_trials", 30)
            if not ticker:
                return {"error": "ticker is required"}
            return engine_backtest_optimize(ticker, strategy, n_trials)

        # 4. Walk-Forward
        elif name == "walk_forward_test":
            ticker = arguments.get("ticker", "").upper()
            strategy = arguments.get("strategy", "rsi_reversion")
            n_splits = arguments.get("n_splits", 3)
            if not ticker:
                return {"error": "ticker is required"}
            return engine_backtest_walk_forward(
                ticker, strategy,
                train_window=200,
                test_window=50,
                n_splits=n_splits
            )

        # 5. 포트폴리오 최적화
        elif name == "optimize_portfolio":
            method = arguments.get("method", "markowitz")
            return engine_portfolio_optimize(method)

        # 6. 시스템 정보
        elif name == "get_system_info":
            info = engine_info()
            health = engine_health()
            return {
                "system": info,
                "health": health,
                "mcp_version": "1.0",
                "tools_count": 6,
                "analysis_tools": 16,
                "ml_models": 5,
                "strategies": 4,
            }

        else:
            return {"error": f"Unknown tool: {name}"}

    async def run(self):
        """서버 실행"""
        async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
            await self.server.run(
                read_stream,
                write_stream,
                InitializationOptions(
                    server_name="stock-ai-agent",
                    server_version="1.0.0",
                    capabilities=self.server.get_capabilities(
                        notification_options=NotificationOptions(),
                        experimental_capabilities={}
                    )
                )
            )


def main():
    """메인 실행 함수"""
    print("=" * 60)
    print("Stock AI Agent MCP Server v1.0")
    print("=" * 60)
    print(f"Started at: {datetime.now()}")
    print("Available tools:")
    print("  1. analyze_stock - 16 technical indicators analysis")
    print("  2. predict_ml - ML ensemble prediction")
    print("  3. optimize_strategy - Backtest optimization")
    print("  4. walk_forward_test - Walk-forward validation")
    print("  5. optimize_portfolio - Portfolio optimization")
    print("  6. get_system_info - System information")
    print("=" * 60)

    server = StockAIServer()
    asyncio.run(server.run())


if __name__ == "__main__":
    main()