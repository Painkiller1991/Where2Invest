"""Investment path comparison: fintech, direct DCA, bank→loan (two variants)."""

from __future__ import annotations

from typing import Any

from app.config_loader import load_config
from app.models.schemas import (
    InvestCompareResponse,
    InvestInput,
    InvestRecommendation,
    InvestResult,
    InvestSuggestResponse,
)
from app.services.forecast import get_last_forecast, is_confirmed
from app.services.gold_iran_price import constants_from_config, gram18
from app.services.loan_math import (
    declining_balance_schedule,
    fund_value_from_cashflows,
    horizon_days,
    max_monthly_payment,
    month_to_day,
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
    # fund: unit NAV starts at 1; compounding handled separately
    return [1.0] * len(oz)


def _lump_end(
    investable: float,
    asset: str,
    prices: list[float],
    fund_annual_pct: float,
    total_days: int,
    buy_month: int = 0,
) -> float:
    if investable <= 0:
        return 0.0
    if asset == "fund":
        day = month_to_day(buy_month)
        return fund_value_from_cashflows([(day, investable)], fund_annual_pct, total_days)
    px0 = prices[buy_month]
    px_h = prices[-1]
    if px0 <= 0:
        return 0.0
    return (investable / px0) * px_h


def _dca_end(
    initial: float,
    monthly: float,
    asset: str,
    prices: list[float],
    fund_annual_pct: float,
    total_days: int,
    h: int,
    *,
    start_month: int = 1,
    end_month: int | None = None,
    initial_month: int = 0,
) -> float:
    """Initial buy at initial_month + monthly buys from start_month..end_month."""
    end_m = h if end_month is None else end_month
    if asset == "fund":
        flows: list[tuple[int, float]] = []
        if initial > 0:
            flows.append((month_to_day(initial_month), initial))
        for m in range(start_month, end_m + 1):
            if monthly > 0:
                flows.append((month_to_day(m), monthly))
        return fund_value_from_cashflows(flows, fund_annual_pct, total_days)

    units = 0.0
    if initial > 0 and prices[initial_month] > 0:
        units += initial / prices[initial_month]
    for m in range(start_month, end_m + 1):
        px = prices[m]
        if monthly > 0 and px > 0:
            units += monthly / px
    return units * prices[-1]


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
) -> InvestResult:
    wealth = end_value
    net = wealth - remaining_debt - total_cash_in
    pct = (net / total_cash_in * 100.0) if total_cash_in > 0 else 0.0
    method = f"{model}__{asset}"
    title = f"{MODEL_TITLES[model]} → {ASSET_TITLES[asset]}"
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


