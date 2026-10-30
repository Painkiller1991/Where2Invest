"""Investment path comparison: fintech, direct DCA, bank→loan (two variants)."""

from __future__ import annotations

from typing import Any

from app.config_loader import load_config
from app.models.schemas import (
    InvestCompareResponse,
    InvestContext,
    InvestInput,
    InvestMonthStep,
    InvestRecommendation,
    InvestResult,
    InvestSuggestResponse,
)
from app.services.forecast import get_last_forecast, is_confirmed
from app.services.gold_iran_price import constants_from_config, gram18
from app.services.loan_math import (
    POINTS_DAYS_PER_MONTH,
    declining_balance_schedule,
    fund_value_from_cashflows,
    horizon_days,
    max_monthly_payment,
    month_to_day,
    points_earned_in_month,
    remaining_principal_after_months,
)

MODEL_TITLES = {
    "fintech_loan": "وام فین‌تک",
    "direct": "خرید مستقیم",
    "bank_points_to_bank": "بانک→وام (ماهانه به بانک)",
    "bank_points_to_asset": "بانک→وام (ماهانه دارایی)",
}

ASSET_TITLES = {
    "gold": "طلای گرم ۱۸",
    "usd": "دلار آزاد",
    "fund": "صندوق درآمد ثابت",
}

ASSET_UNIT_LABELS = {
    "gold": "گرم طلا",
    "usd": "دلار",
    "fund": "",
}


def _sample_series(start: float, forecast_vals: list[float], h: int) -> list[float]:
    """Price/index at month 0..H (inclusive)."""
    out = [float(start)]
    n = len(forecast_vals)
    if n == 0:
        return out + [float(start)] * h
    for m in range(1, h + 1):
        day = month_to_day(m)
        idx = min(n - 1, max(0, day - 1))
        out.append(float(forecast_vals[idx]))
    return out


def _asset_prices(
    asset: str,
    oz: list[float],
    usd: list[float],
    consts: Any,
) -> list[float]:
    if asset == "usd":
        return list(usd)
    if asset == "gold":
        return [gram18(o, u, constants=consts, premium=0.0) for o, u in zip(oz, usd)]
    return [1.0] * len(oz)


class _Book:
    """Mark-to-market book for gold/usd units or fund cashflows."""

    def __init__(self, asset: str, prices: list[float], fund_annual_pct: float) -> None:
        self.asset = asset
        self.prices = prices
        self.fund_annual_pct = fund_annual_pct
        self.units = 0.0
        self.flows: list[tuple[int, float]] = []

    def buy(self, amount: float, month: int) -> float:
        """خرید به تومان؛ مقدار واحد خریده‌شده را برمی‌گرداند (دلار/گرم)."""
        if amount <= 1e-9:
            return 0.0
        m = max(0, min(int(month), len(self.prices) - 1))
        if self.asset == "fund":
            self.flows.append((month_to_day(m), amount))
            return 0.0
        px = self.prices[m]
        if px <= 0:
            return 0.0
        got = amount / px
        self.units += got
        return got

    def value(self, month: int) -> float:
        m = max(0, min(int(month), len(self.prices) - 1))
        if self.asset == "fund":
            return fund_value_from_cashflows(self.flows, self.fund_annual_pct, month_to_day(m))
        return self.units * self.prices[m]

    def price(self, month: int) -> float:
        m = max(0, min(int(month), len(self.prices) - 1))
        if self.asset == "fund":
            contributed = sum(a for _, a in self.flows)
            v = self.value(m)
            return (v / contributed) if contributed > 1e-9 else 1.0
        return self.prices[m]


def _unit_label(asset: str) -> str:
    return ASSET_UNIT_LABELS.get(asset, "")


def _fmt_units(n: float, asset: str) -> str:
    label = _unit_label(asset)
    if not label:
        return ""
    if asset == "usd":
        return f"{n:,.2f} {label}"
    return f"{n:,.4f} {label}"


