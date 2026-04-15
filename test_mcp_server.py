#!/usr/bin/env python3
"""
MCP 서버 테스트 스크립트
Week 1 Day 6-7: 테스트 및 검증
"""

import json
import subprocess
import sys
import time
from datetime import datetime
from typing import Dict, Any, Optional
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from chart_agent_service.config import DEFAULT_TEST_TICKER

# 색상 코드
RED = '\033[0;31m'
GREEN = '\033[0;32m'
YELLOW = '\033[1;33m'
BLUE = '\033[0;34m'
NC = '\033[0m'  # No Color


class MCPServerTester:
    """MCP 서버 테스터"""

    def __init__(self, server_script="mcp_server_extended.py"):
        self.server_script = server_script
        self.process = None
        self.request_id = 0

    def start_server(self):
        """MCP 서버 프로세스 시작"""
        print(f"{BLUE}Starting MCP server...{NC}")
        self.process = subprocess.Popen(
            [sys.executable, self.server_script],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=0
        )
        time.sleep(2)  # 서버 초기화 대기
        print(f"{GREEN}✓ MCP server started{NC}")
        return self.process

    def stop_server(self):
        """서버 종료"""
        if self.process:
            self.process.terminate()
            self.process.wait()
            print(f"{GREEN}✓ MCP server stopped{NC}")

    def send_request(self, method: str, params: Dict[str, Any] = None) -> Optional[Dict[str, Any]]:
        """JSON-RPC 요청 전송"""
        self.request_id += 1
        request = {
            "jsonrpc": "2.0",
            "id": self.request_id,
            "method": method,
            "params": params or {}
        }

        try:
            # 요청 전송
            request_str = json.dumps(request) + "\n"
            self.process.stdin.write(request_str)
            self.process.stdin.flush()

            # 응답 읽기
            response_str = self.process.stdout.readline()
            if response_str:
                return json.loads(response_str)
            return None

        except Exception as e:
            print(f"{RED}Request failed: {e}{NC}")
            return None

    def test_list_tools(self):
        """도구 목록 테스트"""
        print(f"\n{BLUE}=== Testing list_tools ==={NC}")

        response = self.send_request("tools/list")

        if response and "result" in response:
            tools = response["result"].get("tools", [])
            print(f"{GREEN}✓ Found {len(tools)} tools{NC}")

            # 주요 도구 확인
            core_tools = ["analyze_stock", "predict_ml", "optimize_strategy"]
            for tool_name in core_tools:
                if any(t.get("name") == tool_name for t in tools):
                    print(f"  {GREEN}✓{NC} {tool_name}")
                else:
                    print(f"  {RED}✗{NC} {tool_name} not found")

            return True
        else:
            print(f"{RED}✗ Failed to list tools{NC}")
            return False

    def test_analyze_stock(self, ticker=DEFAULT_TEST_TICKER):
        """종목 분석 테스트"""
        print(f"\n{BLUE}=== Testing analyze_stock for {ticker} ==={NC}")

        response = self.send_request(
            "tools/call",
            {
                "name": "analyze_stock",
                "arguments": {"ticker": ticker}
            }
        )

        if response and "result" in response:
            result = response["result"]
            if isinstance(result, list) and len(result) > 0:
                content = result[0].get("text", "")
                try:
                    data = json.loads(content)
                    if "final_signal" in data:
                        print(f"{GREEN}✓ Analysis complete{NC}")
                        print(f"  Signal: {data.get('final_signal')}")
                        print(f"  Score: {data.get('composite_score', 0):+.2f}")
                        print(f"  Confidence: {data.get('confidence', 0)}/10")
                        return True
                except json.JSONDecodeError:
                    pass

        print(f"{RED}✗ Analysis failed{NC}")
        return False

    def test_individual_tool(self, ticker=DEFAULT_TEST_TICKER, tool="rsi_divergence"):
        """개별 도구 테스트"""
        print(f"\n{BLUE}=== Testing analyze_{tool} for {ticker} ==={NC}")

        response = self.send_request(
            "tools/call",
            {
                "name": f"analyze_{tool}",
                "arguments": {"ticker": ticker}
            }
        )

        if response and "result" in response:
            result = response["result"]
            if isinstance(result, list) and len(result) > 0:
                content = result[0].get("text", "")
                try:
                    data = json.loads(content)
                    if "signal" in data:
                        print(f"{GREEN}✓ Tool executed{NC}")
                        print(f"  Signal: {data.get('signal')}")
                        print(f"  Score: {data.get('score', 0):+.2f}")
                        return True
                except json.JSONDecodeError:
                    pass

        print(f"{RED}✗ Tool execution failed{NC}")
        return False

    def test_system_info(self):
        """시스템 정보 테스트"""
        print(f"\n{BLUE}=== Testing get_system_info ==={NC}")

        response = self.send_request(
            "tools/call",
            {
                "name": "get_system_info",
                "arguments": {}
            }
        )

        if response and "result" in response:
            result = response["result"]
            if isinstance(result, list) and len(result) > 0:
                content = result[0].get("text", "")
                try:
                    data = json.loads(content)
                    if "system" in data:
                        print(f"{GREEN}✓ System info retrieved{NC}")
                        print(f"  Total tools: {data.get('total_tools', 0)}")
                        print(f"  ML models: {data.get('ml_models', 0)}")
                        return True
                except json.JSONDecodeError:
                    pass

        print(f"{RED}✗ System info failed{NC}")
        return False


