"""
머신러닝 예측 모듈
- Random Forest / Gradient Boosting / LightGBM / XGBoost / LSTM 앙상블
- SHAP 설명력 (Cluefin 스타일)
- 기술 지표 피처 자동 생성
- 5일 후 방향(상승/하락) 확률 산출
"""
import numpy as np
import pandas as pd
from typing import Optional, Tuple

from config import RSI_PERIOD, BOLLINGER_PERIOD, BOLLINGER_STD, ADX_PERIOD


def _build_features(df: pd.DataFrame) -> pd.DataFrame:
    feat = pd.DataFrame(index=df.index)

    feat["return_1d"] = df["Close"].pct_change(1)
    feat["return_5d"] = df["Close"].pct_change(5)
    feat["return_10d"] = df["Close"].pct_change(10)
    feat["return_20d"] = df["Close"].pct_change(20)

    for p in [5, 10, 20, 50]:
        sma = df["Close"].rolling(p).mean()
        feat[f"sma_ratio_{p}"] = df["Close"] / sma - 1

    feat["volatility_10d"] = df["Close"].pct_change().rolling(10).std()
    feat["volatility_20d"] = df["Close"].pct_change().rolling(20).std()
    feat["vol_ratio"] = feat["volatility_10d"] / feat["volatility_20d"]

    if "RSI" in df.columns:
        feat["rsi"] = df["RSI"]
        feat["rsi_change"] = df["RSI"].diff(5)

    if "ATR" in df.columns:
        feat["atr_pct"] = df["ATR"] / df["Close"] * 100

    bbu = f"BBU_{BOLLINGER_PERIOD}_{BOLLINGER_STD}"
    bbl = f"BBL_{BOLLINGER_PERIOD}_{BOLLINGER_STD}"
    if bbu in df.columns and bbl in df.columns:
        bb_range = df[bbu] - df[bbl]
        feat["bb_width"] = bb_range / df["Close"] * 100
        feat["bb_position"] = (df["Close"] - df[bbl]) / bb_range

    adx_col = f"ADX_{ADX_PERIOD}"
    if adx_col in df.columns:
        feat["adx"] = df[adx_col]

    if "OBV" in df.columns:
        obv = df["OBV"]
        feat["obv_change_10d"] = obv.pct_change(10)

    if "Volume" in df.columns and "Volume_SMA_20" in df.columns:
        feat["volume_ratio"] = df["Volume"] / df["Volume_SMA_20"]

    feat["high_low_range"] = (df["High"] - df["Low"]) / df["Close"]

    feat["day_of_week"] = pd.Series(df.index, index=df.index).apply(
        lambda x: x.weekday() if hasattr(x, "weekday") else 0
    )

    return feat


def _build_target(df: pd.DataFrame, horizon: int = 5) -> pd.Series:
    future_ret = df["Close"].shift(-horizon) / df["Close"] - 1
    return (future_ret > 0).astype(int)


