#!/bin/bash
# Stock AI Analysis System V2.0 - 1-click 부트스트랩
# 실행: bash setup_v2.sh [--minimal]
#   --minimal : venv/deps/.env 만 설정 (Ollama 건너뜀)

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

MINIMAL=0
for arg in "$@"; do
    case "$arg" in
        --minimal) MINIMAL=1 ;;
    esac
done

echo -e "${BLUE}=============================================${NC}"
echo -e "${BLUE} Stock AI V2.0 · 자동 설정 스크립트${NC}"
echo -e "${BLUE}=============================================${NC}"

# ─── 1. Python 버전 ────────────────────────────────────────────
echo ""
echo "1) Python 버전 확인"
python_version=$(python3 --version 2>&1 | grep -oE '[0-9]+\.[0-9]+' | head -1)
required="3.10"
if [ "$(printf '%s\n' "$required" "$python_version" | sort -V | head -n1)" = "$required" ]; then
    echo -e "   ${GREEN}✓${NC} Python $python_version"
else
    echo -e "   ${RED}✗${NC} Python $python_version (>= 3.10 필요)"
    exit 1
fi

# ─── 2. venv ───────────────────────────────────────────────────
echo ""
echo "2) 가상환경"
if [ ! -d "venv" ]; then
    python3 -m venv venv
    echo -e "   ${GREEN}✓${NC} venv 생성"
fi
# shellcheck disable=SC1091
source venv/bin/activate
python -m pip install --upgrade pip --quiet
echo -e "   ${GREEN}✓${NC} venv 활성화 (pip $(pip --version | awk '{print $2}'))"

# ─── 3. 의존성 설치 ────────────────────────────────────────────
echo ""
echo "3) Python 의존성 설치"
for req in stock_analyzer/requirements.txt chart_agent_service/requirements.txt; do
    if [ -f "$req" ]; then
        echo -e "   설치: $req"
        pip install -r "$req" --quiet
    fi
done
echo -e "   ${GREEN}✓${NC} 의존성 설치 완료"

# ─── 4. .env 설정 (SSOT) ───────────────────────────────────────
echo ""
echo "4) 환경 변수(.env) 설정"
if [ ! -f ".env" ]; then
    if [ -f ".env.example" ]; then
        cp .env.example .env
        echo -e "   ${GREEN}✓${NC} .env 생성 (루트, .env.example에서 복사)"
        echo -e "   ${YELLOW}⚠${NC} .env 파일을 열어 API 키와 설정을 입력하세요"
    else
        echo -e "   ${RED}✗${NC} .env.example을 찾을 수 없습니다"
    fi
else
    echo -e "   ${GREEN}✓${NC} .env 이미 존재"
fi

# ─── 5. Ollama (스킵 가능) ─────────────────────────────────────
if [ "$MINIMAL" -eq 1 ]; then
    echo ""
    echo -e "5) Ollama ${YELLOW}(--minimal 모드, 건너뜀)${NC}"
else
    echo ""
    echo "5) Ollama 확인"
    if command -v ollama >/dev/null 2>&1; then
        echo -e "   ${GREEN}✓${NC} Ollama 설치됨 ($(ollama --version 2>&1 | head -1))"
        if curl -sf "${OLLAMA_BASE_URL:-http://localhost:11434}/api/tags" >/dev/null 2>&1; then
            echo -e "   ${GREEN}✓${NC} Ollama 서버 실행 중"
            # 필수 모델 확인
            required_model="qwen3:14b-q4_K_M"
            if ollama list 2>/dev/null | awk '{print $1}' | grep -q "^${required_model}$"; then
                echo -e "   ${GREEN}✓${NC} 모델 ${required_model} 설치됨"
            else
                echo -e "   ${YELLOW}⚠${NC} 모델 ${required_model} 미설치"
                echo "      실행: ollama pull ${required_model}  (약 9GB)"
            fi
        else
            echo -e "   ${YELLOW}⚠${NC} Ollama 서버 미실행"
            echo "      다른 터미널에서 'ollama serve' 실행"
        fi
    else
        echo -e "   ${YELLOW}⚠${NC} Ollama 미설치"
        echo "      공식 설치: https://ollama.com/download"
    fi
fi

# ─── 6. 헬스체크 ───────────────────────────────────────────────
echo ""
echo "6) 헬스 체크"
if python -c "from stock_analyzer.ticker_validator import validate_ticker; v,_,_ = validate_ticker('AAPL'); assert v" 2>/dev/null; then
    echo -e "   ${GREEN}✓${NC} stock_analyzer 임포트 OK"
else
    echo -e "   ${RED}✗${NC} stock_analyzer 임포트 실패 - 의존성 재확인 필요"
fi

if python -c "import sys; sys.path.insert(0,'chart_agent_service'); from config import OLLAMA_MODEL; print(OLLAMA_MODEL)" 2>/dev/null | grep -q "qwen"; then
    echo -e "   ${GREEN}✓${NC} chart_agent_service 설정 OK (qwen 모델)"
else
    echo -e "   ${YELLOW}⚠${NC} chart_agent_service/config.py 확인 필요"
fi

# ─── 완료 안내 ─────────────────────────────────────────────────
echo ""
echo -e "${BLUE}=============================================${NC}"
echo -e "${GREEN} 설정 완료${NC}"
echo -e "${BLUE}=============================================${NC}"
echo ""
echo "다음 단계:"
echo "  1) .env 파일 편집: OLLAMA_MODEL, OPENAI_API_KEY 등"
echo "  2) Ollama 모델 설치 (미설치 시): ollama pull qwen3:14b-q4_K_M"
echo "  3) 백엔드 실행 (터미널 1): cd chart_agent_service && python service.py"
echo "  4) WebUI 실행 (터미널 2): cd stock_analyzer && streamlit run webui.py"
echo ""
