#!/usr/bin/env python3
"""
멀티에이전트 시스템 LLM 장애 수정 테스트
"""

import os
import sys

# 프로젝트 경로 추가
sys.path.insert(0, '/home/ubuntu/stock_auto/stock_analyzer')
sys.path.insert(0, '/home/ubuntu/stock_auto/chart_agent_service')

def test_gpu_memory():
    """GPU 메모리 상태 확인"""
    import subprocess

    print("=" * 70)
    print("GPU 메모리 상태")
    print("=" * 70)

    try:
        result = subprocess.run(
            ['nvidia-smi', '--query-gpu=memory.used,memory.free,memory.total', '--format=csv'],
            capture_output=True, text=True, timeout=2
        )
        print(result.stdout)
    except Exception as e:
        print(f"GPU 메모리 체크 실패: {e}")
    print()


def test_ollama_health():
    """Ollama 서비스 상태 확인"""
    import requests

    print("=" * 70)
    print("Ollama 서비스 상태")
    print("=" * 70)

    try:
        response = requests.get("http://localhost:11434/api/tags", timeout=3)
        if response.status_code == 200:
            models = response.json().get('models', [])
            print(f"✅ Ollama 정상 동작 중 ({len(models)}개 모델)")
            for model in models:
                print(f"  - {model['name']}")
        else:
            print(f"❌ Ollama 응답 이상: {response.status_code}")
    except Exception as e:
        print(f"❌ Ollama 연결 실패: {e}")
    print()


def test_mac_studio():
    """Mac Studio 연결 확인"""
    from dual_node_config import is_mac_studio_available, LLM_NODES

    print("=" * 70)
    print("Mac Studio 연결 상태")
    print("=" * 70)

    mac_url = os.getenv("MAC_STUDIO_URL", LLM_NODES["mac_studio"]["url"])
    print(f"Mac Studio URL: {mac_url}")

    if is_mac_studio_available():
        print("✅ Mac Studio 연결 성공")
    else:
        print("⚠️ Mac Studio 연결 실패 - 로컬 GPU로 폴백")
    print()


def test_multi_agent_simple():
    """멀티에이전트 간단 테스트 (AAPL)"""
    from multi_agent import MultiAgentOrchestrator

    print("=" * 70)
    print("멀티에이전트 시스템 테스트 (AAPL)")
    print("=" * 70)

    # 환경변수 확인
    max_workers = os.getenv('MULTI_AGENT_MAX_WORKERS', '2')
    print(f"병렬 워커 수: {max_workers}")

    try:
        orchestrator = MultiAgentOrchestrator()
        print(f"Mac Studio 사용 가능: {orchestrator.mac_studio_available}")
        print(f"실제 워커 수: {orchestrator.max_workers}")
        print()

        result = orchestrator.analyze("AAPL")

        if result.get("error"):
            print(f"❌ 분석 실패: {result['error']}")
        else:
            print("✅ 분석 성공")
            final = result.get("final_decision", {})
            print(f"  최종 신호: {final.get('final_signal')}")
            print(f"  신뢰도: {final.get('final_confidence')}/10")
            print(f"  유효 에이전트: {final.get('valid_agent_count')}/{final.get('agent_count')}")

            # 에이전트별 결과
            print("\n에이전트별 결과:")
            for agent_result in result.get("agent_results", []):
                status = "✓" if not agent_result.get("error") else "✗"
                print(f"  {status} {agent_result['agent']}: {agent_result['signal']} ({agent_result['confidence']}/10)")

        return result

    except Exception as e:
        print(f"❌ 테스트 실패: {e}")
        import traceback
        traceback.print_exc()
        return None


def main():
    """메인 테스트"""
    print("\n멀티에이전트 LLM 장애 수정 검증")
    print("=" * 70)
    print()

    # 1. GPU 메모리 확인
    test_gpu_memory()

    # 2. Ollama 상태 확인
    test_ollama_health()

    # 3. Mac Studio 연결 확인
    test_mac_studio()

    # 4. 멀티에이전트 분석 테스트
    result = test_multi_agent_simple()

    print("\n" + "=" * 70)
    print("테스트 완료")
    print("=" * 70)

    if result and not result.get("error"):
        print("✅ 모든 테스트 통과")
        return 0
    else:
        print("❌ 일부 테스트 실패")
        return 1


if __name__ == "__main__":
    sys.exit(main())