def train_predict(ticker: str, df: pd.DataFrame,
                  horizon: int = 5, model_type: str = "rf") -> dict:
    try:
        from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
        from sklearn.model_selection import TimeSeriesSplit
        from sklearn.metrics import accuracy_score, classification_report
        from sklearn.preprocessing import StandardScaler
    except ImportError:
        return {"error": "scikit-learn 미설치", "ticker": ticker}

    features = _build_features(df)
    target = _build_target(df, horizon)

    combined = pd.concat([features, target.rename("target")], axis=1).dropna()
    if len(combined) < 100:
        return {"error": "데이터 부족 (최소 100개 필요)", "ticker": ticker, "rows": len(combined)}

    X = combined.drop("target", axis=1)
    y = combined["target"]

    train_size = int(len(X) * 0.8)
    X_train, X_test = X.iloc[:train_size], X.iloc[train_size:]
    y_train, y_test = y.iloc[:train_size], y.iloc[train_size:]

    scaler = StandardScaler()
    X_train_scaled = scaler.fit_transform(X_train)
    X_test_scaled = scaler.transform(X_test)

    if model_type == "gb":
        model = GradientBoostingClassifier(
            n_estimators=100, max_depth=4, learning_rate=0.1, random_state=42
        )
    else:
        model = RandomForestClassifier(
            n_estimators=200, max_depth=6, min_samples_leaf=10, random_state=42, n_jobs=-1
        )

    model.fit(X_train_scaled, y_train)

    y_pred = model.predict(X_test_scaled)
    y_proba = model.predict_proba(X_test_scaled)
    accuracy = accuracy_score(y_test, y_pred)

    tscv = TimeSeriesSplit(n_splits=3)
    cv_scores = []
    for train_idx, val_idx in tscv.split(X_train_scaled):
        model_cv = model.__class__(**model.get_params())
        model_cv.fit(X_train_scaled[train_idx], y_train.iloc[train_idx])
        cv_scores.append(accuracy_score(y_train.iloc[val_idx], model_cv.predict(X_train_scaled[val_idx])))

    latest_features = scaler.transform(X.iloc[[-1]])
    latest_proba = model.predict_proba(latest_features)[0]
    latest_pred = model.predict(latest_features)[0]

    feature_imp = dict(zip(X.columns, model.feature_importances_))
    top_features = sorted(feature_imp.items(), key=lambda x: x[1], reverse=True)[:10]

    score = 0
    up_prob = latest_proba[1] if len(latest_proba) > 1 else 0.5
    if up_prob > 0.65:
        score += 4
    elif up_prob > 0.55:
        score += 2
    elif up_prob < 0.35:
        score -= 4
    elif up_prob < 0.45:
        score -= 2

    if accuracy > 0.55:
        score += 1
    elif accuracy < 0.45:
        score -= 1

    score = max(-10, min(10, score))
    signal = "buy" if score > 2 else ("sell" if score < -2 else "neutral")

    return {
        "tool": "ml_prediction",
        "name": f"ML 예측 ({model_type.upper()}, {horizon}일)",
        "ticker": ticker,
        "signal": signal,
        "score": round(score, 1),
        "horizon_days": horizon,
        "model_type": model_type,
        "prediction": "UP" if latest_pred == 1 else "DOWN",
        "up_probability": round(float(up_prob), 4),
        "down_probability": round(float(1 - up_prob), 4),
        "test_accuracy": round(accuracy, 4),
        "cv_accuracy_mean": round(float(np.mean(cv_scores)), 4),
        "cv_accuracy_std": round(float(np.std(cv_scores)), 4),
        "train_size": train_size,
        "test_size": len(X_test),
        "feature_count": X.shape[1],
        "top_features": [{"name": f, "importance": round(imp, 4)} for f, imp in top_features],
        "detail": f"{horizon}일후 {('UP' if latest_pred == 1 else 'DOWN')}({up_prob:.1%}), "
                   f"정확도={accuracy:.1%}, CV={np.mean(cv_scores):.1%}"
    }


def _compute_shap_values(model, X_train, X_test, model_type: str = "tree") -> dict:
    """SHAP 설명력 계산 (Cluefin 스타일)"""
    try:
        import shap
    except ImportError:
        return {"error": "shap 미설치 (pip install shap)"}

    try:
        if model_type in ("rf", "gb", "lgb", "xgb"):
            explainer = shap.TreeExplainer(model)
            shap_values = explainer.shap_values(X_test)

            # 이진 분류: class 1 (상승) SHAP 사용
            if isinstance(shap_values, list):
                shap_values = shap_values[1]

            # 평균 절대 SHAP 값으로 중요도 계산
            mean_abs_shap = np.abs(shap_values).mean(axis=0)
            feature_importance_shap = dict(zip(X_test.columns, mean_abs_shap))

            # 최근 1개 샘플의 SHAP 값 (설명력)
            latest_shap = dict(zip(X_test.columns, shap_values[-1]))

            return {
                "feature_importance_shap": {k: round(float(v), 6) for k, v in
                    sorted(feature_importance_shap.items(), key=lambda x: x[1], reverse=True)[:10]},
                "latest_shap_values": {k: round(float(v), 6) for k, v in
                    sorted(latest_shap.items(), key=lambda x: abs(x[1]), reverse=True)[:10]},
                "shap_available": True,
            }
        else:
            return {"shap_available": False, "reason": "모델 타입 미지원"}
    except Exception as e:
        return {"shap_available": False, "error": str(e)}


