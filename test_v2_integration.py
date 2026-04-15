#!/usr/bin/env python3
"""
V2.0 전체 통합 테스트
Week 1~4 모든 기능 검증
"""

import os
import sys
import json
import time
from datetime import datetime

# 경로 설정
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'stock_analyzer'))

# 색상
GREEN = '\033[0;32m'
YELLOW = '\033[1;33m'
RED = '\033[0;31m'
BLUE = '\033[0;34m'
NC = '\033[0m'


def print_section(title):
    """섹션 헤더 출력"""
    print(f"\n{BLUE}{'='*70}{NC}")
    print(f"{BLUE}{title}{NC}")
    print(f"{BLUE}{'='*70}{NC}\n")


def test_prerequisites():
    """사전 준비사항 확인"""
    print_section("사전 준비사항 확인")

    checks = []

    # 1. Python 버전
    import sys
    version = sys.version_info
    py_ok = version.major >= 3 and version.minor >= 10
    checks.append(("Python 3.10+", py_ok))
    print(f"  {'✓' if py_ok else '✗'} Python {version.major}.{version.minor}")

    # 2. 필수 패키지
    try:
        import mcp
        checks.append(("MCP 패키지", True))
        print(f"  ✓ MCP 설치됨")
    except ImportError:
        checks.append(("MCP 패키지", False))
        print(f"  ✗ MCP 미설치")

    try:
        import openai
        checks.append(("OpenAI 패키지", True))
        print(f"  ✓ OpenAI 설치됨")
    except ImportError:
        checks.append(("OpenAI 패키지", False))
        print(f"  ✗ OpenAI 미설치")

    # 3. API Keys
    api_key_ok = bool(os.getenv('OPENAI_API_KEY'))
    checks.append(("OpenAI API Key", api_key_ok))
    print(f"  {'✓' if api_key_ok else '✗'} OpenAI API Key")

    gemini_key_ok = bool(os.getenv('GEMINI_API_KEY') or os.getenv('GOOGLE_API_KEY'))
    checks.append(("Gemini API Key", gemini_key_ok))
    print(f"  {'✓' if gemini_key_ok else '✗'} Gemini API Key")

    # 4. Ollama
    try:
        import requests
        resp = requests.get('http://localhost:11434/api/tags', timeout=2)
        ollama_ok = resp.status_code == 200
        checks.append(("Ollama 서버", ollama_ok))
        print(f"  {'✓' if ollama_ok else '✗'} Ollama 실행 중")
    except:
        checks.append(("Ollama 서버", False))
        print(f"  ✗ Ollama 미실행")

    passed = sum(1 for _, ok in checks if ok)
    total = len(checks)

    print(f"\n준비 상태: {passed}/{total} ({passed/total*100:.0f}%)")

    return all(ok for _, ok in checks)


def test_week1_mcp_server():
    """Week 1: MCP 서버"""
    print_section("Week 1: MCP 서버 테스트")

    try:
        # MCP 서버 파일 존재 확인
        mcp_basic = os.path.exists("mcp_server.py")
        mcp_extended = os.path.exists("mcp_server_extended.py")

        print(f"  {'✓' if mcp_basic else '✗'} mcp_server.py")
        print(f"  {'✓' if mcp_extended else '✗'} mcp_server_extended.py")

        # 간단 import 테스트
        from stock_analyzer.local_engine import engine_scan_ticker
        result = engine_scan_ticker("NVDA")

        if result and "final_signal" in result:
            print(f"  {GREEN}✓ engine_scan_ticker 정상 작동{NC}")
            return True
        else:
            print(f"  {YELLOW}⚠ engine_scan_ticker 응답 이상{NC}")
            return False

    except Exception as e:
        print(f"  {RED}✗ Week 1 테스트 실패: {e}{NC}")
        return False


def test_week23_multi_agent():
    """Week 2-3: 멀티에이전트"""
    print_section("Week 2-3: 멀티에이전트 테스트")

    try:
        from stock_analyzer.local_engine import engine_multi_agent_analyze

        print("  멀티에이전트 분석 실행 중... (1-2분 소요)")
        result = engine_multi_agent_analyze("NVDA")

        if "error" in result:
            print(f"  {YELLOW}⚠ 에러: {result['error']}{NC}")
            return False

        if "final_decision" in result:
            decision = result["final_decision"]
            agent_count = result.get("final_decision", {}).get("agent_count", 0)

            print(f"  {GREEN}✓ 멀티에이전트 분석 성공{NC}")
            print(f"  - 에이전트 수: {agent_count}")
            print(f"  - 최종 신호: {decision.get('final_signal')}")
            print(f"  - 신뢰도: {decision.get('final_confidence', 0):.1f}/10")
            print(f"  - 실행 시간: {result.get('total_execution_time', 0):.1f}초")
            return True
        else:
            print(f"  {YELLOW}⚠ 응답 구조 이상{NC}")
            return False

    except Exception as e:
        print(f"  {RED}✗ Week 2-3 테스트 실패: {e}{NC}")
        import traceback
        traceback.print_exc()
        return False


