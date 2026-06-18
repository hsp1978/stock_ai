#!/usr/bin/env python3
"""
듀얼 노드 LLM 설정 (Dual Node Configuration)
- RTX 5070: Qwen 14B (경량 에이전트)
- Mac Studio: Qwen 30B/32B (고성능 에이전트)
"""

import os
import threading
import time
from contextlib import contextmanager
from typing import Dict, Any

import requests
from requests.adapters import HTTPAdapter


def _setting(name: str, default: str = "") -> str:
    if name in os.environ:
        return os.environ.get(name, "")
    try:
        from config import settings

        configured = getattr(settings, name, default)
        return str(configured) if configured is not None else default
    except Exception:
        return default


def _int_setting(name: str, default: int) -> int:
    try:
        return int(_setting(name, str(default)))
    except (TypeError, ValueError):
        return default


def _float_setting(name: str, default: float) -> float:
    try:
        return float(_setting(name, str(default)))
    except (TypeError, ValueError):
        return default


# LLM 노드 설정
LLM_NODES = {
    "rtx_5070": {
        "url": _setting("OLLAMA_BASE_URL", "http://localhost:11434"),
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
        "url": _setting("MAC_STUDIO_URL", "http://hsptest-macstudio:8080"),
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
_mac_health_lock = threading.Lock()
_mac_health_cache: Dict[str, Any] = {
    "checked_at": 0.0,
    "available": False,
    "failures": 0,
    "last_error": None,
    "last_status": None,
}
_node_lock = threading.Lock()
_node_semaphores: Dict[str, threading.BoundedSemaphore] = {}
_node_inflight: Dict[str, int] = {}
_node_overloads: Dict[str, int] = {}


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


def reset_mac_studio_health_cache() -> None:
    """테스트/수동 복구용 Mac Studio health cache 초기화."""
    with _mac_health_lock:
        _mac_health_cache.update({
            "checked_at": 0.0,
            "available": False,
            "failures": 0,
            "last_error": None,
            "last_status": None,
        })


def mac_studio_health_snapshot() -> Dict[str, Any]:
    with _mac_health_lock:
        return dict(_mac_health_cache)


def is_mac_studio_available(force_refresh: bool = False) -> bool:
    """Mac Studio 연결 상태 확인. 짧은 TTL 캐시와 연속 실패 기준으로 오진단을 줄인다."""
    mac_url = LLM_NODES["mac_studio"]["url"]
    ttl = _float_setting("MAC_STUDIO_HEALTH_TTL_SECONDS", 10.0)
    timeout = _float_setting("MAC_STUDIO_HEALTH_TIMEOUT", 7.0)
    fail_threshold = max(1, _int_setting("MAC_STUDIO_HEALTH_FAILURE_THRESHOLD", 2))
    now = time.monotonic()

    with _mac_health_lock:
        cache_age = now - float(_mac_health_cache.get("checked_at") or 0.0)
        if not force_refresh and _mac_health_cache["checked_at"] and cache_age < ttl:
            return bool(_mac_health_cache["available"])

    try:
        response = get_http_session().get(f"{mac_url}/api/tags", timeout=timeout)
        available = response.status_code == 200
        with _mac_health_lock:
            if available:
                _mac_health_cache.update({
                    "checked_at": now,
                    "available": True,
                    "failures": 0,
                    "last_error": None,
                    "last_status": response.status_code,
                })
            else:
                failures = int(_mac_health_cache.get("failures") or 0) + 1
                keep_previous = bool(_mac_health_cache.get("available")) and failures < fail_threshold
                _mac_health_cache.update({
                    "checked_at": now,
                    "available": keep_previous,
                    "failures": failures,
                    "last_error": f"HTTP {response.status_code}",
                    "last_status": response.status_code,
                })
            return bool(_mac_health_cache["available"])
    except Exception as exc:
        with _mac_health_lock:
            failures = int(_mac_health_cache.get("failures") or 0) + 1
            keep_previous = bool(_mac_health_cache.get("available")) and failures < fail_threshold
            _mac_health_cache.update({
                "checked_at": now,
                "available": keep_previous,
                "failures": failures,
                "last_error": str(exc)[:200],
                "last_status": None,
            })
            return bool(_mac_health_cache["available"])


def _node_limit(node: str) -> int:
    if node == "mac_studio":
        return max(1, _int_setting("MAC_STUDIO_MAX_INFLIGHT", 4))
    if node == "rtx_5070":
        return max(1, _int_setting("RTX_5070_MAX_INFLIGHT", 2))
    return max(1, _int_setting("LLM_NODE_MAX_INFLIGHT", 2))


def _get_node_semaphore(node: str) -> threading.BoundedSemaphore:
    with _node_lock:
        sem = _node_semaphores.get(node)
        if sem is None:
            sem = threading.BoundedSemaphore(_node_limit(node))
            _node_semaphores[node] = sem
            _node_inflight.setdefault(node, 0)
            _node_overloads.setdefault(node, 0)
        return sem


@contextmanager
def node_slot(node: str, block: bool = False):
    """노드별 동시 LLM 요청 수를 제한한다."""
    sem = _get_node_semaphore(node)
    acquired = sem.acquire(blocking=block)
    if not acquired:
        with _node_lock:
            _node_overloads[node] = _node_overloads.get(node, 0) + 1
        yield False
        return
    with _node_lock:
        _node_inflight[node] = _node_inflight.get(node, 0) + 1
    try:
        yield True
    finally:
        with _node_lock:
            _node_inflight[node] = max(0, _node_inflight.get(node, 0) - 1)
        sem.release()


def node_load_snapshot() -> Dict[str, int]:
    with _node_lock:
        return dict(_node_inflight)


def node_capacity_snapshot() -> Dict[str, Dict[str, int]]:
    with _node_lock:
        nodes = set(LLM_NODES.keys()) | set(_node_inflight.keys()) | set(_node_overloads.keys())
        return {
            node: {
                "inflight": int(_node_inflight.get(node, 0)),
                "capacity": int(_node_limit(node)),
                "available_slots": max(0, int(_node_limit(node)) - int(_node_inflight.get(node, 0))),
                "overload_count": int(_node_overloads.get(node, 0)),
            }
            for node in sorted(nodes)
        }


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
    _fallback_timeout = _int_setting("MULTI_AGENT_LLM_TIMEOUT", 240)

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
