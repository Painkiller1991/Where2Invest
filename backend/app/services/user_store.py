"""Persist UI prefs + buy-decision snapshots in the same SQLite DB as market data."""

from __future__ import annotations

import json
import logging
from typing import Any

from app.services.market_db import MarketDB

logger = logging.getLogger(__name__)

META_PREFS = "ui_prefs_v1"
META_CHART_TF = "chart_tf"
META_ACTIVE_DECISION = "active_decision_id"

DEFAULT_PREFS: dict[str, Any] = {
    "startDate": "2018-01-01",
    "goldSentiment": 0,
    "usdSentiment": 0,
    "months": 3,
    "forecastModel": "both",
    "capital": 100_000_000,
    "monthlyBudget": 0,
    "fundAnnual": 20,
    "enableGold": True,
    "enableUsd": True,
    "enableFund": True,
    "enableFintech": True,
    "enableDirect": True,
    "enableBankToBank": True,
    "enableBankToAsset": True,
    "loanAmount": 100_000_000,
    "companyFeePct": 5,
    "bankAnnualPct": 22,
    "repayMonths": 12,
    "feeSource": "from_loan",
    "tomanPerPoint": 100_000,
    "pointsForLoan": 100,
    "loanForPoints": 100_000_000,
    "model3BankAnnual": 0,
}


class UserStore:
    def __init__(self, db: MarketDB | None = None) -> None:
        self._db = db or MarketDB()

    def get_state(self) -> dict[str, Any]:
        raw_prefs = self._db.get_meta(META_PREFS)
        has_prefs = raw_prefs is not None
        prefs = {**DEFAULT_PREFS}
        if raw_prefs:
            try:
                prefs.update(json.loads(raw_prefs))
            except json.JSONDecodeError:
                logger.warning("corrupt ui prefs in db; using defaults")
        chart_tf = self._db.get_meta(META_CHART_TF) or "1W"
        if chart_tf not in ("1D", "1W", "1M"):
            chart_tf = "1W"
        active = self._db.get_meta(META_ACTIVE_DECISION) or None
        if active == "":
            active = None
        return {
            "prefs": prefs,
            "has_prefs": has_prefs,
            "chart_tf": chart_tf,
            "active_decision_id": active,
            "decisions": self.list_decisions(),
        }

    def save_prefs(self, prefs: dict[str, Any]) -> dict[str, Any]:
        merged = {**DEFAULT_PREFS, **(prefs or {})}
        self._db.set_meta(META_PREFS, json.dumps(merged, ensure_ascii=False))
        return merged

    def save_chart_tf(self, tf: str) -> str:
        value = tf if tf in ("1D", "1W", "1M") else "1W"
        self._db.set_meta(META_CHART_TF, value)
        return value

    def set_active_decision(self, decision_id: str | None) -> str | None:
        if decision_id:
            # ensure exists
            if self.get_decision(decision_id) is None:
                raise KeyError(decision_id)
            self._db.set_meta(META_ACTIVE_DECISION, decision_id)
            return decision_id
        self._db.set_meta(META_ACTIVE_DECISION, "")
        return None

    def list_decisions(self) -> list[dict[str, Any]]:
        with self._db._connect() as conn:
            rows = conn.execute(
                "SELECT payload FROM decisions ORDER BY created_at DESC"
            ).fetchall()
        out: list[dict[str, Any]] = []
        for row in rows:
            try:
                out.append(json.loads(row["payload"]))
            except json.JSONDecodeError:
                continue
        return out

    def get_decision(self, decision_id: str) -> dict[str, Any] | None:
        with self._db._connect() as conn:
            row = conn.execute(
                "SELECT payload FROM decisions WHERE id = ?", (decision_id,)
            ).fetchone()
        if row is None:
            return None
        try:
            return json.loads(row["payload"])
        except json.JSONDecodeError:
            return None

    def upsert_decision(self, snap: dict[str, Any]) -> dict[str, Any]:
        decision_id = str(snap.get("id") or "")
        if not decision_id:
            raise ValueError("decision id required")
        created_at = int(snap.get("created_at") or 0)
        title = str(snap.get("title") or "")
        note = str(snap.get("note") or "")
        payload = json.dumps(snap, ensure_ascii=False)
        with self._db._connect() as conn:
            conn.execute(
                """
                INSERT INTO decisions(id, created_at, title, note, payload)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    created_at = excluded.created_at,
                    title = excluded.title,
                    note = excluded.note,
                    payload = excluded.payload
                """,
                (decision_id, created_at, title, note, payload),
            )
        return snap

    def update_decision_meta(self, decision_id: str, *, title: str | None = None, note: str | None = None) -> dict[str, Any]:
        snap = self.get_decision(decision_id)
        if snap is None:
            raise KeyError(decision_id)
        if title is not None:
            snap["title"] = title
        if note is not None:
            snap["note"] = note
        return self.upsert_decision(snap)

    def delete_decision(self, decision_id: str) -> None:
        with self._db._connect() as conn:
            conn.execute("DELETE FROM decisions WHERE id = ?", (decision_id,))
        active = self._db.get_meta(META_ACTIVE_DECISION)
        if active == decision_id:
            self._db.set_meta(META_ACTIVE_DECISION, "")

    def import_bundle(
        self,
        *,
        prefs: dict[str, Any] | None = None,
        chart_tf: str | None = None,
        active_decision_id: str | None = None,
        decisions: list[dict[str, Any]] | None = None,
        only_if_empty: bool = True,
    ) -> dict[str, Any]:
        """One-shot migrate from browser localStorage."""
        state = self.get_state()
        if only_if_empty and state["has_prefs"] and state["decisions"]:
            return state
        if prefs and (not only_if_empty or not state["has_prefs"]):
            self.save_prefs(prefs)
        if chart_tf and (not only_if_empty or not self._db.get_meta(META_CHART_TF)):
            self.save_chart_tf(chart_tf)
        if decisions and (not only_if_empty or not state["decisions"]):
            for snap in decisions:
                try:
                    self.upsert_decision(snap)
                except Exception:  # noqa: BLE001
                    logger.exception("skip bad decision import")
        if active_decision_id is not None and (
            not only_if_empty or not self._db.get_meta(META_ACTIVE_DECISION)
        ):
            try:
                self.set_active_decision(active_decision_id or None)
            except KeyError:
                self.set_active_decision(None)
        return self.get_state()


user_store = UserStore()
