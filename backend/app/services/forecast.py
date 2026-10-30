from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_percentage_error

from app.models.schemas import Candle, ForecastPoint, ForecastResponse, ForecastSeries
from app.services.data_fetch import data_gate

logger = logging.getLogger(__name__)

_last_forecast: ForecastResponse | None = None
_confirmed: bool = False


def get_last_forecast() -> ForecastResponse | None:
    return _last_forecast


def is_confirmed() -> bool:
    return _confirmed and _last_forecast is not None


def confirm_forecast(confirm: bool = True) -> ForecastResponse:
    global _confirmed, _last_forecast
    if _last_forecast is None:
        raise RuntimeError("No forecast to confirm")
    _confirmed = confirm
    _last_forecast = _last_forecast.model_copy(update={"confirmed": confirm})
    return _last_forecast


def run_forecast(
    gold_sentiment: float,
    usd_sentiment: float,
    months: int,
    model: str = "both",
) -> ForecastResponse:
    global _last_forecast, _confirmed
    if not data_gate.ready:
        raise RuntimeError("Data gate not ready — complete Step 1 first")

    gold_df, usd_df = data_gate.get_frames()
    horizon_days = max(1, int(months * 30.44))

    gold_series = _forecast_one(
        gold_df["Close"],
        sentiment=gold_sentiment,
        horizon_days=horizon_days,
        model=model,
        symbol="XAUUSD",
        unit="USD/oz",
        hist_df=gold_df,
    )
    usd_series = _forecast_one(
        usd_df["Close"],
        sentiment=usd_sentiment,
        horizon_days=horizon_days,
        model=model,
        symbol="USDIRT",
        unit="toman",
        hist_df=usd_df,
    )

    resp = ForecastResponse(
        gold=gold_series,
        usd=usd_series,
        months=months,
        gold_sentiment=gold_sentiment,
        usd_sentiment=usd_sentiment,
        confirmed=False,
    )
    _last_forecast = resp
    _confirmed = False
    return resp


def _forecast_one(
    series: pd.Series,
    sentiment: float,
    horizon_days: int,
    model: str,
    symbol: str,
    unit: str,
    hist_df: pd.DataFrame,
) -> ForecastSeries:
    series = series.dropna().astype(float)
    series.index = pd.to_datetime(series.index).tz_localize(None)

    results: dict[str, tuple[np.ndarray, dict[str, float]]] = {}

    if model in ("lightgbm", "both"):
        try:
            results["lightgbm"] = _lightgbm_forecast(series, sentiment, horizon_days)
        except Exception as e:  # noqa: BLE001
            logger.exception("LightGBM failed: %s", e)

    if model in ("prophet", "both"):
        try:
            results["prophet"] = _prophet_forecast(series, sentiment, horizon_days)
        except Exception as e:  # noqa: BLE001
            logger.exception("Prophet failed: %s", e)

    if not results:
        # deterministic fallback: drift + sentiment nudge
        results["drift"] = _drift_forecast(series, sentiment, horizon_days)

    # Prefer lightgbm when both
    if "lightgbm" in results:
        chosen = "lightgbm"
    else:
        chosen = next(iter(results))

    preds, metrics = results[chosen]
    if model == "both" and "prophet" in results and "lightgbm" in results:
        # blend
        preds = 0.6 * results["lightgbm"][0] + 0.4 * results["prophet"][0]
        chosen = "lightgbm+prophet"
        metrics = {
            "lgb_mape": results["lightgbm"][1].get("mape", 0.0),
            "prophet_mape": results["prophet"][1].get("mape", 0.0),
        }

    last_ts = pd.Timestamp(series.index.max())
    future_idx = pd.date_range(last_ts + pd.Timedelta(days=1), periods=horizon_days, freq="D")
    forecast_points = [
        ForecastPoint(time=int(pd.Timestamp(t).timestamp()), value=float(v), is_forecast=True)
        for t, v in zip(future_idx, preds)
    ]

    candles = [
        Candle(
            time=int(pd.Timestamp(idx).timestamp()),
            open=float(row["Open"]),
            high=float(row["High"]),
            low=float(row["Low"]),
            close=float(row["Close"]),
            volume=float(row["Volume"]) if "Volume" in row and pd.notna(row.get("Volume")) else None,
        )
        for idx, row in hist_df.iterrows()
    ]

    return ForecastSeries(
        symbol=symbol,
        unit=unit,
        historical=candles,
        forecast=forecast_points,
        model_used=chosen,
        metrics=metrics,
    )


def _sentiment_scale(sentiment: float) -> float:
    # map [-10,10] -> roughly [-2%, +2%] daily drift boost accumulated softly
    return float(sentiment) / 10.0


