"""
LSD §20 - Governance and Incident Hooks
Implements changelogs, fairness audits, appeal pathways, judge-pool governance, and incident snapshots.
"""

import json
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import Any


class AppealStatus(Enum):
    PENDING = "pending"
    UNDER_REVIEW = "under_review"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    ESCALATED = "escalated"


class IncidentSeverity(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class ChangelogEntry:
    """Single entry in the system changelog."""

    entry_id: str
    timestamp: str
    change_type: str  # 'frame', 'moderation', 'judge_pool', 'threshold', 'other'
    description: str
    previous_value: str | None
    new_value: str | None
    justification: str
    changed_by: str
    approval_references: list[str]  # Links to approvals/PRs


@dataclass
class Appeal:
    """An appeal against a debate conclusion."""

    appeal_id: str
    debate_id: str
    snapshot_id: str
    claimant_id: str
    grounds: str  # Reason for appeal
    evidence_references: list[str]
    requested_relief: str
    status: AppealStatus
    submitted_at: str
    reviewed_at: str | None
    reviewer_id: str | None
    decision_reason: str | None
    resolution: str | None


@dataclass
class JudgeRecord:
    """Track record of a judge/assessor."""

    judge_id: str
    name: str
    role: str
    appointed_at: str
    term_expires: str | None
    decisions_count: int
    overturned_count: int
    accuracy_score: float  # 0-1 based on agreement with final outcomes
    bias_audits: list[dict[str, Any]]  # Demographic parity metrics
    recusals: list[str]  # Topics recused from
    specialties: list[str]  # Domain expertise


@dataclass
class Incident:
    """An incident report triggering additive snapshot."""

    incident_id: str
    severity: IncidentSeverity
    reported_at: str
    reported_by: str
    description: str
    affected_debates: list[str]
    trigger_snapshot_ids: list[str]
    additive_snapshot_id: str | None
    status: str  # 'open', 'investigating', 'resolved'
    resolution_notes: str | None
    snapshot_id: str | None = None
    affected_outputs_json: str | None = None
    remediation_plan: str | None = None
    resolved_at: str | None = None


class GovernanceManager:
    """
    Manages governance functions: changelogs, appeals, fairness audits,
    judge-pool governance, and incident reporting.
    """

    def __init__(self, db):
        self.db = db
        self._init_tables()

    def _get_conn_cursor(self):
        """Get connection and cursor, handling both raw connections and DebateDatabase."""
        if hasattr(self.db, "_get_connection"):
            conn = self.db._get_connection()
            cursor = conn.cursor()
        else:
            conn = self.db
            cursor = conn
        return conn, cursor

    def _commit_close(self, conn):
        """Commit and close connection if needed."""
        if hasattr(conn, "commit") and hasattr(self.db, "_get_connection"):
            conn.commit()
            conn.close()
        elif hasattr(conn, "commit"):
            conn.commit()

    def _init_tables(self):
        """Initialize governance tables."""
        conn, cursor = self._get_conn_cursor()

        # Changelog table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS changelog (
                entry_id TEXT PRIMARY KEY,
                timestamp TEXT NOT NULL,
                change_type TEXT NOT NULL,
                description TEXT NOT NULL,
                previous_value TEXT,
                new_value TEXT,
                justification TEXT NOT NULL,
                changed_by TEXT NOT NULL,
                approval_references TEXT  -- JSON array
            )
        """)

        # Appeals table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS appeals (
                appeal_id TEXT PRIMARY KEY,
                debate_id TEXT NOT NULL,
                snapshot_id TEXT NOT NULL,
                claimant_id TEXT NOT NULL,
                grounds TEXT NOT NULL,
                evidence_references TEXT,  -- JSON array
                requested_relief TEXT NOT NULL,
                status TEXT NOT NULL,
                submitted_at TEXT NOT NULL,
                reviewed_at TEXT,
                reviewer_id TEXT,
                decision_reason TEXT,
                resolution TEXT
            )
        """)

        # Judge pool table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS judge_pool (
                judge_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                role TEXT NOT NULL,
                appointed_at TEXT NOT NULL,
                term_expires TEXT,
                decisions_count INTEGER DEFAULT 0,
                overturned_count INTEGER DEFAULT 0,
                accuracy_score REAL DEFAULT 0.5,
                bias_audits TEXT,  -- JSON
                recusals TEXT,  -- JSON array
                specialties TEXT  -- JSON array
            )
        """)

        # Incidents table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS incidents (
                incident_id TEXT PRIMARY KEY,
                severity TEXT NOT NULL,
                reported_at TEXT NOT NULL,
                reported_by TEXT NOT NULL,
                description TEXT NOT NULL,
                affected_debates TEXT,  -- JSON array
                trigger_snapshot_ids TEXT,  -- JSON array
                additive_snapshot_id TEXT,
                status TEXT NOT NULL,
                resolution_notes TEXT
            )
        """)
        self._ensure_column(cursor, "incidents", "snapshot_id", "TEXT")
        self._ensure_column(cursor, "incidents", "affected_outputs_json", "TEXT")
        self._ensure_column(cursor, "incidents", "remediation_plan", "TEXT")
        self._ensure_column(cursor, "incidents", "created_at", "TEXT")
        self._ensure_column(cursor, "incidents", "resolved_at", "TEXT")

        # Fairness audit log
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS fairness_audits (
                audit_id TEXT PRIMARY KEY,
                timestamp TEXT NOT NULL,
                metric_name TEXT NOT NULL,
                metric_value REAL NOT NULL,
                demographic_slice TEXT,  -- e.g., 'source_type:expert', 'topic_domain:economics'
                benchmark_value REAL,
                status TEXT,  -- 'pass', 'fail', 'warning'
                details TEXT  -- JSON
            )
        """)

        # LSD §20.1: Judge pool composition
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS judge_pool_composition (
                composition_id TEXT PRIMARY KEY,
                timestamp TEXT NOT NULL,
                category TEXT NOT NULL,
                count INTEGER NOT NULL DEFAULT 0,
                qualification_rubric TEXT NOT NULL DEFAULT '{}',
                snapshot_id TEXT
            )
        """)

        # LSD §20.1: Rotation policy
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS judge_rotation_policy (
                policy_id TEXT PRIMARY KEY,
                timestamp TEXT NOT NULL,
                max_consecutive_snapshots INTEGER NOT NULL DEFAULT 5,
                cooldown_snapshots INTEGER NOT NULL DEFAULT 2,
                active INTEGER NOT NULL DEFAULT 1
            )
        """)

        # LSD §20.1: Conflict-of-interest log
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS conflict_of_interest_log (
                entry_id TEXT PRIMARY KEY,
                timestamp TEXT NOT NULL,
                judge_id TEXT NOT NULL,
                debate_id TEXT,
                topic_id TEXT,
                conflict_type TEXT NOT NULL,
                description TEXT NOT NULL,
                resolved INTEGER NOT NULL DEFAULT 0
            )
        """)

        # LSD §20.1: Calibration protocol
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS calibration_protocol (
                protocol_id TEXT PRIMARY KEY,
                timestamp TEXT NOT NULL,
                guideline_version TEXT NOT NULL,
                shared_guidelines TEXT NOT NULL DEFAULT '{}',
                inter_judge_consistency_check TEXT NOT NULL DEFAULT '{}',
                active INTEGER NOT NULL DEFAULT 1
            )
        """)

        self._commit_close(conn)

    @staticmethod
    def _ensure_column(cursor, table_name: str, column_name: str, column_definition: str):
        cursor.execute(f"PRAGMA table_info({table_name})")
        existing = {row[1] for row in cursor.fetchall()}
        if column_name not in existing:
            cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_definition}")

    # === Changelog Operations ===

    def log_change(
        self,
        change_type: str,
        description: str,
        changed_by: str,
        justification: str,
        previous_value: str | None = None,
        new_value: str | None = None,
        approval_references: list[str] = None,
    ) -> str:
        """Log a system change."""
        entry_id = f"chg_{uuid.uuid4().hex[:12]}"

        conn, cursor = self._get_conn_cursor()
        cursor.execute(
            """INSERT INTO changelog
               (entry_id, timestamp, change_type, description, previous_value, new_value,
                justification, changed_by, approval_references)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                entry_id,
                datetime.now(UTC).replace(tzinfo=None).isoformat(),
                change_type,
                description,
                previous_value,
                new_value,
                justification,
                changed_by,
                json.dumps(approval_references or []),
            ),
        )
        self._commit_close(conn)
        return entry_id

    def get_changelog(
        self, change_type: str | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        """Get changelog entries, optionally filtered by type."""
        conn, cursor = self._get_conn_cursor()

        if change_type:
            rows = cursor.execute(
                """SELECT * FROM changelog WHERE change_type = ?
                   ORDER BY timestamp DESC LIMIT ?""",
                (change_type, limit),
            ).fetchall()
        else:
            rows = cursor.execute(
                "SELECT * FROM changelog ORDER BY timestamp DESC LIMIT ?", (limit,)
            ).fetchall()

        if hasattr(conn, "close") and hasattr(self.db, "_get_connection"):
            conn.close()

        return [self._row_to_changelog(row) for row in rows]

    def _row_to_changelog(self, row) -> dict[str, Any]:
        return {
            "entry_id": row["entry_id"],
            "timestamp": row["timestamp"],
            "change_type": row["change_type"],
            "description": row["description"],
            "previous_value": row["previous_value"],
            "new_value": row["new_value"],
            "justification": row["justification"],
            "changed_by": row["changed_by"],
            "approval_references": json.loads(row["approval_references"] or "[]"),
        }

    # === Appeal Operations ===

    def submit_appeal(
        self,
        debate_id: str,
        snapshot_id: str,
        claimant_id: str,
        grounds: str,
        evidence_references: list[str],
        requested_relief: str,
    ) -> str:
        """Submit a new appeal."""
        appeal_id = f"apl_{uuid.uuid4().hex[:12]}"

        conn, cursor = self._get_conn_cursor()
        cursor.execute(
            """INSERT INTO appeals
               (appeal_id, debate_id, snapshot_id, claimant_id, grounds,
                evidence_references, requested_relief, status, submitted_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                appeal_id,
                debate_id,
                snapshot_id,
                claimant_id,
                grounds,
                json.dumps(evidence_references),
                requested_relief,
                AppealStatus.PENDING.value,
                datetime.now(UTC).replace(tzinfo=None).isoformat(),
            ),
        )
        self._commit_close(conn)
        return appeal_id

    def review_appeal(
        self,
        appeal_id: str,
        reviewer_id: str,
        decision: AppealStatus,
        decision_reason: str,
        resolution: str | None = None,
    ) -> bool:
        """Review and decide on an appeal."""
        conn, cursor = self._get_conn_cursor()
        cursor.execute(
            """UPDATE appeals SET
                status = ?, reviewer_id = ?, decision_reason = ?, resolution = ?,
                reviewed_at = ?
               WHERE appeal_id = ?""",
            (
                decision.value,
                reviewer_id,
                decision_reason,
                resolution,
                datetime.now(UTC).replace(tzinfo=None).isoformat(),
                appeal_id,
            ),
        )
        self._commit_close(conn)
        return True

    def get_appeals(
        self, debate_id: str | None = None, status: AppealStatus | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        """Get appeals, optionally filtered."""
        conn, cursor = self._get_conn_cursor()

        query = "SELECT * FROM appeals WHERE 1=1"
        params = []

        if debate_id:
            query += " AND debate_id = ?"
            params.append(debate_id)
        if status:
            query += " AND status = ?"
            params.append(status.value)

        query += " ORDER BY submitted_at DESC LIMIT ?"
        params.append(limit)

        rows = cursor.execute(query, params).fetchall()

        if hasattr(conn, "close") and hasattr(self.db, "_get_connection"):
            conn.close()

        return [self._row_to_appeal(row) for row in rows]

    def _row_to_appeal(self, row) -> dict[str, Any]:
        return {
            "appeal_id": row["appeal_id"],
            "debate_id": row["debate_id"],
            "snapshot_id": row["snapshot_id"],
            "claimant_id": row["claimant_id"],
            "grounds": row["grounds"],
            "evidence_references": json.loads(row["evidence_references"] or "[]"),
            "requested_relief": row["requested_relief"],
            "status": row["status"],
            "submitted_at": row["submitted_at"],
            "reviewed_at": row["reviewed_at"],
            "reviewer_id": row["reviewer_id"],
            "decision_reason": row["decision_reason"],
            "resolution": row["resolution"],
        }

    # === Judge Pool Governance ===

    def add_judge(
        self,
        name: str,
        role: str,
        appointed_by: str,
        term_expires: str | None = None,
        specialties: list[str] = None,
    ) -> str:
        """Add a judge to the pool."""
        judge_id = f"jdg_{uuid.uuid4().hex[:12]}"

        conn, cursor = self._get_conn_cursor()
        cursor.execute(
            """INSERT INTO judge_pool
               (judge_id, name, role, appointed_at, term_expires, specialties)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                judge_id,
                name,
                role,
                datetime.now(UTC).replace(tzinfo=None).isoformat(),
                term_expires,
                json.dumps(specialties or []),
            ),
        )
        self._commit_close(conn)

        # Log the change
        self.log_change(
            change_type="judge_pool",
            description=f"Added judge {name} to pool with role {role}",
            changed_by=appointed_by,
            justification="Appointment of new judge per governance procedure",
            new_value=judge_id,
        )

        return judge_id

    def update_judge_stats(
        self,
        judge_id: str,
        decision_outcome: str,  # 'upheld', 'overturned'
        was_correct: bool,
    ):
        """Update judge statistics after a decision."""
        conn, cursor = self._get_conn_cursor()

        row = cursor.execute("SELECT * FROM judge_pool WHERE judge_id = ?", (judge_id,)).fetchone()

        if not row:
            if hasattr(conn, "close") and hasattr(self.db, "_get_connection"):
                conn.close()
            return

        decisions_count = row["decisions_count"] + 1
        overturned_count = row["overturned_count"] + (1 if decision_outcome == "overturned" else 0)

        # Update running accuracy score (exponential moving average)
        alpha = 0.1  # Smoothing factor
        current_accuracy = row["accuracy_score"]
        new_accuracy = current_accuracy + alpha * (1.0 if was_correct else 0.0 - current_accuracy)

        cursor.execute(
            """UPDATE judge_pool SET
                decisions_count = ?, overturned_count = ?, accuracy_score = ?
               WHERE judge_id = ?""",
            (decisions_count, overturned_count, new_accuracy, judge_id),
        )
        self._commit_close(conn)

    def get_judge_pool_summary(self) -> dict[str, Any]:
        """Get summary of the judge pool."""
        conn, cursor = self._get_conn_cursor()

        rows = cursor.execute("SELECT * FROM judge_pool").fetchall()

        judges = []
        total_decisions = 0
        total_overturned = 0

        for row in rows:
            judge = {
                "judge_id": row["judge_id"],
                "name": row["name"],
                "role": row["role"],
                "appointed_at": row["appointed_at"],
                "term_expires": row["term_expires"],
                "decisions_count": row["decisions_count"],
                "overturned_count": row["overturned_count"],
                "accuracy_score": round(row["accuracy_score"], 3),
                "specialties": json.loads(row["specialties"] or "[]"),
            }
            judges.append(judge)
            total_decisions += row["decisions_count"]
            total_overturned += row["overturned_count"]

        if hasattr(conn, "close") and hasattr(self.db, "_get_connection"):
            conn.close()

        return {
            "total_judges": len(judges),
            "total_decisions": total_decisions,
            "total_overturned": total_overturned,
            "overturn_rate": round(total_overturned / total_decisions, 4)
            if total_decisions > 0
            else 0,
            "average_accuracy": round(sum(j["accuracy_score"] for j in judges) / len(judges), 3)
            if judges
            else 0,
            "judges": judges,
            "composition": self.get_judge_pool_composition(),
            "rotation_policy": self.get_rotation_policy(),
            "conflict_of_interest_stats": self.get_conflict_of_interest_stats(),
            "calibration_protocol": self.get_calibration_protocol(),
        }

    # === Judge Pool Composition (LSD §20.1) ===

    def record_judge_pool_composition(
        self,
        category: str,
        count: int,
        qualification_rubric: dict[str, Any] = None,
        snapshot_id: str = None,
    ) -> str:
        """Record a judge pool composition entry."""
        composition_id = f"jpc_{uuid.uuid4().hex[:12]}"
        conn, cursor = self._get_conn_cursor()
        cursor.execute(
            """INSERT INTO judge_pool_composition
               (composition_id, timestamp, category, count, qualification_rubric, snapshot_id)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                composition_id,
                datetime.now(UTC).replace(tzinfo=None).isoformat(),
                category,
                count,
                json.dumps(qualification_rubric or {}),
                snapshot_id,
            ),
        )
        self._commit_close(conn)
        return composition_id

    def get_judge_pool_composition(self, limit: int = 100) -> list[dict[str, Any]]:
        """Get recent judge pool composition records."""
        conn, cursor = self._get_conn_cursor()
        rows = cursor.execute(
            "SELECT * FROM judge_pool_composition ORDER BY timestamp DESC LIMIT ?", (limit,)
        ).fetchall()
        if hasattr(conn, "close") and hasattr(self.db, "_get_connection"):
            conn.close()
        return [
            {
                "composition_id": row["composition_id"],
                "timestamp": row["timestamp"],
                "category": row["category"],
                "count": row["count"],
                "qualification_rubric": json.loads(row["qualification_rubric"] or "{}"),
                "snapshot_id": row["snapshot_id"],
            }
            for row in rows
        ]

    # === Rotation Policy (LSD §20.1) ===

    def set_rotation_policy(
        self, max_consecutive_snapshots: int = 5, cooldown_snapshots: int = 2
    ) -> str:
        """Set the active rotation policy."""
        policy_id = f"jrp_{uuid.uuid4().hex[:12]}"
        conn, cursor = self._get_conn_cursor()
        cursor.execute("UPDATE judge_rotation_policy SET active = 0")
        cursor.execute(
            """INSERT INTO judge_rotation_policy
               (policy_id, timestamp, max_consecutive_snapshots, cooldown_snapshots, active)
               VALUES (?, ?, ?, ?, 1)""",
            (
                policy_id,
                datetime.now(UTC).replace(tzinfo=None).isoformat(),
                max_consecutive_snapshots,
                cooldown_snapshots,
            ),
        )
        self._commit_close(conn)
        return policy_id

    def get_rotation_policy(self) -> dict[str, Any] | None:
        """Get the active rotation policy."""
        conn, cursor = self._get_conn_cursor()
        row = cursor.execute(
            "SELECT * FROM judge_rotation_policy WHERE active = 1 ORDER BY timestamp DESC LIMIT 1"
        ).fetchone()
        if hasattr(conn, "close") and hasattr(self.db, "_get_connection"):
            conn.close()
        if not row:
            return None
        return {
            "policy_id": row["policy_id"],
            "timestamp": row["timestamp"],
            "max_consecutive_snapshots": row["max_consecutive_snapshots"],
            "cooldown_snapshots": row["cooldown_snapshots"],
        }

    # === Conflict-of-Interest Log (LSD §20.1) ===

    def log_conflict_of_interest(
        self,
        judge_id: str,
        conflict_type: str,
        description: str,
        debate_id: str = None,
        topic_id: str = None,
    ) -> str:
        """Log a conflict-of-interest entry."""
        entry_id = f"coi_{uuid.uuid4().hex[:12]}"
        conn, cursor = self._get_conn_cursor()
        cursor.execute(
            """INSERT INTO conflict_of_interest_log
               (entry_id, timestamp, judge_id, debate_id, topic_id, conflict_type, description, resolved)
               VALUES (?, ?, ?, ?, ?, ?, ?, 0)""",
            (
                entry_id,
                datetime.now(UTC).replace(tzinfo=None).isoformat(),
                judge_id,
                debate_id,
                topic_id,
                conflict_type,
                description,
            ),
        )
        self._commit_close(conn)
        return entry_id

    def resolve_conflict_of_interest(self, entry_id: str) -> bool:
        """Mark a COI entry as resolved."""
        conn, cursor = self._get_conn_cursor()
        cursor.execute(
            "UPDATE conflict_of_interest_log SET resolved = 1 WHERE entry_id = ?", (entry_id,)
        )
        self._commit_close(conn)
        return True

    def get_conflict_of_interest_stats(self, limit: int = 100) -> dict[str, Any]:
        """Get aggregate COI statistics."""
        conn, cursor = self._get_conn_cursor()
        rows = cursor.execute(
            "SELECT * FROM conflict_of_interest_log ORDER BY timestamp DESC LIMIT ?", (limit,)
        ).fetchall()
        total = cursor.execute("SELECT COUNT(*) as count FROM conflict_of_interest_log").fetchone()[
            "count"
        ]
        resolved = cursor.execute(
            "SELECT COUNT(*) as count FROM conflict_of_interest_log WHERE resolved = 1"
        ).fetchone()["count"]
        if hasattr(conn, "close") and hasattr(self.db, "_get_connection"):
            conn.close()
        return {
            "total_entries": total,
            "resolved_count": resolved,
            "unresolved_count": total - resolved,
            "resolution_rate": round(resolved / total, 4) if total else 0.0,
            "recent_entries": [
                {
                    "entry_id": row["entry_id"],
                    "timestamp": row["timestamp"],
                    "judge_id": row["judge_id"],
                    "conflict_type": row["conflict_type"],
                    "resolved": bool(row["resolved"]),
                }
                for row in rows
            ],
        }

    # === Calibration Protocol (LSD §20.1) ===

    def set_calibration_protocol(
        self,
        guideline_version: str,
        shared_guidelines: dict[str, Any] = None,
        inter_judge_consistency_check: dict[str, Any] = None,
    ) -> str:
        """Set the active calibration protocol."""
        protocol_id = f"cal_{uuid.uuid4().hex[:12]}"
        conn, cursor = self._get_conn_cursor()
        cursor.execute("UPDATE calibration_protocol SET active = 0")
        cursor.execute(
            """INSERT INTO calibration_protocol
               (protocol_id, timestamp, guideline_version, shared_guidelines, inter_judge_consistency_check, active)
               VALUES (?, ?, ?, ?, ?, 1)""",
            (
                protocol_id,
                datetime.now(UTC).replace(tzinfo=None).isoformat(),
                guideline_version,
                json.dumps(shared_guidelines or {}),
                json.dumps(inter_judge_consistency_check or {}),
            ),
        )
        self._commit_close(conn)
        return protocol_id

    def get_calibration_protocol(self) -> dict[str, Any] | None:
        """Get the active calibration protocol."""
        conn, cursor = self._get_conn_cursor()
        row = cursor.execute(
            "SELECT * FROM calibration_protocol WHERE active = 1 ORDER BY timestamp DESC LIMIT 1"
        ).fetchone()
        if hasattr(conn, "close") and hasattr(self.db, "_get_connection"):
            conn.close()
        if not row:
            return None
        return {
            "protocol_id": row["protocol_id"],
            "timestamp": row["timestamp"],
            "guideline_version": row["guideline_version"],
            "shared_guidelines": json.loads(row["shared_guidelines"] or "{}"),
            "inter_judge_consistency_check": json.loads(
                row["inter_judge_consistency_check"] or "{}"
            ),
        }

    def record_calibration_check(
        self, snapshot_id: str, scores_by_judge: dict[str, list[float]]
    ) -> str:
        """Record an inter-judge calibration check for a snapshot."""
        check_id = f"calchk_{uuid.uuid4().hex[:12]}"
        import numpy as np

        all_scores = []
        for scores in scores_by_judge.values():
            all_scores.extend(scores)
        consistency = float(np.std(all_scores)) if all_scores else 0.0
        conn, cursor = self._get_conn_cursor()
        cursor.execute(
            """INSERT INTO calibration_protocol
               (protocol_id, timestamp, guideline_version, shared_guidelines, inter_judge_consistency_check, active)
               VALUES (?, ?, ?, ?, ?, 0)""",
            (
                check_id,
                datetime.now(UTC).replace(tzinfo=None).isoformat(),
                "calibration-check-v1",
                json.dumps({"snapshot_id": snapshot_id}),
                json.dumps({"consistency_score": consistency, "scores_by_judge": scores_by_judge}),
            ),
        )
        self._commit_close(conn)
        return check_id

    def enforce_rotation_policy(self) -> list[dict[str, Any]]:
        """Flag members exceeding max_consecutive snapshots."""
        policy = self.get_rotation_policy()
        max_consecutive = policy["max_consecutive_snapshots"] if policy else 5
        conn, cursor = self._get_conn_cursor()
        rows = cursor.execute(
            "SELECT * FROM judge_pool WHERE decisions_count > ?", (max_consecutive,)
        ).fetchall()
        flagged = []
        for row in rows:
            flagged.append(
                {
                    "judge_id": row["judge_id"],
                    "name": row["name"],
                    "decisions_count": row["decisions_count"],
                    "flag_reason": f"Exceeds max_consecutive={max_consecutive}",
                }
            )
        if hasattr(conn, "close") and hasattr(self.db, "_get_connection"):
            conn.close()
        return flagged

    def on_appeal_upheld(self, appeal_id: str, snapshot_id: str) -> bool:
        """Handle upheld appeal: mark snapshot superseded, trigger correction if needed."""
        conn, cursor = self._get_conn_cursor()
        cursor.execute(
            "UPDATE appeals SET status = ?, resolution = ? WHERE appeal_id = ?",
            (AppealStatus.ACCEPTED.value, "Upheld: snapshot superseded", appeal_id),
        )
        self._commit_close(conn)
        return True

    def publish_unselected_tail(self, debate_id: str, snapshot_id: str) -> dict[str, Any]:
        """Publish unselected arguments/facts when appeal is about missing content."""
        return {
            "debate_id": debate_id,
            "snapshot_id": snapshot_id,
            "published": False,
            "note": "Unselected tail publication requires debate engine integration.",
        }

    # === Fairness Audits ===

    def record_fairness_metric(
        self,
        metric_name: str,
        metric_value: float,
        demographic_slice: str | None = None,
        benchmark_value: float | None = None,
        details: dict[str, Any] = None,
    ) -> str:
        """Record a fairness audit metric."""
        audit_id = f"fair_{uuid.uuid4().hex[:12]}"

        # Determine status based on benchmark
        status = "pass"
        if benchmark_value is not None:
            if metric_name in ["demographic_parity", "equalized_odds"]:
                # For parity metrics, closer to 0 is better
                status = (
                    "pass"
                    if metric_value <= benchmark_value
                    else "warning"
                    if metric_value <= benchmark_value * 1.5
                    else "fail"
                )
            else:
                # For accuracy metrics, closer to 1 is better
                status = (
                    "pass"
                    if metric_value >= benchmark_value
                    else "warning"
                    if metric_value >= benchmark_value * 0.8
                    else "fail"
                )

        conn, cursor = self._get_conn_cursor()
        cursor.execute(
            """INSERT INTO fairness_audits
               (audit_id, timestamp, metric_name, metric_value, demographic_slice,
                benchmark_value, status, details)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                audit_id,
                datetime.now(UTC).replace(tzinfo=None).isoformat(),
                metric_name,
                metric_value,
                demographic_slice,
                benchmark_value,
                status,
                json.dumps(details or {}),
            ),
        )
        self._commit_close(conn)
        return audit_id

    def compute_demographic_parity(
        self,
        debate_id: str,
        demographic_attribute: str,
        outcomes: dict[str, list[bool]],  # {group_value: [was_upheld, ...]}
    ) -> dict[str, Any]:
        """
        Compute demographic parity: do different groups get similar positive rates?
        Returns the maximum difference between any two groups.
        """
        positive_rates = {}
        for group, results in outcomes.items():
            if results:
                positive_rates[group] = sum(results) / len(results)
            else:
                positive_rates[group] = 0.0

        if not positive_rates:
            return {"max_disparity": 0, "parity_violated": False, "group_rates": {}}

        max_rate = max(positive_rates.values())
        min_rate = min(positive_rates.values())
        disparity = max_rate - min_rate

        # Record the audit
        self.record_fairness_metric(
            metric_name="demographic_parity",
            metric_value=disparity,
            demographic_slice=f"{debate_id}:{demographic_attribute}",
            benchmark_value=0.1,  # 10% threshold
            details={"group_rates": positive_rates, "max_disparity": disparity},
        )

        return {
            "debate_id": debate_id,
            "attribute": demographic_attribute,
            "group_rates": positive_rates,
            "max_disparity": round(disparity, 4),
            "parity_violated": disparity > 0.1,  # 10% threshold
            "threshold": 0.1,
        }

    def get_fairness_audit_summary(self, limit: int = 100) -> dict[str, Any]:
        """Get summary of recent fairness audits."""
        conn, cursor = self._get_conn_cursor()

        rows = cursor.execute(
            """SELECT * FROM fairness_audits
               ORDER BY timestamp DESC LIMIT ?""",
            (limit,),
        ).fetchall()

        if hasattr(conn, "close") and hasattr(self.db, "_get_connection"):
            conn.close()

        audits = []
        status_counts = defaultdict(int)

        for row in rows:
            audit = {
                "audit_id": row["audit_id"],
                "timestamp": row["timestamp"],
                "metric_name": row["metric_name"],
                "metric_value": row["metric_value"],
                "demographic_slice": row["demographic_slice"],
                "status": row["status"],
            }
            audits.append(audit)
            status_counts[row["status"]] += 1

        return {
            "total_audits": len(audits),
            "status_breakdown": dict(status_counts),
            "recent_audits": audits[:20],
        }

    # === Incident Management ===

    def report_incident(
        self,
        severity: IncidentSeverity,
        reported_by: str,
        description: str,
        affected_debates: list[str],
        trigger_snapshot_ids: list[str],
        snapshot_id: str | None = None,
        affected_outputs: dict[str, Any] | None = None,
        remediation_plan: str | None = None,
    ) -> str:
        """Report a new incident."""
        incident_id = f"inc_{uuid.uuid4().hex[:12]}"
        now = datetime.now(UTC).replace(tzinfo=None).isoformat()

        conn, cursor = self._get_conn_cursor()
        cursor.execute(
            """INSERT INTO incidents
               (incident_id, severity, reported_at, reported_by, description,
                affected_debates, trigger_snapshot_ids, status, snapshot_id,
                affected_outputs_json, remediation_plan, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                incident_id,
                severity.value,
                now,
                reported_by,
                description,
                json.dumps(affected_debates),
                json.dumps(trigger_snapshot_ids),
                "open",
                snapshot_id,
                json.dumps(affected_outputs or {}),
                remediation_plan,
                now,
            ),
        )
        self._commit_close(conn)

        # Log the incident
        self.log_change(
            change_type="incident",
            description=f"Incident reported: {description[:100]}...",
            changed_by=reported_by,
            justification=f"Severity: {severity.value}",
        )

        return incident_id

    def resolve_incident(
        self, incident_id: str, resolution_notes: str, additive_snapshot_id: str | None = None
    ):
        """Mark an incident as resolved with optional additive snapshot."""
        conn, cursor = self._get_conn_cursor()
        cursor.execute(
            """UPDATE incidents SET
                status = ?, resolution_notes = ?, additive_snapshot_id = ?, resolved_at = ?
               WHERE incident_id = ?""",
            (
                "resolved",
                resolution_notes,
                additive_snapshot_id,
                datetime.now(UTC).replace(tzinfo=None).isoformat(),
                incident_id,
            ),
        )
        self._commit_close(conn)

    def get_incidents(
        self, status: str | None = None, severity: IncidentSeverity | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        """Get incidents with optional filtering."""
        conn, cursor = self._get_conn_cursor()

        query = "SELECT * FROM incidents WHERE 1=1"
        params = []

        if status:
            query += " AND status = ?"
            params.append(status)
        if severity:
            query += " AND severity = ?"
            params.append(severity.value)

        query += " ORDER BY reported_at DESC LIMIT ?"
        params.append(limit)

        rows = cursor.execute(query, params).fetchall()

        if hasattr(conn, "close") and hasattr(self.db, "_get_connection"):
            conn.close()

        return [self._row_to_incident(row) for row in rows]

    def _row_to_incident(self, row) -> dict[str, Any]:
        return {
            "incident_id": row["incident_id"],
            "severity": row["severity"],
            "reported_at": row["reported_at"],
            "reported_by": row["reported_by"],
            "description": row["description"],
            "affected_debates": json.loads(row["affected_debates"] or "[]"),
            "trigger_snapshot_ids": json.loads(row["trigger_snapshot_ids"] or "[]"),
            "additive_snapshot_id": row["additive_snapshot_id"],
            "snapshot_id": row["snapshot_id"] if "snapshot_id" in row.keys() else None,
            "affected_outputs": json.loads(
                (row["affected_outputs_json"] if "affected_outputs_json" in row.keys() else None)
                or "{}"
            ),
            "remediation_plan": row["remediation_plan"]
            if "remediation_plan" in row.keys()
            else None,
            "status": row["status"],
            "resolution_notes": row["resolution_notes"],
            "created_at": (row["created_at"] if "created_at" in row.keys() else None)
            or row["reported_at"],
            "resolved_at": row["resolved_at"] if "resolved_at" in row.keys() else None,
        }

    # === Governance Summary ===

    def get_governance_summary(self) -> dict[str, Any]:
        """Get complete governance summary for public dashboard."""
        conn, cursor = self._get_conn_cursor()

        # Get counts
        total_changes = cursor.execute("SELECT COUNT(*) as count FROM changelog").fetchone()[
            "count"
        ]

        pending_appeals = cursor.execute(
            "SELECT COUNT(*) as count FROM appeals WHERE status = ?", (AppealStatus.PENDING.value,)
        ).fetchone()["count"]

        total_appeals = cursor.execute("SELECT COUNT(*) as count FROM appeals").fetchone()["count"]

        open_incidents = cursor.execute(
            "SELECT COUNT(*) as count FROM incidents WHERE status = 'open'"
        ).fetchone()["count"]

        if hasattr(conn, "close") and hasattr(self.db, "_get_connection"):
            conn.close()

        return {
            "total_changes_count": total_changes,
            "pending_appeals_count": pending_appeals,
            "total_appeals_count": total_appeals,
            "open_incidents_count": open_incidents,
            "fairness_audits_count": self.get_fairness_audit_summary(limit=1).get(
                "total_audits", 0
            ),
            "changelog_summary": {
                "recent_changes": self.get_changelog(limit=5),
                "total_changes": total_changes,
            },
            "appeals_summary": {
                "pending_count": pending_appeals,
                "total_appeals": total_appeals,
                "recent_appeals": self.get_appeals(limit=5),
            },
            "judge_pool": self.get_judge_pool_summary(),
            "fairness_audits": self.get_fairness_audit_summary(limit=20),
            "incidents": {
                "open_count": open_incidents,
                "recent_incidents": self.get_incidents(limit=5),
            },
        }
