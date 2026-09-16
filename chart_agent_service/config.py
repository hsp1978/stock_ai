"""
차트 분석 에이전트 서비스 설정 (Pydantic Settings 기반).

기동 시점에 .env를 검증한다 — 잘못된 타입/리터럴이면 즉시 ValidationError.
기존 모듈-레벨 상수 (`OLLAMA_BASE_URL`, `BUY_THRESHOLD`, ...) 인터페이스는 그대로 유지.
"""
import os
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from logging_setup import get_logger

logger = get_logger("stock_auto.config")


_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_ROOT_ENV = _PROJECT_ROOT / ".env"


def find_duplicate_env_keys(path: Path) -> list[str]:
    """.env에 두 번 이상 선언된 키 목록.

    dotenv는 뒤에 온 선언을 채택한다. 파일을 위에서 읽은 사람과 실효값이 갈리고,
    그 차이는 조용하다 — `DATA_SOURCE`가 `yfinance` → `toss`로 두 번 선언돼 있어
    문서·주석은 yfinance인데 시스템은 toss로 돌던 사례가 있다 (2026-09-10).

    값은 절대 반환·출력하지 않는다 (키 이름만).
    """
    if not path.exists():
        return []
    seen: dict[str, int] = {}
    try:
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key = line.split("=", 1)[0].strip()
            if key:
                seen[key] = seen.get(key, 0) + 1
    except OSError:
        return []
    return sorted(k for k, n in seen.items() if n > 1)