def _drift_forecast(series: pd.Series, sentiment: float, horizon: int) -> tuple[np.ndarray, dict[str, float]]:
    rets = series.pct_change().dropna()
    mu = float(rets.tail(60).mean()) if len(rets) else 0.0
    boost = _sentiment_scale(sentiment) * 0.0007
    last = float(series.iloc[-1])
    out = []
    px = last
    for _ in range(horizon):
        px = px * (1.0 + mu + boost)
        out.append(px)
    return np.array(out, dtype=float), {"mape": 0.0}


def _make_supervised(series: pd.Series, lags: int = 30) -> tuple[pd.DataFrame, pd.Series]:
    df = pd.DataFrame({"y": series})
    for i in range(1, lags + 1):
        df[f"lag_{i}"] = df["y"].shift(i)
    df["ret_1"] = df["y"].pct_change()
    df["ret_7"] = df["y"].pct_change(7)
    df["ma_7"] = df["y"].rolling(7).mean()
    df["ma_30"] = df["y"].rolling(30).mean()
    df["dow"] = df.index.dayofweek
    df["month"] = df.index.month
    df = df.dropna()
    X = df.drop(columns=["y"])
    y = df["y"]
    return X, y


def _lightgbm_forecast(series: pd.Series, sentiment: float, horizon: int) -> tuple[np.ndarray, dict[str, float]]:
    import lightgbm as lgb

    lags = 30
    X, y = _make_supervised(series, lags=lags)
    if len(X) < 80:
        return _drift_forecast(series, sentiment, horizon)

    split = int(len(X) * 0.85)
    X_train, X_val = X.iloc[:split], X.iloc[split:]
    y_train, y_val = y.iloc[:split], y.iloc[split:]

    # sentiment as constant feature
    for frame in (X_train, X_val):
        frame["sentiment"] = _sentiment_scale(sentiment)

    model = lgb.LGBMRegressor(
        n_estimators=200,
        learning_rate=0.05,
        num_leaves=31,
        subsample=0.8,
        colsample_bytree=0.8,
        random_state=42,
        verbose=-1,
    )
    model.fit(X_train, y_train)
    val_pred = model.predict(X_val)
    mape = float(mean_absolute_percentage_error(y_val, val_pred)) if len(y_val) else 0.0

    # recursive forecast
    hist = series.copy()
    preds: list[float] = []
    sent = _sentiment_scale(sentiment)
    for _ in range(horizon):
        X_next, _ = _make_supervised(hist, lags=lags)
        row = X_next.iloc[[-1]].copy()
        row["sentiment"] = sent
        # align columns
        row = row.reindex(columns=list(X_train.columns), fill_value=0.0)
        yhat = float(model.predict(row)[0])
        # soft sentiment nudge on top
        yhat *= 1.0 + sent * 0.0005
        preds.append(max(yhat, 1e-6))
        new_idx = hist.index.max() + pd.Timedelta(days=1)
        hist.loc[new_idx] = yhat

    return np.array(preds, dtype=float), {"mape": mape}


def _prophet_forecast(series: pd.Series, sentiment: float, horizon: int) -> tuple[np.ndarray, dict[str, float]]:
    from prophet import Prophet

    df = pd.DataFrame({"ds": series.index, "y": series.values})
    # sentiment as future regressor held constant
    df["sentiment"] = _sentiment_scale(sentiment)

    m = Prophet(
        daily_seasonality=False,
        weekly_seasonality=True,
        yearly_seasonality=True,
        changepoint_prior_scale=0.05,
    )
    m.add_regressor("sentiment")
    m.fit(df)

    # quick holdout mape on last 30 points if possible
    mape = 0.0
    if len(df) > 60:
        train = df.iloc[:-30]
        test = df.iloc[-30:]
        m2 = Prophet(
            daily_seasonality=False,
            weekly_seasonality=True,
            yearly_seasonality=True,
            changepoint_prior_scale=0.05,
        )
        m2.add_regressor("sentiment")
        m2.fit(train)
        fc = m2.predict(test[["ds", "sentiment"]])
        mape = float(mean_absolute_percentage_error(test["y"], fc["yhat"]))

    future = m.make_future_dataframe(periods=horizon, freq="D")
    future["sentiment"] = _sentiment_scale(sentiment)
    forecast = m.predict(future)
    preds = forecast["yhat"].iloc[-horizon:].to_numpy(dtype=float)
    preds = np.maximum(preds, 1e-6)
    # mild sentiment tilt on slope
    tilt = 1.0 + _sentiment_scale(sentiment) * 0.0003 * np.arange(1, horizon + 1)
    preds = preds * tilt
    return preds, {"mape": mape}