def _step(
    *,
    month: int,
    label: str,
    events: list[str],
    cash_in: float = 0.0,
    buy: float = 0.0,
    installment: float = 0.0,
    points: float = 0.0,
    deposit: float = 0.0,
    debt: float = 0.0,
    asset_value: float = 0.0,
    cash: float = 0.0,
    price: float = 0.0,
    units_bought: float = 0.0,
    units_held: float = 0.0,
    unit_label: str = "",
) -> InvestMonthStep:
    wealth = asset_value + cash + deposit
    return InvestMonthStep(
        month=month,
        label=label,
        events=events,
        cash_in=cash_in,
        buy=buy,
        installment=installment,
        points=points,
        deposit=deposit,
        debt=debt,
        asset_value=asset_value,
        cash=cash,
        wealth=wealth,
        price=price,
        units_bought=units_bought,
        units_held=units_held,
        unit_label=unit_label,
    )


def _row(
    *,
    model: str,
    asset: str,
    investable: float,
    total_cash_in: float,
    end_value: float,
    remaining_debt: float,
    notes: str,
    valid: bool = True,
    timeline: list[InvestMonthStep] | None = None,
    units_held: float = 0.0,
    end_price: float = 0.0,
) -> InvestResult:
    wealth = end_value
    net = wealth - remaining_debt - total_cash_in
    pct = (net / total_cash_in * 100.0) if total_cash_in > 0 else 0.0
    method = f"{model}__{asset}"
    title = f"{MODEL_TITLES[model]} → {ASSET_TITLES[asset]}"
    ul = _unit_label(asset)
    return InvestResult(
        method=method,
        model=model,
        asset=asset,
        title=title,
        investable=investable,
        start_value=total_cash_in,
        end_value=wealth,
        net_profit=net,
        profit=net,
        profit_pct=pct,
        notes=notes if valid else f"نامعتبر: {notes}",
        valid=valid,
        timeline=timeline or [],
        units_held=units_held,
        unit_label=ul,
        end_price=end_price,
    )


def _enabled_assets(payload: InvestInput) -> list[str]:
    out: list[str] = []
    if payload.enable_gold:
        out.append("gold")
    if payload.enable_usd:
        out.append("usd")
    if payload.enable_fund:
        out.append("fund")
    return out


def _loan_per_point(payload: InvestInput) -> float:
    return float(payload.loan_for_points) / max(float(payload.points_for_loan), 1e-9)


def _sim_direct(
    *,
    capital: float,
    monthly: float,
    asset: str,
    prices: list[float],
    fund_annual_pct: float,
    h: int,
) -> tuple[float, list[InvestMonthStep], float, float]:
    book = _Book(asset, prices, fund_annual_pct)
    ul = _unit_label(asset)
    timeline: list[InvestMonthStep] = []
    u0 = book.buy(capital, 0)
    events0 = [f"خرید اولیه سرمایه {capital:,.0f} تومان"]
    if ul and u0 > 0:
        events0.append(f"≈ {_fmt_units(u0, asset)} @ {book.price(0):,.0f}")
    timeline.append(
        _step(
            month=0,
            label="شروع",
            events=events0,
            cash_in=capital,
            buy=capital,
            asset_value=book.value(0),
            price=book.price(0),
            units_bought=u0,
            units_held=book.units,
            unit_label=ul,
        )
    )
    for m in range(1, h + 1):
        um = book.buy(monthly, m)
        events = [f"خرید DCA ماهانه {monthly:,.0f} تومان"] if monthly > 0 else ["بدون خرید ماهانه"]
        if ul and um > 0:
            events.append(f"≈ {_fmt_units(um, asset)} @ {book.price(m):,.0f}")
        timeline.append(
            _step(
                month=m,
                label=f"ماه {m}",
                events=events,
                cash_in=monthly,
                buy=monthly,
                asset_value=book.value(m),
                price=book.price(m),
                units_bought=um,
                units_held=book.units,
                unit_label=ul,
            )
        )
    return book.value(h), timeline, book.units, book.price(h)


