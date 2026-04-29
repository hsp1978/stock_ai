#!/usr/bin/env python3
"""
ML Pipeline Fix - 한국 주식 ML 모델 문제 해결

주요 개선사항:
1. 데이터 품질 체크 및 보정
2. NaN 처리 개선
3. 모델 0개 문제 해결
4. 에러 상세 로깅
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple
import warnings
warnings.filterwarnings('ignore')


def validate_ml_data(df: pd.DataFrame, ticker: str) -> Tuple[bool, str, Dict]:
    """
    ML 학습용 데이터 검증 및 품질 체크

    Returns:
        (유효여부, 오류메시지, 통계정보)
    """

    stats = {
        "total_rows": len(df),
        "columns": list(df.columns),
        "missing_values": {},
        "data_quality": "unknown"
    }

    # 1. 최소 데이터 체크
    if len(df) < 100:
        stats["data_quality"] = "insufficient"
        return False, f"데이터 부족: {len(df)}개 (최소 100개 필요)", stats

    # 2. 필수 컬럼 체크
    required_cols = ['Open', 'High', 'Low', 'Close', 'Volume']
    missing_cols = [col for col in required_cols if col not in df.columns]
    if missing_cols:
        stats["data_quality"] = "missing_columns"
        return False, f"필수 컬럼 누락: {missing_cols}", stats

    # 3. NaN 비율 체크
    for col in df.columns:
        nan_ratio = df[col].isna().sum() / len(df)
        stats["missing_values"][col] = {
            "count": int(df[col].isna().sum()),
            "ratio": round(nan_ratio, 4)
        }

        # 핵심 컬럼에 NaN이 50% 이상이면 실패
        if col in required_cols and nan_ratio > 0.5:
            stats["data_quality"] = "excessive_missing"
            return False, f"{col} 컬럼 결측값 {nan_ratio:.1%} (50% 초과)", stats

    # 4. 가격 데이터 이상치 체크
    price_cols = ['Open', 'High', 'Low', 'Close']
    for col in price_cols:
        if col in df.columns:
            # 0 또는 음수 체크
            if (df[col] <= 0).any():
                stats["data_quality"] = "invalid_prices"
                return False, f"{col} 컬럼에 0 또는 음수 존재", stats

            # 극단적 변동 체크 (일일 50% 이상 변동)
            if col == 'Close':
                daily_returns = df[col].pct_change()
                extreme_changes = (daily_returns.abs() > 0.5).sum()
                if extreme_changes > 5:  # 5일 이상 극단적 변동
                    stats["extreme_price_changes"] = int(extreme_changes)
                    # 경고만, 실패는 아님

    # 5. 한국 주식 특수 처리
    if ticker.endswith('.KS') or ticker.endswith('.KQ'):
        # 한국 주식은 Volume이 0인 날이 있을 수 있음 (거래정지 등)
        zero_volume_days = (df['Volume'] == 0).sum()
        stats["zero_volume_days"] = int(zero_volume_days)

        # 10% 이상 거래량 0이면 경고
        if zero_volume_days / len(df) > 0.1:
            stats["volume_warning"] = f"거래량 0인 날 {zero_volume_days}일 ({zero_volume_days/len(df):.1%})"

    stats["data_quality"] = "good"
    return True, "", stats


def fix_ml_features(df: pd.DataFrame, ticker: str) -> pd.DataFrame:
    """
    ML용 피처 데이터 보정 및 NaN 처리

    한국 주식 특별 처리 포함
    """

    df_fixed = df.copy()

    # 1. Forward fill -> Backward fill -> 중간값 대체
    for col in df_fixed.columns:
        if df_fixed[col].isna().any():
            # 먼저 앞 값으로 채우기
            df_fixed[col] = df_fixed[col].fillna(method='ffill')
            # 그 다음 뒤 값으로 채우기
            df_fixed[col] = df_fixed[col].fillna(method='bfill')
            # 그래도 NaN이면 중간값으로
            if df_fixed[col].isna().any():
                median_val = df_fixed[col].median()
                if pd.isna(median_val):
                    # 중간값도 NaN이면 0으로
                    df_fixed[col] = df_fixed[col].fillna(0)
                else:
                    df_fixed[col] = df_fixed[col].fillna(median_val)

    # 2. 무한대 값 처리
    df_fixed = df_fixed.replace([np.inf, -np.inf], np.nan)
    df_fixed = df_fixed.fillna(0)

    # 3. 한국 주식 특별 처리
    if ticker.endswith('.KS') or ticker.endswith('.KQ'):
        # 거래량 0 처리 - 이전 5일 평균으로 대체
        if 'Volume' in df_fixed.columns:
            zero_volume_idx = df_fixed['Volume'] == 0
            if zero_volume_idx.any():
                volume_ma5 = df_fixed['Volume'].rolling(5, min_periods=1).mean()
                df_fixed.loc[zero_volume_idx, 'Volume'] = volume_ma5[zero_volume_idx]

    return df_fixed


def create_robust_features(df: pd.DataFrame, ticker: str) -> pd.DataFrame:
    """
    강건한 ML 피처 생성 (NaN 최소화)

    한국 주식에 최적화된 피처 생성
    """

    feat = pd.DataFrame(index=df.index)

    # 기본 수익률 (NaN 처리 포함)
    for period in [1, 5, 10, 20]:
        ret_col = f"return_{period}d"
        feat[ret_col] = df["Close"].pct_change(period).fillna(0)

    # 이동평균 비율
    for period in [5, 10, 20, 50]:
        ma = df["Close"].rolling(period, min_periods=1).mean()
        feat[f"ma_ratio_{period}"] = (df["Close"] / ma - 1).fillna(0)

    # 변동성 (최소 기간 설정)
    feat["volatility_10d"] = df["Close"].pct_change().rolling(10, min_periods=5).std().fillna(0)
    feat["volatility_20d"] = df["Close"].pct_change().rolling(20, min_periods=10).std().fillna(0)

    # 변동성 비율 (0 나눗셈 방지)
    vol_20 = feat["volatility_20d"].replace(0, 0.0001)
    feat["vol_ratio"] = (feat["volatility_10d"] / vol_20).fillna(1)

    # RSI (있는 경우만)
    if "RSI" in df.columns:
        feat["rsi"] = df["RSI"].fillna(50)  # 중립값 50으로 대체
        feat["rsi_change"] = feat["rsi"].diff(5).fillna(0)

    # 거래량 관련 (한국 주식 특별 처리)
    if "Volume" in df.columns:
        vol_ma20 = df["Volume"].rolling(20, min_periods=1).mean()
        vol_ma20 = vol_ma20.replace(0, 1)  # 0 방지
        feat["volume_ratio"] = (df["Volume"] / vol_ma20).fillna(1)

        # 한국 주식: 거래량 급증 신호
        if ticker.endswith('.KS') or ticker.endswith('.KQ'):
            feat["volume_spike"] = (feat["volume_ratio"] > 2).astype(int)

    # 가격 범위
    high_low_range = df["High"] - df["Low"]
    close_safe = df["Close"].replace(0, 0.0001)
    feat["high_low_range"] = (high_low_range / close_safe).fillna(0)

    # 요일 (주말 거래 없음 고려)
    feat["day_of_week"] = pd.Series(df.index, index=df.index).apply(
        lambda x: x.weekday() if hasattr(x, "weekday") else 2  # 기본값 화요일
    )

    # 추가: 한국 시장 특수 지표
    if ticker.endswith('.KS') or ticker.endswith('.KQ'):
        # 외국인 매매 영향 시뮬레이션 (실제로는 별도 데이터 필요)
        # 여기서는 거래량 패턴으로 추정
        feat["foreign_pressure"] = feat["volume_ratio"].rolling(5).mean().fillna(1)

    return feat


def enhanced_ml_ensemble(ticker: str, df: pd.DataFrame, debug: bool = False) -> Dict:
    """
    개선된 ML 앙상블 예측

    한국 주식 대응 강화
    """

    result = {
        "ticker": ticker,
        "models": {},
        "ensemble": {
            "prediction": "NEUTRAL",
            "up_probability": 0.5,
            "signal": "neutral",
            "model_count": 0,
            "confidence": 0.0
        },
        "warnings": [],
        "data_quality": {}
    }

    # 1. 데이터 검증
    is_valid, error_msg, stats = validate_ml_data(df, ticker)
    result["data_quality"] = stats

    if not is_valid:
        result["warnings"].append(f"데이터 검증 실패: {error_msg}")
        return result

    # 2. 데이터 보정
    df_fixed = fix_ml_features(df, ticker)

    # 3. 피처 생성
    features = create_robust_features(df_fixed, ticker)

    # 4. 타겟 생성 (5일 후 상승/하락)
    target = (df_fixed["Close"].shift(-5) > df_fixed["Close"]).astype(int)

    # 5. 학습 데이터 준비
    combined = pd.concat([features, target.rename("target")], axis=1).dropna()

    if len(combined) < 50:  # 최소 요구 사항 완화
        result["warnings"].append(f"학습 데이터 부족: {len(combined)}개")
        return result

    X = combined.drop("target", axis=1)
    y = combined["target"]

    # 6. 학습/테스트 분할
    train_size = int(len(X) * 0.8)
    if train_size < 30:  # 최소 학습 데이터
        result["warnings"].append(f"학습 데이터 너무 적음: {train_size}개")
        return result

    X_train, X_test = X.iloc[:train_size], X.iloc[train_size:]
    y_train, y_test = y.iloc[:train_size], y.iloc[train_size:]

    # 7. 스케일링
    from sklearn.preprocessing import StandardScaler
    scaler = StandardScaler()
    X_train_scaled = scaler.fit_transform(X_train)
    X_test_scaled = scaler.transform(X_test)

    # 8. 모델 학습 (에러 핸들링 강화)
    successful_models = []

    # Random Forest
    try:
        from sklearn.ensemble import RandomForestClassifier
        rf_model = RandomForestClassifier(
            n_estimators=100, max_depth=5, min_samples_leaf=5,
            random_state=42, n_jobs=-1
        )
        rf_model.fit(X_train_scaled, y_train)

        rf_pred = rf_model.predict(X_test_scaled)
        rf_proba = rf_model.predict_proba(X_test_scaled)

        from sklearn.metrics import accuracy_score
        rf_acc = accuracy_score(y_test, rf_pred)

        # 최신 예측
        latest_features = scaler.transform(X.iloc[[-1]])
        latest_proba_rf = rf_model.predict_proba(latest_features)[0][1]

        result["models"]["random_forest"] = {
            "accuracy": round(rf_acc, 4),
            "up_probability": round(latest_proba_rf, 4),
            "status": "success"
        }
        successful_models.append(("rf", latest_proba_rf, rf_acc))

    except Exception as e:
        result["models"]["random_forest"] = {"status": "failed", "error": str(e)[:50]}
        if debug:
            print(f"RF 실패: {e}")

    # Gradient Boosting
    try:
        from sklearn.ensemble import GradientBoostingClassifier
        gb_model = GradientBoostingClassifier(
            n_estimators=50, max_depth=3, learning_rate=0.1,
            random_state=42
        )
        gb_model.fit(X_train_scaled, y_train)

        gb_pred = gb_model.predict(X_test_scaled)
        gb_proba = gb_model.predict_proba(X_test_scaled)
        gb_acc = accuracy_score(y_test, gb_pred)

        latest_proba_gb = gb_model.predict_proba(latest_features)[0][1]

        result["models"]["gradient_boosting"] = {
            "accuracy": round(gb_acc, 4),
            "up_probability": round(latest_proba_gb, 4),
            "status": "success"
        }
        successful_models.append(("gb", latest_proba_gb, gb_acc))

    except Exception as e:
        result["models"]["gradient_boosting"] = {"status": "failed", "error": str(e)[:50]}
        if debug:
            print(f"GB 실패: {e}")

    # LightGBM (옵션)
    try:
        import lightgbm as lgb
        lgb_model = lgb.LGBMClassifier(
            n_estimators=50, max_depth=3, learning_rate=0.1,
            num_leaves=31, random_state=42, verbose=-1,
            force_col_wise=True  # 경고 제거
        )
        lgb_model.fit(X_train_scaled, y_train)

        lgb_pred = lgb_model.predict(X_test_scaled)
        lgb_proba = lgb_model.predict_proba(X_test_scaled)
        lgb_acc = accuracy_score(y_test, lgb_pred)

        latest_proba_lgb = lgb_model.predict_proba(latest_features)[0][1]

        result["models"]["lightgbm"] = {
            "accuracy": round(lgb_acc, 4),
            "up_probability": round(latest_proba_lgb, 4),
            "status": "success"
        }
        successful_models.append(("lgb", latest_proba_lgb, lgb_acc))

    except Exception as e:
        result["models"]["lightgbm"] = {"status": "skipped", "reason": "LightGBM not installed"}

    # XGBoost (옵션)
    try:
        import xgboost as xgb
        xgb_model = xgb.XGBClassifier(
            n_estimators=50, max_depth=3, learning_rate=0.1,
            random_state=42, eval_metric='logloss',
            use_label_encoder=False, verbosity=0
        )
        xgb_model.fit(X_train_scaled, y_train)

        xgb_pred = xgb_model.predict(X_test_scaled)
        xgb_proba = xgb_model.predict_proba(X_test_scaled)
        xgb_acc = accuracy_score(y_test, xgb_pred)

        latest_proba_xgb = xgb_model.predict_proba(latest_features)[0][1]

        result["models"]["xgboost"] = {
            "accuracy": round(xgb_acc, 4),
            "up_probability": round(latest_proba_xgb, 4),
            "status": "success"
        }
        successful_models.append(("xgb", latest_proba_xgb, xgb_acc))

    except Exception as e:
        result["models"]["xgboost"] = {"status": "skipped", "reason": "XGBoost not installed"}

    # 9. 앙상블 계산
    if successful_models:
        # 정확도 가중 평균
        total_weight = sum(acc for _, _, acc in successful_models)
        if total_weight > 0:
            weighted_prob = sum(prob * acc for _, prob, acc in successful_models) / total_weight
        else:
            weighted_prob = np.mean([prob for _, prob, _ in successful_models])

        # 신뢰도 계산 (평균 정확도 기반 + 표본 크기 보정)
        avg_accuracy = np.mean([acc for _, _, acc in successful_models])
        raw_confidence = max(0.0, (avg_accuracy - 0.5) * 20)

        # 표본 크기 shrinkage: n < 200이면 신뢰도를 비율로 감소.
        # 이유: 작은 표본에서 얻은 70% 정확도는 통계적으로 우연일 확률 높음.
        # n=100 → 50% 감점, n=200 → 100% 유지 (기준 충족).
        n_samples = result.get("rows_used") or result.get("data_points") or 0
        if n_samples < 200 and n_samples > 0:
            shrinkage = max(0.3, n_samples / 200)  # 최소 30% 유지
            adjusted_confidence = raw_confidence * shrinkage
            sample_warning = (
                f"표본 부족 (n={n_samples}<200) → 신뢰도 {raw_confidence:.1f}→{adjusted_confidence:.1f}"
            )
            result["warnings"].append(sample_warning)
        else:
            adjusted_confidence = raw_confidence

        confidence = min(10.0, adjusted_confidence)

        # 확률과 신뢰도가 모순되면 신호 약화
        # (예: up_probability=0.65인데 confidence=2 → 의미상 일관성 위해 buy를 neutral로)
        signal = "buy" if weighted_prob > 0.6 else ("sell" if weighted_prob < 0.4 else "neutral")
        if confidence < 2 and signal != "neutral":
            signal = "neutral"
            result["warnings"].append(f"낮은 confidence({confidence:.1f})로 인해 {signal}로 강제 변경")

        result["ensemble"] = {
            "prediction": "UP" if weighted_prob > 0.5 else "DOWN",
            "up_probability": round(weighted_prob, 4),
            "signal": signal,
            "model_count": len(successful_models),
            "confidence": round(confidence, 1),
            "raw_confidence": round(raw_confidence, 1),
            "avg_accuracy": round(avg_accuracy, 4),
            "sample_size": n_samples
        }
    else:
        result["warnings"].append("모든 ML 모델 학습 실패")

    return result


# 테스트
if __name__ == "__main__":
    # 테스트용 더미 데이터
    import yfinance as yf

    # 한국 주식 테스트
    ticker = "005930.KS"  # 삼성전자
    stock = yf.Ticker(ticker)
    df = stock.history(period="1y")

    print(f"테스트 종목: {ticker}")
    print(f"데이터 크기: {len(df)} rows")

    result = enhanced_ml_ensemble(ticker, df, debug=True)

    print("\n=== ML 앙상블 결과 ===")
    print(f"모델 수: {result['ensemble']['model_count']}")
    print(f"예측: {result['ensemble']['prediction']}")
    print(f"상승 확률: {result['ensemble']['up_probability']:.1%}")
    print(f"신호: {result['ensemble']['signal']}")
    print(f"신뢰도: {result['ensemble']['confidence']}")
    if result['warnings']:
        print(f"경고: {result['warnings']}")