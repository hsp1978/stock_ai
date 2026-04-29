#!/usr/bin/env python3
"""
듀얼 노드 LLM 설정 (Dual Node Configuration)
- RTX 5070: Qwen 14B (경량 에이전트)
- Mac Studio: Qwen 30B/32B (고성능 에이전트)
"""

import os
import threading
from typing import Dict, Any

import requests
from requests.adapters import HTTPAdapter

# LLM 노드 설정
LLM_NODES = {
    "rtx_5070": {
        "url": "http://localhost:11434",
        "models": {
            "qwen3_14b": "qwen3:14b-q4_K_M",  # 최신 Qwen3 - 2x 효율
            "qwen_14b": "qwen2.5:14b-instruct-q4_K_M",  # 폴백용
            "llama_8b": "llama3.1:8b",  # 속도 우선 폴백
        },
        "default_model": "qwen3_14b",
        "description": "RTX 5070 - ML/이벤트 분석"
    },
    "mac_studio": {
        # MAC_STUDIO_URL 미설정 시 Tailscale hostname으로 시도 (실패하면 폴백 로직이 RTX 5070으로 라우팅)
        "url": os.getenv("MAC_STUDIO_URL", "http://hsptest-macstudio:8080"),
        "models": {
            "qwen_32b": "qwen2.5:32b",  # 실제 설치된 모델
            "llama_70b": "llama3:70b",  # 대형 모델
            "gpt_20b": "gpt-oss:20b",  # 중형 모델
        },
        "default_model": "qwen_32b",
        "description": "Mac Studio M1 Max - 고성능 작업"
    }
}

# 에이전트별 LLM 라우팅
AGENT_LLM_MAPPING = {
    # 고성능 필요 (Mac Studio)
    "Technical Analyst": {
        "node": "mac_studio",
        "model": "qwen_32b",
        "reason": "복잡한 기술 지표 패턴 분석"
    },
    "Quant Analyst": {
        "node": "mac_studio",
        "model": "qwen_32b",
        "reason": "통계적 계산 및 확률 분석"
    },
    "Decision Maker": {
        "node": "mac_studio",
        "model": "llama_70b",  # 최고 성능 모델
        "reason": "최종 컨센서스 및 충돌 해결"
    },

    # RTX 5070 - Qwen 14B (품질 우선)
    "Risk Manager": {
        "node": "rtx_5070",
        "model": "llama_8b",  # 단순 계산이므로 속도 우선
        "reason": "단순 Kelly/Beta 계산"
    },
    "ML Specialist": {
        "node": "rtx_5070",
        "model": "qwen3_14b",  # Qwen3 최신 - 품질 9/10
        "reason": "ML 해석 정확도 중요 (14초 허용)"
    },
    "Event Analyst": {
        "node": "rtx_5070",
        "model": "qwen3_14b",  # Qwen3 - 내부자 거래 정확도
        "reason": "이벤트 분류 및 내부자 거래 체크"
    },
    "Geopolitical Analyst": {
        "node": "mac_studio",
        "model": "qwen_32b",  # 거시경제/지정학 분석에 고성능 모델 필요
        "reason": "복잡한 거시경제 및 지정학적 관계 분석"
    },
    "Value Investor": {
        "node": "rtx_5070",
        "model": "qwen3_14b",  # 재무 지표 해석
        "reason": "재무제표 분석 및 밸류에이션 평가"
    }
}

def get_llm_config(agent_name: str) -> Dict[str, Any]:
    """
    에이전트별 LLM 설정 반환

    Args:
        agent_name: 에이전트 이름

    Returns:
        LLM 설정 딕셔너리
    """
    mapping = AGENT_LLM_MAPPING.get(agent_name)
    if not mapping:
        # 기본값: RTX 5070
        return {
            "url": LLM_NODES["rtx_5070"]["url"],
            "model": LLM_NODES["rtx_5070"]["default_model"],
            "node": "rtx_5070"
        }

    node = mapping["node"]
    model_key = mapping["model"]

    node_config = LLM_NODES[node]
    model_name = node_config["models"].get(model_key, node_config["default_model"])

    return {
        "url": node_config["url"],
        "model": model_name,
        "node": node,
        "reason": mapping.get("reason", "")
    }

