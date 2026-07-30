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


_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_ROOT_ENV = _PROJECT_ROOT / ".env"


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
    GEMINI_MODEL: str = "gemini-2.0-flash"
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
    SIGNAL_VALIDATION_HOUR: int = Field(default=23, ge=0, le=23)
    SIGNAL_VALIDATION_MINUTE: int = Field(default=0, ge=0, le=59)
    CORPORATE_ACTION_CHECK_HOUR: int = Field(default=0, ge=0, le=23)
    CORPORATE_ACTION_CHECK_MINUTE: int = Field(default=5, ge=0, le=59)
    DATA_HEALTH_CHECK_MINUTES: int = Field(default=60, ge=5)
    DATA_HEALTH_ALERT_STALE_HOURS: float = Field(default=24.0, ge=0)
    OPS_ALERT_DEDUPE_MINUTES: int = Field(default=60, ge=1)
    # 일일 멀티에이전트(V2) 배치 — signal_outcomes 표본 자동 축적용.
    # 시각은 서버 로컬 시간 기준. 기본 17:30 (KRX 마감 15:30 이후).
    MULTI_AGENT_BATCH_ENABLED: bool = True
    MULTI_AGENT_BATCH_HOUR: int = Field(default=17, ge=0, le=23)
    MULTI_AGENT_BATCH_MINUTE: int = Field(default=30, ge=0, le=59)

    WATCHLIST: str = ""

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
    NEWS_TTL_MINUTES: int = Field(default=30, ge=1)

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
OPS_ALERT_DEDUPE_MINUTES = settings.OPS_ALERT_DEDUPE_MINUTES
MULTI_AGENT_BATCH_ENABLED = settings.MULTI_AGENT_BATCH_ENABLED
MULTI_AGENT_BATCH_HOUR = settings.MULTI_AGENT_BATCH_HOUR
MULTI_AGENT_BATCH_MINUTE = settings.MULTI_AGENT_BATCH_MINUTE
WATCHLIST = settings.WATCHLIST
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
    },
    "swing": {
        "sma_periods": [20, 50, 200],
        "ema_periods": [12, 26],
        "atr_multiplier": 2.0,
        "history_period": "2y",
        "timeframe": "daily",
    },
    "longterm": {
        "sma_periods": [50, 120, 200],
        "ema_periods": [50, 100],
        "atr_multiplier": 3.0,
        "history_period": "5y",
        "timeframe": "weekly",
    },
}
_preset = _STYLE_PRESETS[TRADING_STYLE]

DEFAULT_HISTORY_PERIOD = _preset["history_period"]
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