def suggest_monthly_budget(payload: InvestInput) -> InvestSuggestResponse:
    details: dict[str, float] = {}
    if payload.enable_fintech and payload.loan_amount > 0 and payload.repay_months > 0:
        sched = declining_balance_schedule(
            payload.loan_amount, payload.bank_annual_pct, payload.repay_months
        )
        details["fintech"] = max_monthly_payment(sched)
    if payload.enable_bank_to_bank or payload.enable_bank_to_asset:
        if payload.model3_bank_annual_pct > 0:
            deposit = payload.capital_toman
            if payload.enable_bank_to_bank:
                # upper bound suggestion uses max possible loan (with monthly to bank)
                # use wait_months from payload; for suggest we don't know H yet — use deposit+wait
                pass
            loan_a = (
                int(payload.capital_toman // max(payload.toman_per_point, 1))
                * payload.loan_per_point
            )
            # for to_bank path loan can be larger; estimate with wait months of budget unknown
            # use capital-only loan for floor; if monthly known use it
            if payload.monthly_budget_toman > 0 and payload.enable_bank_to_bank:
                dep = payload.capital_toman + payload.monthly_budget_toman * payload.wait_months
                loan_b = int(dep // max(payload.toman_per_point, 1)) * payload.loan_per_point
                loan_a = max(loan_a, loan_b)
            n = payload.repay_months_model3 or 12
            sched3 = declining_balance_schedule(loan_a, payload.model3_bank_annual_pct, n)
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
    total_days = horizon_days(h)
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
        max_pay = max_monthly_payment(sched)
        months_paid = min(h, payload.repay_months)
        rem_debt = remaining_principal_after_months(sched, months_paid)

        for asset in assets:
            notes_parts = [
                f"وام {payload.loan_amount:,.0f}",
                f"کارمزد {fee:,.0f} ({payload.fee_source})",
                f"قسط اول ~{max_pay:,.0f}",
            ]
            valid = True
            if max_pay > monthly + 1e-6:
                valid = False
                notes_parts.append(f"قسط بیشتر از بودجه ماهانه ({monthly:,.0f})")

            leftover = 0.0
            if payload.fee_source == "cash":
                if payload.capital_toman + 1e-6 < fee:
                    valid = False
                    notes_parts.append("سرمایه برای کارمزد کافی نیست")
                    investable = 0.0
                else:
                    investable = payload.loan_amount
                    leftover = payload.capital_toman - fee
            else:
                investable = payload.loan_amount - fee
                leftover = payload.capital_toman

            px = prices_for(asset)
            asset_end = _lump_end(investable, asset, px, payload.fund_annual_pct, total_days, 0)
            end_value = asset_end + leftover
            results.append(
                _row(
                    model="fintech_loan",
                    asset=asset,
                    investable=investable,
                    total_cash_in=total_cash_in,
                    end_value=end_value,
                    remaining_debt=rem_debt if valid else rem_debt,
                    notes="؛ ".join(notes_parts),
                    valid=valid,
                )
            )

    # ——— مدل ۲: خرید مستقیم ———
    if payload.enable_direct:
        for asset in assets:
            px = prices_for(asset)
            end_value = _dca_end(
                payload.capital_toman,
                monthly,
                asset,
                px,
                payload.fund_annual_pct,
                total_days,
                h,
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
                )
            )

    # ——— مدل ۳: بانک → وام ———
    wait = min(payload.wait_months, h)
    repay_n = payload.repay_months_model3 or max(1, h - wait)

    def bank_paths(model_key: str, to_bank: bool) -> None:
        if to_bank:
            deposit = payload.capital_toman + monthly * wait
        else:
            deposit = payload.capital_toman
        points = int(deposit // max(payload.toman_per_point, 1e-9))
        loan = points * payload.loan_per_point
        use_installments = payload.model3_bank_annual_pct > 0 and loan > 0
        sched3 = (
            declining_balance_schedule(loan, payload.model3_bank_annual_pct, repay_n)
            if use_installments
            else []
        )
        max_pay3 = max_monthly_payment(sched3) if sched3 else 0.0

        for asset in assets:
            px = prices_for(asset)
            notes: list[str] = [
                f"انتظار {wait} ماه",
                f"سپرده مبنای وام {deposit:,.0f}",
                f"وام {loan:,.0f}",
            ]
            valid = True
            leftover_cash = 0.0

            if to_bank:
                # months 1..wait: budget to bank (already in deposit); no asset buy
                pre_units_end = 0.0
            else:
                # months 1..wait: DCA asset with monthly (capital stays in bank)
                pre_units_end = _dca_end(
                    0.0,
                    monthly,
                    asset,
                    px,
                    payload.fund_annual_pct,
                    total_days,
                    h,
                    start_month=1,
                    end_month=wait,
                    initial_month=0,
                )

            unlock_cash = deposit + loan  # deposit returns + loan
            # buy lump at wait month
            lump = _lump_end(
                unlock_cash,
                asset,
                px,
                payload.fund_annual_pct,
                total_days,
                buy_month=wait,
            )

            rem_debt = 0.0
            if use_installments:
                if max_pay3 > monthly + 1e-6:
                    valid = False
                    notes.append(f"قسط {max_pay3:,.0f} بیش از بودجه")
                # installments from month wait+1
                months_after = max(0, h - wait)
                paid_count = min(months_after, repay_n)
                rem_debt = remaining_principal_after_months(sched3, paid_count)
                notes.append(f"اقساط بعد از آزادسازی؛ مانده بدهی {rem_debt:,.0f}")
                # no further DCA; asset = pre + lump only
                end_value = pre_units_end + lump + leftover_cash
            else:
                # after unlock: continue DCA months wait+1..H
                post = _dca_end(
                    0.0,
                    monthly,
                    asset,
                    px,
                    payload.fund_annual_pct,
                    total_days,
                    h,
                    start_month=wait + 1,
                    end_month=h,
                    initial_month=0,
                )
                # At horizon we still owe the loan principal (simple payoff)
                rem_debt = loan
                notes.append("بدون بهره وام؛ تسویه اصل در پایان افق")
                end_value = pre_units_end + lump + post + leftover_cash

            # When to_bank, deposit includes monthly*wait which is part of total_cash_in;
            # unlock spends deposit+loan into asset — good.
            # Capital is in total_cash_in; deposit return is inside lump — don't double count cash.

            results.append(
                _row(
                    model=model_key,
                    asset=asset,
                    investable=unlock_cash,
                    total_cash_in=total_cash_in,
                    end_value=end_value,
                    remaining_debt=rem_debt,
                    notes="؛ ".join(notes),
                    valid=valid,
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

    assumptions: dict[str, Any] = {
        "months": h,
        "total_cash_in": total_cash_in,
        "monthly_budget": monthly,
        "capital": payload.capital_toman,
        "usd_start": usd0,
        "usd_end": usd[-1],
        "gold_ounce_start": oz0,
        "gold_ounce_end": oz[-1],
        "models": {"gold": fc.gold.model_used, "usd": fc.usd.model_used},
    }
    return InvestCompareResponse(
        results=results,
        best_method=best,
        recommendation=recommendation,
        assumptions=assumptions,
        suggested_monthly=suggest.suggested_monthly,
    )
