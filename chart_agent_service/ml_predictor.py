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


_tf_gpu_initialized = False

def _ensure_tf_gpu_growth() -> None:
    """TF GPU 동적 메모리 할당 — 한 번만 호출.

    Why: 같은 RTX 5070을 호스트 Ollama(qwen3:14b ~9GB)와 공유하므로 TF가
    기본값으로 전체 VRAM을 미리 잡으면 Ollama가 OOM. memory_growth=True 면
    실제 사용량만큼만 점진적으로 alloc.
    """
    global _tf_gpu_initialized
    if _tf_gpu_initialized:
        return
    try:
        import tensorflow as tf
        gpus = tf.config.list_physical_devices("GPU")
        for gpu in gpus:
            try:
                tf.config.experimental.set_memory_growth(gpu, True)
            except RuntimeError:
                pass  # 이미 다른 호출에서 init 됐을 수도
        _tf_gpu_initialized = True
    except ImportError:
        pass


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

    return feat.replace([np.inf, -np.inf], np.nan)


def _build_target(df: pd.DataFrame, horizon: int = 5) -> pd.Series:
    future_ret = df["Close"].shift(-horizon) / df["Close"] - 1
    target = (future_ret > 0).astype("float64")
    target[future_ret.isna()] = np.nan
    return target


def _format_index_value(value) -> str:
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def _latest_feature_frame(
    features: pd.DataFrame, columns: Optional[list] = None
) -> Tuple[pd.DataFrame, object]:
    """Return the newest valid feature row, independent of target availability."""
    clean = features.replace([np.inf, -np.inf], np.nan)
    if columns is not None:
        missing = [c for c in columns if c not in clean.columns]
        if missing:
            raise ValueError(f"최신 예측 피처 컬럼 누락: {missing}")
        clean = clean.loc[:, columns]
    clean = clean.dropna()
    if clean.empty:
        raise ValueError("최신 예측에 사용할 유효 피처가 없습니다")
    latest = clean.iloc[[-1]]
    return latest, latest.index[-1]


def _prediction_metadata(df: pd.DataFrame, feature_date, horizon: int) -> dict:
    last_date = df.index[-1] if len(df.index) else None
    staleness_rows = 0
    if last_date is not None:
        matches = np.flatnonzero(df.index == feature_date)
        if len(matches):
            staleness_rows = int(len(df.index) - 1 - matches[-1])
        else:
            try:
                staleness_rows = int((df.index > feature_date).sum())
            except Exception:
                staleness_rows = 0
    return {
        "horizon_days": horizon,
        "prediction_feature_date": _format_index_value(feature_date),
        "data_last_date": _format_index_value(last_date) if last_date is not None else None,
        "prediction_staleness_rows": staleness_rows,
        "latest_feature_is_current": staleness_rows == 0,
    }


def _split_train_test_with_gap(
    X: pd.DataFrame,
    y: pd.Series,
    horizon: int,
    train_fraction: float = 0.8,
) -> Tuple[pd.DataFrame, pd.DataFrame, pd.Series, pd.Series, dict]:
    """Chronological split with a purged gap equal to the prediction horizon."""
    split_at = int(len(X) * train_fraction)
    gap = max(0, int(horizon))
    train_end = max(0, split_at - gap)

    if train_end <= 0 or split_at >= len(X):
        raise ValueError("학습/테스트 분할 불가")

    X_train, X_test = X.iloc[:train_end], X.iloc[split_at:]
    y_train, y_test = y.iloc[:train_end], y.iloc[split_at:]
    if X_train.empty or X_test.empty:
        raise ValueError("학습/테스트 데이터 부족")

    return X_train, X_test, y_train, y_test, {
        "train_size": len(X_train),
        "test_size": len(X_test),
        "trainable_rows": len(X),
        "split_index": split_at,
        "purge_gap": split_at - train_end,
    }