_DUPLICATE_ENV_KEYS = find_duplicate_env_keys(_ROOT_ENV)
if _DUPLICATE_ENV_KEYS:
    logger.warning(
        "[config] 경고 — .env에 중복 선언된 키가 있습니다 (뒤 선언이 실효값): "
        + ", ".join(_DUPLICATE_ENV_KEYS)
    )


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_ROOT_ENV),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_MODEL: str = "qwen3:14b-q4_K_M"
    OLLAMA_NUM_PARALLEL: int = 3
    # 종합 판단 프롬프트는 실측 4,700~5,000 토큰인데 Ollama 기본 컨텍스트는
    # 4,096이라 조용히 잘려나갔다(2026-07-29 하루에만 978건). keep=4 규칙상
    # 앞쪽 도구 분석 결과가 버려지고 뒤쪽 지시문만 남아 품질이 직접 훼손된다.
    OLLAMA_NUM_CTX: int = Field(default=8192, ge=2048, le=131072)
    # 기본 keep_alive 5분이면 30분 주기 스캔마다 모델을 내렸다 다시 올린다.
    # 재로드마다 GPU 적재 판정을 새로 하므로 드라이버 상태에 취약해진다.
    OLLAMA_KEEP_ALIVE: str = "1h"
    OPENAI_API_KEY: str = ""
    GEMINI_API_KEY: str = ""
    # gemini-2.0-flash 는 2026-09-15 확인 시 **404 로 폐기**됐다
    # ("no longer available ... use models/gemini-3.6-flash").
    # 무료 등급 쿼터는 모델당 하루 20회이고, Gemini 에이전트 4개 × 7종목 =
    # 배치 1회 28회라 한 모델로는 매일 끊긴다. FALLBACK 은 쿼터가 따로
    # 계산되는 다른 모델이다 (llm/router.py 의 agent-llm-primary-alt).
    GEMINI_MODEL: str = "gemini-3.6-flash"
    GEMINI_FALLBACK_MODEL: str = "gemini-3.5-flash"
    GOOGLE_API_KEY: str = ""
    DEFAULT_LLM_PROVIDER: Literal["ollama", "gemini", "openai"] = "ollama"

    MULTI_AGENT_MAX_WORKERS: int = Field(default=2, ge=1, le=16)
    MULTI_AGENT_TIMEOUT: int = Field(default=300, ge=30)
    MULTI_AGENT_LLM_TIMEOUT: int = Field(default=240, ge=30)
    GEMINI_LLM_TIMEOUT: int = Field(default=30, ge=1, le=120)
    ANALYSIS_AUX_FETCH_TIMEOUT: int = Field(default=20, ge=1, le=300)
    GPU_MONITOR_INTERVAL_SECONDS: float = Field(default=7.0, ge=1)
    GPU_THROTTLE_MEMORY_MB: int = Field(default=11000, ge=0)

    MAC_STUDIO_IP: str = "hsptest-macstudio"
    MAC_STUDIO_URL: str = "http://hsptest-macstudio:8080"
    MAC_STUDIO_HEALTH_TTL_SECONDS: float = Field(default=10.0, ge=0)
    MAC_STUDIO_HEALTH_TIMEOUT: float = Field(default=7.0, ge=0.1, le=60)
    MAC_STUDIO_HEALTH_FAILURE_THRESHOLD: int = Field(default=2, ge=1, le=20)
    MAC_STUDIO_MAX_INFLIGHT: int = Field(default=4, ge=1, le=32)
    # 도달성만으로 노드를 '가용'이라 부르지 않는다. /api/ps 의 size_vram 이 0 이면
    # CPU 폴백이고, 32B 모델 기준 GPU 대비 1/19 속도다 (2026-09-14 실측 0.5 vs 9.4 tok/s).
    # 그 상태로 4개 에이전트를 보내면 타임아웃만 쌓인다 — 차라리 RTX 단독이 낫다.
    MAC_STUDIO_REQUIRE_GPU: bool = True
    MAC_STUDIO_MIN_GPU_FRACTION: float = Field(default=0.5, ge=0.0, le=1.0)
    # ── FastAPI 실행 특성 ─────────────────────────────────────────
    # 핸들러 86개가 전부 sync(`def`) 라 anyio 스레드풀에서 돈다. 기본 한도는 40이고,
    # 느린 요청이 그만큼 몰리면 **모든 엔드포인트가 슬롯을 기다린다** — 2026-09-15
    # 측정: 동시 45개에서 /health 가 30ms → 7.33초 (컨테이너 헬스체크 timeout 2초).
    # 핸들러는 I/O 대기가 대부분이라 스레드를 늘리는 비용은 낮다.
    API_THREAD_LIMIT: int = Field(default=80, ge=8, le=512)
    # /health 가 읽는 프로브 스냅샷 갱신 주기(초). 핸들러는 네트워크를 타지 않는다.
    HEALTH_PROBE_INTERVAL_SECONDS: int = Field(default=15, ge=1, le=300)
    # 노드가 **실제로 생성할 수 있는지** 확인할 때 쓰는 예산(초). 적재된 모델로
    # 1토큰만 만들어 본다. 적재 위치(`size_vram>0`)만 보면 생성이 죽은 노드를
    # 정상으로 읽는다 — 2026-09-16 실측: RTX 가 gpu_fraction 1.0 인데
    # /api/generate 는 모델 무관하게 60초 넘게 GPU 0% 였다 (runner 교착).
    # 너무 짧으면 로드 직후 정상 노드를 unusable 로 오판하므로 여유를 둔다.
    HEALTH_GENERATION_TIMEOUT_SECONDS: float = Field(default=20.0, ge=1.0, le=120.0)
    RTX_5070_MAX_INFLIGHT: int = Field(default=2, ge=1, le=32)
    LLM_NODE_MAX_INFLIGHT: int = Field(default=2, ge=1, le=32)
    LLM_NODE_FAILURE_THRESHOLD: int = Field(default=2, ge=1, le=20)
    LLM_NODE_COOLDOWN_SECONDS: float = Field(default=90.0, ge=0, le=3600)

    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_CHAT_ID: str = ""

    DART_API_KEY: str = ""
    FRED_API_KEY: str = ""
    FMP_API_KEY: str = ""
    FINNHUB_API_KEY: str = ""
    ALPHAVANTAGE_API_KEY: str = ""

    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8100
    AGENT_API_HOST: str = "localhost"
    AGENT_API_PORT: int = 8100
    AGENT_API_URL: str = ""

    SCAN_INTERVAL_MINUTES: int = Field(default=30, ge=1)
    SCAN_PARALLEL_WORKERS: int = Field(default=3, ge=1, le=16)
    SERVICE_SCHEDULER_ENABLED: bool = True
    # ── 스케줄 시각은 모두 **UTC** 다 ──────────────────────────────
    # 컨테이너에 TZ 를 주지 않으므로 APScheduler 도 Etc/UTC 로 돈다. KST 로 읽으면
    # 9시간 어긋난다 — 2026-09-15 확인: 주석은 "서버 로컬 시간 기준"이라고 적혀
    # 있었지만 screener_batch(16:30)가 실제로는 KST 01:30(다음날)에 돌아, 9/13
    # 장 마감 표본이 9/14 날짜로 적립되고 있었다 (ticker_day·horizon 하루 밀림).
    #
    # TZ=Asia/Seoul 로 바꾸지 않는 이유: datetime.now() 가 KST naive 를 뱉게 되고
    # DB 에 이미 쌓인 UTC aware 타임스탬프와 섞인다. horizon 계산이 조용히 틀어지는
    # 쪽이 시각 환산보다 훨씬 위험하다 (CLAUDE.md §5.5 "내부 저장은 UTC aware").
    #
    # 값을 바꿀 때는 KST 의도에서 9를 빼라.  KST 17:30 → UTC 08:30
    SIGNAL_VALIDATION_HOUR: int = Field(default=14, ge=0, le=23)
    SIGNAL_VALIDATION_MINUTE: int = Field(default=0, ge=0, le=59)
    CORPORATE_ACTION_CHECK_HOUR: int = Field(default=15, ge=0, le=23)
    CORPORATE_ACTION_CHECK_MINUTE: int = Field(default=5, ge=0, le=59)
    DATA_HEALTH_CHECK_MINUTES: int = Field(default=60, ge=5)
    DATA_HEALTH_ALERT_STALE_HOURS: float = Field(default=24.0, ge=0)
    # 데이터 신선도 점검 대상 범위. 워치리스트·보유 포지션은 항상 포함하고,
    # 과거 1회성 분석 종목은 이 일수 안에 분석된 것만 본다. 종전에는 프로세스가
    # 기억하는 모든 종목을 봐서, 워치리스트에서 빠진 지 한 달 넘은 종목 15건이
    # 영구 stale 로 남아 **경보가 항상 켜져 있었다** (2026-09-14).
    DATA_HEALTH_RECENT_ANALYSIS_DAYS: int = Field(default=3, ge=0)
    # 보유 포지션 시가평가 주기. 손절·익절·트레일링·시간청산은 전부
    # `update_position_prices()` 안에서만 평가되므로, 이 주기가 곧 **청산 규칙이
    # 검토되는 주기**다. 2026-09-14 이전에는 스케줄 등록 자체가 없어 수동 버튼을
    # 누를 때만 돌았다 (실측: 144일간 미평가).
    POSITION_MARK_INTERVAL_MINUTES: int = Field(default=30, ge=1)
    # 산출물 보존 — output/ 는 2026-09-14 기준 JSON 70,771개 / 1.58 GB 였고
    # 하루 361개씩 늘고 있었다. 정리 주체가 없었다 (crontab 비어 있음).
    # JSON 은 쓰기 전용이라(json_path 를 다시 여는 코드가 없다) 짧게 잡아도
    # 기능에 영향이 없지만, 사후 감사 여지를 두고 기본 30일로 둔다.
    # 차트 PNG 는 화면이 읽으므로 현재 참조 중인 것은 나이와 무관하게 남는다.
    OUTPUT_RETENTION_ENABLED: bool = True
    OUTPUT_JSON_RETENTION_DAYS: int = Field(default=30, ge=1)
    OUTPUT_CHART_RETENTION_DAYS: int = Field(default=30, ge=1)
    OUTPUT_RETENTION_HOUR: int = Field(default=18, ge=0, le=23)
    OUTPUT_RETENTION_MINUTE: int = Field(default=30, ge=0, le=59)
    # 상태 백업 — 단일 노드 SPOF 대비. 잃으면 재생성 불가한 것만 담는다
    # (scan_log/signal_outcomes, 페이퍼 상태, 워치리스트). 분석 JSON·차트는 제외.
    # 기본 경로는 리포지토리 밖이어야 한다 — 같은 디스크라도 실수로 커밋되지 않게.
    STATE_BACKUP_ENABLED: bool = True
    STATE_BACKUP_DIR: str = "/home/ubuntu/stock_auto_backups"
    STATE_BACKUP_KEEP: int = Field(default=7, ge=1)
    STATE_BACKUP_HOUR: int = Field(default=19, ge=0, le=23)
    STATE_BACKUP_MINUTE: int = Field(default=0, ge=0, le=59)
    # 오프사이트 복제 — 백업이 같은 디스크에만 있으면 SPOF 를 못 벗어난다.
    # **목적지는 코드가 정하지 않는다.** 비어 있으면 아무 데도 보내지 않고
    # 'disabled' 로 보고한다 — 설정 안 됨을 성공으로 덮지 않기 위해서다.
    #   /mnt/backup/stock_auto        로컬·마운트 경로
    #   user@host:/path/stock_auto    rsync over SSH (키 인증)
    OFFSITE_BACKUP_DEST: str = ""
    OFFSITE_BACKUP_TIMEOUT_SEC: int = Field(default=900, ge=30)
    OPS_ALERT_DEDUPE_MINUTES: int = Field(default=60, ge=1)
    # 일일 멀티에이전트(V2) 배치 — signal_outcomes 표본 자동 축적용.
    # 시각은 **UTC** (위 주석 참조). 기본 08:30 UTC = 17:30 KST (KRX 마감 15:30 이후).
    # 일일 스크리너 — 표본 적립원. 워치리스트 7종목만으로는 독립 블록이 모이지
    # 않아(2026-09-12 진단), KOSPI+KOSDAQ 스크리너 결과를 매일 표본으로 쌓는다.
    # KRX 마감(15:30) 이후, 멀티에이전트 배치(17:30) 앞에 둔다.
    SCREENER_BATCH_ENABLED: bool = True
    SCREENER_BATCH_HOUR: int = Field(default=7, ge=0, le=23)
    SCREENER_BATCH_MINUTE: int = Field(default=30, ge=0, le=59)

    MULTI_AGENT_BATCH_ENABLED: bool = True
    MULTI_AGENT_BATCH_HOUR: int = Field(default=8, ge=0, le=23)
    MULTI_AGENT_BATCH_MINUTE: int = Field(default=30, ge=0, le=59)

    WATCHLIST: str = ""

    # ── 신호 사후 평가 큐 ─────────────────────────────────────────────
    # days_back 45 + limit 500 + issued_at DESC 조합이 백로그를 영구 아사시켰다:
    # 하루 100건 이상 적립되는 규모에서 매 런이 최신 500건(전부 미도래)만 집어
    # 4,201건이 대기하고 08-06 이후 평가가 0건이었다 (2026-09-10 진단).
    # 30일 horizon이 도래한 뒤에도 여유를 갖도록 창을 넓게 둔다.
    SIGNAL_EVAL_DAYS_BACK: int = Field(default=90, ge=31)
    SIGNAL_EVAL_BATCH_LIMIT: int = Field(default=2000, ge=1)
    # 잔량이 이 값을 넘으면 ops 알림 — '완료'로 보고되는 무동작 런을 드러낸다.
    SIGNAL_EVAL_BACKLOG_ALERT: int = Field(default=500, ge=0)

    # 신호 판정 임계값 — composite score는 '방향성 도구 평균' 스케일.
    # 개별 도구 점수는 [-6, +8] 범위지만 24개를 평균하면 분산이 상쇄돼
    # 실측 [-1.00, +2.04] (p10 -0.19 / p50 +0.41 / p90 +1.14, 26,041 스캔,
    # 2026-06-20~07-30)에 머문다. 과거 ±2.0은 도구 점수 '합계' 스케일 기준이라
    # BUY는 40일간 1건, SELL은 관측 최솟값(-1.0) 밖이라 도달 불가였다 (2026-07-30 진단).
    SIGNAL_BUY_THRESHOLD: float = 1.3
    SIGNAL_SELL_THRESHOLD: float = -0.5

    # 알림 임계값 — 신호 판정보다 느슨하게 잡아 신호 판정이 binding이 되게 한다.
    # (알림이 더 엄격하면 BUY/SELL로 판정된 신호가 통보 없이 사라진다.)
    BUY_THRESHOLD: float = 1.2
    SELL_THRESHOLD: float = -0.4
    MIN_CONFIDENCE: float = 5.0

    TRADING_STYLE: Literal["scalping", "swing", "longterm"] = "swing"

    ACCOUNT_SIZE: float = Field(default=100000, gt=0)
    # 한국(KRW) 종목용 계좌 규모 — ACCOUNT_SIZE(USD 스케일)를 KRW 종목에 그대로 쓰면
    # 리스크 예산이 ~1,000원이 되어 고가 종목 백테스트 수량이 항상 0이 된다 (2026-07 진단).
    ACCOUNT_SIZE_KRW: float = Field(default=100_000_000, gt=0)
    RISK_PER_TRADE_PCT: float = Field(default=1.0, ge=0, le=100)
    MAX_POSITION_PCT: float = Field(default=20.0, ge=0, le=100)
    TAKE_PROFIT_RR_RATIO: float = Field(default=2.0, gt=0)
    COOLING_OFF_DAYS: int = Field(default=3, ge=0)

    RSI_OVERSOLD: int = Field(default=30, ge=0, le=100)
    RSI_OVERBOUGHT: int = Field(default=70, ge=0, le=100)

    POSITION_TRANCHE_1_PCT: float = 40
    POSITION_TRANCHE_2_PCT: float = 30
    POSITION_TRANCHE_3_PCT: float = 30

    DEFAULT_TEST_TICKER: str = "SPY"
    DEFAULT_SCAN_LIMIT: int = Field(default=30, ge=1)

    TRADING_MODE: Literal["paper", "dry_run", "approval", "live"] = "paper"
    BROKER_NAME: Literal["", "alpaca", "kis", "toss"] = ""
    APPROVAL_EXEC_MODE: Literal["paper", "dry_run", "live"] = "paper"
    DAILY_ORDER_LIMIT_USD: float = Field(default=1000, ge=0)
    DAILY_ORDER_LIMIT_KRW: float = Field(default=1000000, ge=0)
    SINGLE_ORDER_LIMIT_USD: float = Field(default=200, ge=0)
    SINGLE_ORDER_LIMIT_KRW: float = Field(default=200000, ge=0)
    APPROVAL_TTL_MINUTES: int = Field(default=30, ge=1)
    ENFORCE_MARKET_HOURS: bool = False

    TRADING_COMMISSION_PCT_KR: float = Field(default=0.015, ge=0)
    TRADING_COMMISSION_PCT_US: float = Field(default=0.0, ge=0)
    TRADING_SLIPPAGE_PCT: float = Field(default=0.05, ge=0)
    TRADING_SELL_TAX_PCT_KR: float = Field(default=0.18, ge=0)

    ANNUAL_RISK_FREE_RATE: float = Field(default=0.0, ge=0)

    ALPACA_API_KEY: str = ""
    ALPACA_SECRET_KEY: str = ""
    ALPACA_BASE_URL: str = "https://paper-api.alpaca.markets"
    ALPACA_DATA_URL: str = "https://data.alpaca.markets"
    ALPACA_DATA_FEED: Literal["iex", "sip"] = "iex"

    DATA_SOURCE: Literal["yfinance", "alpaca", "polygon", "kis", "toss"] = "yfinance"

    # ── 토스증권 Open API (국내+미국, OAuth2 Client Credentials) ──────
    # 발급: https://corp.tossinvest.com/ko/open-api → developers.tossinvest.com
    # 모의투자(Sandbox) 도메인 미정의 → TOSS_PAPER 토글만 제공(추후 대응).
    TOSS_APP_KEY: str = ""
    TOSS_APP_SECRET: str = ""
    TOSS_ACCOUNT_NO: str = ""          # 계좌번호(문자열) — accountSeq는 자동 식별
    TOSS_BASE_URL: str = "https://openapi.tossinvest.com"
    TOSS_PAPER: bool = True

    # ── Step 11: 시장 캘린더 ──────────────────────────────────────────
    DEFAULT_MARKET_KR: str = "KRX"
    DEFAULT_MARKET_US: str = "NYSE"

    # ── Step 10: 백테스트 무위험 수익률 / 거래비용 분리 ────────────────
    ANNUAL_RISK_FREE_RATE_KR: float = Field(default=3.5, ge=0)   # KOFR 기준
    ANNUAL_RISK_FREE_RATE_US: float = Field(default=4.5, ge=0)   # 3M T-Bill 기준
    KRX_TRADING_TAX_PCT: float = Field(default=0.20, ge=0)       # 2026 거래세

    # ── OHLCV 캐시 TTL (Step 3) ────────────────────────────────────
    OHLCV_TTL_EOD_HOURS: float = Field(default=24.0, ge=0)
    OHLCV_TTL_INTRADAY_MINUTES: int = Field(default=5, ge=1)
    OHLCV_RETRY_COUNT: int = Field(default=3, ge=1, le=10)
    YFINANCE_TIMEOUT: int = Field(default=8, ge=1, le=60)
    FUNDAMENTAL_TTL_HOURS: float = Field(default=12.0, ge=0)
    # 뉴스 캐시의 유일한 정기 writer는 일 1회 multi_agent_batch다. TTL 30분은
    # 배치 직후 30분만 fresh이고 나머지 23.5시간은 항상 stale로 잡혀 health
    # 리포트가 상시 빨간불이었다. EOD 1일 1회 분석 주기에 맞춰 24시간으로 정렬.
    NEWS_TTL_MINUTES: int = Field(default=1440, ge=1)

    # ── 뉴스 감성 분석 예산 (LLM 폴백 시 무한 대기 방지) ──────────────
    # Gemini 쿼터 소진 등으로 Ollama 폴백이 발생하면 호출당 200s+가 걸린다.
    # 기사 15건 순차 처리 시 ~50분이 소요되어 /news 엔드포인트가 사실상
    # 무응답이 되므로, 전체 예산·동시성·분석 건수로 상한을 건다.
    NEWS_SENTIMENT_BUDGET_SEC: float = Field(default=90.0, ge=1.0, le=600.0)
    NEWS_SENTIMENT_MAX_ARTICLES: int = Field(default=8, ge=1, le=50)
    NEWS_SENTIMENT_WORKERS: int = Field(default=4, ge=1, le=16)

    # ── GlobalKillSwitch 임계값 ─────────────────────────────────────
    DAILY_LOSS_LIMIT_ALERT_PCT: float = Field(default=2.0, ge=0)
    DAILY_LOSS_LIMIT_HARD_PCT: float = Field(default=3.0, ge=0)
    WEEKLY_DRAWDOWN_LIMIT_PCT: float = Field(default=5.0, ge=0)
    TRAILING_PEAK_DD_PCT: float = Field(default=10.0, ge=0)
    CONSECUTIVE_LOSS_COUNT: int = Field(default=5, ge=1)
    VIX_CAP: float = Field(default=30.0, ge=0)
    VIX_SPIKE_PCT: float = Field(default=20.0, ge=0)
    DATA_STALENESS_HALT_HOURS: float = Field(default=6.0, ge=0)
    COOL_DOWN_HOURS: int = Field(default=24, ge=1)