def _sim_fintech(
    *,
    capital: float,
    monthly: float,
    loan_amount: float,
    fee: float,
    fee_source: str,
    asset: str,
    prices: list[float],
    fund_annual_pct: float,
    h: int,
    sched: list[Any],
) -> tuple[float, float, float, bool, list[str], list[InvestMonthStep], float, float]:
    notes: list[str] = [
        f"وام {loan_amount:,.0f}",
        f"کارمزد {fee:,.0f} ({fee_source})",
    ]
    valid = True
    max_pay = max_monthly_payment(sched)
    notes.append(f"قسط اول ~{max_pay:,.0f}")
    if max_pay > monthly + 1e-6:
        valid = False
        notes.append(f"قسط بیشتر از بودجه ماهانه ({monthly:,.0f})")

    leftover = 0.0
    investable = 0.0
    if fee_source == "cash":
        if capital + 1e-6 < fee:
            valid = False
            notes.append("سرمایه برای کارمزد کافی نیست")
            investable = 0.0
            leftover = capital
        else:
            investable = loan_amount
            leftover = capital - fee
    else:
        investable = loan_amount - fee
        leftover = capital

    book = _Book(asset, prices, fund_annual_pct)
    ul = _unit_label(asset)
    timeline: list[InvestMonthStep] = []
    events0 = [
        f"دریافت وام {loan_amount:,.0f}",
        f"کسر کارمزد {fee:,.0f}",
        f"خرید دارایی {investable:,.0f}",
    ]
    if leftover > 0:
        events0.append(f"مانده نقد {leftover:,.0f}")
    u0 = book.buy(investable, 0)
    if ul and u0 > 0:
        events0.append(f"≈ {_fmt_units(u0, asset)} @ {book.price(0):,.0f}")
    debt0 = loan_amount
    timeline.append(
        _step(
            month=0,
            label="شروع",
            events=events0,
            cash_in=capital,
            buy=investable,
            debt=debt0,
            asset_value=book.value(0),
            cash=leftover,
            price=book.price(0),
            units_bought=u0,
            units_held=book.units,
            unit_label=ul,
        )
    )

    debt = debt0
    for m in range(1, h + 1):
        events: list[str] = []
        installment = 0.0
        buy = 0.0
        um = 0.0
        if m <= len(sched):
            inst = sched[m - 1]
            installment = inst.payment
            debt = inst.remaining
            events.append(f"پرداخت قسط {installment:,.0f} (اصل {inst.principal:,.0f} + بهره {inst.interest:,.0f})")
            surplus = monthly - installment
            if surplus > 1e-6:
                um = book.buy(surplus, m)
                buy = surplus
                events.append(f"مانده بودجه → خرید {surplus:,.0f}")
                if ul and um > 0:
                    events.append(f"≈ {_fmt_units(um, asset)}")
            elif surplus < -1e-6:
                events.append("بودجه کمتر از قسط")
        else:
            debt = 0.0
            if monthly > 1e-6:
                um = book.buy(monthly, m)
                buy = monthly
                events.append(f"پس از تسویه؛ خرید ماهانه {monthly:,.0f}")
                if ul and um > 0:
                    events.append(f"≈ {_fmt_units(um, asset)}")
            else:
                events.append("پس از تسویه وام")
        timeline.append(
            _step(
                month=m,
                label=f"ماه {m}",
                events=events,
                cash_in=monthly,
                buy=buy,
                installment=installment,
                debt=debt,
                asset_value=book.value(m),
                cash=leftover,
                price=book.price(m),
                units_bought=um,
                units_held=book.units,
                unit_label=ul,
            )
        )

    months_paid = min(h, len(sched))
    rem_debt = remaining_principal_after_months(sched, months_paid) if sched else 0.0
    end_value = book.value(h) + leftover
    return end_value, rem_debt, investable, valid, notes, timeline, book.units, book.price(h)


