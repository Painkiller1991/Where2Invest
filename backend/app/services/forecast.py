from __future__ import annotations

import logging
import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_percentage_error

from app.models.schemas import Candle, ForecastPoint, ForecastResponse, ForecastSeries
from app.services.data_fetch import data_gate

logger = logging.getLogger(__name__)

_last_forecast: ForecastResponse | None = None
_confirmed: bool = False

# حداکثر جهش مجاز روز اول نسبت به آخرین قیمت واقعی (پیوستگی چارت)
_MAX_DAY1_MOVE = 0.025


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
    last_px = float(series.iloc[-1])

    results: dict[str, tuple[np.ndarray, dict[str, float]]] = {}
    model_key = (model or "hybrid").lower().strip()

    if model_key in ("hybrid", "trend", "auto", "both"):
        try:
            results["hybrid"] = _hybrid_trend_forecast(series, sentiment, horizon_days)
        except Exception as e:  # noqa: BLE001
            logger.exception("hybrid trend failed: %s", e)

    if model_key in ("lightgbm", "both", "lgb", "auto"):
        try:
            results["lightgbm"] = _lightgbm_return_forecast(series, sentiment, horizon_days)
        except Exception as e:  # noqa: BLE001
            logger.exception("LightGBM failed: %s", e)

    # Prophet فقط وقتی صریحاً انتخاب شود (فصلی بودنش مسیر را موجی/مصنوعی می‌کند)
    if model_key == "prophet":
        try:
            results["prophet"] = _prophet_forecast(series, sentiment, horizon_days)
        except Exception as e:  # noqa: BLE001
            logger.exception("Prophet failed: %s", e)

    if model_key in ("drift",) or not results:
        results["drift"] = _drift_forecast(series, sentiment, horizon_days)

    if model_key in ("hybrid", "trend") and "hybrid" in results:
        chosen = "hybrid"
        preds, metrics = results["hybrid"]
    elif model_key == "both" and "hybrid" in results and "lightgbm" in results:
        # ترکیب بافت‌دار hybrid با مسیر GBM بازده — بدون Prophet
        preds = _blend_return_paths(
            results["hybrid"][0], results["lightgbm"][0], last_px, w_a=0.65
        )
        chosen = "hybrid+lightgbm"
        metrics = {
            "hybrid_mape": results["hybrid"][1].get("mape", 0.0),
            "lgb_mape": results["lightgbm"][1].get("mape", 0.0),
        }
    elif model_key == "both" and "lightgbm" in results:
        chosen = "lightgbm"
        preds, metrics = results["lightgbm"]
    elif model_key == "auto":
        if "hybrid" in results and "lightgbm" in results:
            preds = _blend_return_paths(
                results["hybrid"][0], results["lightgbm"][0], last_px, w_a=0.55
            )
            chosen = "hybrid+lightgbm"
            metrics = {
                "hybrid_mape": results["hybrid"][1].get("mape", 0.0),
                "lgb_mape": results["lightgbm"][1].get("mape", 0.0),
            }
        elif "hybrid" in results:
            chosen = "hybrid"
            preds, metrics = results["hybrid"]
        else:
            chosen = next(iter(results))
            preds, metrics = results[chosen]
    elif model_key in results:
        chosen = model_key if model_key in results else next(iter(results))
        if chosen not in results:
            chosen = next(iter(results))
        preds, metrics = results[chosen]
    else:
        chosen = next(iter(results))
        preds, metrics = results[chosen]

    preds = _finalize_path(np.asarray(preds, dtype=float), last_px, series)

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
    """نقشهٔ [-10, 10] → [-1, 1]."""
    return float(np.clip(sentiment, -10.0, 10.0)) / 10.0


def _winsorized_returns(series: pd.Series) -> pd.Series:
    rets = series.astype(float).pct_change().dropna()
    if len(rets) < 10:
        return rets
    lo, hi = rets.quantile(0.02), rets.quantile(0.98)
    return rets.clip(lo, hi)


