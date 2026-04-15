#!/bin/bash

# V2.0 자동 설정 스크립트
# 실행: bash setup_v2.sh

echo "======================================"
echo "Stock AI Agent V2.0 Setup Script"
echo "======================================"
echo ""

# 색상 정의
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 1. Python 버전 확인
echo "1. Python 버전 확인..."
python_version=$(python3 --version 2>&1 | grep -oE '[0-9]+\.[0-9]+' | head -1)
required_version="3.10"

if [ "$(printf '%s\n' "$required_version" "$python_version" | sort -V | head -n1)" = "$required_version" ]; then
    echo -e "${GREEN}✓${NC} Python $python_version (OK)"
else
    echo -e "${RED}✗${NC} Python $python_version (3.10+ 필요)"
    exit 1
fi

# 2. 가상환경 확인
echo ""
echo "2. 가상환경 확인..."
if [ -d "venv" ]; then
    echo -e "${GREEN}✓${NC} venv 존재"
    source venv/bin/activate
    echo -e "${GREEN}✓${NC} venv 활성화됨"
else
    echo -e "${YELLOW}⚠${NC} venv 없음. 생성하시겠습니까? (y/n)"
    read -r response
    if [ "$response" = "y" ]; then
        python3 -m venv venv
        source venv/bin/activate
        pip install --upgrade pip
        echo -e "${GREEN}✓${NC} venv 생성 및 활성화 완료"
    fi
fi

# 3. 메모리 확인
echo ""
echo "3. 시스템 리소스 확인..."
total_mem=$(free -m | awk 'NR==2{printf "%.1f", $2/1024}')
echo "   총 메모리: ${total_mem}GB"

if (( $(echo "$total_mem > 7" | bc -l) )); then
    echo -e "${GREEN}✓${NC} 메모리 충분 (8GB+ 권장)"
else
    echo -e "${YELLOW}⚠${NC} 메모리 부족 (8GB+ 권장). Ollama 작은 모델 사용 권장"
fi

# 4. 필수 패키지 설치
echo ""
echo "4. 필수 Python 패키지 설치..."
packages_to_install=""

# MCP 확인
if ! python3 -c "import mcp" 2>/dev/null; then
    packages_to_install="$packages_to_install mcp"
    echo -e "${YELLOW}⚠${NC} MCP 미설치"
else
    echo -e "${GREEN}✓${NC} MCP 설치됨"
fi

# OpenAI 확인
if ! python3 -c "import openai" 2>/dev/null; then
    packages_to_install="$packages_to_install openai"
    echo -e "${YELLOW}⚠${NC} OpenAI 미설치"
else
    echo -e "${GREEN}✓${NC} OpenAI 설치됨"
fi

# 패키지 설치
if [ -n "$packages_to_install" ]; then
    echo "   필요한 패키지 설치 중..."
    pip install $packages_to_install
    echo -e "${GREEN}✓${NC} 패키지 설치 완료"
fi

# 5. API Keys 확인
echo ""
echo "5. API Keys 확인..."

# .env 파일 확인
env_file="chart_agent_service/.env"
if [ -f "$env_file" ]; then
    echo -e "${GREEN}✓${NC} .env 파일 존재"

    # Gemini API key
    if grep -q "GEMINI_API_KEY" "$env_file"; then
        echo -e "${GREEN}✓${NC} GEMINI_API_KEY 설정됨"
    else
        echo -e "${YELLOW}⚠${NC} GEMINI_API_KEY 없음"
        echo "   https://makersuite.google.com/app/apikey 에서 발급"
    fi

    # OpenAI API key
    if grep -q "OPENAI_API_KEY" "$env_file"; then
        echo -e "${GREEN}✓${NC} OPENAI_API_KEY 설정됨"
    else
        echo -e "${RED}✗${NC} OPENAI_API_KEY 없음 (V2.0 필수)"
        echo "   https://platform.openai.com/api-keys 에서 발급"
        echo ""
        echo "   API key를 입력하시겠습니까? (Enter to skip)"
        read -r openai_key
        if [ -n "$openai_key" ]; then
            echo "OPENAI_API_KEY=$openai_key" >> "$env_file"
            echo -e "${GREEN}✓${NC} OpenAI API key 저장됨"
        fi
    fi
else
    echo -e "${RED}✗${NC} .env 파일 없음"
    echo "   chart_agent_service/.env 파일을 생성해주세요"
fi

# 6. Ollama 확인
echo ""
echo "6. Ollama 확인..."

