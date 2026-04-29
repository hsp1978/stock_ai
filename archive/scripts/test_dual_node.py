#!/usr/bin/env python3
"""
듀얼 노드 LLM 테스트
RTX 5070 + Mac Studio 연동 확인
"""

import os
import sys
import time
import json
import requests
from datetime import datetime

# 프로젝트 경로 설정
sys.path.insert(0, '/home/ubuntu/stock_auto')
sys.path.insert(0, '/home/ubuntu/stock_auto/stock_analyzer')

from dual_node_config import (
    LLM_NODES,
    AGENT_LLM_MAPPING,
    get_llm_config,
    is_mac_studio_available,
    get_fallback_config,
    performance_monitor
)

def test_node_connection():
    """노드 연결 테스트"""
    print("=" * 70)
    print("듀얼 노드 연결 테스트")
    print("=" * 70)

    results = {}

    # 1. RTX 5070 테스트
    print("\n1. RTX 5070 (로컬) 테스트")
    print("-" * 60)
    rtx_config = LLM_NODES["rtx_5070"]

    try:
        response = requests.get(f"{rtx_config['url']}/api/tags", timeout=5)
        if response.status_code == 200:
            models = response.json().get('models', [])
            print(f"✅ RTX 5070 연결 성공")
            print(f"   URL: {rtx_config['url']}")
            print(f"   사용 가능 모델: {len(models)}개")

            # Qwen3:14b 확인
            qwen3_found = any('qwen3:14b' in m.get('name', '') for m in models)
            if qwen3_found:
                print(f"   ✅ Qwen3:14b-q4_K_M 설치됨")
            else:
                print(f"   ⚠️ Qwen3:14b-q4_K_M 미설치")

            results['rtx_5070'] = {'status': 'connected', 'models': len(models)}
        else:
            print(f"❌ RTX 5070 연결 실패 (상태: {response.status_code})")
            results['rtx_5070'] = {'status': 'error', 'code': response.status_code}
    except Exception as e:
        print(f"❌ RTX 5070 연결 오류: {e}")
        results['rtx_5070'] = {'status': 'error', 'message': str(e)}

    # 2. Mac Studio 테스트
    print("\n2. Mac Studio 테스트")
    print("-" * 60)
    mac_config = LLM_NODES["mac_studio"]

    # 환경변수에서 실제 Mac Studio IP 가져오기
    mac_ip = os.getenv('MAC_STUDIO_IP', '192.168.1.100')
    mac_url = f"http://{mac_ip}:8080"

    print(f"   연결 시도 중: {mac_url}")

    try:
        response = requests.get(f"{mac_url}/api/tags", timeout=5)
        if response.status_code == 200:
            models = response.json().get('models', [])
            print(f"✅ Mac Studio 연결 성공")
            print(f"   URL: {mac_url}")
            print(f"   사용 가능 모델: {len(models)}개")

            for model in models[:5]:  # 상위 5개만 표시
                size_gb = model.get('size', 0) / (1024**3)
                print(f"     - {model['name']}: {size_gb:.1f} GB")

            results['mac_studio'] = {'status': 'connected', 'models': len(models)}
        else:
            print(f"⚠️ Mac Studio 응답 오류 (상태: {response.status_code})")
            results['mac_studio'] = {'status': 'error', 'code': response.status_code}
    except requests.exceptions.Timeout:
        print(f"⚠️ Mac Studio 연결 시간 초과")
        print(f"   → Mac Studio가 꺼져있거나 방화벽 설정 확인 필요")
        results['mac_studio'] = {'status': 'timeout'}
    except Exception as e:
        print(f"⚠️ Mac Studio 연결 불가: {e}")
        print(f"   → 폴백 모드로 전환 (모든 작업을 RTX 5070에서 처리)")
        results['mac_studio'] = {'status': 'offline', 'message': str(e)}

    return results

def test_agent_routing():
    """에이전트별 라우팅 테스트"""
    print("\n" + "=" * 70)
    print("에이전트별 노드 할당")
    print("=" * 70)

    for agent_name, mapping in AGENT_LLM_MAPPING.items():
        config = get_llm_config(agent_name)

        print(f"\n{agent_name}:")
        print(f"  할당 노드: {mapping['node']}")
        print(f"  모델: {config['model']}")
        print(f"  이유: {mapping['reason']}")

        # Mac Studio 에이전트인 경우 폴백 확인
        if mapping['node'] == 'mac_studio':
            if not is_mac_studio_available():
                fallback = get_fallback_config(agent_name)
                print(f"  ⚠️ 폴백: RTX 5070 - {fallback['model']}")