settings = Settings()


# ── 호환성: 기존 module-level 상수 그대로 export ────────────────────
OLLAMA_BASE_URL = settings.OLLAMA_BASE_URL
OLLAMA_MODEL = settings.OLLAMA_MODEL
OLLAMA_NUM_PARALLEL = settings.OLLAMA_NUM_PARALLEL
OLLAMA_NUM_CTX = settings.OLLAMA_NUM_CTX
OLLAMA_KEEP_ALIVE = settings.OLLAMA_KEEP_ALIVE
OPENAI_API_KEY = settings.OPENAI_API_KEY
GEMINI_API_KEY = settings.GEMINI_API_KEY
GEMINI_MODEL = settings.GEMINI_MODEL
GEMINI_FALLBACK_MODEL = settings.GEMINI_FALLBACK_MODEL
TELEGRAM_BOT_TOKEN = settings.TELEGRAM_BOT_TOKEN
TELEGRAM_CHAT_ID = settings.TELEGRAM_CHAT_ID
API_HOST = settings.API_HOST
API_PORT = settings.API_PORT
SCAN_INTERVAL_MINUTES = settings.SCAN_INTERVAL_MINUTES
SERVICE_SCHEDULER_ENABLED = settings.SERVICE_SCHEDULER_ENABLED
SIGNAL_VALIDATION_HOUR = settings.SIGNAL_VALIDATION_HOUR
SIGNAL_VALIDATION_MINUTE = settings.SIGNAL_VALIDATION_MINUTE
CORPORATE_ACTION_CHECK_HOUR = settings.CORPORATE_ACTION_CHECK_HOUR
CORPORATE_ACTION_CHECK_MINUTE = settings.CORPORATE_ACTION_CHECK_MINUTE
DATA_HEALTH_CHECK_MINUTES = settings.DATA_HEALTH_CHECK_MINUTES
DATA_HEALTH_ALERT_STALE_HOURS = settings.DATA_HEALTH_ALERT_STALE_HOURS
DATA_HEALTH_RECENT_ANALYSIS_DAYS = settings.DATA_HEALTH_RECENT_ANALYSIS_DAYS
POSITION_MARK_INTERVAL_MINUTES = settings.POSITION_MARK_INTERVAL_MINUTES
OUTPUT_RETENTION_ENABLED = settings.OUTPUT_RETENTION_ENABLED
OUTPUT_JSON_RETENTION_DAYS = settings.OUTPUT_JSON_RETENTION_DAYS
OUTPUT_CHART_RETENTION_DAYS = settings.OUTPUT_CHART_RETENTION_DAYS
OUTPUT_RETENTION_HOUR = settings.OUTPUT_RETENTION_HOUR
OUTPUT_RETENTION_MINUTE = settings.OUTPUT_RETENTION_MINUTE
STATE_BACKUP_ENABLED = settings.STATE_BACKUP_ENABLED
STATE_BACKUP_DIR = settings.STATE_BACKUP_DIR
STATE_BACKUP_KEEP = settings.STATE_BACKUP_KEEP
STATE_BACKUP_HOUR = settings.STATE_BACKUP_HOUR
STATE_BACKUP_MINUTE = settings.STATE_BACKUP_MINUTE
OFFSITE_BACKUP_DEST = settings.OFFSITE_BACKUP_DEST
OFFSITE_BACKUP_TIMEOUT_SEC = settings.OFFSITE_BACKUP_TIMEOUT_SEC
OPS_ALERT_DEDUPE_MINUTES = settings.OPS_ALERT_DEDUPE_MINUTES
SCREENER_BATCH_ENABLED = settings.SCREENER_BATCH_ENABLED
SCREENER_BATCH_HOUR = settings.SCREENER_BATCH_HOUR
SCREENER_BATCH_MINUTE = settings.SCREENER_BATCH_MINUTE
MULTI_AGENT_BATCH_ENABLED = settings.MULTI_AGENT_BATCH_ENABLED
MULTI_AGENT_BATCH_HOUR = settings.MULTI_AGENT_BATCH_HOUR
MULTI_AGENT_BATCH_MINUTE = settings.MULTI_AGENT_BATCH_MINUTE
WATCHLIST = settings.WATCHLIST
SIGNAL_EVAL_DAYS_BACK = settings.SIGNAL_EVAL_DAYS_BACK
SIGNAL_EVAL_BATCH_LIMIT = settings.SIGNAL_EVAL_BATCH_LIMIT
SIGNAL_EVAL_BACKLOG_ALERT = settings.SIGNAL_EVAL_BACKLOG_ALERT
SIGNAL_BUY_THRESHOLD = settings.SIGNAL_BUY_THRESHOLD
SIGNAL_SELL_THRESHOLD = settings.SIGNAL_SELL_THRESHOLD
BUY_THRESHOLD = settings.BUY_THRESHOLD
SELL_THRESHOLD = settings.SELL_THRESHOLD
MIN_CONFIDENCE = settings.MIN_CONFIDENCE
TRADING_STYLE = settings.TRADING_STYLE
DEFAULT_LLM_PROVIDER = settings.DEFAULT_LLM_PROVIDER
MULTI_AGENT_MAX_WORKERS = settings.MULTI_AGENT_MAX_WORKERS
MULTI_AGENT_TIMEOUT = settings.MULTI_AGENT_TIMEOUT
MULTI_AGENT_LLM_TIMEOUT = settings.MULTI_AGENT_LLM_TIMEOUT
GEMINI_LLM_TIMEOUT = settings.GEMINI_LLM_TIMEOUT
ANALYSIS_AUX_FETCH_TIMEOUT = settings.ANALYSIS_AUX_FETCH_TIMEOUT
YFINANCE_TIMEOUT = settings.YFINANCE_TIMEOUT
GPU_MONITOR_INTERVAL_SECONDS = settings.GPU_MONITOR_INTERVAL_SECONDS
GPU_THROTTLE_MEMORY_MB = settings.GPU_THROTTLE_MEMORY_MB
MAC_STUDIO_IP = settings.MAC_STUDIO_IP
MAC_STUDIO_URL = settings.MAC_STUDIO_URL
MAC_STUDIO_HEALTH_TTL_SECONDS = settings.MAC_STUDIO_HEALTH_TTL_SECONDS
MAC_STUDIO_HEALTH_TIMEOUT = settings.MAC_STUDIO_HEALTH_TIMEOUT
MAC_STUDIO_REQUIRE_GPU = settings.MAC_STUDIO_REQUIRE_GPU
MAC_STUDIO_MIN_GPU_FRACTION = settings.MAC_STUDIO_MIN_GPU_FRACTION
API_THREAD_LIMIT = settings.API_THREAD_LIMIT
HEALTH_PROBE_INTERVAL_SECONDS = settings.HEALTH_PROBE_INTERVAL_SECONDS
HEALTH_GENERATION_TIMEOUT_SECONDS = settings.HEALTH_GENERATION_TIMEOUT_SECONDS
MAC_STUDIO_HEALTH_FAILURE_THRESHOLD = settings.MAC_STUDIO_HEALTH_FAILURE_THRESHOLD
MAC_STUDIO_MAX_INFLIGHT = settings.MAC_STUDIO_MAX_INFLIGHT
RTX_5070_MAX_INFLIGHT = settings.RTX_5070_MAX_INFLIGHT
LLM_NODE_MAX_INFLIGHT = settings.LLM_NODE_MAX_INFLIGHT
LLM_NODE_FAILURE_THRESHOLD = settings.LLM_NODE_FAILURE_THRESHOLD
LLM_NODE_COOLDOWN_SECONDS = settings.LLM_NODE_COOLDOWN_SECONDS
AGENT_API_URL = settings.AGENT_API_URL
SCAN_PARALLEL_WORKERS = settings.SCAN_PARALLEL_WORKERS
GOOGLE_API_KEY = settings.GOOGLE_API_KEY
DART_API_KEY = settings.DART_API_KEY
FRED_API_KEY = settings.FRED_API_KEY
FMP_API_KEY = settings.FMP_API_KEY
TRADING_MODE = settings.TRADING_MODE
BROKER_NAME = settings.BROKER_NAME
TOSS_APP_KEY = settings.TOSS_APP_KEY
TOSS_APP_SECRET = settings.TOSS_APP_SECRET
TOSS_ACCOUNT_NO = settings.TOSS_ACCOUNT_NO
TOSS_BASE_URL = settings.TOSS_BASE_URL
TOSS_PAPER = settings.TOSS_PAPER
APPROVAL_EXEC_MODE = settings.APPROVAL_EXEC_MODE
DAILY_ORDER_LIMIT_USD = settings.DAILY_ORDER_LIMIT_USD
DAILY_ORDER_LIMIT_KRW = settings.DAILY_ORDER_LIMIT_KRW
SINGLE_ORDER_LIMIT_USD = settings.SINGLE_ORDER_LIMIT_USD
SINGLE_ORDER_LIMIT_KRW = settings.SINGLE_ORDER_LIMIT_KRW
APPROVAL_TTL_MINUTES = settings.APPROVAL_TTL_MINUTES
ENFORCE_MARKET_HOURS = settings.ENFORCE_MARKET_HOURS
TRADING_COMMISSION_PCT_KR = settings.TRADING_COMMISSION_PCT_KR
TRADING_COMMISSION_PCT_US = settings.TRADING_COMMISSION_PCT_US
TRADING_SLIPPAGE_PCT = settings.TRADING_SLIPPAGE_PCT
TRADING_SELL_TAX_PCT_KR = settings.TRADING_SELL_TAX_PCT_KR
ANNUAL_RISK_FREE_RATE = settings.ANNUAL_RISK_FREE_RATE