def train_predict_lgb(ticker: str, df: pd.DataFrame, horizon: int = 5) -> dict:
    """LightGBM 예측"""
    try:
        import lightgbm as lgb
        from sklearn.model_selection import TimeSeriesSplit
        from sklearn.metrics import accuracy_score
        from sklearn.preprocessing import StandardScaler
    except ImportError:
        return {"error": "lightgbm 미설치", "ticker": ticker}

    features = _build_features(df)
    target = _build_target(df, horizon)
    combined = pd.concat([features, target.rename("target")], axis=1).dropna()

    if len(combined) < 100:
        return {"error": "데이터 부족", "ticker": ticker, "rows": len(combined)}

    X = combined.drop("target", axis=1)
    y = combined["target"]

    train_size = int(len(X) * 0.8)
    X_train, X_test = X.iloc[:train_size], X.iloc[train_size:]
    y_train, y_test = y.iloc[:train_size], y.iloc[train_size:]

    scaler = StandardScaler()
    X_train_scaled = scaler.fit_transform(X_train)
    X_test_scaled = scaler.transform(X_test)

    X_train_df = pd.DataFrame(X_train_scaled, columns=X.columns, index=X_train.index)
    X_test_df = pd.DataFrame(X_test_scaled, columns=X.columns, index=X_test.index)

    model = lgb.LGBMClassifier(
        n_estimators=100, max_depth=5, learning_rate=0.05,
        num_leaves=31, random_state=42, verbose=-1
    )
    model.fit(X_train_df, y_train)

    y_pred = model.predict(X_test_df)
    y_proba = model.predict_proba(X_test_df)
    accuracy = accuracy_score(y_test, y_pred)

    latest_features = scaler.transform(X.iloc[[-1]])
    latest_features_df = pd.DataFrame(latest_features, columns=X.columns)
    latest_proba = model.predict_proba(latest_features_df)[0]
    latest_pred = model.predict(latest_features_df)[0]

    up_prob = latest_proba[1] if len(latest_proba) > 1 else 0.5

    score = 0
    if up_prob > 0.65:
        score += 4
    elif up_prob > 0.55:
        score += 2
    elif up_prob < 0.35:
        score -= 4
    elif up_prob < 0.45:
        score -= 2
    if accuracy > 0.55:
        score += 1
    score = max(-10, min(10, score))

    shap_result = _compute_shap_values(model, X_train_df, X_test_df, "lgb")

    return {
        "tool": "ml_lgb",
        "name": f"LightGBM 예측 ({horizon}일)",
        "ticker": ticker,
        "signal": "buy" if score > 2 else ("sell" if score < -2 else "neutral"),
        "score": round(score, 1),
        "prediction": "UP" if latest_pred == 1 else "DOWN",
        "up_probability": round(float(up_prob), 4),
        "test_accuracy": round(accuracy, 4),
        "shap": shap_result,
        "detail": f"{horizon}일후 {('UP' if latest_pred == 1 else 'DOWN')}({up_prob:.1%}), 정확도={accuracy:.1%}"
    }


