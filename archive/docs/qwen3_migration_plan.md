# Qwen3 도입 계획

## 🎯 현실적 접근 방법

### 1단계: 현재 (Qwen 2.5 유지)
```python
# RTX 5070 (24GB VRAM)
"ML Specialist": "qwen2.5:14b"      # 9GB - 품질 검증됨
"Event Analyst": "qwen2.5:14b"      # 9GB - 안정적
"Risk Manager": "llama3.1:8b"       # 5GB - 속도 우선
```

### 2단계: Qwen3 테스트 (Hugging Face 직접 사용)
```python
# Hugging Face Transformers로 직접 로드
from transformers import AutoModelForCausalLM, AutoTokenizer

# Qwen3-8B = Qwen2.5-14B 성능
model_name = "Qwen/Qwen3-8B-Instruct"
model = AutoModelForCausalLM.from_pretrained(
    model_name,
    device_map="cuda",
    load_in_4bit=True  # 4-bit quantization
)
```

### 3단계: 성능 비교
```python
# 동일 작업 수행 시 예상 결과
작업: ML Specialist (BAC 분석)

Qwen2.5-14B (현재):
- 메모리: 9GB
- 실행 시간: 11.5초
- 품질 점수: 8/9

Qwen3-8B (예상):
- 메모리: ~5GB (4-bit)
- 실행 시간: ~7초
- 품질 점수: 8/9 (동일)
```

## 📦 Qwen3 설치 방법

### 옵션 1: Hugging Face 직접 사용
```bash
pip install transformers accelerate bitsandbytes

# Python 스크립트
python3 -c "
from transformers import AutoModelForCausalLM, AutoTokenizer
model = AutoModelForCausalLM.from_pretrained(
    'Qwen/Qwen3-8B-Instruct',
    device_map='cuda',
    load_in_4bit=True
)
"
```

### 옵션 2: vLLM 서버
```bash
# vLLM으로 서버 실행
pip install vllm

python -m vllm.entrypoints.openai.api_server \
  --model Qwen/Qwen3-8B-Instruct \
  --quantization awq \
  --max-model-len 8192 \
  --gpu-memory-utilization 0.9
```

### 옵션 3: Ollama 대기
```bash
# Ollama에 Qwen3 추가될 때까지 대기
# 예상: 2025년 Q1-Q2

# 추가되면:
ollama pull qwen3:8b
ollama pull qwen3:14b
```

## 🔄 마이그레이션 로드맵

### Phase 1 (현재)
- Qwen2.5-14B로 품질 확보 ✅
- 실행 시간 11초 감수
- 안정성 우선

### Phase 2 (1개월 내)
- Qwen3-8B HuggingFace 테스트
- 성능 비교 벤치마크
- vLLM 서버 구축

### Phase 3 (2개월 내)
- Qwen3-8B 전환 (2.5-14B → 3-8B)
- 메모리 50% 절감
- 속도 40% 향상

### Phase 4 (Ollama 지원 시)
- 전체 시스템 Qwen3 전환
- Qwen3-4B: Risk Manager
- Qwen3-8B: ML/Event
- Qwen3-14B: Technical/Quant

## 💰 비용 효율 분석

| 모델 | VRAM | 성능 | 효율성 |
|------|------|------|--------|
| Qwen2.5-14B | 9GB | 100% | 기준 |
| Qwen3-8B | 5GB | 100% | **1.8x** |
| Qwen3-4B | 2.5GB | ~70% | **2.5x** |

## 🎯 권장사항

1. **단기 (지금)**: Qwen2.5-14B 유지
   - 이미 검증된 품질
   - 안정적 운영

2. **중기 (1개월)**: Qwen3-8B 테스트
   - HuggingFace 직접 사용
   - 병렬 운영으로 비교

3. **장기 (3개월)**: Qwen3 전면 전환
   - Ollama 지원 대기
   - 또는 vLLM 자체 구축

## 📊 예상 개선 효과

### 현재 (Qwen2.5)
- 전체 실행: 30-40초
- GPU 메모리: 15-18GB
- 품질: 우수

### 미래 (Qwen3)
- 전체 실행: **15-20초** (50% 단축)
- GPU 메모리: **8-10GB** (45% 절감)
- 품질: **동일 또는 향상**

## 🚀 액션 아이템

1. [ ] HuggingFace에서 Qwen3-8B 다운로드 테스트
2. [ ] vLLM 서버 구축 타당성 검토
3. [ ] Ollama Qwen3 지원 모니터링
4. [ ] 주간 성능 비교 테스트 수행