# V2.0 구현 사전 준비 가이드

**작성일:** 2026-04-14
**예상 준비 기간:** 1-2일

---

## 🔑 필수 API Keys

### 1. Gemini API (기존 사용 중)
```bash
# 현재 상태 확인
cat chart_agent_service/.env | grep GEMINI

# 필요한 경우 새로 발급
# https://makersuite.google.com/app/apikey
# 무료 티어: 60 RPM (분당 60회 요청)
```

### 2. OpenAI API (신규 필요) ⚠️
```bash
# GPT-4o 접근 필요 (Decision Maker용)
# https://platform.openai.com/api-keys

# 요금제 확인
# - GPT-4o: $5/1M input, $15/1M output tokens
# - 예상 비용: $1-2/월

# .env에 추가
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o  # 또는 gpt-4o-mini (저렴한 버전)
```

### 3. Ollama (로컬 LLM) ✅
```bash
# 설치 확인
ollama --version

# 설치 필요 시
curl -fsSL https://ollama.com/install.sh | sh

# 모델 다운로드 (Risk Manager, ML Specialist용)
ollama pull llama3.2:3b       # 3B 모델 (2GB RAM)
ollama pull mistral:7b        # 7B 모델 (4GB RAM) - 권장
ollama pull qwen2.5:14b       # 14B 모델 (8GB RAM) - 고성능

# 실행 확인
ollama serve  # http://localhost:11434
curl http://localhost:11434/api/tags
```

---

## 💻 하드웨어 요구사항

### 최소 사양
```yaml
CPU: 4 cores
RAM: 8GB (Ollama 포함 시)
Storage: 20GB 여유 공간
Network: 안정적인 인터넷 (API 호출)
```

### 권장 사양
```yaml
CPU: 8+ cores (멀티에이전트 병렬 처리)
RAM: 16GB+ (Ollama 대형 모델 사용 시)
GPU: 선택사항 (Ollama 가속화)
Storage: 50GB+ (로그 및 백업)
```

### 현재 서버 확인
```bash
# CPU 확인
lscpu | grep "CPU(s)"

# 메모리 확인
free -h

# 디스크 확인
df -h /home/ubuntu

# GPU 확인 (있는 경우)
nvidia-smi
```

---

## 🖥️ 소프트웨어 설치

### 1. Python 환경
```bash
# Python 버전 확인 (3.10+ 필요)
python --version

# 가상환경 활성화
source /home/ubuntu/stock_auto/venv/bin/activate

# pip 업그레이드
pip install --upgrade pip
```

### 2. MCP 패키지 (Week 1)
```bash
# MCP 서버용
pip install mcp

# 또는 fastmcp (더 간단한 버전)
pip install fastmcp
```

### 3. Claude Desktop (MCP 테스트용) ⚠️
```bash
# macOS만 지원 (2026년 4월 기준)
# https://claude.ai/download

# 설치 후 설정 파일 위치
~/Library/Application Support/Claude/claude_desktop_config.json

# Windows/Linux는 대안:
# - MCP 직접 테스트 스크립트 사용
# - API로 시뮬레이션
```

### 4. 추가 Python 패키지
```bash
# 현재 requirements.txt 확인
cat stock_analyzer/requirements.txt

# V2.0 추가 패키지 설치
pip install openai>=1.0.0       # OpenAI GPT-4o
pip install mcp>=0.3.0          # MCP 서버
pip install fastmcp>=0.1.0      # 간단한 MCP 구현
```

---

## 📁 디렉토리 구조 준비

```bash
# V2.0 신규 파일용 디렉토리
mkdir -p stock_analyzer/v2
mkdir -p docs/v2
mkdir -p tests/v2

# 백업 (중요!)
cp -r stock_auto stock_auto_backup_$(date +%Y%m%d)
```

---

## 🔐 보안 설정

### API Key 관리
```bash
# .env 파일 권한 설정
chmod 600 chart_agent_service/.env
chmod 600 stock_analyzer/.env

# .gitignore 확인
grep -E "\.env|api_key" .gitignore
```

### Rate Limiting 설정
```python
# config.py에 추가
GEMINI_RPM = 60      # 분당 60회
OPENAI_RPM = 500     # 분당 500회 (Tier 1)
OLLAMA_RPM = 1000    # 로컬이므로 제한 없음

# 일일 한도
DAILY_LLM_LIMIT = 1000  # 일일 총 호출 제한
```

---

## 📊 비용 계획

### 월간 예상 비용
```yaml
Gemini API:
  - 무료 티어: $0
  - 초과 시: ~$0.5/월

OpenAI API (GPT-4o):
  - Decision Maker 전용
  - 예상: $1-2/월
  - 대안: gpt-4o-mini ($0.3/월)

Ollama:
  - 로컬 실행: $0
  - 전기료만 소비

총계: $1.5-2.5/월
```

