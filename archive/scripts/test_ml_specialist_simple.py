#!/usr/bin/env python3
"""
ML Specialist 성능 테스트 (단순화 버전)
"""

import os
import sys
import time
import json
import requests

# 프로젝트 경로 설정
sys.path.insert(0, '/home/ubuntu/stock_auto')
sys.path.insert(0, '/home/ubuntu/stock_auto/chart_agent_service')

def test_ml_specialist():
    """ML Specialist 성능 비교"""

    # 테스트 프롬프트
    prompt = """당신은 ML Specialist 전문가입니다.
BAC 종목의 머신러닝 앙상블 예측 결과를 해석하세요.

## ML 예측 결과
- 예측: sell
- 상승 확률: 46.0%
- 모델 개수: 5
- RandomForest 정확도: 40%
- XGBoost 정확도: 46%
- LSTM 정확도: 54%
- 백테스트 Sharpe: 0.67
- 최대 손실: -8.2%

다음 JSON 형식으로만 응답하세요:
{
  "signal": "buy" 또는 "sell" 또는 "neutral",
  "confidence": 0-10,
  "reasoning": "판단 근거"
}"""

    results = {}

    # 1. 기존 모델 테스트 (llama3.1:8b)
    print("\n1. 기존 모델 테스트 (llama3.1:8b)")
    print("   실행 중...")

    start_time = time.time()
    try:
        response = requests.post(
            "http://localhost:11434/api/generate",
            json={
                "model": "llama3.1:8b",
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0.5}
            },
            timeout=60
        )
        old_time = time.time() - start_time
        old_result = response.json().get('response', 'Error')
        print(f"   완료: {old_time:.2f}초")
        results['old'] = {'time': old_time, 'response': old_result[:200]}
    except Exception as e:
        print(f"   오류: {e}")
        results['old'] = {'time': 0, 'response': str(e)}

    # 2. 새 모델 테스트 (qwen2.5:14b)
    print("\n2. 새 모델 테스트 (qwen2.5:14b-instruct-q4_K_M)")
    print("   실행 중...")

    start_time = time.time()
    try:
        response = requests.post(
            "http://localhost:11434/api/generate",
            json={
                "model": "qwen2.5:14b-instruct-q4_K_M",
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0.5}
            },
            timeout=60
        )
        new_time = time.time() - start_time
        new_result = response.json().get('response', 'Error')
        print(f"   완료: {new_time:.2f}초")
        results['new'] = {'time': new_time, 'response': new_result[:200]}
    except Exception as e:
        print(f"   오류: {e}")
        results['new'] = {'time': 0, 'response': str(e)}

    # 3. 성능 비교
    print("\n" + "=" * 60)
    print("성능 비교 결과")
    print("=" * 60)

    if 'old' in results and 'new' in results:
        old_time = results['old']['time']
        new_time = results['new']['time']

        if old_time > 0 and new_time > 0:
            improvement = ((old_time - new_time) / old_time) * 100
            speedup = old_time / new_time

            print(f"기존 모델 (llama3.1:8b): {old_time:.2f}초")
            print(f"새 모델 (qwen2.5:14b): {new_time:.2f}초")
            print(f"성능 개선: {improvement:.1f}%")
            print(f"속도 향상: {speedup:.1f}x")

            if new_time < 3:
                print("\n✅ 목표 달성: ML Specialist 실행 시간 3초 이내")
                print(f"   (기존 9.89초 → 현재 {new_time:.2f}초)")
            else:
                print(f"\n⚠️ 추가 최적화 필요: 목표 3초, 현재 {new_time:.2f}초")

            # 예상 총 실행 시간 개선
            print("\n예상 총 실행 시간 개선:")
            old_total = 30  # 기존 총 시간
            new_total = old_total - (9.89 - new_time)  # ML 개선 반영
            print(f"  기존: 약 {old_total}초")
            print(f"  개선: 약 {new_total:.1f}초")
            print(f"  단축: {old_total - new_total:.1f}초 ({(old_total - new_total)/old_total*100:.0f}%)")

if __name__ == "__main__":
    test_ml_specialist()