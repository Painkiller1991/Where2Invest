from __future__ import annotations

import logging
import time
from datetime import date, timedelta
from typing import Any, Literal

import pandas as pd

from app.config_loader import load_config, save_config
from app.models.schemas import Candle, DataStatus, SeriesPayload
from app.services.adapters import (
    BONBAST_FLOOR,
    GoldYahooAdapter,
    UsdBonbastAdapter,
    UsdTgjuAdapter,
    df_to_candles,
    today_utc,
)
from app.services.market_db import SYMBOL_GOLD, SYMBOL_USD, MarketDB

logger = logging.getLogger(__name__)

UpdateMode = Literal["cache", "incremental", "full"]


class DataGate:
    """Fetches gold + USD with SQLite persistence and incremental updates."""

    def __init__(self) -> None:
        self._status = DataStatus(ready=False)
        self._gold_df: pd.DataFrame | None = None
        self._usd_df: pd.DataFrame | None = None
        self._db = MarketDB()

    @property
    def status(self) -> DataStatus:
        return self._status

    @property
    def ready(self) -> bool:
        return self._status.ready

    def get_frames(self) -> tuple[pd.DataFrame, pd.DataFrame]:
        if self._gold_df is None or self._usd_df is None:
            raise RuntimeError("Data not ready")
        return self._gold_df.copy(), self._usd_df.copy()

    def update_start_date(self, start_date: str) -> dict[str, Any]:
        cfg = load_config()
        cfg.setdefault("data", {}).setdefault("history", {})["start_date"] = start_date
        save_config(cfg)
        return cfg

    def bootstrap_from_db(self) -> DataStatus | None:
        """Load existing DB into memory on API start / status poll without network."""
        if not (self._db.has_symbol(SYMBOL_GOLD) and self._db.has_symbol(SYMBOL_USD)):
            return None
        self._db.purge_outliers(SYMBOL_USD, min_abs=10_000.0)
        self._db.purge_outliers(SYMBOL_GOLD)
        cfg = load_config()
        hist = (cfg.get("data") or {}).get("history") or {}
        start = date.fromisoformat(hist.get("start_date") or "2018-01-01")
        end = today_utc()
        gold_df = self._db.load_dataframe(SYMBOL_GOLD, start=start, end=end)
        usd_df = self._db.load_dataframe(SYMBOL_USD, start=start, end=end)
        if gold_df.empty or usd_df.empty:
            return None
        gold_src = self._db.get_meta("gold_src") or "sqlite"
        usd_src = self._db.get_meta("usd_src") or "sqlite"
        self._commit(gold_df, usd_df, gold_src, usd_src, start, end, attempts=0, updated="cache")
        return self._status

    def fetch(self, start_date: str | None = None, force: bool = False) -> DataStatus:
        cfg = load_config()
        data_cfg = cfg.get("data") or {}
        hist = data_cfg.get("history") or {}
        retry_cfg = data_cfg.get("retry") or {}
        max_attempts = int(retry_cfg.get("max_attempts", 5))
        backoffs = list(retry_cfg.get("backoff_seconds") or [2, 5, 10, 20, 40])
        proxy = data_cfg.get("http_proxy") or None

        start_s = start_date or hist.get("start_date") or "2018-01-01"
        if start_date:
            self.update_start_date(start_date)

        start = date.fromisoformat(start_s)
        end_s = hist.get("end_date")
        end = date.fromisoformat(end_s) if end_s else today_utc()
        eff_floor = max(start, BONBAST_FLOOR)

        last_err = "unknown"
        attempts = 0
        for i in range(max_attempts):
            attempts = i + 1
            try:
                mode = self._sync(cfg, eff_floor, end, proxy=proxy, force=force)
                gold_df = self._db.load_dataframe(SYMBOL_GOLD, start=eff_floor, end=end)
                usd_df = self._db.load_dataframe(SYMBOL_USD, start=eff_floor, end=end)
                if gold_df.empty or usd_df.empty:
                    raise RuntimeError("DB empty after sync")
                # Align overlap for modeling
                common_start = max(gold_df.index.min().date(), usd_df.index.min().date())
                common_end = min(gold_df.index.max().date(), usd_df.index.max().date())
                gold_df = gold_df.loc[(gold_df.index.date >= common_start) & (gold_df.index.date <= common_end)]
                usd_df = usd_df.loc[(usd_df.index.date >= common_start) & (usd_df.index.date <= common_end)]
                if gold_df.empty or usd_df.empty:
                    raise RuntimeError("No overlapping dates between gold and USD series")
                gold_src = self._db.get_meta("gold_src") or "sqlite"
                usd_src = self._db.get_meta("usd_src") or "sqlite"
                self._commit(
                    gold_df,
                    usd_df,
                    gold_src,
                    usd_src,
                    common_start,
                    common_end,
                    attempts=attempts,
                    updated=mode,
                )
                return self._status
            except Exception as e:  # noqa: BLE001
                last_err = str(e)
                logger.exception("Fetch attempt %s failed", attempts)
                # Still expose whatever is already in DB so UI can show partial progress
                partial = self.bootstrap_from_db()
                if partial is not None:
                    self._status = partial.model_copy(
                        update={"ready": False, "error": last_err, "attempts": attempts, "updated": "cache"}
                    )
                else:
                    self._status = DataStatus(ready=False, error=last_err, attempts=attempts)
                if i < max_attempts - 1:
                    delay = backoffs[min(i, len(backoffs) - 1)]
                    time.sleep(delay)

        return self._status

    def _sync(
        self,
        cfg: dict[str, Any],
        start: date,
        end: date,
        *,
        proxy: str | None,
        force: bool,
    ) -> UpdateMode:
        has_gold = self._db.has_symbol(SYMBOL_GOLD)
        has_usd = self._db.has_symbol(SYMBOL_USD)

        if force or not (has_gold and has_usd):
            gold_df, gold_src = self._fetch_gold(cfg, start, end, proxy)
            if force:
                self._db.replace_symbol(SYMBOL_GOLD, gold_df)
            else:
                self._db.upsert_dataframe(SYMBOL_GOLD, gold_df)
            self._db.set_meta("gold_src", gold_src)

            usd_df, usd_src = self._fetch_usd(cfg, start, end, proxy)
            if force:
                self._db.replace_symbol(SYMBOL_USD, usd_df)
            else:
                self._db.upsert_dataframe(SYMBOL_USD, usd_df)
            self._db.set_meta("usd_src", usd_src)
            self._db.purge_outliers(SYMBOL_USD, min_abs=10_000.0)
            self._db.purge_outliers(SYMBOL_GOLD)
            self._db.set_meta("saved_at", date.today().isoformat())
            return "full"

        mode: UpdateMode = "cache"
        # Backfill if start is older than first stored date
        for symbol, fetcher, meta_key in (
            (SYMBOL_GOLD, self._fetch_gold, "gold_src"),
            (SYMBOL_USD, self._fetch_usd, "usd_src"),
        ):
            first = self._db.first_date(symbol)
            last = self._db.last_date(symbol)
            assert last is not None

            if first is not None and start < first:
                back_end = first - timedelta(days=1)
                if start <= back_end:
                    try:
                        df, src = fetcher(cfg, start, back_end, proxy)
                        if not df.empty:
                            ref = None
                            # for backfill, ref is first existing close
                            existing = self._db.load_dataframe(symbol)
                            if not existing.empty:
                                ref = float(existing["Close"].iloc[0])
                            self._db.upsert_dataframe(symbol, df, ref_close=ref)
                            self._db.set_meta(meta_key, src)
                            mode = "incremental"
                    except Exception as e:  # noqa: BLE001
                        # Weekend/holiday empty ranges are OK
                        logger.info("Backfill skip for %s (%s → %s): %s", symbol, start, back_end, e)

            # Forward fill from day after last
            fwd_start = last + timedelta(days=1)
            if fwd_start <= end:
                try:
                    df, src = fetcher(cfg, fwd_start, end, proxy)
                    if not df.empty:
                        last_df = self._db.load_dataframe(symbol)
                        ref = float(last_df["Close"].iloc[-1]) if not last_df.empty else None
                        self._db.upsert_dataframe(symbol, df, ref_close=ref)
                        self._db.set_meta(meta_key, src)
                        mode = "incremental"
                except Exception as e:  # noqa: BLE001
                    # Empty/weekend gaps are fine if we already have recent data
                    if (end - last).days > 5:
                        raise
                    logger.info("Incremental skip for %s (%s → %s): %s", symbol, fwd_start, end, e)

        self._db.purge_outliers(SYMBOL_USD, min_abs=10_000.0)
        self._db.purge_outliers(SYMBOL_GOLD)
        self._db.set_meta("saved_at", date.today().isoformat())
        return mode

    def _fetch_gold(
        self, cfg: dict[str, Any], start: date, end: date, proxy: str | None
    ) -> tuple[pd.DataFrame, str]:
        data_cfg = cfg.get("data") or {}
        gold_cfg = data_cfg.get("gold") or {}
        adapter = GoldYahooAdapter()
        return adapter.fetch(
            start,
            end,
            symbol=gold_cfg.get("symbol") or "GC=F",
            fallback=gold_cfg.get("fallback_symbol") or "XAUUSD=X",
            proxy=proxy,
        )

    def _fetch_usd(
        self, cfg: dict[str, Any], start: date, end: date, proxy: str | None
    ) -> tuple[pd.DataFrame, str]:
        data_cfg = cfg.get("data") or {}
        usd_cfg = data_cfg.get("usd_irr") or {}
        tgju_cfg = cfg.get("tgju") or {}
        unit = usd_cfg.get("unit") or "toman"
        primary = (usd_cfg.get("primary") or "bonbast").lower()
        fallback = (usd_cfg.get("fallback") or "tgju").lower()

        errors: list[str] = []
        for provider in (primary, fallback):
            try:
                if provider == "bonbast":
                    return UsdBonbastAdapter().fetch(start, end, unit=unit, proxy=proxy)
                if provider == "tgju":
                    return UsdTgjuAdapter().fetch(
                        start,
                        end,
                        symbol=usd_cfg.get("tgju_symbol") or "price_dollar_rl",
                        unit=unit,
                        proxy=proxy,
                        history_url_template=tgju_cfg.get("history_url"),
                    )
                raise RuntimeError(f"Unknown USD provider: {provider}")
            except Exception as e:  # noqa: BLE001
                errors.append(f"{provider}: {e}")
        raise RuntimeError("USD fetch failed: " + " | ".join(errors))

    def _commit(
        self,
        gold_df: pd.DataFrame,
        usd_df: pd.DataFrame,
        gold_src: str,
        usd_src: str,
        start: date,
        end: date,
        attempts: int,
        updated: UpdateMode = "cache",
    ) -> None:
        self._gold_df = gold_df
        self._usd_df = usd_df
        g_start = gold_df.index.min().date().isoformat()
        g_end = gold_df.index.max().date().isoformat()
        u_start = usd_df.index.min().date().isoformat()
        u_end = usd_df.index.max().date().isoformat()
        self._status = DataStatus(
            ready=True,
            attempts=attempts,
            effective_start=start.isoformat(),
            error=None,
            updated=updated,
            gold=SeriesPayload(
                symbol="XAUUSD",
                title="انس جهانی طلا",
                unit="USD/oz",
                candles=[Candle(**c) for c in df_to_candles(gold_df)],
                source=gold_src,
                start_date=g_start,
                end_date=g_end,
            ),
            usd=SeriesPayload(
                symbol="USDIRT",
                title="دلار آزاد ایران",
                unit="toman",
                candles=[Candle(**c) for c in df_to_candles(usd_df)],
                source=usd_src,
                start_date=u_start,
                end_date=u_end,
            ),
        )


data_gate = DataGate()
# Warm status from DB if present (new process / restart)
data_gate.bootstrap_from_db()
