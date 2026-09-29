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


def _bool_setting(name: str, default: bool) -> bool:
    raw = _setting(name, "1" if default else "0")
    if isinstance(raw, bool):
        return raw
    return str(raw).strip().lower() not in {"0", "false", "no", "off", ""}


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

    # ── RTX 5070 Ollama (qwen3:14b, 무거운 쪽 2개) ─────────────
    #
    # 2026-09-16: Ollama 4개를 2:2 로 나눈다. 근거는 아래 A/B(정상 노드 실측).
    # 무거운 둘(Technical·ML)을 빠른 노드로 보낸다 — #76 의 2:2 런에서 Mac 큐가
    # 2개로 줄었을 때 Technical 45.5초·ML 63.2초로, 나머지 둘보다 무거웠다.
    #
    # **트레이드오프**: 이 둘은 qwen2.5:32b → qwen3:14b 로 모델이 바뀐다.
    # 속도는 7배지만 파라미터는 절반 이하다.
    #
    # 2026-09-17 측정 — 품질 영향은 **중립이 아니다.** 같은 입력(동일 프롬프트,
    # 지표 16개), 노드별 5회:
    #
    #   Quant Analyst   Mac qwen2.5:32b  neutral 4 / buy 1   평균 신뢰도 5.0
    #                   RTX qwen3:14b    buy 5              평균 신뢰도 6.9
    #   Risk Manager    Mac qwen2.5:32b  neutral 4 / buy 1   평균 신뢰도 5.1
    #                   RTX qwen3:14b    buy 5              평균 신뢰도 6.5
    #
    # 분포가 겹치지 않는다. qwen3:14b 가 **체계적으로 더 낙관적이고 더
    # 확신한다.** 신뢰도 차이는 판정에 직접 닿는다 —
    # `enhanced_decision_maker.STRENGTH_CAP_CONFIDENCE = 5.0` 이라, Mac 은
    # 경계선(5.0~5.1)이고 RTX 는 상한이 풀리는 쪽(6.5~6.9)이다.
    #
    # 어느 쪽이 **맞는지**는 모른다. `signal_outcomes` 를 소스별로 쌓아야 한다.
    # 그때까지 속도를 이유로 더 옮기지 않는다 (§9.2 측정 가능성 > 최적화).
    # 나빠지면 매핑만 되돌리면 된다.
    "Technical Analyst": {
        "provider": "ollama",
        "node": "rtx_5070",
        "model": "qwen3_14b",
        "reason": "무거운 해석 — 빠른 노드로 (2026-09-16 분산). 품질은 관찰 중"
    },
    "ML Specialist": {
        "provider": "ollama",
        "node": "rtx_5070",
        "model": "qwen3_14b",
        "reason": "무거운 해석 — 빠른 노드로 (2026-09-16 분산). 품질은 관찰 중"
    },

    # ── Mac Studio Ollama (qwen2.5:32b, 수치 계산·리스크) ─────
    #
    # 2026-09-15: 이 넷을 2:2 로 나눠 RTX 에 분산해 봤고 **더 느려져서 되돌렸다.**
    #
    #   에이전트          이전(Mac 4개)   RTX 분산 후
    #   Technical         132.3초    →    45.5초   (Mac 부하 감소, 의도대로)
    #   ML Specialist     146.7초    →    63.2초   (동일)
    #   Quant  → RTX       46.8초    →   320.1초   ✗
    #   Risk   → RTX       91.0초    →   279.1초   ✗
    #   ─────────────────────────────────────────
    #   한 종목 총        149.9초    →   322.6초   (2.2배 악화)
    #
    # 2026-09-16 정정: **위 측정은 무효다.** 당시 RTX 는 이미 교착 중이었다
    # (§13.9p). 나는 원인을 "12GB 에 10.8GB 모델이라 여유 1.4GB — 동시 2요청의
    # KV 캐시 부족"으로 적었는데, `ollama serve` 재시작 후 재측정하니 전부 틀렸다:
    #
    #   단독 1요청   128 tok  64.39 tok/s   2.12s
    #   동시 2요청   128 tok  64.2 / 64.41 tok/s  — 요청당 저하 0, 큐잉으로 직렬화
    #   VRAM         9,488 / 12,227 MiB  — 여유 2.7GB (1.4GB 아님)
    #   Mac 대조     qwen2.5:32b  9.63 tok/s  → RTX 가 6.7배 빠르다
    #
    # Quant 320초·Risk 279초는 실효 ~2 tok/s 로, 정상 노드의 값이 아니다. 같은
    # 주석에 "측정 직후 8토큰도 90초 내에 못 끝냈다"고 적어두고도 측정값을 유효한
    # 것으로 읽은 것이 오류다 — **고장난 노드에서 잰 수치로 설계 결정을 내렸다.**
    #
    # 정상 RTX 에서 다시 쟀다 (Gemini 미사용, 실제 에이전트와 같은 호출 조건:
    # think=False, temperature=0.0, num_thread=4, 프롬프트 ~900 tok):
    #
    #   A 현재(Mac 4)   벽시계 94.2초   34.2 / 54.2 / 74.2 / 94.2초
    #                                   ← 20초 간격 = 완전 직렬 큐잉
    #   B 2:2 분산      벽시계 40.3초   Mac 20.4·40.3 / RTX 5.9·8.4 (63 tok/s)
    #   ─────────────────────────────────────────
    #   한 종목 Ollama 구간  2.33배 **개선** (7종목 환산 11.0분 → 4.7분)
    #
    # 이득의 출처는 처리량이 아니라 **큐 길이**다. 두 노드 모두
    # OLLAMA_NUM_PARALLEL=1 로 직렬 처리하므로, 4개를 한 노드에 몰면 마지막
    # 에이전트가 3개분을 대기한다. 나누면 대기가 절반이 된다.
    "Quant Analyst": {
        "provider": "ollama",
        "node": "mac_studio",
        "model": "qwen_32b",
        "reason": "통계적 계산 및 확률 분석"
    },
    "Risk Manager": {
        "provider": "ollama",
        "node": "mac_studio",
        "model": "qwen_32b",
        "reason": "Kelly/Beta 수치 계산 — Mac Studio 우선"
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
    # 도달성과 별개로 **가속기 상태**를 남긴다 (2026-09-14). 아래 주석 참조.
    "runtime": "unknown",
    "cpu_only_models": [],
}
_node_lock = threading.Lock()
_node_semaphores: Dict[str, threading.BoundedSemaphore] = {}
_node_inflight: Dict[str, int] = {}
_node_overloads: Dict[str, int] = {}
_node_failures: Dict[str, int] = {}
_node_cooldown_until: Dict[str, float] = {}
_node_last_error: Dict[str, str | None] = {}


