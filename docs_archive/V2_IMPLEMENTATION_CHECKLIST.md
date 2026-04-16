# V2.0 구현 체크리스트

개발자용 실무 체크리스트 - 각 단계별로 체크하며 진행

---

## 🔧 사전 준비

### 개발 환경
```bash
# Python 버전 확인
□ python --version  # 3.10+ 필수

# 가상환경 활성화
□ source venv/bin/activate

# 의존성 설치
□ pip install mcp  # MCP 서버용
□ pip install --upgrade google-generativeai openai  # LLM
```

### API Keys 확인
```bash
# .env 파일 확인
□ GEMINI_API_KEY=...
□ OPENAI_API_KEY=...
□ Ollama 실행 중: curl http://localhost:11434/api/tags
```

### 기존 코드 동작 확인
```bash
# V1.0 테스트
□ python test_new_features.py  # 모든 테스트 통과
□ streamlit run webui.py  # UI 정상 동작
□ curl http://localhost:8100/  # FastAPI 응답
```

---

## 📅 Week 1: MCP 서버 구현

### Day 1-2: 기본 구조
```python
# mcp_server.py 생성
□ FastMCP import
□ local_engine 연동
□ 5개 핵심 tool 정의:
  □ analyze_stock (종합 분석)
  □ predict_ml (ML 예측)
  □ optimize_strategy (백테스트)
  □ walk_forward_test
  □ optimize_portfolio
```

### Day 3-4: 16개 도구 노출
```python
# 개별 도구 MCP tool 화
□ trend_ma_analysis
□ rsi_divergence_analysis
□ bollinger_squeeze_analysis
□ macd_momentum_analysis
□ adx_trend_strength_analysis
□ volume_profile_analysis
□ fibonacci_retracement_analysis
□ volatility_regime_analysis
□ mean_reversion_analysis
□ momentum_rank_analysis
□ support_resistance_analysis
□ correlation_regime_analysis
□ risk_position_sizing
□ kelly_criterion_analysis
□ beta_correlation_analysis
□ event_driven_analysis
```

### Day 5: 스트리밍 지원
```python
# 긴 작업 진행률 표시
□ async def 변환
□ yield로 진행 상황 전송
□ Walk-Forward에 적용
□ ML 앙상블에 적용
```

### Day 6-7: 테스트 및 연동
```bash
# 테스트 스크립트
□ test_mcp_server.py 작성
□ 21개 tool 각각 테스트
□ 에러 처리 테스트

# Claude Desktop 연동
□ claude_desktop_config.json 설정
□ Claude에서 "Analyze NVDA" 테스트
□ 응답 시간 < 30초 확인
```

### Week 1 검증
```
□ MCP 서버 단독 실행 가능
□ 모든 tool 정상 응답
□ Claude Desktop 연동 성공
□ docs/MCP_GUIDE.md 작성
```

---

## 📅 Week 2-3: 멀티에이전트

### Day 1-3: BaseAgent 구현
```python
# multi_agent.py
□ BaseAgent 클래스
  □ __init__ (name, tools, llm_provider)
  □ analyze() 메소드
  □ _build_prompt()
  □ _parse_response()

□ AgentResult dataclass
  □ agent_name
  □ signal
  □ confidence
  □ reasoning
  □ evidence
```

### Day 4-6: 전문 에이전트
```python
□ TechnicalAnalyst 클래스
  □ 6개 도구 연결
  □ Gemini LLM 사용

□ QuantAnalyst 클래스
  □ 6개 도구 연결
  □ Gemini LLM 사용

□ RiskManager 클래스
  □ 3개 도구 연결
  □ Ollama LLM 사용

□ MLSpecialist 클래스 (선택)
□ EventAnalyst 클래스 (선택)
```

### Day 7-9: Orchestrator
```python
□ MultiAgentOrchestrator 클래스
  □ 병렬 실행 (ThreadPoolExecutor)
  □ 타임아웃 처리 (60초)
  □ 실패 에이전트 skip

□ DecisionMaker 클래스
  □ aggregate() 메소드
  □ 의견 충돌 해결 로직
  □ OpenAI GPT-4o 사용
  □ 소수 의견 반영
```

### Day 10-12: 통합
```python
# local_engine.py
□ engine_multi_agent_analyze() 추가
□ 디스패처에 /multi-agent/ 라우트 추가

# webui.py
□ Multi-Agent 페이지 추가
□ Single vs Multi 비교
□ 에이전트별 의견 표시
□ 충돌 해결 과정 표시
```

### Day 13-14: 검증
```python
# 백테스트 비교
□ 100개 종목 테스트
□ Single LLM 정확도 측정
□ Multi-Agent 정확도 측정
□ 정확도 향상 > 3% 확인
```

### Week 2-3 검증
```
□ 6개 에이전트 정상 동작
□ 병렬 실행 < 120초
□ 의견 충돌 시 해결 성공
□ WebUI 비교 페이지 완성
```

