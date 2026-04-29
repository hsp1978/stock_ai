#!/usr/bin/env python3
"""
LLM 서비스 간단 테스트
"""

import os
import sys
import time

sys.path.insert(0, '/home/ubuntu/stock_auto/stock_analyzer')

def test_ollama_direct():
    """Ollama 직접 호출 테스트"""
    import requests

    print("=" * 70)
    print("Ollama 직접 호출 테스트")
    print("=" * 70)

    try:
        response = requests.post(
            "http://localhost:11434/api/generate",
            json={
                "model": "qwen3:14b-q4_K_M",
                "prompt": "Say hello in Korean.",
                "stream": False,
                "options": {
                    "temperature": 0.0,
                    "num_gpu": 1,
                    "num_thread": 4
                }
            },
            timeout=60
        )

        if response.status_code == 200:
            text = response.json().get('response', '')
            print(f"✅ Ollama 응답 성공:\n{text[:200]}")
            return True
        else:
            print(f"❌ Ollama 응답 실패: {response.status_code}")
            return False

    except Exception as e:
        print(f"❌ Ollama 호출 에러: {e}")
        return False


def test_gpu_memory():
    """GPU 메모리 체크 테스트"""
    import subprocess

    print("\n" + "=" * 70)
    print("GPU 메모리 체크")
    print("=" * 70)

    try:
        result = subprocess.run(
            ['nvidia-smi', '--query-gpu=memory.used', '--format=csv,noheader,nounits'],
            capture_output=True, text=True, timeout=2
        )
        if result.returncode == 0:
            mem_used = int(result.stdout.strip())
            print(f"GPU 메모리 사용: {mem_used} MiB / 12227 MiB")

            if mem_used > 11000:
                print("⚠️ GPU 메모리 90% 이상 사용 중 - 대기 필요")
                return False
            else:
                print("✅ GPU 메모리 충분")
                return True
    except Exception as e:
        print(f"❌ GPU 체크 실패: {e}")
        return False


def test_dual_node_config():
    """듀얼 노드 설정 테스트"""
    from dual_node_config import get_llm_config, is_mac_studio_available

    print("\n" + "=" * 70)
    print("듀얼 노드 설정")
    print("=" * 70)

    # Mac Studio 연결 확인
    mac_available = is_mac_studio_available()
    print(f"Mac Studio 사용 가능: {mac_available}")

    # 에이전트별 설정 확인
    agents = ["Technical Analyst", "ML Specialist", "Decision Maker"]
    for agent in agents:
        config = get_llm_config(agent)
        print(f"\n{agent}:")
        print(f"  노드: {config['node']}")
        print(f"  모델: {config['model']}")
        print(f"  URL: {config['url']}")


def main():
    print("\nLLM 서비스 테스트")
    print("=" * 70)

    # 1. GPU 메모리 확인
    gpu_ok = test_gpu_memory()

    # 2. Ollama 직접 호출
    ollama_ok = test_ollama_direct()

    # 3. 듀얼 노드 설정
    test_dual_node_config()

    print("\n" + "=" * 70)
    if gpu_ok and ollama_ok:
        print("✅ LLM 서비스 정상")
        return 0
    else:
        print("⚠️ LLM 서비스 일부 문제 있음")
        return 1


if __name__ == "__main__":
    sys.exit(main())