def get_http_session() -> requests.Session:
    """LLM 호출용 공유 HTTP 세션 (연결 재사용으로 포트 고갈 방지)"""
    global _http_session
    if _http_session is None:
        with _session_lock:
            if _http_session is None:
                sess = requests.Session()
                # [수정] ThreadPoolExecutor가 여러 개 실행되며 좀비 스레드가 생길 경우
                # Connection Pool 고갈로 인한 무한 블로킹 방지를 위해 pool_maxsize 대폭 증가
                adapter = HTTPAdapter(pool_connections=20, pool_maxsize=100)
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
            "runtime": "unknown",
            "cpu_only_models": [],
        })


def mac_studio_health_snapshot() -> Dict[str, Any]:
    with _mac_health_lock:
        return dict(_mac_health_cache)


def mac_studio_runtime_status(timeout: float | None = None) -> Dict[str, Any]:
    """Mac Studio Ollama 가 **GPU 로 돌고 있는지** 본다.

    `/api/tags` 200 은 데몬이 응답한다는 뜻일 뿐 가속기와 무관하다. agent-api 쪽은
    이미 같은 검사를 하고 있었는데(`service._ollama_runtime_status`, #15) Mac Studio
    노드에는 옮겨지지 않았다. 그 사이에 실제로 이런 일이 있었다 (2026-09-14 진단):

      2026-09-09 13:50  다른 프로세스가 CPU 를 점유
      2026-09-09 13:51  Ollama 기동 중 "failure during GPU discovery
                        — failed to finish discovery before timeout"
                        → load_tensors: offloaded 0/65 layers to GPU

    Metal 은 정상 인식됐고(`Apple M1 Max, 25557 MiB free`) 레이어를 하나도 올리지
    않았을 뿐이다. 32B 모델이 CPU 에서 돌아 **0.5 tok/s** 가 나왔다 — GPU 기준의
    1/19 다. 그동안 `is_mac_studio_available()` 은 5일 내내 True 를 돌려줬고,
    8개 중 4개 에이전트가 그 노드로 갔다. 모델 적재는 되므로 `/api/ps` 의
    `size_vram` 이 0 인 것으로 잡아낼 수 있다.

    Returns: {"status": gpu|cpu_fallback|idle|unknown, "models": [...], ...}
      idle  — 적재된 모델이 없어 **판정 불가**. '정상'이 아니다
    """
    mac_url = LLM_NODES["mac_studio"]["url"]
    timeout = timeout if timeout is not None else _float_setting(
        "MAC_STUDIO_HEALTH_TIMEOUT", 7.0
    )
    status: Dict[str, Any] = {"status": "unknown", "models": []}
    try:
        response = get_http_session().get(f"{mac_url}/api/ps", timeout=timeout)
        if response.status_code != 200:
            status["error"] = f"HTTP {response.status_code}"
            return status
        models = response.json().get("models") or []
    except Exception as exc:
        status["error"] = str(exc)[:200]
        return status

    cpu_only = []
    for model in models:
        name = model.get("name") or model.get("model") or "?"
        size = int(model.get("size") or 0)
        vram = int(model.get("size_vram") or 0)
        fraction = round(vram / size, 3) if size else None
        if fraction is None or fraction < _float_setting("MAC_STUDIO_MIN_GPU_FRACTION", 0.5):
            cpu_only.append(name)
        status["models"].append({
            "name": name,
            "size_bytes": size,
            "size_vram_bytes": vram,
            "gpu_fraction": fraction,
        })

    if not models:
        status["status"] = "idle"
        return status

    if cpu_only:
        status["status"] = "cpu_fallback"
        status["cpu_only_models"] = cpu_only
        return status

    # 적재 위치가 맞아도 **생성이 죽어 있을 수 있다.**
    # 2026-09-16 실측(RTX): /api/tags 200, gpu_fraction 1.0 인데 /api/generate 는
    # 모델 무관하게 60초 넘게 GPU 0% 였다 (runner 교착). CPU 폴백이 아니므로 위
    # 검사로는 잡히지 않는다. 그래서 1토큰 생성까지 확인한다.
    status["status"] = "gpu"
    generation = probe_node_generation(
        mac_url, models[0].get("name"), timeout=timeout, node="mac_studio"
    )
    status["generation"] = generation
    if generation["status"] in ("stalled", "error"):
        status["status"] = "unusable"
        status["unusable_reason"] = generation.get("detail") or generation["status"]
    return status