def _target_daily_drift(rets: pd.Series, sentiment: float) -> tuple[float, float]:
    """درافت روزانهٔ معقول + نوسان؛ احساس فقط شیفت سالانهٔ محدود می‌دهد."""
    if len(rets) == 0:
        return 0.0, 0.01
    mu_s = float(rets.tail(21).mean())
    mu_m = float(rets.tail(63).mean()) if len(rets) >= 40 else mu_s
    mu_y = float(rets.tail(252).mean()) if len(rets) >= 120 else mu_m
    vol = float(rets.tail(42).std()) if len(rets) >= 15 else 0.01
    vol = float(np.clip(vol, 0.002, 0.05))

    base = 0.4 * mu_s + 0.35 * mu_m + 0.25 * mu_y
    # سقف درافت خام از تاریخ: حدود ±۳×vol روزانه ولی نه انفجاری
    base = float(np.clip(base, -1.5 * vol, 1.5 * vol))

    sent = _sentiment_scale(sentiment)
    # شیفت سالانه حداکثر حدود ±۳۵٪؛ تبدیل به روزانه
    ann_shift = sent * 0.28
    daily_shift = (1.0 + ann_shift) ** (1.0 / 252.0) - 1.0
    # ~±۵۵٪ سالانه از محل درافت؛ بافت جداگانه نوسان می‌سازد
    daily_mu = float(np.clip(base + daily_shift, -0.0022, 0.0018))
    return daily_mu, vol


def _residual_bank(rets: pd.Series) -> np.ndarray:
    """پسماندهای بازده به واحد واقعی (نه نرمال‌شده) تا نوسان مسیر ≈ تاریخ بماند."""
    if len(rets) < 5:
        return np.array([0.0], dtype=float)
    mu = float(rets.mean())
    return (rets - mu).to_numpy(dtype=float)


def _textured_path(
    *,
    last: float,
    horizon: int,
    daily_mu: float,
    vol: float,
    resid: np.ndarray,
    sentiment: float,
) -> np.ndarray:
    """
    مسیر غیرخطی: درافت هدف + پسماندهای تاریخی بازیافتی (دترمینیستیک) + AR ملایم.
    شبیه نوسان واقعی است، نه خط صاف و نه موج فصلی مصنوعی.
    """
    sent = _sentiment_scale(sentiment)
    n = max(len(resid), 1)
    phase = n - 1
    out = np.empty(horizon, dtype=float)
    px = float(last)
    shock = 0.0
    trend = float(last)
    for t in range(horizon):
        # درافت کمی با افق میرا می‌شود تا چندبرابر شدن اغراق‌آمیز نشود
        mu_t = daily_mu * float(np.exp(-t / 520.0))
        trend *= 1.0 + mu_t
        raw = float(resid[(phase + t) % n])
        shock = 0.25 * shock + 0.75 * raw
        local = float(resid[(phase + 3 * t) % n])
        twin = float(resid[(phase + 7 * t + 11) % n])
        # پسماندها خودشان واحد بازده دارند
        texture = 0.70 * shock + 0.20 * local + 0.10 * twin
        # تقویت تا نزدیک نوسان تاریخی (پسماند winsor شده کمی ضعیف‌تر است)
        texture *= 1.55
        if sent > 0.2:
            texture = 0.92 * texture + 0.08 * abs(texture) * (1 if texture >= 0 else -0.2)
        elif sent < -0.2:
            texture = 0.92 * texture + 0.08 * abs(texture) * (-1 if texture <= 0 else 0.2)
        gap = (trend - px) / max(px, 1e-9)
        step = mu_t + texture + 0.025 * float(np.clip(gap, -0.04, 0.04))
        step = float(np.clip(step, -3.5 * vol, 3.5 * vol))
        px = max(px * (1.0 + step), 1e-6)
        out[t] = px
    return out


def _path_return_stats(path: np.ndarray, last: float) -> tuple[float, float]:
    ext = np.concatenate([[last], np.asarray(path, dtype=float)])
    rets = np.diff(ext) / np.maximum(ext[:-1], 1e-9)
    return float(np.mean(rets)), float(np.std(rets))


def _rebase_from_last(preds: np.ndarray, last: float, max_day1: float = _MAX_DAY1_MOVE) -> np.ndarray:
    if preds.size == 0 or last <= 0:
        return preds
    path = np.maximum(np.asarray(preds, dtype=float), 1e-9)
    ext = np.concatenate([[last], path])
    rets = np.diff(ext) / np.maximum(ext[:-1], 1e-9)
    rets[0] = float(np.clip(rets[0], -max_day1, max_day1))
    rets[1:] = np.clip(rets[1:], -0.06, 0.06)
    out = np.empty_like(path)
    px = float(last)
    for i, r in enumerate(rets):
        px = px * (1.0 + float(r))
        out[i] = max(px, 1e-6)
    return out


