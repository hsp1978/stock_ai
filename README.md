# Stock AI Analysis System V2

8개 AI 에이전트가 16개 분석 도구로 한국/미국 주식을 멀티-LLM(Gemini · GPT-4o · Ollama)으로 분석하는 듀얼 노드 플랫폼.

```
RTX 5070 (testdev)        ←Tailscale→        Mac Studio (hsptest-macstudio)
├ webui (Streamlit)                          └ Ollama heavy (qwen2.5:32b, llama3:70b)
├ agent-api (FastAPI)
└ Ollama light (qwen3:14b)
```

---

## ⚡ 빠른 시작

```bash
git clone <repo>
cd stock_auto
cp .env.example .env       # API 키 입력 (OPENAI/GEMINI/DART/FRED/FMP)
docker compose --profile dev up -d
curl http://localhost:8100/health      # {"status":"healthy","ollama":"connected", ...}
open http://localhost:8501              # Streamlit WebUI
```

호스트 Ollama(11434)와 Mac Studio Ollama(8080) 가 살아있으면 듀얼 노드, 한 쪽 죽으면 자동으로 RTX 5070 단독 모드로 폴백.

---

## 🤖 멀티에이전트 — 8개 + Decision Maker

| 에이전트 | 역할 | 라우팅 노드 | 모델 |
|---|---|---|---|
| Technical Analyst | 차트 패턴, 기술 지표 6개 | Mac Studio | qwen2.5:32b |
| Quant Analyst | 통계 모델 6개 | Mac Studio | qwen2.5:32b |
| Geopolitical Analyst | 거시/지정학 분석 | Mac Studio | qwen2.5:32b |
| Risk Manager | Kelly, ATR 포지션 사이징 | RTX 5070 | llama3.1:8b |
| ML Specialist | 5모델 앙상블 + SHAP | RTX 5070 | qwen3:14b |
| Event Analyst | 뉴스, 내부자 거래 | RTX 5070 | qwen3:14b |
| Value Investor | 재무제표, 밸류에이션 | RTX 5070 | qwen3:14b |
| **Decision Maker** | 충돌 해결 + 최종 판단 | Mac Studio | llama3:70b |

흐름: 7개 에이전트 병렬 실행 → 각자 buy/sell/neutral + confidence(0~10) → Decision Maker 가 충돌 해결 + 최종 리포트.

---

## 🔧 분석 도구 16개

### 기술적 (6)
| 도구 | 신호 |
|---|---|
| trend_ma | SMA 20/50/200 정배열 → 매수 |
| rsi_divergence | Bullish Divergence → 매수 |
| bollinger_squeeze | 스퀴즈 후 돌파 대기 |
| macd_momentum | 골든크로스 + 히스토그램↑ |
| adx_trend_strength | ADX > 25 + DI+ > DI- |
| volume_profile | 거래량↑ + 가격↑ |

### 퀀트 (6)
| 도구 | 신호 |
|---|---|
| fibonacci_retracement | 38.2% 되돌림 후 반등 |
| volatility_regime | 저변동성 → 돌파 대기 |
| mean_reversion | Z < -2 → 매수 |
| momentum_rank | 3개월 > 1개월 모멘텀 |
| support_resistance | 지지선 근처 반등 |
| correlation_regime | Hurst > 0.5 → 추세 지속 |

### 리스크/이벤트 (4)
| 도구 | 신호 |
|---|---|
| risk_position_sizing | ATR 기반 최적 수량 |
| kelly_criterion | 승률·손익비 기반 비중 |
| beta_correlation | 시장 민감도 |
| event_driven | 뉴스 + 매크로 종합 |

---

## 🧠 ML 앙상블

5 모델: **RandomForest · GradientBoosting · LightGBM · XGBoost · LSTM**

성능 기반 가중 평균 + voting + 모델 간 합의도(confidence). SHAP 으로 feature importance 설명. HyperOpt(Optuna) 으로 파라미터 자동 탐색, Walk-Forward(Rolling 학습/테스트) 로 과적합 검증.

---

## 📊 백테스트

4 전략: SMA Cross · RSI Reversion · Bollinger Reversion · Composite(16 도구 종합).