def _make_tscv(TimeSeriesSplit, n_splits: int, horizon: int):
    try:
        return TimeSeriesSplit(n_splits=n_splits, gap=max(0, int(horizon)))
    except TypeError:
        return TimeSeriesSplit(n_splits=n_splits)


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
    y = combined["target"].astype(int)

    latest_X, latest_feature_date = _latest_feature_frame(features, list(X.columns))
    try:
        X_train, X_test, y_train, y_test, split_meta = _split_train_test_with_gap(X, y, horizon)
    except ValueError as e:
        return {"error": str(e), "ticker": ticker, "rows": len(combined)}

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

    tscv = _make_tscv(TimeSeriesSplit, n_splits=3, horizon=horizon)
    cv_scores = []
    try:
        for train_idx, val_idx in tscv.split(X_train):
            scaler_cv = StandardScaler()
            X_cv_train = scaler_cv.fit_transform(X_train.iloc[train_idx])
            X_cv_val = scaler_cv.transform(X_train.iloc[val_idx])
            model_cv = model.__class__(**model.get_params())
            model_cv.fit(X_cv_train, y_train.iloc[train_idx])
            cv_scores.append(accuracy_score(y_train.iloc[val_idx], model_cv.predict(X_cv_val)))
    except Exception:
        cv_scores = []

    latest_features = scaler.transform(latest_X)
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

    cv_mean = float(np.mean(cv_scores)) if cv_scores else None
    cv_std = float(np.std(cv_scores)) if cv_scores else None
    metadata = _prediction_metadata(df, latest_feature_date, horizon)

    return {
        "tool": "ml_prediction",
        "name": f"ML 예측 ({model_type.upper()}, {horizon}일)",
        "ticker": ticker,
        "signal": signal,
        "score": round(score, 1),
        "model_type": model_type,
        "prediction": "UP" if latest_pred == 1 else "DOWN",
        "up_probability": round(float(up_prob), 4),
        "down_probability": round(float(1 - up_prob), 4),
        "test_accuracy": round(accuracy, 4),
        "cv_accuracy_mean": round(cv_mean, 4) if cv_mean is not None else None,
        "cv_accuracy_std": round(cv_std, 4) if cv_std is not None else None,
        **split_meta,
        **metadata,
        "feature_count": X.shape[1],
        "top_features": [{"name": f, "importance": round(imp, 4)} for f, imp in top_features],
        "detail": f"{horizon}일후 {('UP' if latest_pred == 1 else 'DOWN')}({up_prob:.1%}), "
                   f"정확도={accuracy:.1%}, CV={(cv_mean if cv_mean is not None else 0):.1%}"
    }


def _positive_class_shap(shap_values):
    if isinstance(shap_values, list):
        return shap_values[1] if len(shap_values) > 1 else shap_values[0]
    arr = np.asarray(shap_values)
    if arr.ndim == 3:
        return arr[:, :, 1] if arr.shape[2] > 1 else arr[:, :, 0]
    return arr