---

## 📅 Week 4: 자동 리밸런싱

### Day 1-3: Rebalancer 모듈
```python
# portfolio_rebalancer.py
□ _load_rebalance_state()
□ _save_rebalance_state()
□ compute_drift()
□ should_rebalance()
□ compute_rebalancing_orders()
□ execute_rebalancing()
  □ 현재 포지션 조회
  □ 목표 비중 계산
  □ Drift 계산
  □ 주문 생성
  □ 거래비용 적용
```

### Day 4-5: 연동
```python
# local_engine.py
□ engine_portfolio_rebalance() 추가
□ 디스패처에 /portfolio/rebalance 추가
□ dry_run 파라미터 지원

# paper_trader.py
□ 리밸런싱 주문 처리
□ 거래 히스토리 기록
```

### Day 6-7: 스케줄러
```python
# scanner.py
□ scheduled_rebalance() 함수
□ APScheduler cron job 등록
  □ 매주 월요일 09:30
  □ 실행 로그 기록
□ 수동 트리거 API
```

### Week 4 검증
```
□ Dry-run 모드 테스트
□ 실제 리밸런싱 실행
□ 거래비용 정확히 계산
□ Drift 5% 시 자동 실행
□ 스케줄러 정상 동작
```

---

## 🧪 최종 통합 테스트

### 기능 테스트
```bash
# 모든 신규 기능 테스트
□ python test_v2_features.py

# 개별 모듈 테스트
□ MCP 서버 21개 tool
□ 멀티에이전트 6개
□ 리밸런싱 dry-run
□ 리밸런싱 실전
```

### 성능 테스트
```
□ MCP 응답 시간 < 30초
□ Multi-Agent < 120초
□ 리밸런싱 < 60초
□ 동시 요청 10개 처리
```

### 비용 테스트
```
□ 일일 LLM 호출 횟수 측정
□ 월간 예상 비용 < $3
□ 캐싱 적용 확인
```

---

## 📚 문서화

### 필수 문서
```
□ docs/MCP_GUIDE.md
  □ 설치 방법
  □ Claude Desktop 설정
  □ 21개 tool 설명

□ docs/MULTI_AGENT_GUIDE.md
  □ 6개 에이전트 역할
  □ 의견 조율 프로세스
  □ 비교 분석 예시

□ docs/REBALANCING_GUIDE.md
  □ 트리거 조건
  □ 거래비용 계산
  □ 스케줄 설정
```

### API 문서
```
□ /multi-agent/{ticker}
□ /portfolio/rebalance
□ 각 MCP tool 스펙
```

---

## 🚀 배포

### 사전 점검
```
□ 모든 테스트 통과
□ 문서 작성 완료
□ 코드 리뷰 완료
□ git commit & push
```

### 배포 단계
```bash
# 1. 백업
□ cp -r stock_auto stock_auto_v1_backup

# 2. 의존성 설치
□ pip install -r requirements.txt

# 3. 서비스 재시작
□ pm2 restart all  # 또는 사용 중인 프로세스 매니저

# 4. 헬스체크
□ curl http://localhost:8100/health
□ MCP 서버 응답 확인
```

### 모니터링
```
□ 에러 로그 확인
□ LLM API 사용량
□ 응답 시간 추적
□ 리밸런싱 실행 기록
```

---

## ✅ 완료 기준

### 필수 완료 항목
- [ ] MCP 서버 21개 tool 노출
- [ ] Claude Desktop 연동 확인
- [ ] 6개 멀티에이전트 구현
- [ ] 의견 충돌 해결 로직
- [ ] 자동 리밸런싱 구현
- [ ] 주간 스케줄러 동작
- [ ] 모든 테스트 통과
- [ ] 문서 작성 완료

### 성과 지표 달성
- [ ] 분석 정확도 > 60%
- [ ] 응답 시간 목표 달성
- [ ] LLM 비용 < $3/월
- [ ] 리밸런싱 자동화 95%

---

## 🔧 트러블슈팅

### 자주 발생하는 문제

**MCP 서버 연결 실패**
```bash
# 해결책
□ Python 경로 확인
□ mcp 패키지 설치 확인
□ claude_desktop_config.json 경로
```

**멀티에이전트 타임아웃**
```python
# 해결책
□ timeout=60 → 120 증가
□ 실패한 에이전트 skip 로직
□ 캐싱 적극 활용
```

**리밸런싱 주문 실패**
```python
# 해결책
□ paper_trader 상태 확인
□ 포지션 데이터 검증
□ 거래비용 계산 로직 확인
```

---

## 📞 지원

- 기술 문의: AI Team Lead
- 긴급 이슈: Slack #stock-ai-dev
- 문서: /docs 디렉토리

---

**마지막 업데이트:** 2026-04-14
**다음 리뷰:** Week 1 완료 후