_STYLE_PRESETS = {
    "scalping": {
        "sma_periods": [5, 20],
        "ema_periods": [9, 21],
        "atr_multiplier": 1.2,
        "history_period": "60d",
        "timeframe": "intraday",
        # 의도 보유기간. 평가 horizon 은 이 값에서 파생된다 — 10일 보유를 의도한
        # 신호를 7일에 채점하면 무엇을 재는지 알 수 없다 (2026-09 진단).
        "holding_days": 2,
    },
    "swing": {
        "sma_periods": [20, 50, 200],
        "ema_periods": [12, 26],
        "atr_multiplier": 2.0,
        "history_period": "2y",
        "timeframe": "daily",
        "holding_days": 10,
    },
    "longterm": {
        "sma_periods": [50, 120, 200],
        "ema_periods": [50, 100],
        "atr_multiplier": 3.0,
        "history_period": "5y",
        "timeframe": "weekly",
        "holding_days": 60,
    },
}
_preset = _STYLE_PRESETS[TRADING_STYLE]

DEFAULT_HISTORY_PERIOD = _preset["history_period"]
# 의도 보유기간 (일). entry_plan 과 평가 horizon 이 같은 값을 본다.
EXPECTED_HOLDING_DAYS = _preset["holding_days"]
SMA_PERIODS = _preset["sma_periods"]
EMA_PERIODS = _preset["ema_periods"]
ATR_STOP_MULTIPLIER = _preset["atr_multiplier"]
TIMEFRAME = _preset["timeframe"]
RSI_PERIOD = 14
BOLLINGER_PERIOD = 20
BOLLINGER_STD = 2.0
ADX_PERIOD = 14
ATR_PERIOD = 14
MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9

