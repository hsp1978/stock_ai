#!/usr/bin/env python3
"""
통합 ML Specialist 테스트
실제 BAC 데이터로 전체 분석 파이프라인 실행
"""

import sys
import os
import json
import time

# 프로젝트 경로 설정
sys.path.insert(0, '/home/ubuntu/stock_auto')
sys.path.insert(0, '/home/ubuntu/stock_auto/stock_analyzer')
sys.path.insert(0, '/home/ubuntu/stock_auto/chart_agent_service')

from multi_agent import MLSpecialist
from data_collector import fetch_ohlcv, calculate_indicators
from analysis_tools import AnalysisTools

def test_integrated_ml():
    """통합 ML Specialist 테스트"""

    print("=" * 70)
    print("통합 ML Specialist 테스트 (BAC)")
    print("=" * 70)

    ticker = "BAC"

    # 1. 데이터 수집
    print(f"\n1. {ticker} 데이터 수집 중...")
    df = fetch_ohlcv(ticker)
    df = calculate_indicators(df)
    tools = AnalysisTools(ticker, df)

    # 2. ML Specialist 실행
    print("\n2. ML Specialist 실행 (Qwen 14B)...")
    ml_agent = MLSpecialist()

    start_time = time.time()
    result = ml_agent.analyze(ticker, tools)
    execution_time = time.time() - start_time

    # 3. 결과 출력
    print("\n3. 분석 결과:")
    print("-" * 60)
    print(f"   에이전트: {result.agent_name}")
    print(f"   신호: {result.signal}")
    print(f"   신뢰도: {result.confidence}/10")
    print(f"   실행 시간: {execution_time:.2f}초")
    print(f"\n   판단 근거:")
    print(f"   {result.reasoning}")

    # 4. 증거 데이터 확인
    if result.evidence:
        print("\n4. ML 예측 상세:")
        print("-" * 60)
        for evidence in result.evidence:
            if evidence.get('tool') == 'ml_ensemble':
                ml_result = evidence.get('result', {})
                ensemble = ml_result.get('ensemble', {})
                models = ml_result.get('models', {})

                print(f"   앙상블 예측: {ensemble.get('signal', 'N/A')}")
                print(f"   상승 확률: {ensemble.get('up_probability', 0):.1%}")
                print(f"   평균 신뢰도: {ensemble.get('confidence', 0):.2f}")

                print("\n   모델별 정확도:")
                for model_name, model_data in models.items():
                    accuracy = model_data.get('test_accuracy', 0)
                    prediction = model_data.get('prediction', 'N/A')
                    print(f"     - {model_name}: {accuracy:.1%} (예측: {prediction})")

                backtest = ml_result.get('backtest', {})
                if backtest:
                    print(f"\n   백테스트 결과:")
                    print(f"     - 총 수익률: {backtest.get('total_return', 0):.1%}")
                    print(f"     - Sharpe Ratio: {backtest.get('sharpe_ratio', 0):.2f}")
                    print(f"     - 최대 손실: {backtest.get('max_drawdown', 0):.1%}")
                    print(f"     - 거래 횟수: {backtest.get('n_trades', 0)}회")

    # 5. 품질 평가
    print("\n5. 품질 평가:")
    print("-" * 60)

    quality_score = 0
    quality_notes = []

    # 신호 일관성 체크
    if result.signal in ['buy', 'sell', 'neutral']:
        quality_score += 2
        quality_notes.append("✅ 유효한 신호")
    else:
        quality_notes.append("❌ 무효한 신호")

    # 신뢰도 범위 체크
    if 0 <= result.confidence <= 10:
        quality_score += 2
        quality_notes.append(f"✅ 신뢰도 적절 ({result.confidence}/10)")
    else:
        quality_notes.append("❌ 신뢰도 범위 초과")

    # 근거 품질 체크
    if len(result.reasoning) > 50:
        quality_score += 2
        quality_notes.append(f"✅ 상세한 근거 ({len(result.reasoning)}자)")
    else:
        quality_notes.append("❌ 근거 부족")

    # 실행 시간 체크
    if execution_time < 10:
        quality_score += 1
        quality_notes.append(f"✅ 실행 시간 양호 ({execution_time:.1f}초)")
    else:
        quality_notes.append(f"⚠️ 실행 시간 초과 ({execution_time:.1f}초)")

    # BAC에 대한 예상 결과와 비교
    if result.signal == 'sell' and result.confidence >= 6:
        quality_score += 3
        quality_notes.append("✅ BAC 분석 정확 (매도 + 높은 신뢰도)")
    elif result.signal == 'sell':
        quality_score += 2
        quality_notes.append("⚠️ BAC 신호는 맞지만 신뢰도 낮음")
    else:
        quality_notes.append(f"❌ BAC 분석 부정확 (예상: sell, 실제: {result.signal})")

    print(f"   품질 점수: {quality_score}/10")
    for note in quality_notes:
        print(f"   {note}")

    # 6. 최종 평가
    print("\n" + "=" * 70)
    print("최종 평가")
    print("=" * 70)

    if quality_score >= 8:
        print("✅ 우수: Qwen 14B가 높은 품질의 ML 분석을 제공합니다.")
    elif quality_score >= 6:
        print("⚠️ 양호: 기본적인 분석은 가능하나 개선 여지가 있습니다.")
    else:
        print("❌ 미흡: 추가 조정이 필요합니다.")

    print(f"\n실행 시간: {execution_time:.2f}초")
    if execution_time < 3:
        print("   → 목표(3초) 달성 ✅")
    elif execution_time < 6:
        print("   → 허용 범위(6초) 내 ⚠️")
    else:
        print("   → 개선 필요 ❌")

    # 결과 저장
    result_data = {
        "ticker": ticker,
        "agent": result.agent_name,
        "signal": result.signal,
        "confidence": result.confidence,
        "reasoning": result.reasoning,
        "execution_time": execution_time,
        "quality_score": quality_score,
        "quality_notes": quality_notes,
        "llm_provider": result.llm_provider
    }

    with open("/home/ubuntu/stock_auto/integrated_ml_result.json", "w", encoding='utf-8') as f:
        json.dump(result_data, f, indent=2, ensure_ascii=False)

    print("\n결과가 integrated_ml_result.json에 저장되었습니다.")

    return result_data

if __name__ == "__main__":
    test_integrated_ml()