def test_direct_import():
    """직접 import 테스트 (MCP 서버 없이)"""
    print(f"\n{BLUE}=== Direct Import Test ==={NC}")

    try:
        from stock_analyzer.local_engine import engine_info, engine_health

        info = engine_info()
        health = engine_health()

        print(f"{GREEN}✓ Direct import successful{NC}")
        print(f"  Version: {info.get('version', 'unknown')}")
        print(f"  Healthy: {health.get('healthy', False)}")
        return True

    except ImportError as e:
        print(f"{RED}✗ Import failed: {e}{NC}")
        return False


def main():
    """메인 테스트 실행"""
    print(f"\n{BLUE}{'='*60}{NC}")
    print(f"{BLUE}MCP Server Test Suite{NC}")
    print(f"{BLUE}{'='*60}{NC}")
    print(f"Test started: {datetime.now()}\n")

    results = []

    # 1. 직접 import 테스트
    results.append(("Direct Import", test_direct_import()))

    # 2. MCP 서버 테스트
    tester = MCPServerTester("mcp_server_extended.py")

    try:
        # 서버 시작
        tester.start_server()

        # 테스트 실행
        results.append(("List Tools", tester.test_list_tools()))
        results.append(("Analyze Stock", tester.test_analyze_stock(DEFAULT_TEST_TICKER)))
        results.append(("RSI Divergence", tester.test_individual_tool(DEFAULT_TEST_TICKER, "rsi_divergence")))
        results.append(("System Info", tester.test_system_info()))

    except Exception as e:
        print(f"{RED}Test error: {e}{NC}")

    finally:
        # 서버 종료
        tester.stop_server()

    # 결과 요약
    print(f"\n{BLUE}{'='*60}{NC}")
    print(f"{BLUE}Test Results Summary{NC}")
    print(f"{BLUE}{'='*60}{NC}")

    passed = sum(1 for _, result in results if result)
    total = len(results)

    for test_name, result in results:
        status = f"{GREEN}✓ PASS{NC}" if result else f"{RED}✗ FAIL{NC}"
        print(f"{status} {test_name}")

    print(f"\n{BLUE}Total: {passed}/{total} passed ({passed/total*100:.0f}%){NC}")

    if passed == total:
        print(f"{GREEN}🎉 All tests passed!{NC}")
        return 0
    else:
        print(f"{YELLOW}⚠ Some tests failed{NC}")
        return 1


def test_simple():
    """간단한 테스트 (서버 없이)"""
    print(f"\n{BLUE}=== Simple Function Test ==={NC}")

    try:
        # local_engine 직접 테스트
        from stock_analyzer.local_engine import engine_scan_ticker

        print(f"Testing engine_scan_ticker('{DEFAULT_TEST_TICKER}')...")
        result = engine_scan_ticker(DEFAULT_TEST_TICKER)

        if result and "final_signal" in result:
            print(f"{GREEN}✓ Success!{NC}")
            print(f"  Signal: {result['final_signal']}")
            print(f"  Score: {result.get('composite_score', 0):+.2f}")
            print(f"  Tools analyzed: {result.get('tool_count', 0)}")
        else:
            print(f"{YELLOW}⚠ Unexpected result format{NC}")
            print(f"  Keys: {list(result.keys()) if result else 'None'}")

    except Exception as e:
        print(f"{RED}✗ Test failed: {e}{NC}")


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "--simple":
        test_simple()
    else:
        sys.exit(main())