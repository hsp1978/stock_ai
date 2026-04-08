#!/bin/bash
# ─────────────────────────────────────────────
# 관심 종목 일괄 분석 스크립트
# watchlist.txt 파일에서 종목을 읽어 순차 분석
# ─────────────────────────────────────────────

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# 가상환경 활성화 (경로를 환경에 맞게 수정)
VENV_PATH="${SCRIPT_DIR}/../venv/bin/activate"
if [ -f "$VENV_PATH" ]; then
    source "$VENV_PATH"
fi

# 종목 파일 경로 (인자로 지정 가능, 기본: watchlist.txt)
WATCHLIST_FILE="${1:-${SCRIPT_DIR}/watchlist.txt}"

# AI 모드 (none / gpt4o / ollama)
AI_MODE="${2:-none}"

# 텔레그램 전송 여부 (true / false)
SEND_TELEGRAM="${3:-false}"

# ─────────────────────────────────────────────

if [ ! -f "$WATCHLIST_FILE" ]; then
    echo "[오류] 종목 파일 없음: $WATCHLIST_FILE"
    exit 1
fi

# 주석(#)과 빈 줄 제거 후 종목 목록 추출
TICKERS=$(grep -v '^\s*#' "$WATCHLIST_FILE" | grep -v '^\s*$' | tr -d '[:space:]' | tr '\n' ' ')
TICKER_COUNT=$(echo "$TICKERS" | wc -w)

echo "============================================"
echo "  일괄 분석 시작: $(date '+%Y-%m-%d %H:%M')"
echo "  종목 파일: $WATCHLIST_FILE"
echo "  종목 수: $TICKER_COUNT"
echo "  AI 모드: $AI_MODE"
echo "  텔레그램: $SEND_TELEGRAM"
echo "============================================"

TELEGRAM_FLAG=""
if [ "$SEND_TELEGRAM" = "true" ]; then
    TELEGRAM_FLAG="--telegram"
fi

SUCCESS=0
FAIL=0

for TICKER in $TICKERS; do
    echo ""
    echo "── $TICKER 분석 시작 ($(date '+%H:%M:%S')) ──"
    python main.py "$TICKER" --ai "$AI_MODE" $TELEGRAM_FLAG

    if [ $? -eq 0 ]; then
        SUCCESS=$((SUCCESS + 1))
    else
        FAIL=$((FAIL + 1))
        echo "[경고] $TICKER 분석 실패"
    fi

    # API 부하 방지 딜레이
    sleep 5
done

echo ""
echo "============================================"
echo "  일괄 분석 완료: $(date '+%Y-%m-%d %H:%M')"
echo "  성공: $SUCCESS / 실패: $FAIL / 전체: $TICKER_COUNT"
echo "============================================"
