from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any

import httpx
import pandas as pd

logger = logging.getLogger(__name__)

BONBAST_FLOOR = date(2012, 10, 9)


def _to_unix(ts: pd.Timestamp) -> int:
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    return int(ts.timestamp())


def df_to_candles(df: pd.DataFrame) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for idx, row in df.iterrows():
        ts = pd.Timestamp(idx)
        o = float(row["Open"])
        h = float(row["High"])
        l = float(row["Low"])
        c = float(row["Close"])
        vol = float(row["Volume"]) if "Volume" in row and pd.notna(row.get("Volume")) else None
        rows.append(
            {
                "time": _to_unix(ts),
                "open": o,
                "high": h,
                "low": l,
                "close": c,
                "volume": vol,
            }
        )
    return rows


class GoldYahooAdapter:
    def fetch(self, start: date, end: date, symbol: str, fallback: str, proxy: str | None = None) -> tuple[pd.DataFrame, str]:
        import yfinance as yf

        last_err: Exception | None = None
        for sym in (symbol, fallback):
            try:
                ticker = yf.Ticker(sym)
                # yfinance end is exclusive-ish; add one day
                df = ticker.history(
                    start=start.isoformat(),
                    end=(end + timedelta(days=1)).isoformat(),
                    interval="1d",
                    auto_adjust=True,
                )
                if df is None or df.empty:
                    raise RuntimeError(f"Empty history for {sym}")
                df = df.rename(columns=str.title) if "Open" not in df.columns else df
                needed = ["Open", "High", "Low", "Close"]
                for col in needed:
                    if col not in df.columns:
                        raise RuntimeError(f"Missing column {col} for {sym}")
                if "Volume" not in df.columns:
                    df["Volume"] = 0.0
                df = df[needed + ["Volume"]].dropna(subset=["Close"])
                df.index = pd.to_datetime(df.index).tz_localize(None)
                return df, f"yfinance:{sym}"
            except Exception as e:  # noqa: BLE001
                last_err = e
                logger.warning("Gold fetch failed for %s: %s", sym, e)
        raise RuntimeError(f"Gold fetch failed: {last_err}")


class UsdBonbastAdapter:
    """Fetch USD/IRT history via Bonbast-style endpoints / HTML history pages."""

    FLOOR = BONBAST_FLOOR

    def fetch(self, start: date, end: date, unit: str = "toman", proxy: str | None = None) -> tuple[pd.DataFrame, str]:
        start = max(start, self.FLOOR)
        # Prefer graph-like bulk if available via unofficial endpoints; fall back to day sampling + httpx
        try:
            df = self._fetch_via_graph(start, end, proxy=proxy)
            if df is not None and not df.empty:
                return self._normalize_unit(df, unit), "bonbast:graph"
        except Exception as e:  # noqa: BLE001
            logger.warning("Bonbast graph failed: %s", e)

        df = self._fetch_via_history_pages(start, end, proxy=proxy)
        if df.empty:
            raise RuntimeError("Bonbast returned no USD history")
        return self._normalize_unit(df, unit), "bonbast:history"

    def _normalize_unit(self, df: pd.DataFrame, unit: str) -> pd.DataFrame:
        # Bonbast quotes toman; if somehow rial, convert
        if unit == "rial":
            df = df.copy()
            for col in ["Open", "High", "Low", "Close"]:
                df[col] = df[col] * 10.0
        return df

    def _fetch_via_graph(self, start: date, end: date, proxy: str | None) -> pd.DataFrame | None:
        # Try bonbast package if installed; chunk by year for long ranges
        try:
            from bonbast import BonbastClient  # type: ignore
        except ImportError:
            return self._fetch_via_http_history(start, end, proxy=proxy)

        client = BonbastClient()
        chart: dict[Any, Any] = {}
        try:
            cur_year = start.year
            while cur_year <= end.year:
                chunk_start = max(start, date(cur_year, 1, 1))
                chunk_end = min(end, date(cur_year, 12, 31))
                part = client.graph("usd", chunk_start, chunk_end) or {}
                chart.update(part)
                cur_year += 1
        finally:
            close = getattr(client, "close", None)
            if callable(close):
                close()

        if not chart:
            return None
        rows = []
        for d, sell in sorted(chart.items(), key=lambda x: x[0]):
            dt = pd.Timestamp(d)
            px = float(sell)
            rows.append({"Date": dt, "Open": px, "High": px, "Low": px, "Close": px, "Volume": 0.0})
        return pd.DataFrame(rows).set_index("Date").sort_index()

    def _fetch_via_http_history(self, start: date, end: date, proxy: str | None) -> pd.DataFrame | None:
        """Sample month-start pages from bonbast archive endpoints when package missing."""
        # Bonbast historical page pattern often used by scrapers
        rows: list[dict[str, Any]] = []
        cur = start
        with httpx.Client(timeout=30.0, proxy=proxy, follow_redirects=True) as client:
            while cur <= end:
                url = f"https://bonbast.com/historical/{cur.year}/{cur.month:02d}/{cur.day:02d}"
                try:
                    r = client.get(url, headers={"User-Agent": "Where2Invest/1.0"})
                    if r.status_code == 200 and "usd" in r.text.lower():
                        # Very light parse: look for usd sell in JSON-ish or table
                        px = self._parse_usd_from_html(r.text)
                        if px is not None:
                            rows.append(
                                {
                                    "Date": pd.Timestamp(cur),
                                    "Open": px,
                                    "High": px,
                                    "Low": px,
                                    "Close": px,
                                    "Volume": 0.0,
                                }
                            )
                except Exception as e:  # noqa: BLE001
                    logger.debug("bonbast day %s failed: %s", cur, e)
                cur += timedelta(days=7)  # weekly samples as coarse fallback
        if not rows:
            return None
        return pd.DataFrame(rows).set_index("Date").sort_index()

    def _fetch_via_history_pages(self, start: date, end: date, proxy: str | None) -> pd.DataFrame:
        df = self._fetch_via_http_history(start, end, proxy)
        if df is None or df.empty:
            # Last resort: synthesize from current TGJU-like scrape of bonbast home
            px = self._fetch_current_usd(proxy)
            if px is None:
                return pd.DataFrame()
            idx = pd.date_range(start=start, end=end, freq="D")
            return pd.DataFrame(
                {"Open": px, "High": px, "Low": px, "Close": px, "Volume": 0.0},
                index=idx,
            )
        # Forward-fill weekly samples to daily
        full_idx = pd.date_range(start=df.index.min(), end=min(end, date.today()), freq="D")
        df = df.reindex(full_idx).ffill().dropna()
        df.index.name = "Date"
        return df

    def _fetch_current_usd(self, proxy: str | None) -> float | None:
        try:
            with httpx.Client(timeout=20.0, proxy=proxy, follow_redirects=True) as client:
                r = client.get("https://bonbast.com", headers={"User-Agent": "Where2Invest/1.0"})
                return self._parse_usd_from_html(r.text)
        except Exception as e:  # noqa: BLE001
            logger.warning("bonbast current failed: %s", e)
            return None

    @staticmethod
    def _parse_usd_from_html(html: str) -> float | None:
        import re

        # Common patterns on bonbast
        patterns = [
            r'id="usd1"[^>]*>([0-9,]+)',
            r'"usd1"\s*:\s*"?([0-9]+)"?',
            r"USD.*?(?:sell|Sell).*?([0-9]{4,})",
        ]
        for p in patterns:
            m = re.search(p, html, re.I | re.S)
            if m:
                return float(m.group(1).replace(",", ""))
        return None


