"""Check market.db for duplicate candle timestamps / calendar days."""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DB = ROOT / "data" / "market.db"


def main() -> None:
    print(f"db={DB} exists={DB.exists()}")
    if not DB.exists():
        return

    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    for symbol in ("XAUUSD", "USDIRT"):
        total = cur.execute(
            "SELECT COUNT(*) AS n FROM candles WHERE symbol = ?", (symbol,)
        ).fetchone()["n"]
        distinct_ts = cur.execute(
            "SELECT COUNT(DISTINCT ts) AS n FROM candles WHERE symbol = ?", (symbol,)
        ).fetchone()["n"]
        print(f"\n=== {symbol} ===")
        print(f"rows={total} distinct_ts={distinct_ts} ts_dup_extra={total - distinct_ts}")

        # PK should prevent exact (symbol,ts) dupes; still report any
        exact = cur.execute(
            """
            SELECT ts, COUNT(*) AS c
            FROM candles
            WHERE symbol = ?
            GROUP BY ts
            HAVING c > 1
            ORDER BY c DESC
            LIMIT 20
            """,
            (symbol,),
        ).fetchall()
        print(f"exact_ts_duplicate_groups={len(exact)}")
        for row in exact[:10]:
            print(f"  ts={row['ts']} count={row['c']}")

        # Same calendar UTC day with different ts (near-dupes)
        rows = cur.execute(
            "SELECT ts, open, high, low, close FROM candles WHERE symbol = ? ORDER BY ts",
            (symbol,),
        ).fetchall()
        by_day: dict[str, list[sqlite3.Row]] = defaultdict(list)
        for r in rows:
            day = datetime.fromtimestamp(int(r["ts"]), tz=timezone.utc).strftime("%Y-%m-%d")
            by_day[day].append(r)

        multi = {d: rs for d, rs in by_day.items() if len(rs) > 1}
        print(f"calendar_days={len(by_day)} days_with_multiple_rows={len(multi)}")
        for d, rs in list(sorted(multi.items()))[:15]:
            stamps = [datetime.fromtimestamp(int(x["ts"]), tz=timezone.utc).isoformat() for x in rs]
            closes = [round(float(x["close"]), 2) for x in rs]
            print(f"  {d}: n={len(rs)} closes={closes} ts={stamps}")

        # Consecutive identical close (possible scrape dup)
        same_close_runs = 0
        prev_c = None
        for r in rows:
            c = float(r["close"])
            if prev_c is not None and abs(c - prev_c) < 1e-9:
                same_close_runs += 1
            prev_c = c
        print(f"consecutive_identical_close_pairs={same_close_runs}")

        if rows:
            first = datetime.fromtimestamp(int(rows[0]["ts"]), tz=timezone.utc).date()
            last = datetime.fromtimestamp(int(rows[-1]["ts"]), tz=timezone.utc).date()
            print(f"range={first} → {last}")

    # Any symbol outside expected
    others = cur.execute(
        "SELECT symbol, COUNT(*) AS n FROM candles GROUP BY symbol"
    ).fetchall()
    print("\nall_symbols:", [(r["symbol"], r["n"]) for r in others])
    con.close()


if __name__ == "__main__":
    main()