ACCOUNT_SIZE = settings.ACCOUNT_SIZE
ACCOUNT_SIZE_KRW = settings.ACCOUNT_SIZE_KRW
RISK_PER_TRADE_PCT = settings.RISK_PER_TRADE_PCT
MAX_POSITION_PCT = settings.MAX_POSITION_PCT
TAKE_PROFIT_RR_RATIO = settings.TAKE_PROFIT_RR_RATIO
COOLING_OFF_DAYS = settings.COOLING_OFF_DAYS

RSI_OVERSOLD = settings.RSI_OVERSOLD
RSI_OVERBOUGHT = settings.RSI_OVERBOUGHT

POSITION_TRANCHE_1_PCT = settings.POSITION_TRANCHE_1_PCT
POSITION_TRANCHE_2_PCT = settings.POSITION_TRANCHE_2_PCT
POSITION_TRANCHE_3_PCT = settings.POSITION_TRANCHE_3_PCT

DEFAULT_TEST_TICKER = settings.DEFAULT_TEST_TICKER
DEFAULT_SCAN_LIMIT = settings.DEFAULT_SCAN_LIMIT

AGENT_API_HOST = settings.AGENT_API_HOST
AGENT_API_PORT = settings.AGENT_API_PORT

ALPACA_API_KEY = settings.ALPACA_API_KEY
ALPACA_SECRET_KEY = settings.ALPACA_SECRET_KEY
ALPACA_BASE_URL = settings.ALPACA_BASE_URL
ALPACA_DATA_URL = settings.ALPACA_DATA_URL
ALPACA_DATA_FEED = settings.ALPACA_DATA_FEED

DATA_SOURCE = settings.DATA_SOURCE

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "output")
os.makedirs(OUTPUT_DIR, exist_ok=True)