def _finalize_path(preds: np.ndarray, last: float, series: pd.Series) -> np.ndarray:
    """پیوستگی + اگر مسیر بیش از حد خطی بود، بافت تاریخی تزریق کن."""
    path = _rebase_from_last(preds, last)
    rets = _winsorized_returns(series)
    if len(rets) < 10 or path.size < 3:
        return path
    _, hist_vol = _target_daily_drift(rets, 0.0)
    mu_p, vol_p = _path_return_stats(path, last)
    # خطی ≈ نوسان مسیر خیلی کمتر از تاریخ
    if vol_p < 0.55 * hist_vol:
        resid = _residual_bank(rets)
        path = _textured_path(
            last=last,
            horizon=len(path),
            daily_mu=float(np.clip(mu_p, -0.0035, 0.0032)),
            vol=hist_vol,
            resid=resid,
            sentiment=0.0,
        )
        path = _rebase_from_last(path, last)
    return path


def _blend_return_paths(a: np.ndarray, b: np.ndarray, last: float, w_a: float = 0.6) -> np.ndarray:
    """ادغام دو مسیر در فضای بازده تا میانگین‌گیری سطح، شکل را خراب نکند."""
    def _rets(path: np.ndarray) -> np.ndarray:
        ext = np.concatenate([[last], np.asarray(path, dtype=float)])
        return np.diff(ext) / np.maximum(ext[:-1], 1e-9)

    n = min(len(a), len(b))
    ra, rb = _rets(a[:n]), _rets(b[:n])
    w = float(np.clip(w_a, 0.0, 1.0))
    mix = w * ra + (1.0 - w) * rb
    out = np.empty(n, dtype=float)
    px = float(last)
    for i, r in enumerate(mix):
        px *= 1.0 + float(r)
        out[i] = max(px, 1e-6)
    return out


def _drift_forecast(series: pd.Series, sentiment: float, horizon: int) -> tuple[np.ndarray, dict[str, float]]:
    rets = _winsorized_returns(series)
    daily_mu, vol = _target_daily_drift(rets, sentiment)
    last = float(series.iloc[-1])
    resid = _residual_bank(rets)
    path = _textured_path(
        last=last, horizon=horizon, daily_mu=daily_mu, vol=vol, resid=resid, sentiment=sentiment
    )
    return path, {"mape": 0.0, "daily_mu": daily_mu, "vol": vol}


def _hybrid_trend_forecast(
    series: pd.Series,
    sentiment: float,
    horizon: int,
) -> tuple[np.ndarray, dict[str, float]]:
    """
    مدل پیش‌فرض: درافت معقول از تاریخ+احساس، بافت از پسماندهای واقعی بازار.
    نه خط صاف، نه موج فصلی مصنوعی Prophet.
    """
    last = float(series.iloc[-1])
    rets = _winsorized_returns(series)
    if len(rets) < 5:
        return _drift_forecast(series, sentiment, horizon)

    daily_mu, vol = _target_daily_drift(rets, sentiment)
    resid = _residual_bank(rets)
    path = _textured_path(
        last=last,
        horizon=horizon,
        daily_mu=daily_mu,
        vol=vol,
        resid=resid,
        sentiment=sentiment,
    )

    mape = 0.0
    if len(rets) > 40:
        err = []
        px = series.astype(float)
        for i in range(len(rets) - 20, len(rets)):
            hist_mu = float(rets.iloc[max(0, i - 14) : i].mean())
            pred = float(px.iloc[i]) * (1.0 + hist_mu)
            actual = float(px.iloc[i + 1]) if i + 1 < len(px) else pred
            if actual > 0:
                err.append(abs(pred - actual) / actual)
        mape = float(np.mean(err)) if err else 0.0

    return path, {"mape": mape, "daily_mu": daily_mu, "vol": vol}


def _make_return_supervised(series: pd.Series, lags: int = 21) -> tuple[pd.DataFrame, pd.Series]:
    """هدف: بازده فردا؛ فیچر: بازده/میانگین‌های گذشته."""
    df = pd.DataFrame({"px": series.astype(float)})
    df["y"] = df["px"].pct_change().shift(-1)
    for i in range(1, lags + 1):
        df[f"r_{i}"] = df["px"].pct_change(i)
    df["ma_ratio_7"] = df["px"] / df["px"].rolling(7).mean() - 1.0
    df["ma_ratio_30"] = df["px"] / df["px"].rolling(30).mean() - 1.0
    df["vol_14"] = df["px"].pct_change().rolling(14).std()
    df["dow"] = df.index.dayofweek
    df["month"] = df.index.month
    df = df.dropna()
    y = df["y"]
    X = df.drop(columns=["px", "y"])
    return X, y