def _sim_bank(
    *,
    capital: float,
    monthly: float,
    asset: str,
    prices: list[float],
    fund_annual_pct: float,
    h: int,
    to_bank: bool,
    toman_per_point: float,
    points_needed: float,
    loan_for_points: float,
    model3_bank_annual_pct: float,
    repay_months_model3: int | None,
) -> tuple[float, float, float, bool, list[str], list[InvestMonthStep], float, float]:
    tpp = max(float(toman_per_point), 1e-9)
    need = max(float(points_needed), 0.0)
    deposit = max(float(capital), 0.0)
    points = 0.0
    unlocked = False
    wait = h
    loan = 0.0
    debt = 0.0
    sched: list[Any] = []
    pay_i = 0
    book = _Book(asset, prices, fund_annual_pct)
    ul = _unit_label(asset)
    timeline: list[InvestMonthStep] = []
    investable = 0.0

    timeline.append(
        _step(
            month=0,
            label="شروع",
            events=[f"موجودی اولیه برای امتیاز {deposit:,.0f} تومان"],
            cash_in=capital,
            deposit=deposit,
            points=0.0,
            asset_value=0.0,
            cash=0.0,
            price=book.price(0),
            unit_label=ul,
        )
    )

    for m in range(1, h + 1):
        events: list[str] = []
        buy = 0.0
        um = 0.0
        installment = 0.0
        cash_in = monthly

        if not unlocked:
            daily_pts = deposit / tpp
            gained = points_earned_in_month(deposit, tpp)
            points += gained
            events.append(
                f"امتیاز روزانه ≈{daily_pts:.1f} × {POINTS_DAYS_PER_MONTH} روز "
                f"= +{gained:.1f} → جمع {points:.1f}/{need:g}"
            )
            if points + 1e-9 >= need:
                unlocked = True
                wait = m
                loan = float(loan_for_points)
                debt = loan
                unlock_cash = deposit + loan
                investable = unlock_cash
                um += book.buy(unlock_cash, m)
                buy += unlock_cash
                events.append(f"رسیدن به امتیاز؛ آزادسازی وام {loan:,.0f}")
                events.append(f"خرید یکجا سپرده+وام {unlock_cash:,.0f}")
                if ul and um > 0:
                    events.append(f"≈ {_fmt_units(um, asset)} @ {book.price(m):,.0f}")
                deposit = 0.0
                repay_n = max(1, int(repay_months_model3) if repay_months_model3 else 12)
                if loan > 0:
                    # بهره ۰ = فقط اصل مساوی ماهانه؛ همچنان قسط برای بودجه ماهانه لازم است
                    sched = declining_balance_schedule(
                        loan, max(0.0, float(model3_bank_annual_pct)), repay_n
                    )
                    events.append(
                        f"شروع اقساط {repay_n} ماهه (قسط اول ~{max_monthly_payment(sched):,.0f})"
                    )
                if monthly > 1e-6:
                    u_m = book.buy(monthly, m)
                    um += u_m
                    buy += monthly
                    events.append(f"بودجه ماه آزادسازی → خرید {monthly:,.0f}")
                    if ul and u_m > 0:
                        events.append(f"≈ {_fmt_units(u_m, asset)}")
            else:
                if to_bank:
                    deposit += monthly
                    events.append(f"واریز ماهانه به بانک؛ سپرده {deposit:,.0f}")
                else:
                    um = book.buy(monthly, m)
                    buy = monthly
                    events.append(f"خرید ماهانه دارایی {monthly:,.0f}؛ سپرده امتیاز {deposit:,.0f}")
                    if ul and um > 0:
                        events.append(f"≈ {_fmt_units(um, asset)} @ {book.price(m):,.0f}")
        else:
            use_inst = bool(sched)
            if use_inst and pay_i < len(sched):
                inst = sched[pay_i]
                installment = inst.payment
                debt = inst.remaining
                pay_i += 1
                events.append(
                    f"قسط {pay_i}/{len(sched)}: {installment:,.0f} "
                    f"(اصل {inst.principal:,.0f} + بهره {inst.interest:,.0f})"
                )
                surplus = monthly - installment
                if surplus > 1e-6:
                    um = book.buy(surplus, m)
                    buy = surplus
                    events.append(f"مانده بودجه → خرید {surplus:,.0f}")
                    if ul and um > 0:
                        events.append(f"≈ {_fmt_units(um, asset)}")
                elif surplus < -1e-6:
                    events.append("بودجه کمتر از قسط")
            else:
                if monthly > 1e-6:
                    um = book.buy(monthly, m)
                    buy = monthly
                    events.append(f"خرید ماهانه {monthly:,.0f}")
                    if ul and um > 0:
                        events.append(f"≈ {_fmt_units(um, asset)}")
        timeline.append(
            _step(
                month=m,
                label=f"ماه {m}",
                events=events,
                cash_in=cash_in,
                buy=buy,
                installment=installment,
                points=points,
                deposit=deposit,
                debt=debt,
                asset_value=book.value(m),
                cash=0.0,
                price=book.price(m),
                units_bought=um,
                units_held=book.units,
                unit_label=ul,
            )
        )

    reached = unlocked
    notes: list[str] = [
        f"انتظار محاسبه‌شده {wait} ماه",
        f"امتیاز {points:.1f} (نیاز {need:g})",
        f"سپرده در آزادسازی {(investable - loan) if reached else deposit:,.0f}",
        f"وام {loan:,.0f}",
    ]
    valid = True
    if not reached:
        valid = False
        notes.append("تا پایان افق به امتیاز لازم نرسید — بدون آزادسازی وام")
        if to_bank:
            end_value = deposit
            if timeline:
                last = timeline[-1]
                timeline[-1] = last.model_copy(
                    update={
                        "events": list(last.events) + [f"پایان افق؛ سپرده نقدی {deposit:,.0f} بدون وام"],
                        "asset_value": 0.0,
                        "deposit": deposit,
                        "wealth": deposit,
                        "debt": 0.0,
                        "units_held": 0.0,
                    }
                )
            rem_debt = 0.0
            investable = deposit
        else:
            if deposit > 1e-6:
                u_end = book.buy(deposit, h)
                if timeline:
                    last = timeline[-1]
                    extra = [f"پایان افق؛ تبدیل سپرده امتیاز {deposit:,.0f} به دارایی"]
                    if ul and u_end > 0:
                        extra.append(f"≈ {_fmt_units(u_end, asset)}")
                    timeline[-1] = last.model_copy(
                        update={
                            "events": list(last.events) + extra,
                            "buy": last.buy + deposit,
                            "deposit": 0.0,
                            "asset_value": book.value(h),
                            "wealth": book.value(h),
                            "units_bought": last.units_bought + u_end,
                            "units_held": book.units,
                        }
                    )
                deposit = 0.0
            end_value = book.value(h)
            rem_debt = 0.0
            investable = capital
    else:
        max_pay3 = max_monthly_payment(sched) if sched else 0.0
        if sched:
            if max_pay3 > monthly + 1e-6:
                valid = False
                notes.append(f"قسط اول قرارداد ~{max_pay3:,.0f} بیش از بودجه ماهانه")
            notes.append(
                f"اقساط {len(sched)} ماهه (قسط اول ~{max_pay3:,.0f})؛ "
                f"در افق {pay_i} قسط؛ مانده بدهی {debt:,.0f}"
            )
            rem_debt = debt
        else:
            rem_debt = loan
        end_value = book.value(h)

    return end_value, rem_debt, investable, valid, notes, timeline, book.units, book.price(h)


