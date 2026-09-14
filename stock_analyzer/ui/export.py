"""리포트 원본 내보내기 — 대시보드·상세 두 페이지가 같은 함수를 쓴다.

`webui.py` 분해 (CLAUDE.md §6-10). 페이지보다 먼저 내보낸다.
"""

from __future__ import annotations

from datetime import datetime

from ui.api_client import api_get


def export_comprehensive_data(ticker: str, include_multi_agent: bool = True) -> dict:
    """
    종목의 모든 분석 데이터를 수집하여 export용 dict 반환
    - Single LLM (V1.0) 결과
    - Multi-Agent (V2.0) 결과
    - 백테스트 결과
    - ML 예측 결과
    """
    export_data = {
        "ticker": ticker,
        "export_timestamp": datetime.now().isoformat(),
        "version": "2.0"
    }

    # 1. Single LLM 분석 결과
    single_result = api_get(f"/results/{ticker}")
    if single_result:
        export_data["single_llm_analysis"] = {
            "final_signal": single_result.get("final_signal"),
            "composite_score": single_result.get("composite_score"),
            "confidence": single_result.get("confidence"),
            "signal_distribution": single_result.get("signal_distribution"),
            "tool_summaries": single_result.get("tool_summaries", []),
            "tool_details": single_result.get("tool_details", []),
            "llm_conclusion": single_result.get("llm_conclusion"),
            "analyzed_at": single_result.get("analyzed_at")
        }

    # 2. Multi-Agent 분석 결과 (옵션)
    if include_multi_agent:
        # 8개 에이전트 병렬 LLM 호출. 백엔드 MULTI_AGENT_TIMEOUT(기본 600s)보다 약간 더 길게.
        multi_result = api_get(f"/multi-agent/{ticker}", timeout=660)
        if multi_result and not multi_result.get("error"):
            export_data["multi_agent_analysis"] = {
                "ticker": multi_result.get("ticker"),
                "multi_agent_mode": multi_result.get("multi_agent_mode"),
                "agent_results": multi_result.get("agent_results", []),
                "final_decision": multi_result.get("final_decision"),
                "total_execution_time": multi_result.get("total_execution_time"),
                "timestamp": multi_result.get("timestamp")
            }

    # 3. 백테스트 결과
    backtest_result = api_get(f"/backtest/{ticker}")
    if backtest_result:
        export_data["backtest"] = backtest_result

    # 4. ML 예측 결과
    ml_result = api_get(f"/ml/{ticker}")
    if ml_result:
        export_data["ml_prediction"] = ml_result

    # 5. 펀더멘털 데이터
    if single_result:
        export_data["fundamentals"] = single_result.get("fundamentals", {})
        export_data["options_pcr"] = single_result.get("options_pcr", {})
        export_data["insider_trades"] = single_result.get("insider_trades", [])

    return export_data