### 비용 절감 옵션
```python
# 1. 캐싱 활성화
CACHE_TTL = 3600  # 1시간 캐시

# 2. 테스트 모드
TEST_MODE = True  # 실제 API 호출 없이 mock 데이터

# 3. 저렴한 모델 사용
USE_MINI_MODELS = True  # gpt-4o-mini, gemini-flash 등
```

---

## ✅ 사전 준비 체크리스트

### 필수 항목
- [ ] Python 3.10+ 설치 확인
- [ ] 8GB+ RAM 확인
- [ ] Gemini API key 확인 (기존)
- [ ] OpenAI API key 발급 ⚠️
- [ ] Ollama 설치 및 모델 다운로드
- [ ] 프로젝트 백업 완료

### 선택 항목
- [ ] Claude Desktop 설치 (Mac 사용 시)
- [ ] GPU 드라이버 설치 (있는 경우)
- [ ] 모니터링 도구 설정

### 테스트
```bash
# 1. Gemini 테스트
python -c "
import os
from google.generativeai import configure, GenerativeModel
configure(api_key=os.getenv('GEMINI_API_KEY'))
model = GenerativeModel('gemini-1.5-flash')
print(model.generate_content('Hello').text)
"

# 2. OpenAI 테스트 (key 발급 후)
python -c "
from openai import OpenAI
client = OpenAI()
response = client.chat.completions.create(
    model='gpt-4o-mini',
    messages=[{'role': 'user', 'content': 'Hello'}]
)
print(response.choices[0].message.content)
"

# 3. Ollama 테스트
curl -X POST http://localhost:11434/api/generate \
  -d '{"model": "mistral:7b", "prompt": "Hello"}'
```

---

## 🚨 주의사항

### API Key 노출 방지
```bash
# 절대 하지 말 것
git add .env  # ❌
git commit -m "api_key=sk-..."  # ❌

# 안전한 방법
export OPENAI_API_KEY=sk-...  # 환경변수
source .env  # .gitignore에 포함
```

### 비용 관리
```python
# 일일 한도 초과 방지
if daily_calls > DAILY_LLM_LIMIT:
    use_cache_only = True

# 비싼 모델 제한
if not critical_decision:
    use_mini_model = True
```

### 로컬 LLM 메모리
```bash
# Ollama 모델별 메모리 요구사항
# 3B 모델: 2-3GB
# 7B 모델: 4-5GB
# 14B 모델: 8-10GB

# 메모리 부족 시 작은 모델 사용
ollama pull tinyllama:1b  # 1GB만 필요
```

---

## 🔄 대안 옵션

### OpenAI 대신 사용 가능한 LLM

#### 1. Anthropic Claude API
```bash
# Decision Maker 대안
pip install anthropic
# API key 필요 (유료)
```

#### 2. Groq API (빠른 추론)
```bash
# 무료 티어 제공
pip install groq
# https://console.groq.com/keys
```

#### 3. Together AI
```bash
# 다양한 오픈소스 모델
pip install together
# $25 무료 크레딧
```

#### 4. 완전 로컬 (Ollama only)
```python
# Decision Maker도 Ollama로
# 단, 성능 하락 가능성
ollama pull llama3.1:70b  # 40GB RAM 필요
```

---

## 📞 지원 및 문의

### API 관련
- Gemini: https://ai.google.dev/support
- OpenAI: https://platform.openai.com/docs
- Ollama: https://github.com/ollama/ollama/issues

### 비용 계산기
- OpenAI: https://platform.openai.com/tokenizer
- Gemini: https://ai.google.dev/pricing

---

## 🎯 준비 완료 확인

모든 준비가 완료되면:

```bash
# 통합 확인 스크립트
python -c "
print('=== V2.0 Prerequisites Check ===')
import sys
print(f'Python: {sys.version}')

try:
    import mcp
    print('✓ MCP 설치됨')
except:
    print('✗ MCP 미설치 - pip install mcp')

try:
    import openai
    print('✓ OpenAI 설치됨')
except:
    print('✗ OpenAI 미설치 - pip install openai')

import os
if os.getenv('GEMINI_API_KEY'):
    print('✓ Gemini API key 설정됨')
else:
    print('✗ Gemini API key 없음')

if os.getenv('OPENAI_API_KEY'):
    print('✓ OpenAI API key 설정됨')
else:
    print('✗ OpenAI API key 없음 - 발급 필요')

import requests
try:
    r = requests.get('http://localhost:11434/api/tags', timeout=2)
    if r.status_code == 200:
        print('✓ Ollama 실행 중')
    else:
        print('✗ Ollama 응답 오류')
except:
    print('✗ Ollama 미실행 - ollama serve')

print('=== 준비 상태 확인 완료 ===')
"
```

준비가 완료되면 Week 1 MCP 서버 구현을 시작할 수 있습니다!