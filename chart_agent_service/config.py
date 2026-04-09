"""
차트 분석 에이전트 서비스 설정
Mac Studio (M1 Max) 전용
"""
import os
from dotenv import load_dotenv

load_dotenv()

# ═══ Ollama 설정 ═══
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.1:8b")

# ═══ OpenAI 설정 (선택) ═══
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

# ═══ 텔레그램 설정 ═══
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# ═══ 서비스 설정 ═══
API_HOST = os.getenv("API_HOST", "0.0.0.0")
API_PORT = int(os.getenv("API_PORT", "8100"))

# ═══ 스케줄러 설정 ═══
SCAN_INTERVAL_MINUTES = int(os.getenv("SCAN_INTERVAL_MINUTES", "30"))

# ═══ 관심 종목 ═══
# 콤마 구분 또는 watchlist.txt 파일 참조
WATCHLIST = os.getenv("WATCHLIST", "")

# ═══ 알림 임계값 ═══
# 종합 점수가 이 값을 넘으면 텔레그램 알림
BUY_THRESHOLD = float(os.getenv("BUY_THRESHOLD", "5.0"))     # +5.0 이상 → 매수 알림
SELL_THRESHOLD = float(os.getenv("SELL_THRESHOLD", "-5.0"))   # -5.0 이하 → 매도 알림

# 신뢰도 최소값 (이 이상이어야 알림)
MIN_CONFIDENCE = float(os.getenv("MIN_CONFIDENCE", "5.0"))

# ═══ 투자 스타일 프리셋 ═══
# "scalping" | "swing" | "longterm"
TRADING_STYLE = os.getenv("TRADING_STYLE", "swing")

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

_preset = _STYLE_PRESETS.get(TRADING_STYLE, _STYLE_PRESETS["swing"])

# ═══ 데이터 설정 ═══
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

# ═══ 리스크 관리 설정 ═══
ACCOUNT_SIZE = float(os.getenv("ACCOUNT_SIZE", "100000"))
RISK_PER_TRADE_PCT = float(os.getenv("RISK_PER_TRADE_PCT", "1.0"))
MAX_POSITION_PCT = float(os.getenv("MAX_POSITION_PCT", "20.0"))
TAKE_PROFIT_RR_RATIO = float(os.getenv("TAKE_PROFIT_RR_RATIO", "2.0"))
COOLING_OFF_DAYS = int(os.getenv("COOLING_OFF_DAYS", "3"))

# ═══ 출력 디렉토리 ═══
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "output")
os.makedirs(OUTPUT_DIR, exist_ok=True)
