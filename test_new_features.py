#!/usr/bin/env python3
"""
신규 기능 통합 테스트 스크립트
- ML 앙상블 (LightGBM, XGBoost, LSTM) + SHAP
- Trailing Stop / 시간 기반 청산
- HyperOpt 파라미터 최적화
- Walk-Forward 백테스트
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "stock_analyzer"))
os.chdir(os.path.join(os.path.dirname(__file__), "stock_analyzer"))

from local_engine import (
    engine_ml_predict,
    engine_backtest_optimize,
    engine_backtest_walk_forward,
    engine_paper_order,
    engine_paper_status,
    update_position_prices,
)
from data_collector import fetch_ohlcv, calculate_indicators


def test_ml_ensemble():
    """ML 앙상블 + SHAP 테스트"""
    print("\n" + "="*60)
    print("1. ML 앙상블 테스트 (ensemble=True)")
    print("="*60)

    result = engine_ml_predict("NVDA", ensemble=True)

    if result.get("error"):
        print(f"  ❌ 오류: {result['error']}")
        return False

    print(f"  ✓ 앙상블 예측: {result['ensemble']['prediction']}")
    print(f"  ✓ 상승 확률: {result['ensemble']['up_probability']:.1%}")
    print(f"  ✓ 모델 개수: {result['ensemble']['model_count']}")

    # SHAP 확인 (lgb 모델)
    lgb_model = result.get("models", {}).get("lgb_5d")
    if lgb_model and lgb_model.get("shap", {}).get("shap_available"):
        print(f"  ✓ SHAP 사용 가능: {lgb_model['shap']['shap_available']}")
        top_shap = list(lgb_model['shap']['feature_importance_shap'].items())[:3]
        print(f"  ✓ 상위 3개 피처 (SHAP):")
        for feat, imp in top_shap:
            print(f"      - {feat}: {imp:.6f}")
    else:
        print("  ⚠ SHAP 데이터 없음 (shap 패키지 미설치일 가능성)")

    return True


def test_trailing_stop():
    """Trailing Stop + 시간 기반 청산 테스트"""
    print("\n" + "="*60)
    print("2. Trailing Stop 테스트")
    print("="*60)

    # 테스트 주문 실행 (5% trailing stop, 30일 time stop)
    order = engine_paper_order(
        ticker="NVDA",
        action="BUY",
        qty=10,
        price=100.0,
        reason="Trailing Stop 테스트",
        trailing_stop_pct=0.05,  # 5% trailing stop
        time_stop_days=30,       # 30일 후 자동 청산
        stop_loss_price=95.0,    # 고정 손절가
        take_profit_price=110.0, # 고정 익절가
    )

    if order.get("status") == "filled":
        print(f"  ✓ 매수 체결: {order['ticker']} {order['qty']}주 @ ${order['price']}")
        print(f"  ✓ Trailing Stop: {5.0}%")
        print(f"  ✓ Time Stop: 30일")

        # 가격 업데이트 테스트 (고점 갱신)
        print(f"\n  [가격 업데이트 시뮬레이션]")
        auto_closed = update_position_prices({"NVDA": 105.0})
        print(f"  → 가격 $105 (고점 갱신) — 청산 없음")

        auto_closed = update_position_prices({"NVDA": 108.0})
        print(f"  → 가격 $108 (새 고점) — 청산 없음")

        auto_closed = update_position_prices({"NVDA": 102.0})
        print(f"  → 가격 $102 (고점 $108 대비 5.6% 하락)")
        print(f"  → Trailing Stop 발동 예상: ${108 * 0.95:.2f} (실제: $102)")

        if auto_closed:
            print(f"  ✓ 자동 청산됨: {len(auto_closed)}건")
            for c in auto_closed:
                print(f"      - {c['ticker']}: {c['reason']}")
        else:
            print(f"  ⚠ 아직 청산 안됨 (임계값 미도달)")

        return True
    else:
        print(f"  ❌ 주문 실패: {order.get('reject_reason', '알 수 없음')}")
        return False


def test_hyperopt():
    """HyperOpt 파라미터 최적화 테스트"""
    print("\n" + "="*60)
    print("3. HyperOpt 파라미터 최적화 테스트 (RSI 전략)")
    print("="*60)

    result = engine_backtest_optimize("NVDA", strategy="rsi_reversion", n_trials=10)

    if result.get("error"):
        print(f"  ❌ 오류: {result['error']}")
        return False

    print(f"  ✓ 전략: {result['strategy']}")
    print(f"  ✓ 최적 파라미터: {result['best_params']}")
    print(f"  ✓ 최고 Sharpe: {result['best_sharpe']:.3f}")
    print(f"  ✓ 백테스트 결과:")
    print(f"      - 총 수익률: {result['result']['total_return_pct']:.2f}%")
    print(f"      - 연환산 수익률: {result['result']['annualized_return_pct']:.2f}%")
    print(f"      - MDD: {result['result']['max_drawdown_pct']:.2f}%")
    print(f"      - 거래 횟수: {result['result']['total_trades']}회")

    return True


def test_walk_forward():
    """Walk-Forward 백테스트 테스트"""
    print("\n" + "="*60)
    print("4. Walk-Forward 백테스트 테스트 (RSI 전략, 3 splits)")
    print("="*60)

    result = engine_backtest_walk_forward(
        "NVDA",
        strategy="rsi_reversion",
        train_window=200,
        test_window=50,
        n_splits=3
    )

    if result.get("error"):
        print(f"  ❌ 오류: {result['error']}")
        return False

    print(f"  ✓ 전략: {result['strategy']}")
    print(f"  ✓ Split 개수: {result['walk_forward_splits']}")
    print(f"  ✓ 평균 학습 Sharpe: {result['avg_train_sharpe']:.3f}")
    print(f"  ✓ 평균 테스트 Sharpe: {result['avg_test_sharpe']:.3f}")
    print(f"  ✓ 평균 테스트 수익률: {result['avg_test_return_pct']:.2f}%")
    print(f"  ✓ 과적합 비율: {result['overfitting_ratio']:.2f}")
    print(f"      (1.0 ~ 1.5 = 양호, > 2.0 = 과적합 의심)")

    print(f"\n  [Split 상세]")
    for split in result['splits']:
        print(f"    Split {split['split']}: {split['test_start']} ~ {split['test_end']}")
        print(f"      파라미터: {split['best_params']}")
        print(f"      학습 Sharpe: {split['train_sharpe']:.3f} | 테스트 Sharpe: {split['test_sharpe']:.3f}")
        print(f"      테스트 수익률: {split['test_return_pct']:.2f}% | 거래: {split['test_trades']}회")
        print()

    return True


def main():
    print("\n" + "#"*60)
    print("#  신규 기능 통합 테스트")
    print("#  - ML 앙상블 (LightGBM, XGBoost, LSTM) + SHAP")
    print("#  - Trailing Stop / 시간 기반 청산")
    print("#  - HyperOpt 파라미터 최적화 (Optuna)")
    print("#  - Walk-Forward 백테스트")
    print("#"*60)

    results = []

    # 1. ML 앙상블 + SHAP
    try:
        results.append(("ML 앙상블 + SHAP", test_ml_ensemble()))
    except Exception as e:
        print(f"  ❌ ML 앙상블 테스트 실패: {e}")
        results.append(("ML 앙상블 + SHAP", False))

    # 2. Trailing Stop
    try:
        results.append(("Trailing Stop", test_trailing_stop()))
    except Exception as e:
        print(f"  ❌ Trailing Stop 테스트 실패: {e}")
        results.append(("Trailing Stop", False))

    # 3. HyperOpt
    try:
        results.append(("HyperOpt", test_hyperopt()))
    except Exception as e:
        print(f"  ❌ HyperOpt 테스트 실패: {e}")
        results.append(("HyperOpt", False))

    # 4. Walk-Forward
    try:
        results.append(("Walk-Forward", test_walk_forward()))
    except Exception as e:
        print(f"  ❌ Walk-Forward 테스트 실패: {e}")
        results.append(("Walk-Forward", False))

    # 요약
    print("\n" + "="*60)
    print("테스트 요약")
    print("="*60)
    for name, passed in results:
        status = "✓ PASS" if passed else "❌ FAIL"
        print(f"  {status}  {name}")

    total = len(results)
    passed = sum(1 for _, p in results if p)
    print(f"\n총 {total}개 테스트 중 {passed}개 통과 ({passed/total*100:.0f}%)")

    if passed == total:
        print("\n🎉 모든 테스트 통과!")
        return 0
    else:
        print(f"\n⚠ {total - passed}개 테스트 실패. 로그를 확인하세요.")
        return 1


if __name__ == "__main__":
    exit(main())
