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
        # Mac Studio M1 Max 32GB 통합 메모리 — 32B(q4_K_M, ~19GB)가 안전 한계.
        # 70B(~40GB)는 OOM 으로 로드 불가하므로 라우팅 매핑에서 제외.
        "models": {
            "qwen_32b": "qwen2.5:32b-instruct-q4_K_M",  # 메인 고성능 모델
            "gpt_20b": "gpt-oss:20b",                    # 중형 폴백
            "llama_8b": "llama3.1:8b",                   # 경량 폴백
        },
        "default_model": "qwen_32b",
        "description": "Mac Studio M1 Max 32GB - 고성능 작업"
    }
}

# 에이전트별 LLM 라우팅
# provider: "ollama" | "gemini" | "openai"
#   - "ollama" : node/model 필드로 노드 지정
#   - "gemini" : Gemini API 직접 호출 (node/model 무시)
#   - "openai" : OpenAI API 직접 호출 (node/model 무시)
AGENT_LLM_MAPPING = {
    # ── Gemini 외부 LLM (텍스트 해석·추론 중심) ────────────────
    "Decision Maker": {
        "provider": "gemini",
        "reason": "최종 컨센서스·충돌 해결 — Gemini 고품질 추론"
    },
    "Value Investor": {
        "provider": "gemini",
        "reason": "재무제표·Graham/Buffett 가치 평가 — Gemini 지식 기반"
    },
    "Event Analyst": {
        "provider": "gemini",
        "reason": "뉴스·이벤트·내부자 거래 분류 — Gemini 최신 컨텍스트"
    },
    "Geopolitical Analyst": {
        "provider": "gemini",
        "reason": "지정학·거시경제 복잡 관계 분석 — Gemini 지식 기반"
    },

    # ── Mac Studio Ollama (qwen2.5:32b, 수치·통계 분석) ────────
    "Technical Analyst": {
        "provider": "ollama",
        "node": "mac_studio",
        "model": "qwen_32b",
        "reason": "복잡한 기술 지표 패턴 분석"
    },
    "Quant Analyst": {
        "provider": "ollama",
        "node": "mac_studio",
        "model": "qwen_32b",
        "reason": "통계적 계산 및 확률 분석"
    },

    # ── Mac Studio Ollama (qwen2.5:32b, 수치 계산·ML 해석) ────
    # RTX 5070 GPU 는 Ollama(qwen3:14b) 전용으로 비워 두고,
    # Ollama 추론 작업 전부를 Mac Studio 로 집중.
    "Risk Manager": {
        "provider": "ollama",
        "node": "mac_studio",
        "model": "qwen_32b",
        "reason": "Kelly/Beta 수치 계산 — Mac Studio 우선"
    },
    "ML Specialist": {
        "provider": "ollama",
        "node": "mac_studio",
        "model": "qwen_32b",
        "reason": "ML 예측 해석 정확도 — Mac Studio 우선"
    },
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
        return {
            "provider": "ollama",
            "url": LLM_NODES["rtx_5070"]["url"],
            "model": LLM_NODES["rtx_5070"]["default_model"],
            "node": "rtx_5070"
        }

    provider = mapping.get("provider", "ollama")

    # Gemini / OpenAI 는 Ollama 노드 정보 불필요
    if provider != "ollama":
        return {
            "provider": provider,
            "reason": mapping.get("reason", "")
        }

    node = mapping["node"]
    model_key = mapping["model"]
    node_config = LLM_NODES[node]
    model_name = node_config["models"].get(model_key, node_config["default_model"])

    return {
        "provider": "ollama",
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

    # 폴백 timeout 도 MULTI_AGENT_LLM_TIMEOUT 과 정합 (기본 240s)
    _fallback_timeout = int(os.getenv("MULTI_AGENT_LLM_TIMEOUT", "240"))

    # 고성능 에이전트는 더 많은 시간 할당
    if agent_name in ["Technical Analyst", "Quant Analyst", "Decision Maker"]:
        return {
            "url": rtx_config["url"],
            "model": rtx_config["models"]["qwen_14b"],  # 더 큰 모델 사용
            "node": "rtx_5070",
            "timeout": _fallback_timeout,
            "temperature": 0.3  # 더 정확한 답변
        }

    return {
        "url": rtx_config["url"],
        "model": rtx_config["default_model"],
        "node": "rtx_5070",
        "timeout": _fallback_timeout,
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