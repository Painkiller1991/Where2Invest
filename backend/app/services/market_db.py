from __future__ import annotations

import sqlite3
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from app.config_loader import project_root

SYMBOL_GOLD = "XAUUSD"
SYMBOL_USD = "USDIRT"


def sanitize_candles(
    df: pd.DataFrame,
    *,
    ref_close: float | None = None,
    symbol: str = "",
    max_abs_ret: float = 0.45,
) -> pd.DataFrame:
    """Drop rows with impossible jumps (bad scrape / wrong unit)."""
    if df is None or df.empty:
        return df
    out = df.copy().sort_index()
    min_abs = 10_000.0 if symbol == SYMBOL_USD else None
    keep: list[bool] = []
    prev = ref_close
    for _, row in out.iterrows():
        close = float(row["Close"])
        low = float(row["Low"])
        high = float(row["High"])
        if close <= 0 or low <= 0 or high <= 0:
            keep.append(False)
            continue
        if min_abs is not None and (close < min_abs or low < min_abs):
            keep.append(False)
            continue
        if prev is not None and prev > 0:
            if abs(close / prev - 1.0) > max_abs_ret:
                keep.append(False)
                continue
        keep.append(True)
        prev = close
    return out.loc[keep]


def default_db_path() -> Path:
    path = project_root() / "data" / "market.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


class MarketDB:
    def __init__(self, db_path: Path | None = None) -> None:
        self.path = db_path or default_db_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS candles (
                    symbol TEXT NOT NULL,
                    ts INTEGER NOT NULL,
                    open REAL NOT NULL,
                    high REAL NOT NULL,
                    low REAL NOT NULL,
                    close REAL NOT NULL,
                    volume REAL,
                    PRIMARY KEY (symbol, ts)
                );
                CREATE INDEX IF NOT EXISTS idx_candles_symbol_ts ON candles(symbol, ts);

                CREATE TABLE IF NOT EXISTS meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                """
            )

    def get_meta(self, key: str) -> str | None:
        with self._connect() as conn:
            row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
            return None if row is None else str(row["value"])

    def set_meta(self, key: str, value: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO meta(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )

    def has_symbol(self, symbol: str) -> bool:
        with self._connect() as conn:
            row = conn.execute("SELECT 1 FROM candles WHERE symbol = ? LIMIT 1", (symbol,)).fetchone()
            return row is not None

    def first_date(self, symbol: str) -> date | None:
        with self._connect() as conn:
            row = conn.execute("SELECT MIN(ts) AS m FROM candles WHERE symbol = ?", (symbol,)).fetchone()
            if row is None or row["m"] is None:
                return None
            return datetime.utcfromtimestamp(int(row["m"])).date()

    def last_date(self, symbol: str) -> date | None:
        with self._connect() as conn:
            row = conn.execute("SELECT MAX(ts) AS m FROM candles WHERE symbol = ?", (symbol,)).fetchone()
            if row is None or row["m"] is None:
                return None
            return datetime.utcfromtimestamp(int(row["m"])).date()

    def delete_candle_ts(self, symbol: str, ts: int) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM candles WHERE symbol = ? AND ts = ?", (symbol, int(ts)))

    def purge_outliers(self, symbol: str, *, max_abs_ret: float = 0.45, min_abs: float | None = None) -> int:
        """Remove absurd spikes vs previous close (e.g. 1199 next to 271200)."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT ts, open, high, low, close FROM candles WHERE symbol = ? ORDER BY ts",
                (symbol,),
            ).fetchall()
        if len(rows) < 2:
            return 0
        drop_ts: list[int] = []
        prev = float(rows[0]["close"])
        for row in rows[1:]:
            close = float(row["close"])
            low = float(row["low"])
            if min_abs is not None and (close < min_abs or low < min_abs):
                drop_ts.append(int(row["ts"]))
                continue
            if prev > 0 and abs(close / prev - 1.0) > max_abs_ret:
                drop_ts.append(int(row["ts"]))
                continue
            prev = close
        for ts in drop_ts:
            self.delete_candle_ts(symbol, ts)
        return len(drop_ts)

    def upsert_dataframe(self, symbol: str, df: pd.DataFrame, *, ref_close: float | None = None) -> int:
        if df is None or df.empty:
            return 0
        df = sanitize_candles(df, ref_close=ref_close, symbol=symbol)
        if df.empty:
            return 0
        rows: list[tuple[Any, ...]] = []
        for idx, row in df.iterrows():
            ts = pd.Timestamp(idx)
            if ts.tzinfo is not None:
                ts = ts.tz_convert("UTC").tz_localize(None)
            # store as UTC midnight for the calendar day
            day = ts.tz_localize(None).normalize()
            unix = int(pd.Timestamp(year=day.year, month=day.month, day=day.day, tz="UTC").timestamp())
            vol = float(row["Volume"]) if "Volume" in row and pd.notna(row.get("Volume")) else None
            rows.append(
                (
                    symbol,
                    unix,
                    float(row["Open"]),
                    float(row["High"]),
                    float(row["Low"]),
                    float(row["Close"]),
                    vol,
                )
            )
        with self._connect() as conn:
            conn.executemany(
                """
                INSERT INTO candles(symbol, ts, open, high, low, close, volume)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol, ts) DO UPDATE SET
                    open = excluded.open,
                    high = excluded.high,
                    low = excluded.low,
                    close = excluded.close,
                    volume = excluded.volume
                """,
                rows,
            )
        return len(rows)

    def replace_symbol(self, symbol: str, df: pd.DataFrame) -> int:
        with self._connect() as conn:
            conn.execute("DELETE FROM candles WHERE symbol = ?", (symbol,))
        return self.upsert_dataframe(symbol, df)

    def load_dataframe(self, symbol: str, start: date | None = None, end: date | None = None) -> pd.DataFrame:
        clauses = ["symbol = ?"]
        params: list[Any] = [symbol]
        if start is not None:
            clauses.append("ts >= ?")
            params.append(int(datetime(start.year, start.month, start.day).timestamp()))
        if end is not None:
            clauses.append("ts <= ?")
            # inclusive end of day
            params.append(int(datetime(end.year, end.month, end.day, 23, 59, 59).timestamp()))
        sql = f"SELECT ts, open, high, low, close, volume FROM candles WHERE {' AND '.join(clauses)} ORDER BY ts"
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        if not rows:
            return pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])
        data = {
            "Open": [r["open"] for r in rows],
            "High": [r["high"] for r in rows],
            "Low": [r["low"] for r in rows],
            "Close": [r["close"] for r in rows],
            "Volume": [r["volume"] if r["volume"] is not None else 0.0 for r in rows],
        }
        idx = pd.to_datetime([r["ts"] for r in rows], unit="s")
        df = pd.DataFrame(data, index=idx)
        df.index.name = "Date"
        return df
