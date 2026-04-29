#!/usr/bin/env python3
"""
M1 Mac Studio 에이전트 연결 상태 확인 스크립트
"""

import sys
import os
import requests
import json
from datetime import datetime

sys.path.insert(0, 'stock_analyzer')

print("=" * 80)
print("M1 Mac Studio 에이전트 연결 상태 확인")
print(f"시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print("=" * 80)

# 1. 환경 변수 및 설정 확인
print("\n[1] 환경 설정")
print("-" * 40)

mac_studio_url = os.getenv("MAC_STUDIO_URL", "http://localhost:8080")
print(f"  MAC_STUDIO_URL: {mac_studio_url}")

from dual_node_config import (
    LLM_NODES,
    AGENT_LLM_MAPPING,
    is_mac_studio_available,
    get_llm_config,
    performance_monitor
)

# 2. Mac Studio 노드 설정
print("\n[2] Mac Studio 노드 설정")
print("-" * 40)
mac_config = LLM_NODES["mac_studio"]
print(f"  URL: {mac_config['url']}")
print(f"  기본 모델: {mac_config['default_model']}")
print(f"  사용 가능 모델:")
for model_key, model_name in mac_config["models"].items():
    print(f"    - {model_key}: {model_name}")

# 3. Mac Studio를 사용하는 에이전트
print("\n[3] Mac Studio 할당 에이전트")
print("-" * 40)
mac_agents = [
    agent for agent, config in AGENT_LLM_MAPPING.items()
    if config["node"] == "mac_studio"
]
for agent in mac_agents:
    config = AGENT_LLM_MAPPING[agent]
    print(f"  • {agent}")
    print(f"    - 모델: {config['model']}")
    print(f"    - 이유: {config['reason']}")

# 4. 연결 상태 테스트
print("\n[4] 연결 상태 테스트")
print("-" * 40)

# Health check
try:
    print(f"  Health check: {mac_config['url']}/health")
    response = requests.get(f"{mac_config['url']}/health", timeout=3)
    if response.status_code == 200:
        print(f"  ✅ Health check 성공 (status: {response.status_code})")
    else:
        print(f"  ❌ Health check 실패 (status: {response.status_code})")
except requests.exceptions.ConnectionError:
    print(f"  ❌ 연결 실패 - Mac Studio 서버가 실행 중이지 않음")
except requests.exceptions.Timeout:
    print(f"  ❌ 타임아웃 - 응답 시간 초과")
except Exception as e:
    print(f"  ❌ 오류: {e}")

# 5. Ollama API 테스트 (Mac Studio)
print("\n[5] Ollama API 테스트 (Mac Studio)")
print("-" * 40)

try:
    # 모델 목록 조회
    print(f"  모델 목록 조회: {mac_config['url']}/api/tags")
    response = requests.get(f"{mac_config['url']}/api/tags", timeout=5)

    if response.status_code == 200:
        data = response.json()
        models = data.get('models', [])

        if models:
            print(f"  ✅ {len(models)}개 모델 발견:")
            for model in models[:5]:  # 최대 5개만 표시
                name = model.get('name', 'unknown')
                size = model.get('size', 0) / 1024**3  # GB로 변환
                print(f"    - {name} ({size:.1f}GB)")

            # qwen2.5:32b 모델 확인
            model_names = [m.get('name', '') for m in models]
            if any('qwen2.5:32b' in name or 'qwen-32b' in name for name in model_names):
                print(f"  ✅ qwen2.5:32b 모델 확인됨")
            else:
                print(f"  ⚠️ qwen2.5:32b 모델 없음")
        else:
            print(f"  ⚠️ 모델이 설치되지 않음")
    else:
        print(f"  ❌ API 호출 실패 (status: {response.status_code})")

except Exception as e:
    print(f"  ❌ Ollama API 테스트 실패: {e}")

# 6. is_mac_studio_available() 함수 테스트
print("\n[6] 내장 함수 테스트")
print("-" * 40)
if is_mac_studio_available():
    print("  ✅ is_mac_studio_available() = True")
else:
    print("  ❌ is_mac_studio_available() = False")

# 7. RTX 5070 (로컬) 상태 확인
print("\n[7] RTX 5070 (로컬) 상태")
print("-" * 40)
rtx_config = LLM_NODES["rtx_5070"]
try:
    response = requests.get(f"{rtx_config['url']}/api/tags", timeout=3)
    if response.status_code == 200:
        models = response.json().get('models', [])
        print(f"  ✅ RTX 5070 정상 ({len(models)}개 모델)")
        for model in models[:3]:
            print(f"    - {model.get('name', 'unknown')}")
    else:
        print(f"  ❌ RTX 5070 응답 이상")
except Exception as e:
    print(f"  ❌ RTX 5070 연결 실패: {e}")

# 8. 성능 통계 (있는 경우)
print("\n[8] 성능 통계")
print("-" * 40)
summary = performance_monitor.get_summary()
if summary["total_agents"] > 0:
    print(f"  총 에이전트: {summary['total_agents']}")
    print(f"  평균 실행 시간: {summary['avg_execution_time']:.2f}초")

    for agent, metrics in summary["agent_performance"].items():
        print(f"\n  {agent}:")
        print(f"    - 실행 횟수: {metrics['count']}")
        print(f"    - 평균 시간: {metrics['avg_time']:.2f}초")
        print(f"    - 노드 사용: {metrics['node_usage']}")
else:
    print("  통계 데이터 없음")

# 9. 권장사항
print("\n[9] 상태 요약 및 권장사항")
print("-" * 40)

mac_available = is_mac_studio_available()
if mac_available:
    print("  ✅ Mac Studio 정상 작동 중")
    print("  → 고성능 에이전트들이 Mac Studio를 사용합니다")
else:
    print("  ❌ Mac Studio 연결 불가")
    print("  → 모든 에이전트가 RTX 5070으로 폴백됩니다")
    print("\n  해결 방법:")
    print("  1. Mac Studio에서 Ollama 실행 확인:")
    print("     $ ollama serve")
    print("  2. 포트 포워딩 확인 (8080 포트)")
    print("  3. 환경 변수 설정:")
    print("     $ export MAC_STUDIO_URL=http://<mac-studio-ip>:8080")

print("\n" + "=" * 80)
print("점검 완료")
print("=" * 80)