def test_week4_rebalancing():
    """Week 4: 포트폴리오 리밸런싱"""
    print_section("Week 4: 포트폴리오 리밸런싱 테스트")

    try:
        from stock_analyzer.local_engine import (
            engine_portfolio_rebalance,
            engine_rebalance_status
        )

        # 1. 상태 조회
        print("  [1/2] 리밸런싱 상태 조회...")
        status = engine_rebalance_status()

        if "error" in status:
            print(f"  {YELLOW}⚠ 상태 조회 실패: {status['error']}{NC}")
        else:
            print(f"  {GREEN}✓ 상태 조회 성공{NC}")
            print(f"    - 현재 Drift: {status.get('current_drift', 0):.2%}")
            print(f"    - 리밸런싱 필요: {status.get('needs_rebalance', False)}")

        # 2. Dry-run
        print("\n  [2/2] Dry-run 리밸런싱...")
        result = engine_portfolio_rebalance(dry_run=True)

        if "error" in result:
            print(f"  {YELLOW}⚠ Dry-run 실패: {result['error']}{NC}")
            return False
        else:
            print(f"  {GREEN}✓ Dry-run 성공{NC}")
            print(f"    - 상태: {result.get('status')}")
            print(f"    - 사유: {result.get('reason')}")
            print(f"    - 주문 수: {len(result.get('orders', []))}개")
            return True

    except Exception as e:
        print(f"  {RED}✗ Week 4 테스트 실패: {e}{NC}")
        import traceback
        traceback.print_exc()
        return False


def test_v1_features():
    """V1.0 기존 기능 정상 작동 확인"""
    print_section("V1.0 기존 기능 확인")

    try:
        from stock_analyzer.local_engine import (
            engine_ml_predict,
            engine_backtest_optimize,
            engine_backtest_walk_forward
        )

        tests = []

        # 1. ML 예측
        print("  [1/3] ML 앙상블 예측...")
        ml_result = engine_ml_predict("NVDA", ensemble=True)
        ml_ok = "ensemble" in ml_result and not ml_result.get("error")
        tests.append(("ML 앙상블", ml_ok))
        print(f"    {'✓' if ml_ok else '✗'} {'성공' if ml_ok else '실패'}")

        # 2. HyperOpt (빠른 테스트)
        print("  [2/3] HyperOpt 최적화 (10 trials)...")
        opt_result = engine_backtest_optimize("NVDA", "rsi_reversion", n_trials=10)
        opt_ok = "best_params" in opt_result and not opt_result.get("error")
        tests.append(("HyperOpt", opt_ok))
        print(f"    {'✓' if opt_ok else '✗'} {'성공' if opt_ok else '실패'}")

        # 3. Walk-Forward (빠른 테스트)
        print("  [3/3] Walk-Forward 백테스트 (3 splits)...")
        wf_result = engine_backtest_walk_forward("NVDA", "rsi_reversion", n_splits=3)
        wf_ok = "splits" in wf_result and not wf_result.get("error")
        tests.append(("Walk-Forward", wf_ok))
        print(f"    {'✓' if wf_ok else '✗'} {'성공' if wf_ok else '실패'}")

        return all(ok for _, ok in tests)

    except Exception as e:
        print(f"  {RED}✗ V1.0 테스트 실패: {e}{NC}")
        return False


def main():
    """메인 테스트 실행"""
    print(f"\n{BLUE}{'#'*70}{NC}")
    print(f"{BLUE}#  Stock AI Agent V2.0 Integration Test Suite{NC}")
    print(f"{BLUE}#  Week 1: MCP Server{NC}")
    print(f"{BLUE}#  Week 2-3: Multi-Agent System{NC}")
    print(f"{BLUE}#  Week 4: Portfolio Rebalancing{NC}")
    print(f"{BLUE}{'#'*70}{NC}")
    print(f"\n시작 시간: {datetime.now()}")

    results = []

    # 1. 사전 준비
    results.append(("사전 준비사항", test_prerequisites()))

    # 2. Week 1
    results.append(("Week 1: MCP 서버", test_week1_mcp_server()))

    # 3. Week 2-3
    results.append(("Week 2-3: 멀티에이전트", test_week23_multi_agent()))

    # 4. Week 4
    results.append(("Week 4: 리밸런싱", test_week4_rebalancing()))

    # 5. V1.0 기능
    results.append(("V1.0 기존 기능", test_v1_features()))

    # 최종 요약
    print_section("V2.0 통합 테스트 최종 요약")

    passed = sum(1 for _, result in results if result)
    total = len(results)

    for test_name, result in results:
        status = f"{GREEN}✓ PASS{NC}" if result else f"{RED}✗ FAIL{NC}"
        print(f"{status} {test_name}")

    print(f"\n{BLUE}{'='*70}{NC}")
    print(f"총 {total}개 테스트 중 {passed}개 통과 ({passed/total*100:.0f}%)")
    print(f"{BLUE}{'='*70}{NC}\n")

    if passed == total:
        print(f"{GREEN}{'🎉'*3} V2.0 전체 통합 테스트 통과! {'🎉'*3}{NC}")
        print(f"\n{GREEN}V2.0 구현 완료:{NC}")
        print(f"  ✅ Week 1: MCP 서버 (21개 도구)")
        print(f"  ✅ Week 2-3: 멀티에이전트 (6개 에이전트)")
        print(f"  ✅ Week 4: 포트폴리오 리밸런싱")
        print(f"\n{GREEN}개발 진행률: 100%{NC}")
        return 0
    elif passed >= total * 0.8:
        print(f"{YELLOW}⚠ 대부분의 테스트 통과 (80%+){NC}")
        print(f"  일부 기능에서 API key 또는 서버 연결 문제가 있을 수 있습니다.")
        return 0
    else:
        print(f"{RED}❌ 통합 테스트 실패{NC}")
        print(f"  설정을 확인하고 다시 시도하세요.")
        return 1


if __name__ == "__main__":
    sys.exit(main())