def train_predict_xgb(ticker: str, df: pd.DataFrame, horizon: int = 5) -> dict:
    """XGBoost 예측"""
    try:
        import xgboost as xgb
        from sklearn.metrics import accuracy_score
        from sklearn.preprocessing import StandardScaler
    except ImportError:
        return {"error": "xgboost 미설치", "ticker": ticker}

    features = _build_features(df)
    target = _build_target(df, horizon)
    combined = pd.concat([features, target.rename("target")], axis=1).dropna()

    if len(combined) < 100:
        return {"error": "데이터 부족", "ticker": ticker, "rows": len(combined)}

    X = combined.drop("target", axis=1)
    y = combined["target"]

    train_size = int(len(X) * 0.8)
    X_train, X_test = X.iloc[:train_size], X.iloc[train_size:]
    y_train, y_test = y.iloc[:train_size], y.iloc[train_size:]

    scaler = StandardScaler()
    X_train_scaled = scaler.fit_transform(X_train)
    X_test_scaled = scaler.transform(X_test)

    X_train_df = pd.DataFrame(X_train_scaled, columns=X.columns, index=X_train.index)
    X_test_df = pd.DataFrame(X_test_scaled, columns=X.columns, index=X_test.index)

    model = xgb.XGBClassifier(
        n_estimators=100, max_depth=5, learning_rate=0.05,
        random_state=42, eval_metric='logloss', use_label_encoder=False
    )
    model.fit(X_train_df, y_train)

    y_pred = model.predict(X_test_df)
    y_proba = model.predict_proba(X_test_df)
    accuracy = accuracy_score(y_test, y_pred)

    latest_features = scaler.transform(X.iloc[[-1]])
    latest_features_df = pd.DataFrame(latest_features, columns=X.columns)
    latest_proba = model.predict_proba(latest_features_df)[0]
    latest_pred = model.predict(latest_features_df)[0]

    up_prob = latest_proba[1] if len(latest_proba) > 1 else 0.5

    score = 0
    if up_prob > 0.65:
        score += 4
    elif up_prob > 0.55:
        score += 2
    elif up_prob < 0.35:
        score -= 4
    elif up_prob < 0.45:
        score -= 2
    if accuracy > 0.55:
        score += 1
    score = max(-10, min(10, score))

    shap_result = _compute_shap_values(model, X_train_df, X_test_df, "xgb")

    return {
        "tool": "ml_xgb",
        "name": f"XGBoost 예측 ({horizon}일)",
        "ticker": ticker,
        "signal": "buy" if score > 2 else ("sell" if score < -2 else "neutral"),
        "score": round(score, 1),
        "prediction": "UP" if latest_pred == 1 else "DOWN",
        "up_probability": round(float(up_prob), 4),
        "test_accuracy": round(accuracy, 4),
        "shap": shap_result,
        "detail": f"{horizon}일후 {('UP' if latest_pred == 1 else 'DOWN')}({up_prob:.1%}), 정확도={accuracy:.1%}"
    }


def train_predict_lstm(ticker: str, df: pd.DataFrame, horizon: int = 5, lookback: int = 20) -> dict:
    """LSTM 시계열 예측 (Qlib 스타일)"""
    try:
        import tensorflow as tf
        from tensorflow import keras
        from sklearn.preprocessing import StandardScaler
        from sklearn.metrics import accuracy_score
    except ImportError:
        return {"error": "tensorflow 미설치", "ticker": ticker}

    features = _build_features(df)
    target = _build_target(df, horizon)
    combined = pd.concat([features, target.rename("target")], axis=1).dropna()

    if len(combined) < lookback + 50:
        return {"error": f"데이터 부족 (최소 {lookback + 50}개 필요)", "ticker": ticker}

    X = combined.drop("target", axis=1).values
    y = combined["target"].values

    # 스케일링
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    # 시계열 윈도우 생성 (lookback 기간)
    X_seq, y_seq = [], []
    for i in range(lookback, len(X_scaled)):
        X_seq.append(X_scaled[i-lookback:i])
        y_seq.append(y[i])
    X_seq, y_seq = np.array(X_seq), np.array(y_seq)

    train_size = int(len(X_seq) * 0.8)
    X_train, X_test = X_seq[:train_size], X_seq[train_size:]
    y_train, y_test = y_seq[:train_size], y_seq[train_size:]

    # LSTM 모델
    model = keras.Sequential([
        keras.layers.LSTM(50, return_sequences=True, input_shape=(lookback, X.shape[1])),
        keras.layers.Dropout(0.2),
        keras.layers.LSTM(30),
        keras.layers.Dropout(0.2),
        keras.layers.Dense(1, activation='sigmoid')
    ])
    model.compile(optimizer='adam', loss='binary_crossentropy', metrics=['accuracy'])

    # 조용히 학습
    model.fit(X_train, y_train, epochs=20, batch_size=32, validation_split=0.1, verbose=0)

    # 예측
    y_pred_proba = model.predict(X_test, verbose=0).flatten()
    y_pred = (y_pred_proba > 0.5).astype(int)
    accuracy = accuracy_score(y_test, y_pred)

    # 최신 예측
    latest_seq = X_scaled[-lookback:].reshape(1, lookback, X.shape[1])
    latest_proba = float(model.predict(latest_seq, verbose=0)[0, 0])
    latest_pred = 1 if latest_proba > 0.5 else 0

    score = 0
    if latest_proba > 0.65:
        score += 4
    elif latest_proba > 0.55:
        score += 2
    elif latest_proba < 0.35:
        score -= 4
    elif latest_proba < 0.45:
        score -= 2
    if accuracy > 0.55:
        score += 1
    score = max(-10, min(10, score))

    return {
        "tool": "ml_lstm",
        "name": f"LSTM 예측 ({horizon}일)",
        "ticker": ticker,
        "signal": "buy" if score > 2 else ("sell" if score < -2 else "neutral"),
        "score": round(score, 1),
        "prediction": "UP" if latest_pred == 1 else "DOWN",
        "up_probability": round(latest_proba, 4),
        "test_accuracy": round(accuracy, 4),
        "lookback": lookback,
        "detail": f"{horizon}일후 {('UP' if latest_pred == 1 else 'DOWN')}({latest_proba:.1%}), 정확도={accuracy:.1%}"
    }


