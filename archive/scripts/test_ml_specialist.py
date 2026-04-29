#!/usr/bin/env python3
"""
ML Specialist 성능 테스트
Qwen 14B 모델로 전환 후 성능 비교
"""

import time
import json
from stock_analyzer.multi_agent import MLSpecialistAgent

def test_ml_specialist_performance():
    """ML Specialist 성능 테스트"""

    # 테스트 데이터 (BAC 분석 데이터)
    test_data = {
        "ticker": "BAC",
        "current_price": 54.32,
        "ml_prediction": {
            "models": {
                "RandomForest": {
                    "prediction": 0,
                    "probability": 0.575,
                    "test_accuracy": 0.40
                },
                "XGBoost": {
                    "prediction": 0,
                    "probability": 0.505,
                    "test_accuracy": 0.46
                },
                "LSTM": {
                    "prediction": 0,
                    "probability": 0.54,
                    "test_accuracy": 0.54
                }
            },
            "ensemble": {
                "signal": "sell",
                "up_probability": 0.46,
                "confidence": 0.47
            },
            "backtest": {
                "total_return": 0.034,
                "sharpe_ratio": 0.67,
                "max_drawdown": -0.082,
                "n_trades": 35
            }
        }
    }

    # ML Specialist 에이전트 생성
    ml_agent = MLSpecialistAgent()

    print("=" * 60)
    print("ML Specialist 성능 테스트")
    print("=" * 60)

    # 기존 모델 (llama3.1:8b) 테스트
    print("\n1. 기존 모델 테스트 (llama3.1:8b)")
    ml_agent.model = "llama3.1:8b"  # 기존 모델로 설정

    start_time = time.time()
    result_old = ml_agent.analyze(test_data)
    old_duration = time.time() - start_time

    print(f"   실행 시간: {old_duration:.2f}초")
    print(f"   신호: {result_old.get('signal', 'N/A')}")
    print(f"   신뢰도: {result_old.get('confidence', 0):.1f}")

    # 새 모델 (Qwen 14B) 테스트
    print("\n2. 새 모델 테스트 (qwen2.5:14b-instruct-q4_K_M)")
    ml_agent.model = "qwen2.5:14b-instruct-q4_K_M"  # 새 모델로 설정

    start_time = time.time()
    result_new = ml_agent.analyze(test_data)
    new_duration = time.time() - start_time

    print(f"   실행 시간: {new_duration:.2f}초")
    print(f"   신호: {result_new.get('signal', 'N/A')}")
    print(f"   신뢰도: {result_new.get('confidence', 0):.1f}")

    # 성능 비교
    print("\n" + "=" * 60)
    print("성능 비교 결과")
    print("=" * 60)

    improvement = ((old_duration - new_duration) / old_duration) * 100
    speedup = old_duration / new_duration

    print(f"기존 모델: {old_duration:.2f}초")
    print(f"새 모델: {new_duration:.2f}초")
    print(f"성능 개선: {improvement:.1f}%")
    print(f"속도 향상: {speedup:.1f}x")

    if new_duration < 3:
        print("\n✅ 목표 달성: ML Specialist 실행 시간 3초 이내")
    else:
        print(f"\n⚠️ 추가 최적화 필요: 목표 3초, 현재 {new_duration:.2f}초")

    # 결과 품질 비교
    print("\n품질 검증:")
    print(f"기존 모델 추론: {result_old.get('reasoning', 'N/A')[:100]}...")
    print(f"새 모델 추론: {result_new.get('reasoning', 'N/A')[:100]}...")

    return {
        "old_model": {
            "name": "llama3.1:8b",
            "duration": old_duration,
            "result": result_old
        },
        "new_model": {
            "name": "qwen2.5:14b-instruct-q4_K_M",
            "duration": new_duration,
            "result": result_new
        },
        "improvement": {
            "percentage": improvement,
            "speedup": speedup
        }
    }

if __name__ == "__main__":
    results = test_ml_specialist_performance()

    # 결과를 파일로 저장
    with open("/home/ubuntu/stock_auto/stock_analyzer/ml_specialist_benchmark.json", "w") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    print("\n벤치마크 결과가 ml_specialist_benchmark.json에 저장되었습니다.")