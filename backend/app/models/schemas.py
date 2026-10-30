from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class Candle(BaseModel):
    time: int  # unix seconds
    open: float
    high: float
    low: float
    close: float
    volume: float | None = None


class SeriesPayload(BaseModel):
    symbol: str
    title: str
    unit: str
    candles: list[Candle]
    source: str
    start_date: str
    end_date: str


class DataStatus(BaseModel):
    ready: bool
    gold: SeriesPayload | None = None
    usd: SeriesPayload | None = None
    error: str | None = None
    attempts: int = 0
    effective_start: str | None = None
    updated: Literal["cache", "incremental", "full"] | None = None


class ConfigUpdate(BaseModel):
    patch: dict[str, Any]


class FetchRequest(BaseModel):
    start_date: str | None = None
    force: bool = False


class ForecastRequest(BaseModel):
    gold_sentiment: float = Field(ge=-10, le=10)
    usd_sentiment: float = Field(ge=-10, le=10)
    months: int = Field(ge=1, le=36)
    model: Literal["lightgbm", "prophet", "both"] = "both"


class ForecastPoint(BaseModel):
    time: int
    value: float
    is_forecast: bool = True


class ForecastSeries(BaseModel):
    symbol: str
    unit: str
    historical: list[Candle]
    forecast: list[ForecastPoint]
    model_used: str
    metrics: dict[str, float] = Field(default_factory=dict)


class ForecastResponse(BaseModel):
    gold: ForecastSeries
    usd: ForecastSeries
    months: int
    gold_sentiment: float
    usd_sentiment: float
    confirmed: bool = False


class ConfirmForecastRequest(BaseModel):
    confirm: bool = True


class InvestInput(BaseModel):
    capital_toman: float = Field(ge=0)
    monthly_budget_toman: float = Field(ge=0, default=0)
    fund_annual_pct: float = 20.0

    enable_gold: bool = True
    enable_usd: bool = True
    enable_fund: bool = True

    enable_fintech: bool = True
    enable_direct: bool = True
    enable_bank_to_bank: bool = True
    enable_bank_to_asset: bool = True

    # مدل ۱ — فین‌تک
    loan_amount: float = 100_000_000
    company_fee_pct: float = 5.0
    bank_annual_pct: float = 22.0
    repay_months: int = Field(default=12, ge=1, le=120)
    fee_source: Literal["from_loan", "cash"] = "from_loan"

    # مدل ۳ — بانک → امتیاز → وام
    toman_per_point: float = 100_000
    loan_per_point: float = 1_000_000
    wait_months: int = Field(default=3, ge=1, le=36)
    model3_bank_annual_pct: float = 0.0
    repay_months_model3: int | None = None


class InvestResult(BaseModel):
    method: str
    model: str
    asset: str
    title: str
    investable: float = 0.0
    start_value: float
    end_value: float
    net_profit: float
    profit: float
    profit_pct: float
    notes: str = ""
    valid: bool = True


class InvestRecommendation(BaseModel):
    model: str
    asset: str
    method: str
    net_profit: float
    profit_pct: float
    message: str


class InvestSuggestResponse(BaseModel):
    suggested_monthly: float
    details: dict[str, float] = Field(default_factory=dict)


class InvestCompareResponse(BaseModel):
    results: list[InvestResult]
    best_method: str
    recommendation: InvestRecommendation | None = None
    assumptions: dict[str, Any]
    suggested_monthly: float = 0.0
