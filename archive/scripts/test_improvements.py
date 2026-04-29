#!/usr/bin/env python3
"""
시스템 개선사항 테스트
9개 합의 개선안이 정상 적용되었는지 검증
"""

import sys
import json
from datetime import datetime

def test_improvements(ticker="PLTR"):
    """개선사항 적용 확인 테스트"""

    print(f"\n{'='*70}")
    print(f"시스템 개선사항 검증 - {ticker}")
    print(f"시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*70}\n")

    try:
        # 1. ML Specialist의 정확도 50% 미만 처리 테스트
        print("[1] ML Specialist 정확도 체크...")
        from stock_analyzer.multi_agent import MLSpecialist
        from chart_agent_service.analysis_tools import AnalysisTools
        from data_collector import fetch_ohlcv, calculate_indicators

        df = fetch_ohlcv(ticker)
        df = calculate_indicators(df)
        tools = AnalysisTools(ticker, df)

        ml_agent = MLSpecialist()
        ml_result = ml_agent.analyze(ticker, tools)

        # ML 결과 확인
        if "45.5%" in ml_result.reasoning or "50% 미만" in ml_result.reasoning:
            print("  ✅ ML 정확도 50% 미만 무시 규칙 적용됨")
            print(f"  → 신뢰도: {ml_result.confidence}, Signal: {ml_result.signal}")
        else:
            print(f"  ℹ️ ML reasoning: {ml_result.reasoning[:100]}...")

        # 2. Kelly 50% 상한 체크
        print("\n[2] Kelly Criterion 50% 상한 체크...")
        kelly_result = tools.kelly_criterion_analysis()

        if 'kelly_cap_pct' in kelly_result:
            print(f"  ✅ Kelly 상한 적용: {kelly_result['kelly_cap_pct']}%")
            print(f"  → Raw: {kelly_result.get('kelly_raw_pct')}%, Final: {kelly_result['optimal_position_pct']}%")

        # 3. MA Breakout + Volume 체크
        print("\n[3] MA Breakout + 거래량 체크...")
        ma_result = tools.trend_ma_analysis()

        if 'volume_ratio' in ma_result:
            print(f"  ✅ 거래량 비율: {ma_result['volume_ratio']}x")
            if ma_result.get('volume_warning'):
                print(f"  → 경고: {ma_result['volume_warning']}")

        # 4. R/R min() 체크
        print("\n[4] Risk/Reward min() 적용...")
        rr_result = tools.risk_position_sizing()

        if 'final_levels' in rr_result and 'effective_rr' in rr_result['final_levels']:
            print(f"  ✅ Effective R/R: {rr_result['final_levels']['effective_rr']}")
            print(f"  → Method: {rr_result['final_levels']['rr_method']}")

        # 5. Volume 시간프레임 명시
        print("\n[5] Volume 시간프레임...")
        vol_result = tools.volume_profile_analysis()

        if 'timeframe' in vol_result:
            print(f"  ✅ Timeframe: {vol_result['timeframe']}")
            print(f"  → SMA Period: {vol_result.get('volume_sma_period')}일")

        # 6. Enhanced Decision Maker의 Fundamental 체크
        print("\n[6] Fundamental Risks 체크...")
        from stock_analyzer.enhanced_decision_maker import EnhancedDecisionMaker
        dm = EnhancedDecisionMaker()

        fundamental_risks = dm._check_fundamental_risks(ticker)

        if fundamental_risks:
            print(f"  ✅ Beta: {fundamental_risks.get('beta')}")
            print(f"  ✅ P/E: {fundamental_risks.get('pe_trailing')}")
            print(f"  ✅ 52주 하락률: {fundamental_risks.get('week52_decline'):.1f}%" if fundamental_risks.get('week52_decline') else "  ✅ 52주 하락률: N/A")

            if fundamental_risks.get('critical_risks'):
                print(f"  ⚠️ Critical Risks:")
                for risk in fundamental_risks['critical_risks']:
                    print(f"    - {risk}")

            if fundamental_risks.get('warnings'):
                print(f"  ⚠️ Warnings:")
                for warning in fundamental_risks['warnings'][:3]:  # 최대 3개만
                    print(f"    - {warning}")

        # 7. 전체 Multi-Agent 실행
        print(f"\n[7] 전체 Multi-Agent 시스템 실행...")
        from stock_analyzer.multi_agent import MultiAgentOrchestrator

        orchestrator = MultiAgentOrchestrator()
        full_result = orchestrator.analyze(ticker)

        if 'error' in full_result:
            print(f"  ❌ 오류: {full_result['error']}")
        else:
            print(f"  ✅ 최종 신호: {full_result['final_decision']['final_signal']}")
            print(f"  ✅ 신뢰도: {full_result['final_decision']['final_confidence']}")

            # Reasoning 길이 체크
            for agent_result in full_result.get('agent_results', []):
                reasoning = agent_result.get('reasoning', '')
                sentences = [s.strip() for s in reasoning.split('.') if s.strip()]
                if len(sentences) < 3 and not agent_result.get('error'):
                    print(f"  ⚠️ {agent_result['agent']}: reasoning {len(sentences)}문장 (최소 3문장 미달)")

            # Fundamental risks 체크
            if 'fundamental_risks' in full_result.get('final_decision', {}):
                print("  ✅ Fundamental risks가 최종 결정에 포함됨")

        print(f"\n{'='*70}")
        print("검증 완료!")
        print(f"{'='*70}\n")

        return full_result

    except Exception as e:
        print(f"\n❌ 테스트 실패: {str(e)}")
        import traceback
        traceback.print_exc()
        return None


if __name__ == "__main__":
    ticker = sys.argv[1] if len(sys.argv) > 1 else "PLTR"
    result = test_improvements(ticker)

    if result and 'error' not in result:
        # 결과 저장
        filename = f"improvements_test_{ticker}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"\n결과 저장: {filename}")