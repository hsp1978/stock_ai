# 치명적 버그 수정 보고서
## 002810.KS (삼영무역) 분석에서 발견된 문제 해결

### 발생일: 2026-04-23
### 보고자: 사용자
### 수정자: Claude

---

## 🔴 발견된 치명적 버그

### 1. **0명 매수인데 "buy" 신호 출력**
- **증상**: 모든 에이전트가 neutral (0.0/10)인데 최종 신호가 "buy"
- **원인**: 에이전트 전원 장애 시 V1 지표 점수만으로 매수 신호 생성
- **위험도**: **CRITICAL** - 실전에서 손실 직결 가능

### 2. **에이전트 전원 장애 무시**
- **증상**: 7개 에이전트 모두 "LLM 서비스 일시 장애"
- **원인**: valid_agents == 0 체크 누락
- **위험도**: **HIGH** - 분석 신뢰성 완전 상실

### 3. **리스크 "특별한 리스크 없음" 오표시**
- **증상**: 시스템 전체 장애인데 "특별한 리스크 없음"
- **원인**: 에이전트 실패를 리스크로 간주하지 않음
- **위험도**: **MEDIUM** - 잘못된 안심 유도

---

## ✅ 적용된 수정사항

### 1. **enhanced_decision_maker.py 수정**

#### A. 에이전트 실패 추적 강화 (54-84줄)
```python
# [수정 전]
for result in agent_results:
    if result.error:
        continue
    valid_agents += 1

# [수정 후]
for result in agent_results:
    if result.error:
        failed_agents.append(result.agent_name)
        continue

    # confidence 0.0인 경우도 실패로 간주
    if result.confidence > 0:
        valid_agents += 1
    else:
        failed_agents.append(f"{result.agent_name} (0.0 confidence)")
```

#### B. 전원 장애 시 즉시 리턴 (113-131줄)
```python
# 에이전트 전원 장애 체크
if valid_agents == 0:
    return {
        "final_signal": "neutral",
        "final_confidence": 0.0,
        "consensus": f"0명 매수, 0명 매도, {len(agent_results)}명 중립 (전원 장애)",
        "reasoning": f"모든 에이전트 분석 실패: {', '.join(failed_agents[:3])}...",
        "key_risks": ["전체 LLM 서비스 장애", "분석 완전 무효"],
        "warnings": ["⚠️ 전체 에이전트 장애로 V2 분석 무효. V1 지표만 참고하세요."],
        "system_failure": True
    }
```

#### C. 0명 매수 → buy 차단 (550-616줄)
```python
# 0명 매수인데 buy 신호 방지
if signal_counts["buy"] == 0 and signal_counts["sell"] == 0:
    return {
        "signal": "neutral",
        "confidence": 2.0,
        "reasoning": f"모든 에이전트가 중립 의견 ({signal_counts['neutral']}명)",
        "risks": ["방향성 부재", "신호 약함"]
    }

# 추가 검증: 최종 차단
if signal_counts["buy"] == 0 and base_signal == "buy":
    base_signal = "neutral"
    strength_level = "very_weak"
```

### 2. **multi_agent.py 수정**

#### A. Ollama 헬스체크 추가 (1365-1390줄)
```python
def _check_ollama_health(self) -> bool:
    """Ollama 서버 상태 체크"""
    try:
        response = requests.get("http://localhost:11434/api/tags", timeout=3)
        if response.status_code == 200:
            tags = response.json().get('models', [])
            if len(tags) > 0:
                print(f"  ✅ Ollama 서버 정상 ({len(tags)}개 모델)")
                return True
        print("  ❌ Ollama 서버 장애")
        return False
    except:
        return False
```

#### B. 분석 시작 전 경고 (1474-1479줄)
```python
# Ollama 장애 시 경고
if not self.ollama_healthy:
    warnings.append("⚠️ Ollama 서버 장애로 에이전트 실패 예상")
    print("  ⚠️ 경고: Ollama 서버 장애 감지")
```

---

## 🧪 검증 방법

### 테스트 스크립트
`/home/ubuntu/stock_auto/test_002810_fix.py`

### 검증 항목
- [x] 에이전트 전원 장애 감지
- [x] 0명 매수 → buy 방지
- [x] Ollama 헬스체크
- [x] 시스템 장애 경고 표시
- [x] 중립 신호 정상 출력

---

## 📊 수정 전후 비교

### 수정 전
```
의견 분포: 0명 매수, 0명 매도, 6명 중립
최종 신호: buy ← 버그!
신뢰도: 5.0/10
리스크: "특별한 리스크 없음"
```

### 수정 후
```
의견 분포: 0명 매수, 0명 매도, 6명 중립 (전원 장애)
최종 신호: neutral ← 정상
신뢰도: 0.0/10
리스크: ["전체 LLM 서비스 장애", "분석 완전 무효"]
경고: "⚠️ 전체 에이전트 장애로 V2 분석 무효"
```

---

## 🚨 권장 추가 조치

### 즉시 (P0)
- [x] 프로덕션 배포 전 필수 적용
- [x] 기존 분석 리포트 재검토
- [ ] alert 시스템 연동

### 단기 (P1)
- [ ] Ollama 대체 LLM 자동 전환
- [ ] 에이전트별 재시도 로직
- [ ] 실시간 모니터링 대시보드

### 중기 (P2)
- [ ] 에이전트 투표 가중치 시스템
- [ ] 부분 장애 허용 로직
- [ ] 과거 장애 패턴 학습

---

## 📝 교훈

1. **Fail-Safe 원칙**: 불확실할 때는 중립
2. **명시적 검증**: 모든 가정에 assert
3. **장애 투명성**: 문제를 숨기지 말고 명확히 표시
4. **다수결 ≠ 점수**: 에이전트 의견과 지표 점수는 독립적

---

## 결론

**002810.KS 분석에서 발견된 "0명 매수 → buy" 버그는 완전히 수정되었습니다.**

이제 시스템은:
- 에이전트 전원 장애를 정확히 감지
- 무효한 매수/매도 신호를 차단
- 사용자에게 명확한 경고 제공
- V1/V2 분리하여 fallback 제공

**이 수정은 실전 손실을 방지할 수 있는 매우 중요한 개선입니다.**