# LLM Provider 선택 기능 사용 가이드

## 개요
멀티에이전트 시스템이 이제 **Gemini, OpenAI, Ollama** 3가지 LLM 제공자를 지원합니다.
각 에이전트별로 다른 LLM을 사용하거나, 전체적으로 하나의 LLM을 사용할 수 있습니다.

## 지원 LLM Provider

### 1. Gemini (Google)
- **모델**: `gemini-2.0-flash`
- **장점**: 무료 티어 제공, 빠른 응답 속도
- **단점**: API 할당량 제한 (분당 15회)
- **설정**: `GEMINI_API_KEY` 또는 `GOOGLE_API_KEY` 환경 변수

### 2. OpenAI
- **모델**: `gpt-4o-mini`
- **장점**: 높은 품질, 안정적인 서비스
- **단점**: 유료 (토큰당 과금)
- **설정**: `OPENAI_API_KEY` 환경 변수

### 3. Ollama (로컬)
- **모델**: `qwen3:14b-q4_K_M` (설정 가능)
- **장점**: 무료, 데이터 프라이버시
- **단점**: GPU/메모리 필요, 설정 복잡
- **설정**: 로컬 서비스 실행 (기본 포트 11434)

## 설정 방법

### 1. 환경 변수 설정

```bash
# .env 파일 생성
cp stock_analyzer/.env.example stock_analyzer/.env

# .env 파일 편집
nano stock_analyzer/.env
```

```env
# 기본 LLM Provider 선택
DEFAULT_LLM_PROVIDER=openai  # gemini, openai, ollama 중 하나

# API 키 설정
OPENAI_API_KEY=sk-xxxxx
GEMINI_API_KEY=xxxxx  # 또는 GOOGLE_API_KEY=xxxxx

# Ollama 설정 (선택사항)
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=qwen3:14b-q4_K_M
```

### 2. 필요한 패키지 설치

```bash
pip install -r stock_analyzer/requirements.txt
```

## 사용 방법

### 방법 1: 환경 변수로 기본 Provider 설정

```bash
# 터미널에서
export DEFAULT_LLM_PROVIDER=gemini
python stock_analyzer/webui.py
```

### 방법 2: Python 코드에서 직접 설정

```python
from multi_agent import MultiAgentOrchestrator

# 모든 에이전트가 같은 provider 사용
orchestrator = MultiAgentOrchestrator(llm_provider="openai")
result = orchestrator.analyze("005930.KS")  # 삼성전자
```

### 방법 3: 에이전트별로 다른 Provider 사용

```python
from multi_agent import MultiAgentOrchestrator

# 에이전트별 provider 설정
orchestrator = MultiAgentOrchestrator(
    llm_provider="ollama",  # 기본값
    agent_providers={
        "Technical Analyst": "gemini",    # 기술적 분석은 Gemini
        "ML Specialist": "openai",        # ML 전문가는 OpenAI
        "Value Investor": "openai",       # 가치 투자는 OpenAI
        # 나머지는 기본값(ollama) 사용
    }
)

result = orchestrator.analyze("루닛")  # 한국 주식
```

## 테스트 실행

제공된 테스트 스크립트로 각 provider를 테스트할 수 있습니다:

```bash
python test_llm_providers.py
```

출력 예시:
```
======================================================================
Testing OPENAI Provider
======================================================================
✅ OpenAI API key found
✅ 분석 완료!
  최종 신호: neutral
  신뢰도: 5.0/10

에이전트별 결과:
  ✓ Technical Analyst (openai): neutral (5.0/10)
  ✓ Value Investor (openai): sell (8.0/10)
  ✓ ML Specialist (openai): sell (4.0/10)
```

## 최적 구성 추천

### 1. 무료 사용자
```env
DEFAULT_LLM_PROVIDER=gemini
```
- Gemini의 무료 티어 활용
- 분당 15회 제한에 주의

### 2. 품질 우선 사용자
```env
DEFAULT_LLM_PROVIDER=openai
```
- OpenAI GPT-4o-mini 사용
- 가장 안정적이고 정확한 분석

### 3. 프라이버시 중시 사용자
```env
DEFAULT_LLM_PROVIDER=ollama
```
- 로컬에서 모든 처리
- GPU 메모리 최소 12GB 권장

### 4. 하이브리드 구성 (추천)
```python
orchestrator = MultiAgentOrchestrator(
    llm_provider="gemini",  # 기본: 무료 Gemini
    agent_providers={
        "Decision Maker": "openai",  # 중요한 최종 결정은 OpenAI
        "ML Specialist": "openai",   # ML 분석은 정확도 높은 OpenAI
    }
)
```

## 성능 비교

| Provider | 속도 | 품질 | 비용 | 안정성 |
|----------|------|------|------|--------|
| Gemini   | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ | 무료* | ⭐⭐⭐ |
| OpenAI   | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | 유료 | ⭐⭐⭐⭐⭐ |
| Ollama   | ⭐⭐⭐ | ⭐⭐⭐⭐ | 무료 | ⭐⭐ |

*Gemini: 무료 티어 제한 있음 (분당 15회)

## 문제 해결

### 1. Gemini "quota exceeded" 오류
- 원인: API 할당량 초과
- 해결: 다른 provider로 전환하거나 1분 대기

### 2. OpenAI "insufficient_quota" 오류
- 원인: OpenAI 크레딧 부족
- 해결: OpenAI 계정에 크레딧 충전

### 3. Ollama "connection refused" 오류
- 원인: Ollama 서비스 미실행
- 해결:
  ```bash
  # Ollama 서비스 시작
  ollama serve

  # 모델 다운로드 (최초 1회)
  ollama pull llama3.2:latest
  ```

### 4. 모든 에이전트가 neutral 0.0/10 반환
- 원인: LLM 응답 실패
- 해결:
  - API 키 확인
  - 네트워크 연결 확인
  - 다른 provider로 전환

## 주의사항

1. **API 키 보안**: `.env` 파일을 git에 커밋하지 마세요
2. **비용 관리**: OpenAI 사용 시 토큰 사용량 모니터링
3. **속도 최적화**: 병렬 실행으로 인한 API 한계 고려
4. **백업 전략**: 주 provider 실패 시 대체 provider 준비

## 추가 개발 예정

- [ ] Claude API 지원
- [ ] Anthropic API 지원
- [ ] 자동 failover 기능
- [ ] 비용 추적 기능
- [ ] 캐싱 최적화

## 문의 및 지원

문제 발생 시 이슈를 등록해주세요:
- GitHub Issues: [프로젝트 저장소]/issues
- 로그 확인: `tail -f stock_analyzer/logs/*.log`