"""Loan amortization (declining balance) and fund / DCA helpers."""

from __future__ import annotations

from dataclasses import dataclass


DAYS_PER_MONTH = 30.44


@dataclass(frozen=True)
class Installment:
    month: int
    payment: float
    interest: float
    principal: float
    remaining: float


def horizon_days(months: int) -> int:
    return max(1, int(round(months * DAYS_PER_MONTH)))


def month_to_day(month: int) -> int:
    """Day index at end of month m (m=0 → day 0)."""
    if month <= 0:
        return 0
    return int(round(month * DAYS_PER_MONTH))


def declining_balance_schedule(
    principal: float,
    annual_pct: float,
    n_months: int,
) -> list[Installment]:
    """Equal principal each month + interest on remaining balance."""
    if principal <= 0 or n_months <= 0:
        return []
    r_m = annual_pct / 100.0 / 12.0
    remaining = float(principal)
    principal_m = float(principal) / n_months
    out: list[Installment] = []
    for m in range(1, n_months + 1):
        interest = remaining * r_m
        payment = principal_m + interest
        remaining = max(0.0, remaining - principal_m)
        out.append(
            Installment(
                month=m,
                payment=payment,
                interest=interest,
                principal=principal_m,
                remaining=remaining,
            )
        )
    return out


def max_monthly_payment(schedule: list[Installment]) -> float:
    if not schedule:
        return 0.0
    return max(i.payment for i in schedule)


def remaining_principal_after_months(
    schedule: list[Installment],
    months_paid: int,
) -> float:
    """Remaining principal after paying the first `months_paid` installments."""
    if not schedule:
        return 0.0
    if months_paid <= 0:
        return sum(i.principal for i in schedule)
    if months_paid >= len(schedule):
        return 0.0
    return schedule[months_paid - 1].remaining


def fund_compound(amount: float, annual_pct: float, days: int) -> float:
    if amount <= 0 or days <= 0:
        return max(0.0, amount)
    r = annual_pct / 100.0 / 365.0
    return amount * ((1.0 + r) ** days)


def fund_value_from_cashflows(
    cashflows: list[tuple[int, float]],
    annual_pct: float,
    total_days: int,
) -> float:
    """Each (day_index, amount) compounds until total_days."""
    total = 0.0
    for day, amt in cashflows:
        if amt <= 0:
            continue
        left = max(0, total_days - day)
        total += fund_compound(amt, annual_pct, left)
    return total