def run_ml_prediction(ticker: str, df: pd.DataFrame, ensemble: bool = True) -> dict:
    """ML 예측 (앙상블 옵션)"""
    results = {}

    # 기본 모델 (RF, GB)
    for model_type in ["rf", "gb"]:
        for horizon in [5]:
            key = f"{model_type}_{horizon}d"
            results[key] = train_predict(ticker, df, horizon=horizon, model_type=model_type)

    # 앙상블 모드: LightGBM, XGBoost, LSTM 추가
    if ensemble:
        try:
            lgb_result = train_predict_lgb(ticker, df, horizon=5)
            if not lgb_result.get("error"):
                results["lgb_5d"] = lgb_result
        except Exception as e:
            print(f"  [LightGBM 오류] {e}")

        try:
            xgb_result = train_predict_xgb(ticker, df, horizon=5)
            if not xgb_result.get("error"):
                results["xgb_5d"] = xgb_result
        except Exception as e:
            print(f"  [XGBoost 오류] {e}")

        try:
            lstm_result = train_predict_lstm(ticker, df, horizon=5)
            if not lstm_result.get("error"):
                results["lstm_5d"] = lstm_result
        except Exception as e:
            print(f"  [LSTM 오류] {e}")

    # 앙상블 예측 (가중 평균)
    valid_models = [r for r in results.values() if not r.get("error")]
    if valid_models:
        ensemble_up_prob = np.mean([r.get("up_probability", 0.5) for r in valid_models])
        ensemble_pred = "UP" if ensemble_up_prob > 0.5 else "DOWN"
        ensemble_signal = "buy" if ensemble_up_prob > 0.6 else ("sell" if ensemble_up_prob < 0.4 else "neutral")
    else:
        ensemble_up_prob = 0.5
        ensemble_pred = "HOLD"
        ensemble_signal = "neutral"

    best = max(results.values(), key=lambda x: x.get("test_accuracy", 0) if not x.get("error") else 0)

    return {
        "ticker": ticker,
        "models": results,
        "ensemble": {
            "prediction": ensemble_pred,
            "up_probability": round(float(ensemble_up_prob), 4),
            "signal": ensemble_signal,
            "model_count": len(valid_models),
        },
        "best_model": best.get("tool", "rf_5d"),
        "best_prediction": best.get("prediction", "?"),
        "best_up_probability": best.get("up_probability", 0.5),
        "best_accuracy": best.get("test_accuracy", 0),
    }