class UsdTgjuAdapter:
    """TGJU free-market USD — live + best-effort history."""

    def fetch(
        self,
        start: date,
        end: date,
        symbol: str = "price_dollar_rl",
        unit: str = "toman",
        proxy: str | None = None,
        history_url_template: str | None = None,
    ) -> tuple[pd.DataFrame, str]:
        url = (history_url_template or "https://api.tgju.org/v1/market/indicator/summary-table-data/{symbol}").format(
            symbol=symbol
        )
        with httpx.Client(timeout=45.0, proxy=proxy, follow_redirects=True) as client:
            # TGJU DataTables-style endpoint often needs POST params; try GET first then POST
            payload = {
                "draw": 1,
                "start": 0,
                "length": 5000,
                "order[0][column]": 0,
                "order[0][dir]": "desc",
            }
            r = client.post(url, data=payload, headers={"User-Agent": "Where2Invest/1.0"})
            if r.status_code >= 400:
                r = client.get(url, headers={"User-Agent": "Where2Invest/1.0"})
            r.raise_for_status()
            data = r.json()

        rows = data.get("data") or data.get("aaData") or []
        parsed: list[dict[str, Any]] = []
        for item in rows:
            try:
                # Typical: [date_jalali, open, low, high, close, change, pct, datetime]
                if isinstance(item, list) and len(item) >= 5:
                    close = float(str(item[4]).replace(",", ""))
                    high = float(str(item[3]).replace(",", ""))
                    low = float(str(item[2]).replace(",", ""))
                    open_ = float(str(item[1]).replace(",", ""))
                    # last field often gregorian-ish datetime string
                    dt_raw = item[-1] if len(item) > 5 else item[0]
                    dt = pd.to_datetime(str(dt_raw), errors="coerce")
                    if pd.isna(dt):
                        continue
                    parsed.append(
                        {
                            "Date": dt.normalize(),
                            "Open": open_,
                            "High": high,
                            "Low": low,
                            "Close": close,
                            "Volume": 0.0,
                        }
                    )
            except Exception:  # noqa: BLE001
                continue

        if not parsed:
            # live-only fallback
            live = self._live_price(symbol, proxy)
            if live is None:
                raise RuntimeError("TGJU returned no history and no live price")
            idx = pd.date_range(start=start, end=end, freq="D")
            df = pd.DataFrame(
                {"Open": live, "High": live, "Low": live, "Close": live, "Volume": 0.0},
                index=idx,
            )
            source = "tgju:live-flat"
        else:
            df = pd.DataFrame(parsed).drop_duplicates("Date").set_index("Date").sort_index()
            df = df.loc[(df.index.date >= start) & (df.index.date <= end)]
            source = "tgju:history"

        # TGJU is rial; convert to toman if requested
        if unit == "toman":
            for col in ["Open", "High", "Low", "Close"]:
                df[col] = df[col] / 10.0
        return df, source

    def _live_price(self, symbol: str, proxy: str | None) -> float | None:
        try:
            with httpx.Client(timeout=20.0, proxy=proxy, follow_redirects=True) as client:
                r = client.get(
                    "https://call3.tgju.org/ajax.json",
                    headers={"User-Agent": "Where2Invest/1.0"},
                )
                if r.status_code == 200:
                    data = r.json()
                    # current structure varies; try common keys
                    current = data.get("current") or data.get("price") or {}
                    node = current.get(symbol) or current.get("price_dollar_rl")
                    if isinstance(node, dict):
                        p = node.get("p") or node.get("price")
                        if p:
                            return float(str(p).replace(",", ""))
        except Exception as e:  # noqa: BLE001
            logger.warning("TGJU live failed: %s", e)
        return None


def today_utc() -> date:
    return datetime.now(timezone.utc).date()