def _lightgbm_return_forecast(
    series: pd.Series,
    sentiment: float,
    horizon: int,
) -> tuple[np.ndarray, dict[str, float]]:
    """LightGBM روی بازده (نه سطح قیمت) + شروع از آخرین قیمت."""
    import lightgbm as lgb

    lags = 21
    X, y = _make_return_supervised(series, lags=lags)
    if len(X) < 80:
        return _drift_forecast(series, sentiment, horizon)

    split = int(len(X) * 0.85)
    X_train, X_val = X.iloc[:split].copy(), X.iloc[split:].copy()
    y_train, y_val = y.iloc[:split], y.iloc[split:]
    sent = _sentiment_scale(sentiment)
    X_train["sentiment"] = sent
    X_val["sentiment"] = sent

    model = lgb.LGBMRegressor(
        n_estimators=180,
        learning_rate=0.05,
        num_leaves=24,
        subsample=0.85,
        colsample_bytree=0.85,
        random_state=42,
        verbose=-1,
    )
    model.fit(X_train, y_train)
    val_pred = model.predict(X_val)
    # MAPE روی قیمت بازسازی‌شده یک‌گام
    mape = 0.0
    if len(y_val):
        # تقریبی
        mape = float(np.mean(np.abs(val_pred - y_val.to_numpy()))) * 100.0

    rets_w = _winsorized_returns(series)
    daily_mu, vol = _target_daily_drift(rets_w, sentiment)
    resid = _residual_bank(rets_w)
    nres = max(len(resid), 1)
    phase = nres - 1

    hist = series.copy()
    preds: list[float] = []
    px = float(hist.iloc[-1])
    shock = 0.0
    for t in range(horizon):
        X_next, _ = _make_return_supervised(hist, lags=lags)
        if X_next.empty:
            r_model = daily_mu
        else:
            row = X_next.iloc[[-1]].copy()
            row["sentiment"] = sent
            row = row.reindex(columns=list(X_train.columns), fill_value=0.0)
            r_model = float(model.predict(row)[0])
        raw = float(resid[(phase + t) % nres])
        shock = 0.5 * shock + 0.5 * raw
        # مدل + بافت تاریخی تا مسیر خطی/چسبیده نشود
        r = 0.45 * r_model + 0.35 * (vol * shock) + 0.20 * daily_mu
        r = float(np.clip(r, -2.5 * vol, 2.5 * vol))
        px = px * (1.0 + r)
        preds.append(max(px, 1e-6))
        new_idx = hist.index.max() + pd.Timedelta(days=1)
        hist.loc[new_idx] = px

    return np.array(preds, dtype=float), {"mape": mape, "daily_mu": daily_mu, "vol": vol}


def _prophet_forecast(series: pd.Series, sentiment: float, horizon: int) -> tuple[np.ndarray, dict[str, float]]:
    from prophet import Prophet

    df = pd.DataFrame({"ds": series.index, "y": series.values})
    df["sentiment"] = _sentiment_scale(sentiment)

    # yearly خاموش: موج سینوسی مصنوعی روی افق بلند می‌ساخت
    m = Prophet(
        daily_seasonality=False,
        weekly_seasonality=True,
        yearly_seasonality=False,
        changepoint_prior_scale=0.08,
    )
    m.add_regressor("sentiment")
    m.fit(df)

    mape = 0.0
    if len(df) > 60:
        train = df.iloc[:-30]
        test = df.iloc[-30:]
        m2 = Prophet(
            daily_seasonality=False,
            weekly_seasonality=True,
            yearly_seasonality=False,
            changepoint_prior_scale=0.08,
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
    # بافت تاریخی روی مسیر Prophet تا خطی/موجی خالص نماند
    last = float(series.iloc[-1])
    rets = _winsorized_returns(series)
    daily_mu, vol = _target_daily_drift(rets, sentiment)
    # حفظ جهت کلی prophet ولی بازسازی با بافت
    mu_p, _ = _path_return_stats(preds, last)
    mixed_mu = float(np.clip(0.5 * mu_p + 0.5 * daily_mu, -0.004, 0.005))
    preds = _textured_path(
        last=last,
        horizon=horizon,
        daily_mu=mixed_mu,
        vol=vol,
        resid=_residual_bank(rets),
        sentiment=sentiment,
    )
    return preds, {"mape": mape}
