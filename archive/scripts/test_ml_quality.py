#!/usr/bin/env python3
"""
ML Specialist 품질 테스트 - 속도보다 정확도/품질 중심
"""

import os
import sys
import time
import json
import requests

# 프로젝트 경로 설정
sys.path.insert(0, '/home/ubuntu/stock_auto')
sys.path.insert(0, '/home/ubuntu/stock_auto/chart_agent_service')

def parse_json_response(response_text):
    """JSON 응답 파싱"""
    try:
        # JSON 블록 추출
        if "```json" in response_text:
            json_start = response_text.find("```json") + 7
            json_end = response_text.find("```", json_start)
            json_str = response_text[json_start:json_end].strip()
        elif "{" in response_text and "}" in response_text:
            # 첫 번째 { 부터 마지막 } 까지 추출
            json_start = response_text.find("{")
            json_end = response_text.rfind("}") + 1
            json_str = response_text[json_start:json_end]
        else:
            return None

        return json.loads(json_str)
    except:
        return None

def test_ml_quality():
    """ML Specialist 품질 비교 테스트"""

    # 복잡한 테스트 시나리오들
    test_cases = [
        {
            "name": "BAC - 내부자 매도 + ML 매도 신호",
            "prompt": """당신은 ML Specialist 전문가입니다.
BAC 종목의 머신러닝 분석 결과를 해석하세요.

## ML 예측 결과
- 앙상블 예측: sell (매도)
- 상승 확률: 46.0%
- RandomForest: 매도 (정확도 40%)
- XGBoost: 매도 (정확도 46%)
- LSTM: 매도 (정확도 54%)
- LightGBM: 매도 (정확도 52%)
- CatBoost: 중립 (정확도 48%)

## 백테스트 결과
- 총 수익률: 3.4%
- Sharpe Ratio: 0.67
- 최대 손실: -8.2%
- 거래 횟수: 35회
- 승률: 45.7%

## 추가 컨텍스트
- CEO/CFO가 최근 30일간 100만주 매도
- RSI 73.5 (과매수)
- 52주 최고가 대비 -5.6%

다음 JSON 형식으로 응답하세요:
{
  "signal": "buy/sell/neutral",
  "confidence": 0-10,
  "reasoning": "판단 근거 (핵심 포인트 포함)"
}"""
        },
        {
            "name": "NVDA - 상충되는 신호",
            "prompt": """당신은 ML Specialist 전문가입니다.
NVDA 종목의 머신러닝 분석 결과를 해석하세요.

## ML 예측 결과
- 앙상블 예측: buy (매수)
- 상승 확률: 68.5%
- RandomForest: 매수 (정확도 62%)
- XGBoost: 매수 (정확도 71%)
- LSTM: 매도 (정확도 45%)
- LightGBM: 매수 (정확도 69%)
- CatBoost: 매수 (정확도 65%)

## 백테스트 결과
- 총 수익률: 156.3%
- Sharpe Ratio: 1.89
- 최대 손실: -28.5%
- 거래 횟수: 89회
- 승률: 58.4%

## 모델 신뢰도 분석
- 고정확도 모델(60%+): 4개 모두 매수
- 저정확도 모델(<50%): 1개 매도
- 앙상블 일치도: 80%

다음 JSON 형식으로 응답하세요:
{
  "signal": "buy/sell/neutral",
  "confidence": 0-10,
  "reasoning": "판단 근거 (모델 정확도 가중치 반영)"
}"""
        },
        {
            "name": "TSLA - 높은 변동성",
            "prompt": """당신은 ML Specialist 전문가입니다.
TSLA 종목의 머신러닝 분석 결과를 해석하세요.

## ML 예측 결과
- 앙상블 예측: neutral (중립)
- 상승 확률: 51.2%
- RandomForest: 매수 (정확도 38%)
- XGBoost: 매도 (정확도 41%)
- LSTM: 중립 (정확도 49%)
- LightGBM: 매수 (정확도 44%)
- CatBoost: 매도 (정확도 43%)

## 백테스트 결과
- 총 수익률: -12.4%
- Sharpe Ratio: -0.31
- 최대 손실: -48.2%
- 거래 횟수: 127회
- 승률: 42.3%

## 특이사항
- 모든 모델 정확도 50% 미만
- 극도로 높은 변동성 (일일 변동 5%+)
- 백테스트 성과 부정적

다음 JSON 형식으로 응답하세요:
{
  "signal": "buy/sell/neutral",
  "confidence": 0-10,
  "reasoning": "판단 근거 (낮은 정확도와 높은 리스크 반영)"
}"""
        }
    ]

    print("=" * 70)
    print("ML Specialist 품질 비교 테스트")
    print("=" * 70)

    results = {}

    for test_case in test_cases:
        print(f"\n### 시나리오: {test_case['name']}")
        print("-" * 60)

        case_results = {}

        # 1. 기존 모델 (llama3.1:8b)
        print("\n1. Llama 3.1 8B 분석:")
        try:
            start = time.time()
            response = requests.post(
                "http://localhost:11434/api/generate",
                json={
                    "model": "llama3.1:8b",
                    "prompt": test_case['prompt'],
                    "stream": False,
                    "options": {"temperature": 0.3}
                },
                timeout=60
            )
            llama_time = time.time() - start
            llama_response = response.json().get('response', '')
            llama_parsed = parse_json_response(llama_response)

            if llama_parsed:
                print(f"   신호: {llama_parsed.get('signal', 'N/A')}")
                print(f"   신뢰도: {llama_parsed.get('confidence', 0)}/10")
                print(f"   근거: {llama_parsed.get('reasoning', 'N/A')[:150]}...")
                print(f"   실행 시간: {llama_time:.2f}초")
                case_results['llama'] = llama_parsed
                case_results['llama']['time'] = llama_time
            else:
                print("   파싱 실패")
                case_results['llama'] = {'error': 'parsing failed', 'raw': llama_response[:200]}
        except Exception as e:
            print(f"   오류: {e}")
            case_results['llama'] = {'error': str(e)}

        # 2. 새 모델 (qwen2.5:14b)
        print("\n2. Qwen 2.5 14B 분석:")
        try:
            start = time.time()
            response = requests.post(
                "http://localhost:11434/api/generate",
                json={
                    "model": "qwen2.5:14b-instruct-q4_K_M",
                    "prompt": test_case['prompt'],
                    "stream": False,
                    "options": {"temperature": 0.3}
                },
                timeout=60
            )
            qwen_time = time.time() - start
            qwen_response = response.json().get('response', '')
            qwen_parsed = parse_json_response(qwen_response)

            if qwen_parsed:
                print(f"   신호: {qwen_parsed.get('signal', 'N/A')}")
                print(f"   신뢰도: {qwen_parsed.get('confidence', 0)}/10")
                print(f"   근거: {qwen_parsed.get('reasoning', 'N/A')[:150]}...")
                print(f"   실행 시간: {qwen_time:.2f}초")
                case_results['qwen'] = qwen_parsed
                case_results['qwen']['time'] = qwen_time
            else:
                print("   파싱 실패")
                case_results['qwen'] = {'error': 'parsing failed', 'raw': qwen_response[:200]}
        except Exception as e:
            print(f"   오류: {e}")
            case_results['qwen'] = {'error': str(e)}

        # 3. 비교 분석
        print("\n3. 품질 비교:")
        if 'llama' in case_results and 'qwen' in case_results:
            if 'signal' in case_results['llama'] and 'signal' in case_results['qwen']:
                # 신호 일치 여부
                if case_results['llama']['signal'] == case_results['qwen']['signal']:
                    print(f"   ✓ 신호 일치: {case_results['llama']['signal']}")
                else:
                    print(f"   ✗ 신호 불일치: Llama={case_results['llama']['signal']}, Qwen={case_results['qwen']['signal']}")

                # 신뢰도 비교
                llama_conf = case_results['llama'].get('confidence', 0)
                qwen_conf = case_results['qwen'].get('confidence', 0)
                print(f"   신뢰도: Llama={llama_conf}/10, Qwen={qwen_conf}/10")

                # 근거 품질 (길이로 간접 평가)
                llama_reasoning = case_results['llama'].get('reasoning', '')
                qwen_reasoning = case_results['qwen'].get('reasoning', '')
                print(f"   근거 상세도: Llama={len(llama_reasoning)}자, Qwen={len(qwen_reasoning)}자")

                # 실행 시간
                print(f"   실행 시간: Llama={case_results['llama']['time']:.2f}초, Qwen={case_results['qwen']['time']:.2f}초")

        results[test_case['name']] = case_results

    # 전체 요약
    print("\n" + "=" * 70)
    print("전체 품질 평가 요약")
    print("=" * 70)

    # 품질 점수 계산
    llama_score = 0
    qwen_score = 0

    for scenario, result in results.items():
        print(f"\n{scenario}:")

        # BAC 시나리오 - 정답은 sell with high confidence
        if "BAC" in scenario:
            if 'llama' in result and result['llama'].get('signal') == 'sell':
                llama_score += 2
                if result['llama'].get('confidence', 0) >= 7:
                    llama_score += 1
            if 'qwen' in result and result['qwen'].get('signal') == 'sell':
                qwen_score += 2
                if result['qwen'].get('confidence', 0) >= 7:
                    qwen_score += 1

        # NVDA 시나리오 - 정답은 buy with moderate-high confidence
        elif "NVDA" in scenario:
            if 'llama' in result and result['llama'].get('signal') == 'buy':
                llama_score += 2
                if 6 <= result['llama'].get('confidence', 0) <= 8:
                    llama_score += 1
            if 'qwen' in result and result['qwen'].get('signal') == 'buy':
                qwen_score += 2
                if 6 <= result['qwen'].get('confidence', 0) <= 8:
                    qwen_score += 1

        # TSLA 시나리오 - 정답은 neutral with low confidence
        elif "TSLA" in scenario:
            if 'llama' in result and result['llama'].get('signal') == 'neutral':
                llama_score += 2
                if result['llama'].get('confidence', 0) <= 3:
                    llama_score += 1
            if 'qwen' in result and result['qwen'].get('signal') == 'neutral':
                qwen_score += 2
                if result['qwen'].get('confidence', 0) <= 3:
                    qwen_score += 1

    print("\n최종 품질 점수 (최대 9점):")
    print(f"  Llama 3.1 8B: {llama_score}/9")
    print(f"  Qwen 2.5 14B: {qwen_score}/9")

    if qwen_score > llama_score:
        print("\n✅ Qwen 2.5 14B가 더 높은 품질의 분석을 제공합니다.")
        print("   속도는 느리지만 정확도가 더 높습니다.")
    elif llama_score > qwen_score:
        print("\n✅ Llama 3.1 8B가 더 높은 품질의 분석을 제공합니다.")
        print("   속도도 빠르고 정확도도 높습니다.")
    else:
        print("\n⚫ 두 모델의 품질이 비슷합니다.")
        print("   속도를 고려하면 Llama 3.1 8B가 유리합니다.")

    # 결과 저장
    with open("/home/ubuntu/stock_auto/ml_quality_results.json", "w", encoding='utf-8') as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    print("\n상세 결과가 ml_quality_results.json에 저장되었습니다.")

if __name__ == "__main__":
    test_ml_quality()