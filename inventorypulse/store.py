import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .models import Decision


class Store:
    """Local audit store; transactions enforce immutable runs and one decision per SKU."""

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS decisions(
                    run_id TEXT NOT NULL, sku TEXT NOT NULL, recommendation_id TEXT NOT NULL,
                    decision TEXT NOT NULL, reviewer TEXT NOT NULL, reason TEXT NOT NULL, at TEXT NOT NULL,
                    PRIMARY KEY(run_id, sku), FOREIGN KEY(run_id) REFERENCES runs(id));
                CREATE TABLE IF NOT EXISTS audit(
                    sequence INTEGER PRIMARY KEY, event TEXT NOT NULL, previous_hash TEXT NOT NULL,
                    hash TEXT NOT NULL);
            """)

    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.execute("PRAGMA foreign_keys=ON")
        return db

    @staticmethod
    def event(db, event):
        previous = db.execute("SELECT hash FROM audit ORDER BY sequence DESC LIMIT 1").fetchone()
        previous = previous[0] if previous else "0" * 64
        payload = json.dumps(event, sort_keys=True)
        digest = hashlib.sha256((previous + payload).encode()).hexdigest()
        db.execute("INSERT INTO audit(event, previous_hash, hash) VALUES(?,?,?)", (payload, previous, digest))

    def save(self, run):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute("SELECT payload FROM runs WHERE id=?", (run["run_id"],)).fetchone()
            payload = json.dumps(run, sort_keys=True)
            if existing:
                if existing[0] != payload:
                    raise ValueError("Run ID collision: cannot overwrite immutable evidence")
                return
            db.execute("INSERT INTO runs VALUES(?,?)", (run["run_id"], payload))
            for handoff in run["handoffs"]:
                self.event(db, dict(kind="agent_handoff", **handoff))
            for assessment in run.get("agent_framework", {}).get("agent_assessments", []):
                self.event(db, dict(kind="agent_assessment", run_id=run["run_id"], **assessment))

    def get(self, run_id=None):
        with self.connect() as db:
            row = (
                db.execute("SELECT payload FROM runs WHERE id=?", (run_id,)).fetchone()
                if run_id
                else db.execute("SELECT payload FROM runs ORDER BY rowid DESC LIMIT 1").fetchone()
            )
            if row is None:
                raise KeyError("Run not found")
            run = json.loads(row[0])
            decisions = db.execute(
                "SELECT recommendation_id,decision,reviewer,reason,at FROM decisions WHERE run_id=?",
                (run["run_id"],),
            ).fetchall()
        run["decisions"] = [
            dict(zip(("recommendation_id", "decision", "reviewer", "reason", "at"), d)) for d in decisions
        ]
        from decimal import Decimal

        approved = Decimal(0)
        by_id = {d["recommendation_id"]: d for d in run["decisions"]}
        decided_skus = {r["canonical_sku"] for r in run["recommendations"] if r["recommendation_id"] in by_id}
        for rec in run["recommendations"]:
            decision = by_id.get(rec["recommendation_id"])
            if decision:
                rec["approval_state"] = decision["decision"]
                if decision["decision"] == "approved":
                    approved += Decimal(rec["estimated_release"])
            elif rec["canonical_sku"] in decided_skus:
                rec["approval_state"] = "not_selected"
        run["summary"]["approved_release"] = str(approved)
        return run

    def decide(self, run_id: str, decision: Decision):
        run = self.get(run_id)
        rec = next(
            (r for r in run["recommendations"] if r["recommendation_id"] == decision.recommendation_id), None
        )
        if rec is None:
            raise KeyError("Recommendation not found in this run")
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                db.execute(
                    "INSERT INTO decisions VALUES(?,?,?,?,?,?,?)",
                    (
                        run_id,
                        rec["canonical_sku"],
                        decision.recommendation_id,
                        decision.decision,
                        decision.reviewer,
                        decision.reason,
                        now,
                    ),
                )
            except sqlite3.IntegrityError as error:
                raise ValueError("This SKU already has a final decision for this run") from error
            self.event(
                db,
                dict(
                    kind="human_decision",
                    run_id=run_id,
                    canonical_sku=rec["canonical_sku"],
                    at=now,
                    **decision.model_dump(),
                ),
            )
        return self.get(run_id)

    def audit(self):
        with self.connect() as db:
            return [
                dict(sequence=r[0], event=json.loads(r[1]), previous_hash=r[2], hash=r[3])
                for r in db.execute("SELECT * FROM audit ORDER BY sequence")
            ]
