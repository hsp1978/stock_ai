"""
시스템 설정 파일
API 키는 .env 파일에서 로드하거나 환경변수로 설정
"""
import os
from dotenv import load_dotenv

load_dotenv()

# === API 설정 ===
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
FMP_API_KEY = os.getenv("FMP_API_KEY", "")
FRED_API_KEY = os.getenv("FRED_API_KEY", "")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.1:8b")

# === 리스크 관리 기본값 ===
MAX_POSITION_PCT = 0.05          # 단일 종목 최대 비중 5%
MAX_PORTFOLIO_DRAWDOWN = 0.15    # 포트폴리오 최대 허용 드로다운 15%
DEFAULT_STOP_LOSS_ATR_MULT = 2.0 # ATR 2배 기반 손절
DEFAULT_TAKE_PROFIT_RATIO = 2.0  # 리스크 대비 수익 비율 (Risk:Reward = 1:2)
ACCOUNT_SIZE = 10000             # 기본 계좌 크기 (USD)

# === 기술 지표 기본 파라미터 ===
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
STOCHASTIC_K = 14
STOCHASTIC_D = 3
STOCHASTIC_SMOOTH = 3
ICHIMOKU_TENKAN = 9
ICHIMOKU_KIJUN = 26
ICHIMOKU_SENKOU_B = 52
WILLIAMS_R_PERIOD = 14
CMF_PERIOD = 20

# === 데이터 수집 설정 ===
DEFAULT_HISTORY_PERIOD = "2y"    # 기본 2년치 데이터
CHART_HISTORY_DAYS = 120         # 차트 표시 기간 (거래일)

# === 텔레그램 설정 ===
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# === 출력 설정 ===
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "output")
os.makedirs(OUTPUT_DIR, exist_ok=True)