def test_performance():
    """성능 테스트"""
    print("\n" + "=" * 70)
    print("노드별 성능 테스트")
    print("=" * 70)

    test_prompt = """당신은 기술적 분석 전문가입니다.
현재 주가가 이동평균선 위에 있고 RSI가 65일 때,
매수/매도 판단을 내려주세요.

JSON 형식으로 답변:
{"signal": "buy/sell", "confidence": 1-10}"""

    # RTX 5070 테스트
    print("\n1. RTX 5070 성능 테스트 (Qwen3:14b)")
    print("-" * 60)

    start = time.time()
    try:
        response = requests.post(
            "http://localhost:11434/api/generate",
            json={
                "model": "qwen3:14b-q4_K_M",
                "prompt": test_prompt,
                "stream": False,
                "options": {"temperature": 0.3, "num_ctx": 8192}
            },
            timeout=30
        )
        elapsed = time.time() - start

        if response.status_code == 200:
            result = response.json().get('response', '')
            print(f"✅ 응답 시간: {elapsed:.2f}초")

            # JSON 파싱 시도
            if '{' in result:
                json_start = result.find('{')
                json_end = result.rfind('}') + 1
                json_str = result[json_start:json_end]
                try:
                    parsed = json.loads(json_str)
                    print(f"   신호: {parsed.get('signal')}")
                    print(f"   신뢰도: {parsed.get('confidence')}/10")
                except:
                    print("   (JSON 파싱 실패)")
        else:
            print(f"❌ 오류: 상태 코드 {response.status_code}")
    except Exception as e:
        print(f"❌ 테스트 실패: {e}")

    # Mac Studio 테스트 (연결된 경우)
    mac_ip = os.getenv('MAC_STUDIO_IP', '192.168.1.100')
    mac_url = f"http://{mac_ip}:8080"

    print(f"\n2. Mac Studio 성능 테스트")
    print("-" * 60)

    try:
        # 먼저 사용 가능한 모델 확인
        response = requests.get(f"{mac_url}/api/tags", timeout=3)
        if response.status_code == 200:
            models = response.json().get('models', [])
            if models:
                # 가장 큰 모델 사용
                model_name = models[0]['name']
                print(f"   테스트 모델: {model_name}")

                start = time.time()
                response = requests.post(
                    f"{mac_url}/api/generate",
                    json={
                        "model": model_name,
                        "prompt": test_prompt,
                        "stream": False,
                        "options": {"temperature": 0.3}
                    },
                    timeout=30
                )
                elapsed = time.time() - start

                if response.status_code == 200:
                    print(f"✅ 응답 시간: {elapsed:.2f}초")
                else:
                    print(f"⚠️ 응답 오류: {response.status_code}")
        else:
            print("⚠️ Mac Studio 오프라인 - 테스트 건너뜀")
    except:
        print("⚠️ Mac Studio 연결 불가 - 폴백 모드")

def generate_config_env():
    """환경 설정 파일 생성"""
    print("\n" + "=" * 70)
    print("환경 설정 파일 생성")
    print("=" * 70)

    env_content = f"""# 듀얼 노드 LLM 설정
# 생성일: {datetime.now().isoformat()}

# Mac Studio IP 주소 (실제 IP로 변경 필요)
MAC_STUDIO_IP=192.168.1.100
MAC_STUDIO_URL=http://192.168.1.100:8080

# 노드별 설정
RTX_5070_URL=http://localhost:11434
RTX_5070_MODEL=qwen3:14b-q4_K_M

# 메모리 최적화
OLLAMA_NUM_PARALLEL=1
OLLAMA_MAX_LOADED_MODELS=1

# 타임아웃 설정
LLM_TIMEOUT_FAST=30
LLM_TIMEOUT_SLOW=120
"""

    with open('/home/ubuntu/stock_auto/dual_node.env', 'w') as f:
        f.write(env_content)

    print("✅ dual_node.env 파일 생성 완료")
    print("   → MAC_STUDIO_IP를 실제 IP로 수정하세요")

def main():
    """메인 테스트 실행"""
    print("\n")
    print("🚀 듀얼 노드 LLM 시스템 테스트")
    print("=" * 70)

    # 1. 연결 테스트
    connection_results = test_node_connection()

    # 2. 라우팅 테스트
    test_agent_routing()

    # 3. 성능 테스트
    test_performance()

    # 4. 설정 파일 생성
    generate_config_env()

    # 5. 최종 권고사항
    print("\n" + "=" * 70)
    print("최종 권고사항")
    print("=" * 70)

    if connection_results.get('mac_studio', {}).get('status') == 'connected':
        print("✅ 듀얼 노드 모드 활성화 가능")
        print("   → 고성능 에이전트는 Mac Studio에서 실행")
        print("   → 경량 에이전트는 RTX 5070에서 실행")
    else:
        print("⚠️ 단일 노드 모드 (RTX 5070만 사용)")
        print("   → Mac Studio 설정 방법:")
        print("     1. Mac Studio에 mac_studio_setup.sh 복사")
        print("     2. chmod +x mac_studio_setup.sh && ./mac_studio_setup.sh")
        print("     3. dual_node.env에서 MAC_STUDIO_IP 수정")
        print("   → 모든 에이전트가 RTX 5070에서 실행됨")
        print("   → Qwen3:14b-q4_K_M 사용으로 품질은 유지")

    # 결과 저장
    test_results = {
        'timestamp': datetime.now().isoformat(),
        'connection': connection_results,
        'rtx_5070_model': 'qwen3:14b-q4_K_M',
        'mac_studio_status': connection_results.get('mac_studio', {}).get('status', 'offline')
    }

    with open('/home/ubuntu/stock_auto/dual_node_test_results.json', 'w', encoding='utf-8') as f:
        json.dump(test_results, f, indent=2, ensure_ascii=False)

    print("\n테스트 결과가 dual_node_test_results.json에 저장되었습니다.")

if __name__ == "__main__":
    main()