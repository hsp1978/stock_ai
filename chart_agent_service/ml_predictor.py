"""
머신러닝 예측 모듈
- Random Forest / Gradient Boosting 기반 방향 예측
- 기술 지표 피처 자동 생성
- 5일 후 방향(상승/하락) 확률 산출
"""
import numpy as np
import pandas as pd
from typing import Optional

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


def run_ml_prediction(ticker: str, df: pd.DataFrame) -> dict:
    results = {}
    for model_type in ["rf", "gb"]:
        for horizon in [5]:
            key = f"{model_type}_{horizon}d"
            results[key] = train_predict(ticker, df, horizon=horizon, model_type=model_type)

    best = max(results.values(), key=lambda x: x.get("test_accuracy", 0))
    return {
        "ticker": ticker,
        "models": results,
        "best_model": best.get("model_type", "rf"),
        "best_prediction": best.get("prediction", "?"),
        "best_up_probability": best.get("up_probability", 0.5),
        "best_accuracy": best.get("test_accuracy", 0),
    }
