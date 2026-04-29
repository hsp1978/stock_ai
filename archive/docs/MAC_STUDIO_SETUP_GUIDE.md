# 🖥️ Mac Studio 듀얼 노드 설정 가이드

## 📋 개요
RTX 5070과 Mac Studio를 연동하여 듀얼 노드 LLM 시스템을 구성합니다.

## 🎯 현재 상태
- **RTX 5070**: ✅ Qwen3:14b-q4_K_M 설치 완료 (단일 노드 모드로 작동 중)
- **Mac Studio**: ⚠️ 오프라인 (설정 필요)

## 🚀 Mac Studio 설정 방법

### 1단계: 설정 스크립트 복사
Mac Studio 터미널에서:
```bash
# 설정 스크립트 다운로드 (RTX 5070 서버에서)
scp ubuntu@[RTX_5070_IP]:/home/ubuntu/stock_auto/mac_studio_setup.sh ~/
chmod +x ~/mac_studio_setup.sh
```

### 2단계: Ollama 설치 및 설정
```bash
# 설정 스크립트 실행
./mac_studio_setup.sh
```

이 스크립트가 자동으로:
- Ollama 설치
- 필요한 모델 다운로드 (Qwen 30B/32B)
- 서버 설정 (포트 8080)
- 자동 시작 설정

### 3단계: 방화벽 설정
Mac 시스템 환경설정:
1. 시스템 환경설정 → 보안 및 개인 정보 보호
2. 방화벽 → 방화벽 옵션
3. Ollama 허용 (포트 8080)

또는 터미널에서:
```bash
sudo pfctl -d  # 방화벽 임시 비활성화 (테스트용)
```

### 4단계: RTX 5070 서버 설정 업데이트
RTX 5070 서버에서:
```bash
# dual_node.env 편집
nano /home/ubuntu/stock_auto/dual_node.env

# MAC_STUDIO_IP를 실제 IP로 변경
MAC_STUDIO_IP=192.168.1.XXX  # 실제 Mac Studio IP
```

Mac Studio IP 확인:
```bash
# Mac Studio에서
ifconfig | grep inet
```

### 5단계: 연결 테스트
RTX 5070에서:
```bash
# 연결 테스트
curl http://[MAC_STUDIO_IP]:8080/api/tags

# 듀얼 노드 테스트
python3 /home/ubuntu/stock_auto/test_dual_node.py
```

## 📊 노드별 역할 분담

### RTX 5070 (Qwen3:14b-q4_K_M)
- **ML Specialist**: ML 모델 해석
- **Event Analyst**: 이벤트/내부자 거래 분석
- **Risk Manager**: Kelly/Beta 계산

### Mac Studio (Qwen 30B/32B)
- **Technical Analyst**: 복잡한 기술 분석
- **Quant Analyst**: 통계적 계산
- **Decision Maker**: 최종 의사결정

## 🔄 폴백 모드
Mac Studio가 오프라인일 경우:
- 모든 에이전트가 RTX 5070에서 실행
- Qwen3:14b-q4_K_M 사용 (품질 유지)
- 실행 시간은 증가하지만 정확도 유지

## ⚡ 성능 최적화

### RTX 5070 (12GB VRAM)
```bash
export OLLAMA_NUM_PARALLEL=1
export OLLAMA_MAX_LOADED_MODELS=1
```

### Mac Studio (64GB RAM)
```bash
export OLLAMA_NUM_PARALLEL=2
export OLLAMA_MAX_LOADED_MODELS=2
```

## 📈 예상 성능 개선

### 현재 (단일 노드)
- 전체 분석 시간: 60-90초
- 모든 작업 RTX 5070에서 처리
- 메모리 제약으로 순차 실행

### 듀얼 노드 활성화 시
- 전체 분석 시간: **30-40초** (50% 단축)
- 병렬 처리 가능
- 고성능 모델 사용 가능

## 🔧 문제 해결

### Mac Studio 연결 실패
1. IP 주소 확인
2. 방화벽 설정 확인
3. Ollama 서버 실행 확인
```bash
# Mac Studio에서
ps aux | grep ollama
netstat -an | grep 8080
```

### 모델 다운로드 실패
```bash
# Mac Studio에서 수동 다운로드
ollama pull qwen2.5:32b-instruct-q4_K_M
```

### 메모리 부족
- Mac Studio: 모델 크기 조정
- RTX 5070: 컨텍스트 크기 감소

## 📞 지원
문제 발생 시 다음 정보와 함께 보고:
- `dual_node_test_results.json`
- `ollama list` 출력
- 네트워크 설정 정보