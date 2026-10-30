"""Intrinsic Iranian gold price from global ounce × free-market USD."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GoldIranConstants:
    troy_oz_grams: float = 31.1034768
    mithqal_divisor: float = 9.5742


def gram24(
    ounce_usd: float,
    usd_toman: float,
    *,
    constants: GoldIranConstants | None = None,
    premium: float = 0.0,
) -> float:
    """Price of 1 gram of 24k gold in toman (no craft fee)."""
    c = constants or GoldIranConstants()
    base = (ounce_usd * usd_toman) / c.troy_oz_grams
    return base * (1.0 + premium)


def gram_k(
    ounce_usd: float,
    usd_toman: float,
    karat: float,
    *,
    constants: GoldIranConstants | None = None,
    premium: float = 0.0,
) -> float:
    """Price of 1 gram at given karat (e.g. 18, 21, 24)."""
    return gram24(ounce_usd, usd_toman, constants=constants, premium=premium) * (karat / 24.0)


def gram18(
    ounce_usd: float,
    usd_toman: float,
    *,
    constants: GoldIranConstants | None = None,
    premium: float = 0.0,
) -> float:
    return gram_k(ounce_usd, usd_toman, 18, constants=constants, premium=premium)


def mithqal17(
    ounce_usd: float,
    usd_toman: float,
    *,
    constants: GoldIranConstants | None = None,
    premium: float = 0.0,
) -> float:
    """Common Iranian board formula for 17-karat mithqal."""
    c = constants or GoldIranConstants()
    base = (ounce_usd * usd_toman) / c.mithqal_divisor
    return base * (1.0 + premium)


def constants_from_config(cfg: dict) -> GoldIranConstants:
    raw = (cfg.get("gold_ir") or {}).get("constants") or {}
    return GoldIranConstants(
        troy_oz_grams=float(raw.get("troy_oz_grams", 31.1034768)),
        mithqal_divisor=float(raw.get("mithqal_divisor", 9.5742)),
    )