_session_lock = threading.Lock()
_http_session: "requests.Session | None" = None


def get_http_session() -> requests.Session:
    """LLM 호출용 공유 HTTP 세션 (연결 재사용으로 포트 고갈 방지)"""
    global _http_session
    if _http_session is None:
        with _session_lock:
            if _http_session is None:
                sess = requests.Session()
                adapter = HTTPAdapter(pool_connections=10, pool_maxsize=20)
                sess.mount("http://", adapter)
                sess.mount("https://", adapter)
                _http_session = sess
    return _http_session


def is_mac_studio_available() -> bool:
    """Mac Studio 연결 상태 확인"""
    mac_url = LLM_NODES["mac_studio"]["url"]

    try:
        response = get_http_session().get(f"{mac_url}/api/tags", timeout=2)
        return response.status_code == 200
    except Exception:
        return False

def get_fallback_config(agent_name: str) -> Dict[str, Any]:
    """
    Mac Studio 장애 시 폴백 설정

    Args:
        agent_name: 에이전트 이름

    Returns:
        폴백 LLM 설정
    """
    # 모든 에이전트를 RTX 5070으로 폴백
    rtx_config = LLM_NODES["rtx_5070"]

    # 고성능 에이전트는 더 많은 시간 할당
    if agent_name in ["Technical Analyst", "Quant Analyst", "Decision Maker"]:
        return {
            "url": rtx_config["url"],
            "model": rtx_config["models"]["qwen_14b"],  # 더 큰 모델 사용
            "node": "rtx_5070",
            "timeout": 120,  # 2배 타임아웃
            "temperature": 0.3  # 더 정확한 답변
        }

    return {
        "url": rtx_config["url"],
        "model": rtx_config["default_model"],
        "node": "rtx_5070",
        "timeout": 60,
        "temperature": 0.5
    }

# 성능 모니터링
class PerformanceMonitor:
    """에이전트별 성능 추적 (스레드 안전)"""

    def __init__(self):
        self.metrics: Dict[str, Any] = {}
        self._lock = threading.Lock()

    def record(self, agent_name: str, execution_time: float, node: str):
        """실행 시간 기록"""
        with self._lock:
            if agent_name not in self.metrics:
                self.metrics[agent_name] = {
                    "count": 0,
                    "total_time": 0,
                    "avg_time": 0,
                    "node_usage": {}
                }

            self.metrics[agent_name]["count"] += 1
            self.metrics[agent_name]["total_time"] += execution_time
            self.metrics[agent_name]["avg_time"] = (
                self.metrics[agent_name]["total_time"] /
                self.metrics[agent_name]["count"]
            )

            # 노드별 사용 횟수
            if node not in self.metrics[agent_name]["node_usage"]:
                self.metrics[agent_name]["node_usage"][node] = 0
            self.metrics[agent_name]["node_usage"][node] += 1

    def get_summary(self) -> Dict[str, Any]:
        """성능 요약"""
        with self._lock:
            # 얕은 복사로 스냅샷 반환
            metrics_snapshot = {k: dict(v) for k, v in self.metrics.items()}
        return {
            "agent_performance": metrics_snapshot,
            "total_agents": len(metrics_snapshot),
            "avg_execution_time": sum(
                m["avg_time"] for m in metrics_snapshot.values()
            ) / len(metrics_snapshot) if metrics_snapshot else 0
        }

# 전역 성능 모니터
performance_monitor = PerformanceMonitor()

if __name__ == "__main__":
    # 설정 테스트
    print("=== 듀얼 노드 LLM 설정 ===\n")

    for agent_name in AGENT_LLM_MAPPING.keys():
        config = get_llm_config(agent_name)
        print(f"{agent_name}:")
        print(f"  노드: {config['node']}")
        print(f"  모델: {config['model']}")
        print(f"  URL: {config['url']}")
        print(f"  이유: {config.get('reason', 'N/A')}")
        print()

    # Mac Studio 연결 확인
    if is_mac_studio_available():
        print("✅ Mac Studio 연결 성공")
    else:
        print("⚠️ Mac Studio 연결 실패 - 폴백 모드 사용")