def suggest_monthly_budget(payload: InvestInput) -> InvestSuggestResponse:
    """ماکس قسط اول بین شیوه‌های وامِ فعال (فین‌تک / بانک). مستقیم قسط ندارد."""
    details: dict[str, float] = {}
    if payload.enable_fintech and payload.loan_amount > 0 and payload.repay_months > 0:
        sched = declining_balance_schedule(
            payload.loan_amount,
            max(0.0, float(payload.bank_annual_pct)),
            payload.repay_months,
        )
        if sched:
            details["fintech"] = max_monthly_payment(sched)
    if payload.enable_bank_to_bank or payload.enable_bank_to_asset:
        loan_a = float(payload.loan_for_points)
        n = max(1, int(payload.repay_months_model3) if payload.repay_months_model3 else 12)
        if loan_a > 0:
            sched3 = declining_balance_schedule(
                loan_a, max(0.0, float(payload.model3_bank_annual_pct)), n
            )
            if sched3:
                details["bank_loan"] = max_monthly_payment(sched3)
    suggested = max(details.values()) if details else 0.0
    return InvestSuggestResponse(suggested_monthly=suggested, details=details)


def compare_methods(payload: InvestInput) -> InvestCompareResponse:
    if not is_confirmed():
        raise RuntimeError("Forecast not confirmed — finish Step 3 first")
    fc = get_last_forecast()
    if fc is None:
        raise RuntimeError("No forecast available")

    cfg = load_config()
    consts = constants_from_config(cfg)
    h = int(fc.months)
    total_cash_in = payload.capital_toman + payload.monthly_budget_toman * h
    monthly = payload.monthly_budget_toman

    gold_fc = [p.value for p in fc.gold.forecast]
    usd_fc = [p.value for p in fc.usd.forecast]
    oz0 = fc.gold.historical[-1].close
    usd0 = fc.usd.historical[-1].close
    oz = _sample_series(oz0, gold_fc, h)
    usd = _sample_series(usd0, usd_fc, h)

    assets = _enabled_assets(payload)
    results: list[InvestResult] = []
    suggest = suggest_monthly_budget(payload)

    price_cache: dict[str, list[float]] = {
        a: _asset_prices(a, oz, usd, consts) for a in ("gold", "usd", "fund")
    }

    def prices_for(asset: str) -> list[float]:
        return price_cache[asset]

    # ——— مدل ۱: فین‌تک ———
    if payload.enable_fintech:
        fee = payload.loan_amount * payload.company_fee_pct / 100.0
        sched = declining_balance_schedule(
            payload.loan_amount, payload.bank_annual_pct, payload.repay_months
        )
        for asset in assets:
            end_value, rem_debt, investable, valid, notes_parts, timeline, units_held, end_px = _sim_fintech(
                capital=payload.capital_toman,
                monthly=monthly,
                loan_amount=payload.loan_amount,
                fee=fee,
                fee_source=payload.fee_source,
                asset=asset,
                prices=prices_for(asset),
                fund_annual_pct=payload.fund_annual_pct,
                h=h,
                sched=sched,
            )
            results.append(
                _row(
                    model="fintech_loan",
                    asset=asset,
                    investable=investable,
                    total_cash_in=total_cash_in,
                    end_value=end_value,
                    remaining_debt=rem_debt,
                    notes="؛ ".join(notes_parts),
                    valid=valid,
                    timeline=timeline,
                    units_held=units_held,
                    end_price=end_px,
                )
            )

    # ——— مدل ۲: خرید مستقیم ———
    if payload.enable_direct:
        for asset in assets:
            end_value, timeline, units_held, end_px = _sim_direct(
                capital=payload.capital_toman,
                monthly=monthly,
                asset=asset,
                prices=prices_for(asset),
                fund_annual_pct=payload.fund_annual_pct,
                h=h,
            )
            results.append(
                _row(
                    model="direct",
                    asset=asset,
                    investable=payload.capital_toman,
                    total_cash_in=total_cash_in,
                    end_value=end_value,
                    remaining_debt=0.0,
                    notes=f"خرید اولیه + DCA ماهانه {monthly:,.0f} تومان",
                    valid=True,
                    timeline=timeline,
                    units_held=units_held,
                    end_price=end_px,
                )
            )

    # ——— مدل ۳: بانک → وام ———
    def bank_paths(model_key: str, to_bank: bool) -> None:
        for asset in assets:
            end_value, rem_debt, investable, valid, notes, timeline, units_held, end_px = _sim_bank(
                capital=payload.capital_toman,
                monthly=monthly,
                asset=asset,
                prices=prices_for(asset),
                fund_annual_pct=payload.fund_annual_pct,
                h=h,
                to_bank=to_bank,
                toman_per_point=payload.toman_per_point,
                points_needed=payload.points_for_loan,
                loan_for_points=payload.loan_for_points,
                model3_bank_annual_pct=payload.model3_bank_annual_pct,
                repay_months_model3=payload.repay_months_model3,
            )
            results.append(
                _row(
                    model=model_key,
                    asset=asset,
                    investable=investable,
                    total_cash_in=total_cash_in,
                    end_value=end_value,
                    remaining_debt=rem_debt,
                    notes="؛ ".join(notes),
                    valid=valid,
                    timeline=timeline,
                    units_held=units_held,
                    end_price=end_px,
                )
            )

    if payload.enable_bank_to_bank:
        bank_paths("bank_points_to_bank", True)
    if payload.enable_bank_to_asset:
        bank_paths("bank_points_to_asset", False)

    valid_rows = [r for r in results if r.valid]
    valid_rows.sort(key=lambda r: r.net_profit, reverse=True)
    results.sort(key=lambda r: (not r.valid, -r.net_profit))

    recommendation: InvestRecommendation | None = None
    best = ""
    if valid_rows:
        top = valid_rows[0]
        best = top.method
        if top.net_profit >= 0:
            msg = (
                f"با این پول، راه «{MODEL_TITLES[top.model]}» را برو و "
                f"«{ASSET_TITLES[top.asset]}» بخر؛ طبق پیش‌بینی تاییدشده احتمالاً حدود "
                f"{top.net_profit:,.0f} تومان (~{top.profit_pct:.1f}٪) سود می‌کنی."
            )
        else:
            msg = (
                f"در این افق همه گزینه‌ها سخت‌اند؛ کم‌زیان‌ترین: "
                f"«{MODEL_TITLES[top.model]}» → «{ASSET_TITLES[top.asset]}» "
                f"با زیان حدود {abs(top.net_profit):,.0f} تومان (~{top.profit_pct:.1f}٪)."
            )
        recommendation = InvestRecommendation(
            model=top.model,
            asset=top.asset,
            method=top.method,
            net_profit=top.net_profit,
            profit_pct=top.profit_pct,
            message=msg,
        )

    g0 = gram18(oz0, usd0, constants=consts, premium=0.0)
    g1 = gram18(oz[-1], usd[-1], constants=consts, premium=0.0)

    def _pct(a: float, b: float) -> float:
        return ((b - a) / a * 100.0) if a else 0.0

    context = InvestContext(
        horizon_months=h,
        usd_now=usd0,
        usd_end=usd[-1],
        usd_change_pct=_pct(usd0, usd[-1]),
        ounce_now=oz0,
        ounce_end=oz[-1],
        ounce_change_pct=_pct(oz0, oz[-1]),
        gram18_now=g0,
        gram18_end=g1,
        gram18_change_pct=_pct(g0, g1),
        capital_toman=payload.capital_toman,
        monthly_budget_toman=monthly,
        total_cash_in=total_cash_in,
        capital_as_usd_now=(payload.capital_toman / usd0) if usd0 else 0.0,
        capital_as_gram18_now=(payload.capital_toman / g0) if g0 else 0.0,
        monthly_as_usd_now=(monthly / usd0) if usd0 else 0.0,
        monthly_as_gram18_now=(monthly / g0) if g0 else 0.0,
        capital_as_usd_end=(payload.capital_toman / usd[-1]) if usd[-1] else 0.0,
        capital_as_gram18_end=(payload.capital_toman / g1) if g1 else 0.0,
        monthly_as_usd_end=(monthly / usd[-1]) if usd[-1] else 0.0,
        monthly_as_gram18_end=(monthly / g1) if g1 else 0.0,
    )

    assumptions: dict[str, Any] = {
        "months": h,
        "total_cash_in": total_cash_in,
        "monthly_budget": monthly,
        "capital": payload.capital_toman,
        "usd_start": usd0,
        "usd_end": usd[-1],
        "gold_ounce_start": oz0,
        "gold_ounce_end": oz[-1],
        "gram18_start": g0,
        "gram18_end": g1,
        "models": {"gold": fc.gold.model_used, "usd": fc.usd.model_used},
    }
    return InvestCompareResponse(
        results=results,
        best_method=best,
        recommendation=recommendation,
        assumptions=assumptions,
        suggested_monthly=suggest.suggested_monthly,
        context=context,
    )
