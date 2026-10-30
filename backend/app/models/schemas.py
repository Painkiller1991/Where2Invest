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
    model: Literal["hybrid", "auto", "lightgbm", "prophet", "both", "drift"] = "hybrid"


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
    # هر `toman_per_point` تومان موجودی = ۱ امتیاز در روز (×۳۰ در ماه)؛ با `points_for_loan` امتیاز، `loan_for_points` وام
    toman_per_point: float = 100_000
    points_for_loan: float = Field(default=100.0, gt=0)
    loan_for_points: float = Field(default=100_000_000.0, gt=0)
    model3_bank_annual_pct: float = 0.0
    repay_months_model3: int | None = None


class InvestMonthStep(BaseModel):
    """یک ماه از سناریو برای نمایش جزئیات قابل‌بازشدن."""

    month: int
    label: str = ""
    events: list[str] = Field(default_factory=list)
    cash_in: float = 0.0
    buy: float = 0.0
    installment: float = 0.0
    points: float = 0.0
    deposit: float = 0.0
    debt: float = 0.0
    asset_value: float = 0.0
    cash: float = 0.0
    wealth: float = 0.0
    price: float = 0.0
    units_bought: float = 0.0
    units_held: float = 0.0
    unit_label: str = ""


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
    timeline: list[InvestMonthStep] = Field(default_factory=list)
    units_held: float = 0.0
    unit_label: str = ""
    end_price: float = 0.0


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


class InvestContext(BaseModel):
    """اعداد ثابت کمکی برای UI حین/بعد از محاسبه."""

    horizon_months: int
    usd_now: float
    usd_end: float
    usd_change_pct: float
    ounce_now: float
    ounce_end: float
    ounce_change_pct: float
    gram18_now: float
    gram18_end: float
    gram18_change_pct: float
    capital_toman: float
    monthly_budget_toman: float
    total_cash_in: float
    capital_as_usd_now: float
    capital_as_gram18_now: float
    monthly_as_usd_now: float
    monthly_as_gram18_now: float
    capital_as_usd_end: float
    capital_as_gram18_end: float
    monthly_as_usd_end: float
    monthly_as_gram18_end: float


class InvestCompareResponse(BaseModel):
    results: list[InvestResult]
    best_method: str
    recommendation: InvestRecommendation | None = None
    assumptions: dict[str, Any]
    suggested_monthly: float = 0.0
    context: InvestContext | None = None
