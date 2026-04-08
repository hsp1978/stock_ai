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
WATCHLIST = os.getenv("WATCHLIST", "AAPL,MSFT,NVDA,GOOGL,AMZN,META,TSLA")

# ═══ 알림 임계값 ═══
# 종합 점수가 이 값을 넘으면 텔레그램 알림
BUY_THRESHOLD = float(os.getenv("BUY_THRESHOLD", "5.0"))     # +5.0 이상 → 매수 알림
SELL_THRESHOLD = float(os.getenv("SELL_THRESHOLD", "-5.0"))   # -5.0 이하 → 매도 알림

# 신뢰도 최소값 (이 이상이어야 알림)
MIN_CONFIDENCE = float(os.getenv("MIN_CONFIDENCE", "5.0"))

# ═══ 데이터 설정 ═══
DEFAULT_HISTORY_PERIOD = "2y"
SMA_PERIODS = [20, 50, 200]
EMA_PERIODS = [12, 26]
RSI_PERIOD = 14
BOLLINGER_PERIOD = 20
BOLLINGER_STD = 2.0
ADX_PERIOD = 14
ATR_PERIOD = 14
MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9

# ═══ 출력 디렉토리 ═══
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "output")
os.makedirs(OUTPUT_DIR, exist_ok=True)