def _compute_shap_values(model, X_train, X_test, model_type: str = "tree",
                         latest_X: Optional[pd.DataFrame] = None) -> dict:
    """SHAP 설명력 계산 (Cluefin 스타일)"""
    try:
        import shap
    except ImportError:
        return {"error": "shap 미설치 (pip install shap)"}

    try:
        if model_type in ("rf", "gb", "lgb", "xgb"):
            explainer = shap.TreeExplainer(model)
            shap_values = _positive_class_shap(explainer.shap_values(X_test))

            # 평균 절대 SHAP 값으로 중요도 계산
            mean_abs_shap = np.abs(shap_values).mean(axis=0)
            feature_importance_shap = dict(zip(X_test.columns, mean_abs_shap))

            if latest_X is not None:
                latest_values = _positive_class_shap(explainer.shap_values(latest_X))
                latest_row = latest_values[0]
                explanation_target = "latest_prediction_feature"
            else:
                latest_row = shap_values[-1]
                explanation_target = "last_test_sample"
            latest_shap = dict(zip(X_test.columns, latest_row))

            return {
                "feature_importance_shap": {k: round(float(v), 6) for k, v in
                    sorted(feature_importance_shap.items(), key=lambda x: x[1], reverse=True)[:10]},
                "latest_shap_values": {k: round(float(v), 6) for k, v in
                    sorted(latest_shap.items(), key=lambda x: abs(x[1]), reverse=True)[:10]},
                "explanation_target": explanation_target,
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
    y = combined["target"].astype(int)

    latest_X, latest_feature_date = _latest_feature_frame(features, list(X.columns))
    try:
        X_train, X_test, y_train, y_test, split_meta = _split_train_test_with_gap(X, y, horizon)
    except ValueError as e:
        return {"error": str(e), "ticker": ticker, "rows": len(combined)}

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

    latest_features = scaler.transform(latest_X)
    latest_features_df = pd.DataFrame(latest_features, columns=X.columns, index=latest_X.index)
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

    shap_result = _compute_shap_values(model, X_train_df, X_test_df, "lgb", latest_features_df)
    metadata = _prediction_metadata(df, latest_feature_date, horizon)

    return {
        "tool": "ml_lgb",
        "name": f"LightGBM 예측 ({horizon}일)",
        "ticker": ticker,
        "signal": "buy" if score > 2 else ("sell" if score < -2 else "neutral"),
        "score": round(score, 1),
        "horizon_days": horizon,
        "prediction": "UP" if latest_pred == 1 else "DOWN",
        "up_probability": round(float(up_prob), 4),
        "test_accuracy": round(accuracy, 4),
        **split_meta,
        **metadata,
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
    y = combined["target"].astype(int)

    latest_X, latest_feature_date = _latest_feature_frame(features, list(X.columns))
    try:
        X_train, X_test, y_train, y_test, split_meta = _split_train_test_with_gap(X, y, horizon)
    except ValueError as e:
        return {"error": str(e), "ticker": ticker, "rows": len(combined)}

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

    latest_features = scaler.transform(latest_X)
    latest_features_df = pd.DataFrame(latest_features, columns=X.columns, index=latest_X.index)
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

    shap_result = _compute_shap_values(model, X_train_df, X_test_df, "xgb", latest_features_df)
    metadata = _prediction_metadata(df, latest_feature_date, horizon)

    return {
        "tool": "ml_xgb",
        "name": f"XGBoost 예측 ({horizon}일)",
        "ticker": ticker,
        "signal": "buy" if score > 2 else ("sell" if score < -2 else "neutral"),
        "score": round(score, 1),
        "horizon_days": horizon,
        "prediction": "UP" if latest_pred == 1 else "DOWN",
        "up_probability": round(float(up_prob), 4),
        "test_accuracy": round(accuracy, 4),
        **split_meta,
        **metadata,
        "shap": shap_result,
        "detail": f"{horizon}일후 {('UP' if latest_pred == 1 else 'DOWN')}({up_prob:.1%}), 정확도={accuracy:.1%}"
    }


def train_predict_lstm(ticker: str, df: pd.DataFrame, horizon: int = 5, lookback: int = 20) -> dict:
    """LSTM 시계열 예측 (Qlib 스타일)"""
    _ensure_tf_gpu_growth()
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

    X_df = combined.drop("target", axis=1)
    y = combined["target"].astype(int).values
    feature_clean = features.replace([np.inf, -np.inf], np.nan).loc[:, list(X_df.columns)].dropna()
    if len(feature_clean) < lookback:
        return {"error": "최신 LSTM 시퀀스 피처 부족", "ticker": ticker}
    latest_feature_date = feature_clean.index[-1]
    X = X_df.values

    split_at = int(len(X) * 0.8)
    train_cut = max(0, split_at - max(0, int(horizon)))
    if train_cut <= lookback or split_at >= len(X):
        return {"error": "학습/테스트 분할 불가", "ticker": ticker}

    # 스케일링: 학습 구간으로만 fit하여 테스트/최신 구간 누수 방지
    scaler = StandardScaler()
    scaler.fit(X[:train_cut])
    X_scaled = scaler.transform(X)
    latest_seq_scaled = scaler.transform(feature_clean.tail(lookback).values)

    # 시계열 윈도우 생성 (lookback 기간)
    X_seq, y_seq, target_indices = [], [], []
    for i in range(lookback, len(X_scaled)):
        X_seq.append(X_scaled[i-lookback:i])
        y_seq.append(y[i])
        target_indices.append(i)
    X_seq, y_seq = np.array(X_seq), np.array(y_seq)
    target_indices = np.array(target_indices)

    train_mask = target_indices < train_cut
    test_mask = target_indices >= split_at
    X_train, X_test = X_seq[train_mask], X_seq[test_mask]
    y_train, y_test = y_seq[train_mask], y_seq[test_mask]
    if len(X_train) == 0 or len(X_test) == 0:
        return {"error": "LSTM 학습/테스트 시퀀스 부족", "ticker": ticker}

    # LSTM 모델
    model = keras.Sequential([
        keras.layers.LSTM(50, return_sequences=True, input_shape=(lookback, X.shape[1])),
        keras.layers.Dropout(0.2),
        keras.layers.LSTM(30),
        keras.layers.Dropout(0.2),
        keras.layers.Dense(1, activation='sigmoid')
    ])
    model.compile(optimizer='adam', loss='binary_crossentropy', metrics=['accuracy'])

    fit_X, fit_y = X_train, y_train
    fit_kwargs = {"epochs": 20, "batch_size": 32, "verbose": 0, "shuffle": False}
    if len(X_train) > 10:
        val_size = max(1, int(len(X_train) * 0.1))
        fit_X, fit_y = X_train[:-val_size], y_train[:-val_size]
        fit_kwargs["validation_data"] = (X_train[-val_size:], y_train[-val_size:])

    # 조용히 학습
    model.fit(fit_X, fit_y, **fit_kwargs)

    # 예측
    y_pred_proba = model.predict(X_test, verbose=0).flatten()
    y_pred = (y_pred_proba > 0.5).astype(int)
    accuracy = accuracy_score(y_test, y_pred)

    # 최신 예측
    latest_seq = latest_seq_scaled.reshape(1, lookback, X.shape[1])
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

    split_meta = {
        "train_size": len(X_train),
        "test_size": len(X_test),
        "trainable_rows": len(X_df),
        "split_index": split_at,
        "purge_gap": split_at - train_cut,
    }
    metadata = _prediction_metadata(df, latest_feature_date, horizon)

    return {
        "tool": "ml_lstm",
        "name": f"LSTM 예측 ({horizon}일)",
        "ticker": ticker,
        "signal": "buy" if score > 2 else ("sell" if score < -2 else "neutral"),
        "score": round(score, 1),
        "horizon_days": horizon,
        "prediction": "UP" if latest_pred == 1 else "DOWN",
        "up_probability": round(latest_proba, 4),
        "test_accuracy": round(accuracy, 4),
        **split_meta,
        **metadata,
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

    # 앙상블 예측 (성능 기반 가중 평균)
    valid_models = [r for r in results.values() if not r.get("error")]
    if valid_models:
        weights = []
        probs = []
        model_weights = {}
        for r in valid_models:
            prob = float(r.get("up_probability", 0.5))
            acc = float(r.get("test_accuracy", 0.0) or 0.0)
            weight = max(acc, 0.0)
            weights.append(weight)
            probs.append(prob)
            model_weights[r.get("tool", "unknown")] = round(weight, 4)
        total_weight = float(np.sum(weights))
        if total_weight > 0:
            ensemble_up_prob = float(np.average(probs, weights=weights))
            ensemble_method = "accuracy_weighted"
        else:
            ensemble_up_prob = float(np.mean(probs))
            ensemble_method = "simple_mean_fallback"
        ensemble_pred = "UP" if ensemble_up_prob > 0.5 else "DOWN"
        ensemble_signal = "buy" if ensemble_up_prob > 0.6 else ("sell" if ensemble_up_prob < 0.4 else "neutral")
        avg_accuracy = float(np.mean([r.get("test_accuracy", 0.0) for r in valid_models]))
    else:
        ensemble_up_prob = 0.5
        ensemble_pred = "HOLD"
        ensemble_signal = "neutral"
        ensemble_method = "no_valid_model"
        model_weights = {}
        avg_accuracy = 0.0

    best = max(results.values(), key=lambda x: x.get("test_accuracy", 0) if not x.get("error") else 0)

    return {
        "ticker": ticker,
        "models": results,
        "ensemble": {
            "prediction": ensemble_pred,
            "up_probability": round(float(ensemble_up_prob), 4),
            "signal": ensemble_signal,
            "model_count": len(valid_models),
            "method": ensemble_method,
            "model_weights": model_weights,
            "avg_accuracy": round(avg_accuracy, 4),
        },
        "best_model": best.get("tool", "rf_5d"),
        "best_prediction": best.get("prediction", "?"),
        "best_up_probability": best.get("up_probability", 0.5),
        "best_accuracy": best.get("test_accuracy", 0),
    }