```
HyperOpt 결과 예시:
  Sharpe Ratio: 2.34, CAGR: 28.5%, Max DD: -12.3%
Walk-Forward (3 split 평균):
  Sharpe: 1.93, 과적합 비율: 1.15 (< 1.5 양호)
```

---

## 🔌 MCP 서버 (Claude Desktop 연동)

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

기본 6 도구 (`mcp_server.py`) 또는 확장 21 도구 (`mcp_server_extended.py`). 상세: [`docs/v2/MCP_GUIDE.md`](docs/v2/MCP_GUIDE.md).

---

## 🚀 운영

```bash
docker compose --profile dev up -d       # 기동
docker compose ps                         # 상태
docker compose logs -f agent-api          # 로그
docker compose --profile dev down         # 종료
docker compose --profile dev build        # 코드 변경 후 재빌드
```

검증:
```bash
curl http://localhost:8100/health                       # agent-api
curl http://localhost:8100/api/tags 2>/dev/null         # Ollama 연결
docker exec stock-auto-webui python -c \
  "import sys; sys.path.insert(0,'/app/stock_analyzer'); \
   from dual_node_config import is_mac_studio_available; \
   print(is_mac_studio_available())"                    # Mac Studio 라우팅
```

---

## 🌐 Mac Studio 듀얼 노드

Tailscale MagicDNS 로 `hsptest-macstudio:8080` 직결. Mac Studio 측은 Homebrew Ollama (`OLLAMA_HOST=0.0.0.0:8080`) 또는 Docker (compose `mac` 프로파일) 둘 다 가능. 자세한 셋업: [`docs/PHASE_1_MAC_STUDIO.md`](docs/PHASE_1_MAC_STUDIO.md), 운영: [`docs/PHASE_3_OPERATION.md`](docs/PHASE_3_OPERATION.md).

Mac Studio 끄면 자동으로 RTX 5070 단독 모드 (Decision Maker 도 RTX 로 폴백, 큰 모델 + 2배 timeout).

---

## 🏗️ 디렉토리 구조

```
.env  .env.example  compose.yaml  .dockerignore
mcp_server.py  mcp_server_extended.py
chart_agent_service/      # FastAPI agent-api
  config.py               # Pydantic Settings 60필드 + Literal/범위 검증
  service.py  analysis_tools.py  data_collector.py
  backtest_engine.py  ml_predictor.py  paper_trader.py
  brokers/  data_sources/  execution/  risk_management/
stock_analyzer/           # Streamlit webui + scanner
  webui.py  multi_agent.py  scanner.py  local_engine.py
  dual_node_config.py     # 8 agent 라우팅 + 폴백
docs/                     # 운영/배포 문서
archive/                  # legacy scripts/docs/setup
```

---

## 📚 문서

- [`docs/DEPLOY_BASELINE.md`](docs/DEPLOY_BASELINE.md) — 배포 리팩토링 4-Phase 기록 + 게이트
- [`docs/PHASE_1_MAC_STUDIO.md`](docs/PHASE_1_MAC_STUDIO.md) — Mac Studio Tailscale 셋업
- [`docs/PHASE_3_OPERATION.md`](docs/PHASE_3_OPERATION.md) — Compose 운영 가이드
- [`docs/USER_MANUAL.md`](docs/USER_MANUAL.md) — WebUI 사용법
- [`docs/v2/MCP_GUIDE.md`](docs/v2/MCP_GUIDE.md) — MCP 21 도구

---

## 🔄 버전 히스토리

- **V2.1** (2026-04-29) — 배포 리팩토링: Tailscale 호스트네임, Pydantic Settings 통합, Docker Compose, 루트 60+ 파일 archive
- **V2.0** (2026-04-14) — 멀티에이전트 8개, MCP 서버 21 도구, ML 앙상블 + SHAP, HyperOpt, Walk-Forward, Trailing Stop, 주간 트렌드 DB
- **V1.2** (2025-04-08) — 시장 지수 10개 대시보드
- **V1.1** (2025-04-08) — 16-도구 + FRED 매크로
- **V1.0** (2025-04-08) — 12-도구 + GPT-4o + Ollama + Streamlit

---

## 📝 라이선스

MIT