def node_is_busy(node: str) -> bool:
    """이 노드가 **우리 요청**을 처리 중인가 (`node_slot` 집계 기준)."""
    return node_load_snapshot().get(node, 0) > 0


def probe_node_generation(
    base_url: str,
    model: str | None,
    timeout: float | None = None,
    node: str | None = None,
) -> Dict[str, Any]:
    """적재된 모델로 **1토큰만** 생성해 본다 — 노드를 실제로 쓸 수 있는지.

    모델이 적재돼 있을 때만 호출한다. 유휴 노드에 보내면 모델 로드(수십 초)를
    유발해 검사가 스스로 부하를 만든다.

    `node` 를 주면 **그 노드가 이미 우리 요청을 처리 중일 때 건너뛴다.** 두
    노드 모두 OLLAMA_NUM_PARALLEL=1 로 직렬 처리하므로, 바쁜 노드에 보낸 프로브는
    큐 뒤에 줄을 서고 타임아웃한다 — 정상 노드가 `stalled` 로 보고된다. Mac 이면
    `is_mac_studio_available()` 이 False 가 되어 **바쁠 때 정확히 라우팅에서
    빠지는** 되먹임이 된다 (2026-09-16 실측: 스캔 중 RTX 가 GPU 98%·250W 로
    일하는데 프로브는 90초 타임아웃).

    처리 중이라는 사실 자체가 1토큰 합성 호출보다 강한 증거다 — 요청이 돌고
    있으면 생성 경로는 살아 있다. 게다가 건너뛰면 프로브가 부하를 더하지 않는다.

    Returns: {"status": ok|stalled|skipped|error, "latency_ms": int|None, ...}
    """
    if not model:
        return {"status": "skipped", "reason": "model_name_unknown", "latency_ms": None}

    if node and node_is_busy(node):
        return {
            "status": "skipped",
            "reason": "node_busy",
            "model": model,
            "latency_ms": None,
            "detail": "우리 요청을 처리 중 — 생성 경로가 살아 있다는 증거이므로 프로브를 건너뜀",
        }

    budget = timeout if timeout is not None else _float_setting(
        "HEALTH_GENERATION_TIMEOUT_SECONDS", 20.0
    )
    started = time.monotonic()
    try:
        response = get_http_session().post(
            f"{base_url.rstrip('/')}/api/generate",
            json={
                "model": model,
                "prompt": "ok",
                "stream": False,
                "options": {"num_predict": 1},
            },
            timeout=budget,
        )
    except requests.exceptions.Timeout:
        return {
            "status": "stalled",
            "model": model,
            "latency_ms": int((time.monotonic() - started) * 1000),
            "detail": f"{budget:g}초 안에 1토큰도 생성하지 못했다 — 적재는 됐으나 생성 불가",
        }
    except Exception as exc:
        return {
            "status": "error",
            "model": model,
            "latency_ms": int((time.monotonic() - started) * 1000),
            "detail": f"{type(exc).__name__}: {exc}"[:160],
        }

    latency_ms = int((time.monotonic() - started) * 1000)
    if response.status_code != 200:
        return {
            "status": "error",
            "model": model,
            "latency_ms": latency_ms,
            "detail": f"HTTP {response.status_code}",
        }
    return {"status": "ok", "model": model, "latency_ms": latency_ms}


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
        reachable = response.status_code == 200

        # 도달한다고 쓸 수 있는 건 아니다. CPU 폴백 중인 노드로 보내면
        # 타임아웃만 쌓인다 — 차라리 RTX 단독이 낫다.
        runtime = {"status": "unknown"}
        require_gpu = _bool_setting("MAC_STUDIO_REQUIRE_GPU", True)
        if reachable:
            runtime = mac_studio_runtime_status(timeout=timeout)
        # 쓸 수 없는 두 가지를 모두 제외한다:
        #   cpu_fallback — GPU 에 안 올라갔다 (2026-09-14, 0.5 tok/s)
        #   unusable     — 올라갔는데 1토큰도 못 만든다 (2026-09-16, runner 교착)
        runtime_status = runtime.get("status")
        degraded = require_gpu and runtime_status in ("cpu_fallback", "unusable")
        available = reachable and not degraded

        with _mac_health_lock:
            if available:
                _mac_health_cache.update({
                    "checked_at": now,
                    "available": True,
                    "failures": 0,
                    "last_error": None,
                    "last_status": response.status_code,
                    "runtime": runtime_status,
                    "cpu_only_models": [],
                })
            elif degraded:
                # 연결 실패가 아니다 — 연속 실패 카운터로 덮지 않는다.
                if runtime_status == "unusable":
                    reason = "생성 불가 — " + str(runtime.get("unusable_reason") or "")
                else:
                    reason = "CPU 폴백 감지 — GPU 미적재: " + ", ".join(
                        runtime.get("cpu_only_models") or []
                    )
                _mac_health_cache.update({
                    "checked_at": now,
                    "available": False,
                    "failures": 0,
                    "last_error": reason[:200],
                    "last_status": response.status_code,
                    "runtime": runtime_status,
                    "cpu_only_models": runtime.get("cpu_only_models") or [],
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


def _node_failure_threshold(node: str) -> int:
    env_name = f"{node.upper()}_FAILURE_THRESHOLD"
    return max(1, _int_setting(env_name, _int_setting("LLM_NODE_FAILURE_THRESHOLD", 2)))


def _node_cooldown_seconds(node: str) -> float:
    env_name = f"{node.upper()}_COOLDOWN_SECONDS"
    return max(0.0, _float_setting(env_name, _float_setting("LLM_NODE_COOLDOWN_SECONDS", 90.0)))


def _get_node_semaphore(node: str) -> threading.BoundedSemaphore:
    with _node_lock:
        sem = _node_semaphores.get(node)
        if sem is None:
            sem = threading.BoundedSemaphore(_node_limit(node))
            _node_semaphores[node] = sem
            _node_inflight.setdefault(node, 0)
            _node_overloads.setdefault(node, 0)
            _node_failures.setdefault(node, 0)
            _node_cooldown_until.setdefault(node, 0.0)
            _node_last_error.setdefault(node, None)
        return sem


def is_node_in_cooldown(node: str) -> bool:
    with _node_lock:
        return time.monotonic() < float(_node_cooldown_until.get(node) or 0.0)


def record_node_failure(node: str | None, exc: Exception) -> None:
    """Record node-level call failure and open a short cooldown after repeats."""
    if not node:
        return
    now = time.monotonic()
    with _node_lock:
        failures = int(_node_failures.get(node) or 0) + 1
        _node_failures[node] = failures
        _node_last_error[node] = str(exc)[:200]
        if failures >= _node_failure_threshold(node):
            _node_cooldown_until[node] = now + _node_cooldown_seconds(node)


def record_node_success(node: str | None) -> None:
    if not node:
        return
    with _node_lock:
        _node_failures[node] = 0
        _node_cooldown_until[node] = 0.0
        _node_last_error[node] = None


def reset_node_cooldowns(node: str | None = None) -> None:
    with _node_lock:
        targets = [node] if node else list(set(LLM_NODES.keys()) | set(_node_failures.keys()))
        for target in targets:
            _node_failures[target] = 0
            _node_cooldown_until[target] = 0.0
            _node_last_error[target] = None


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


def node_capacity_snapshot() -> Dict[str, Dict[str, Any]]:
    with _node_lock:
        nodes = set(LLM_NODES.keys()) | set(_node_inflight.keys()) | set(_node_overloads.keys())
        now = time.monotonic()
        return {
            node: {
                "inflight": int(_node_inflight.get(node, 0)),
                "capacity": int(_node_limit(node)),
                "available_slots": max(0, int(_node_limit(node)) - int(_node_inflight.get(node, 0))),
                "overload_count": int(_node_overloads.get(node, 0)),
                "failure_count": int(_node_failures.get(node, 0)),
                "cooldown_remaining_sec": int(max(0.0, float(_node_cooldown_until.get(node) or 0.0) - now)),
                "last_error": _node_last_error.get(node),
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
