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
    OPENAI_API_KEY: str = ""
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-2.0-flash"
    GOOGLE_API_KEY: str = ""
    DEFAULT_LLM_PROVIDER: Literal["ollama", "gemini", "openai"] = "ollama"

    MULTI_AGENT_MAX_WORKERS: int = Field(default=2, ge=1, le=16)

    MAC_STUDIO_IP: str = "hsptest-macstudio"
    MAC_STUDIO_URL: str = "http://hsptest-macstudio:8080"

    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_CHAT_ID: str = ""

    DART_API_KEY: str = ""
    FRED_API_KEY: str = ""
    FMP_API_KEY: str = ""

    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8100
    AGENT_API_HOST: str = "localhost"
    AGENT_API_PORT: int = 8100
    AGENT_API_URL: str = ""

    SCAN_INTERVAL_MINUTES: int = Field(default=30, ge=1)
    SCAN_PARALLEL_WORKERS: int = Field(default=3, ge=1, le=16)

    WATCHLIST: str = ""

    BUY_THRESHOLD: float = 5.0
    SELL_THRESHOLD: float = -5.0
    MIN_CONFIDENCE: float = 5.0

    TRADING_STYLE: Literal["scalping", "swing", "longterm"] = "swing"

    ACCOUNT_SIZE: float = Field(default=100000, gt=0)
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
    BROKER_NAME: Literal["", "alpaca", "kis"] = ""
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

    DATA_SOURCE: Literal["yfinance", "alpaca", "polygon", "kis"] = "yfinance"


settings = Settings()


# ── 호환성: 기존 module-level 상수 그대로 export ────────────────────
OLLAMA_BASE_URL = settings.OLLAMA_BASE_URL
OLLAMA_MODEL = settings.OLLAMA_MODEL
OLLAMA_NUM_PARALLEL = settings.OLLAMA_NUM_PARALLEL
OPENAI_API_KEY = settings.OPENAI_API_KEY
GEMINI_API_KEY = settings.GEMINI_API_KEY
GEMINI_MODEL = settings.GEMINI_MODEL
TELEGRAM_BOT_TOKEN = settings.TELEGRAM_BOT_TOKEN
TELEGRAM_CHAT_ID = settings.TELEGRAM_CHAT_ID
API_HOST = settings.API_HOST
API_PORT = settings.API_PORT
SCAN_INTERVAL_MINUTES = settings.SCAN_INTERVAL_MINUTES
WATCHLIST = settings.WATCHLIST
BUY_THRESHOLD = settings.BUY_THRESHOLD
SELL_THRESHOLD = settings.SELL_THRESHOLD
MIN_CONFIDENCE = settings.MIN_CONFIDENCE
TRADING_STYLE = settings.TRADING_STYLE
DEFAULT_LLM_PROVIDER = settings.DEFAULT_LLM_PROVIDER
MULTI_AGENT_MAX_WORKERS = settings.MULTI_AGENT_MAX_WORKERS
MAC_STUDIO_IP = settings.MAC_STUDIO_IP
MAC_STUDIO_URL = settings.MAC_STUDIO_URL
AGENT_API_URL = settings.AGENT_API_URL
SCAN_PARALLEL_WORKERS = settings.SCAN_PARALLEL_WORKERS
GOOGLE_API_KEY = settings.GOOGLE_API_KEY
DART_API_KEY = settings.DART_API_KEY
FRED_API_KEY = settings.FRED_API_KEY
FMP_API_KEY = settings.FMP_API_KEY
TRADING_MODE = settings.TRADING_MODE
BROKER_NAME = settings.BROKER_NAME
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