if command -v ollama &> /dev/null; then
    echo -e "${GREEN}✓${NC} Ollama 설치됨"

    # Ollama 실행 확인
    if curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
        echo -e "${GREEN}✓${NC} Ollama 서버 실행 중"

        # 모델 확인
        models=$(ollama list 2>/dev/null | tail -n +2 | awk '{print $1}')
        if [ -n "$models" ]; then
            echo "   설치된 모델:"
            echo "$models" | while read -r model; do
                echo "   - $model"
            done
        else
            echo -e "${YELLOW}⚠${NC} 모델 없음. 설치하시겠습니까? (y/n)"
            read -r response
            if [ "$response" = "y" ]; then
                echo "   Mistral 7B 모델 다운로드 중... (4GB)"
                ollama pull mistral:7b
                echo -e "${GREEN}✓${NC} 모델 설치 완료"
            fi
        fi
    else
        echo -e "${YELLOW}⚠${NC} Ollama 서버 미실행"
        echo "   다른 터미널에서 실행: ollama serve"
    fi
else
    echo -e "${RED}✗${NC} Ollama 미설치"
    echo "   설치하시겠습니까? (y/n)"
    read -r response
    if [ "$response" = "y" ]; then
        curl -fsSL https://ollama.com/install.sh | sh
        echo -e "${GREEN}✓${NC} Ollama 설치 완료"
        echo "   ollama serve 실행 후 다시 이 스크립트를 실행하세요"
    fi
fi

# 7. 백업 생성
echo ""
echo "7. 백업 생성..."
backup_dir="backups/v1_backup_$(date +%Y%m%d_%H%M%S)"

if [ ! -d "backups" ]; then
    mkdir -p backups
fi

echo "   백업을 생성하시겠습니까? (권장) (y/n)"
read -r response
if [ "$response" = "y" ]; then
    echo "   백업 중... (약 1분 소요)"
    cp -r . "$backup_dir" 2>/dev/null || true
    echo -e "${GREEN}✓${NC} 백업 완료: $backup_dir"
fi

# 8. V2 디렉토리 생성
echo ""
echo "8. V2 디렉토리 구조 생성..."
mkdir -p stock_analyzer/v2
mkdir -p docs/v2
mkdir -p tests/v2
echo -e "${GREEN}✓${NC} 디렉토리 생성 완료"

# 9. 최종 확인
echo ""
echo "======================================"
echo "설정 완료 상태"
echo "======================================"

# 점수 계산
total_score=0
max_score=7

# Python
if [ "$(printf '%s\n' "$required_version" "$python_version" | sort -V | head -n1)" = "$required_version" ]; then
    echo -e "${GREEN}✓${NC} Python 3.10+"
    ((total_score++))
else
    echo -e "${RED}✗${NC} Python 버전 부족"
fi

# venv
if [ -n "$VIRTUAL_ENV" ]; then
    echo -e "${GREEN}✓${NC} 가상환경 활성화"
    ((total_score++))
else
    echo -e "${YELLOW}⚠${NC} 가상환경 비활성화"
fi

# MCP
if python3 -c "import mcp" 2>/dev/null; then
    echo -e "${GREEN}✓${NC} MCP 패키지"
    ((total_score++))
else
    echo -e "${RED}✗${NC} MCP 패키지"
fi

# OpenAI
if python3 -c "import openai" 2>/dev/null; then
    echo -e "${GREEN}✓${NC} OpenAI 패키지"
    ((total_score++))
else
    echo -e "${RED}✗${NC} OpenAI 패키지"
fi

# Gemini key
if [ -f "$env_file" ] && grep -q "GEMINI_API_KEY" "$env_file"; then
    echo -e "${GREEN}✓${NC} Gemini API key"
    ((total_score++))
else
    echo -e "${YELLOW}⚠${NC} Gemini API key"
fi

# OpenAI key
if [ -f "$env_file" ] && grep -q "OPENAI_API_KEY" "$env_file"; then
    echo -e "${GREEN}✓${NC} OpenAI API key"
    ((total_score++))
else
    echo -e "${RED}✗${NC} OpenAI API key (필수)"
fi

# Ollama
if curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
    echo -e "${GREEN}✓${NC} Ollama 실행 중"
    ((total_score++))
else
    echo -e "${YELLOW}⚠${NC} Ollama 미실행"
fi

echo ""
echo "======================================"
echo "준비 점수: $total_score / $max_score"

if [ $total_score -eq $max_score ]; then
    echo -e "${GREEN}모든 준비 완료! V2.0 개발을 시작할 수 있습니다.${NC}"
elif [ $total_score -ge 5 ]; then
    echo -e "${YELLOW}대부분 준비됨. 일부 항목 확인 필요.${NC}"
else
    echo -e "${RED}추가 설정이 필요합니다. 위 항목들을 확인하세요.${NC}"
fi

echo "======================================"
echo ""
echo "다음 단계:"
echo "1. OpenAI API key 발급 (없는 경우)"
echo "2. ollama serve 실행 (다른 터미널)"
echo "3. python test_v2_prerequisites.py 실행 (테스트)"
echo "4. Week 1 MCP 서버 구현 시작"