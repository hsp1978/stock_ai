# Stock AI Agent MCP Server Guide

## 개요

Stock AI Agent를 MCP (Model Context Protocol) 서버로 실행하여 Claude Desktop, ChatGPT, 기타 AI 에이전트에서 직접 호출 가능합니다.

## 서버 실행

```bash
# 기본 서버 (6개 도구)
python mcp_server.py

# 확장 서버 (21개 도구)
python mcp_server_extended.py
```

## 사용 가능한 도구 (21개)

### 핵심 도구 (5개)

1. **analyze_stock**
   - 설명: 16개 기술적 분석 도구를 사용한 종합 분석
   - 파라미터: `ticker` (예: "NVDA")
   - 반환: 매수/매도/관망 신호, 점수, 신뢰도

2. **predict_ml**
   - 설명: ML 앙상블 예측 (LightGBM, XGBoost, LSTM)
   - 파라미터: `ticker`, `ensemble` (기본값: true)
   - 반환: 가격 방향 예측, SHAP 설명력

3. **optimize_strategy**
   - 설명: Optuna를 사용한 백테스트 전략 최적화
   - 파라미터: `ticker`, `strategy`, `n_trials`
   - 반환: 최적 파라미터, Sharpe ratio

4. **walk_forward_test**
   - 설명: Walk-forward 백테스트로 과적합 검출
   - 파라미터: `ticker`, `strategy`, `n_splits`
   - 반환: 분할별 성과, 과적합 비율

5. **optimize_portfolio**
   - 설명: 포트폴리오 최적화 (Markowitz/Risk Parity)
   - 파라미터: `method` (markowitz/risk_parity)
   - 반환: 최적 비중, 예상 수익/리스크

### 개별 분석 도구 (16개)

| 도구명 | 설명 |
|--------|------|
| analyze_trend_ma | 이동평균 추세 분석 |
| analyze_rsi_divergence | RSI 다이버전스 감지 |
| analyze_bollinger_squeeze | 볼린저밴드 스퀴즈 |
| analyze_macd_momentum | MACD 모멘텀 분석 |
| analyze_adx_trend_strength | ADX 추세 강도 |
| analyze_volume_profile | 거래량 프로파일 |
| analyze_fibonacci_retracement | 피보나치 되돌림 |
| analyze_volatility_regime | 변동성 체제 분류 |
| analyze_mean_reversion | 평균회귀 기회 |
| analyze_momentum_rank | 모멘텀 순위 |
| analyze_support_resistance | 지지/저항선 |
| analyze_correlation_regime | 상관관계 분석 |
| analyze_risk_position_sizing | 리스크 기반 포지션 |
| analyze_kelly_criterion | 켈리 기준 최적 베팅 |
| analyze_beta_correlation | 베타/시장 상관성 |
| analyze_event_driven | 이벤트 기반 분석 |

### 시스템 도구 (1개)

- **get_system_info**: 시스템 상태 및 기능 정보

## Claude Desktop 설정

### macOS

1. Claude Desktop 설치: https://claude.ai/download

2. 설정 파일 생성:
```bash
nano ~/Library/Application\ Support/Claude/claude_desktop_config.json
```

3. 설정 내용:
```json
{
  "mcpServers": {
    "stock-ai": {
      "command": "python",
      "args": ["/home/ubuntu/stock_auto/mcp_server_extended.py"]
    }
  }
}
```

4. Claude Desktop 재시작

### 사용 예시

Claude Desktop에서:

```
"NVDA 주식 분석해줘"
→ analyze_stock 자동 호출

"NVDA의 머신러닝 예측 결과 보여줘"
→ predict_ml 자동 호출

"내 포트폴리오 최적화해줘"
→ optimize_portfolio 자동 호출
```

## Python에서 직접 테스트

```python
# 간단 테스트
python test_mcp_server.py --simple

# 전체 테스트
python test_mcp_server.py
```

## JSON-RPC 직접 호출

```python
import json
import subprocess

# 서버 시작
process = subprocess.Popen(
    ["python", "mcp_server_extended.py"],
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    text=True
)

# 도구 호출
request = {
    "jsonrpc": "2.0",
    "method": "tools/call",
    "params": {
        "name": "analyze_stock",
        "arguments": {"ticker": "NVDA"}
    },
    "id": 1
}

process.stdin.write(json.dumps(request) + "\n")
response = json.loads(process.stdout.readline())
print(response)
```

## 트러블슈팅

### MCP 서버 실행 오류

```bash
# Python 경로 확인
which python

# 가상환경 활성화
source /home/ubuntu/stock_auto/venv/bin/activate

# 의존성 확인
pip list | grep mcp
```

### Claude Desktop 연결 실패

1. 설정 파일 경로 확인
2. Python 절대 경로 사용
3. 로그 확인: `~/Library/Logs/Claude/`

### 도구 실행 오류

```python
# 직접 테스트
from stock_analyzer.local_engine import engine_scan_ticker
result = engine_scan_ticker("NVDA")
print(result)
```

## 성능 최적화

- **캐싱**: 1시간 동안 동일 종목 캐시
- **병렬 처리**: 개별 도구는 독립적으로 실행
- **타임아웃**: 각 도구 60초 제한

## 보안

- API key는 .env 파일에 저장
- 로컬 네트워크에서만 실행
- 민감한 데이터는 로그에 기록 안 함

## 다음 단계

Week 2-3: 멀티에이전트 시스템 구현
- 6개 전문 에이전트 추가
- 병렬 실행 및 의견 조율
- Decision Maker 구현